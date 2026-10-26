"""Full trip analysis: routes -> checkpoints + ETA -> batched weather -> risk -> ranking.

This is the only place that wires the pure modules (geo, eta, risk, recommend) to the
external clients. Each stage is timed and logged at debug level.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from django.conf import settings
from django.core.cache import cache

from . import eta, geo, heatmap, recommend, risk, routing_client, weather_client
from .errors import NotFound

logger = logging.getLogger("routing")

ANALYSIS_CACHE_SECONDS = 60 * 30


@dataclass
class TripRequest:
    origin: object
    destination: object
    departure: datetime
    load_weight_lb: float
    checkpoint_interval_miles: int


@contextmanager
def _timed(timings: dict, name: str):
    t0 = time.perf_counter()
    yield
    timings[name] = round((time.perf_counter() - t0) * 1000, 1)
    logger.debug("%s took %.1f ms", name, timings[name])


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def analysis_key(req: TripRequest) -> str:
    raw = json.dumps(
        [req.origin, req.destination, req.departure.isoformat(), req.load_weight_lb, req.checkpoint_interval_miles],
        sort_keys=True,
        default=str,
    ).lower()
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def analyze(req: TripRequest) -> dict:
    analysis_id = analysis_key(req)
    cached = cache.get(f"analysis:{analysis_id}")
    if cached is not None:
        return {**cached, "cached": True}

    timings: dict[str, float] = {}
    t_start = time.perf_counter()

    with _timed(timings, "geocode_ms"):
        origin = routing_client.resolve_place(req.origin)
        destination = routing_client.resolve_place(req.destination)

    with _timed(timings, "routing_ms"):
        routes = routing_client.get_routes(origin, destination)
    if not routes:
        raise NotFound("No drivable route found between these locations.")

    # --- Geometry, checkpoints and ETAs -------------------------------------------------------------
    with _timed(timings, "checkpoints_ms"):
        prepared = []
        for i, r in enumerate(routes):
            cum = geo.cumulative_miles(r.lats, r.lons)
            # Rescale haversine length to the engine's road distance so mile markers match the route summary.
            scale = r.distance_miles / cum[-1] if cum[-1] > 0 else 1.0
            cum = cum * scale
            cum_secs = eta.cumulative_seconds(r.segment_seconds, cum, r.duration_seconds)
            marks = geo.checkpoint_miles(float(cum[-1]), req.checkpoint_interval_miles)
            c_lats, c_lons = geo.interpolate_along(cum, r.lats, r.lons, marks)
            etas = eta.eta_at_miles(req.departure, cum, cum_secs, marks)
            prepared.append(
                {
                    "id": f"route_{i}",
                    "route": r,
                    "cum": cum,
                    "marks": marks,
                    "seg_miles": geo.represented_miles(marks),
                    "c_lats": c_lats,
                    "c_lons": c_lons,
                    "etas": etas,
                }
            )

    # --- Weather: one batched fetch for every checkpoint of every route ------------------------------
    with _timed(timings, "weather_ms"):
        raw = [(float(la), float(lo)) for p in prepared for la, lo in zip(p["c_lats"], p["c_lons"])]
        step = weather_client.choose_grid_step(raw)
        snap = lambda la, lo: (weather_client.round_coord(la, step), weather_client.round_coord(lo, step))  # noqa: E731
        all_points = sorted({snap(la, lo) for la, lo in raw})
        all_etas = [e for p in prepared for e in p["etas"]]
        first = eta.round_to_hour(min(all_etas))
        last = eta.round_to_hour(max(all_etas))
        wx = weather_client.fetch(all_points, first, last)

    # --- Risk, summaries, ranking ---------------------------------------------------------------------
    with _timed(timings, "risk_ms"):
        summaries = []
        for p in prepared:
            checkpoints = []
            for k, mile in enumerate(p["marks"]):
                eta_dt = p["etas"][k]
                eta_hour = eta.round_to_hour(eta_dt)
                point = snap(float(p["c_lats"][k]), float(p["c_lons"][k]))
                values = wx.at(point, eta_hour)
                cp = {
                    "mile": round(float(mile), 1),
                    "lat": round(float(p["c_lats"][k]), 5),
                    "lon": round(float(p["c_lons"][k]), 5),
                    "eta": _iso(eta_dt),
                    "forecast_hour": _iso(eta_hour.astimezone(timezone.utc)),
                    "represented_miles": round(float(p["seg_miles"][k]), 2),
                }
                if values is None:
                    cp.update(status="forecast_unavailable", weather=None, risk=None)
                    score = None
                else:
                    a = risk.assess(risk.Weather(**values), req.load_weight_lb)
                    cp.update(
                        status="ok",
                        weather={k2: round(v, 2) for k2, v in values.items()},
                        risk=a.as_dict(),
                    )
                    score = a.score
                checkpoints.append(cp)
                p.setdefault("scores", []).append(score)
            p["checkpoints"] = checkpoints
            summaries.append(
                recommend.summarize(
                    p["id"], p["route"].duration_seconds / 3600, list(zip(p["seg_miles"].tolist(), p["scores"]))
                )
            )
        ranking = recommend.rank(summaries)
        rank_of = {s.route_id: n + 1 for n, s in enumerate(ranking.order)}
        summary_of = {s.route_id: s for s in summaries}

    # --- Heatmap grid (weather itself is fetched lazily by /api/heatmap) -------------------------------
    with _timed(timings, "grid_ms"):
        samples = []
        for p in prepared:
            idx = geo.downsample_by_distance(p["cum"], 5.0)
            samples.append((p["route"].lats[idx], p["route"].lons[idx]))
        g_lats, g_lons, dlat, dlon = heatmap.corridor_grid(samples)
        cache.set(
            f"heatgrid:{analysis_id}",
            {
                "lats": g_lats,
                "lons": g_lons,
                "dlat": dlat,
                "dlon": dlon,
                "start": req.departure,
                "load": req.load_weight_lb,
            },
            ANALYSIS_CACHE_SECONDS * 2,
        )

    # --- Response --------------------------------------------------------------------------------------
    with _timed(timings, "serialize_ms"):
        out_routes = []
        for p in prepared:
            r = p["route"]
            keep = geo.simplify(r.lats, r.lons)
            s = summary_of[p["id"]]
            out_routes.append(
                {
                    "id": p["id"],
                    "source": r.source,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": np.round(np.column_stack([r.lons[keep], r.lats[keep]]), 5).tolist(),
                    },
                    "distance_miles": round(r.distance_miles, 1),
                    "duration_hours": round(r.duration_seconds / 3600, 2),
                    "arrival": _iso(p["etas"][-1]),
                    "checkpoints": p["checkpoints"],
                    "summary": s.as_dict(),
                    "rank": rank_of[p["id"]],
                    "recommended": rank_of[p["id"]] == 1,
                    "recommendation_reason": ranking.reasons.get(p["id"], ""),
                }
            )
        out_routes.sort(key=lambda x: x["rank"])
        all_lats = np.concatenate([p["route"].lats for p in prepared])
        all_lons = np.concatenate([p["route"].lons for p in prepared])

    _, horizon_end = weather_client.horizon()
    timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
    logger.info("analysis %s: %s", analysis_id, timings)
    result = {
        "analysis_id": analysis_id,
        "origin": origin.as_dict(),
        "destination": destination.as_dict(),
        "departure_time": _iso(req.departure),
        "load_weight_lb": req.load_weight_lb,
        "checkpoint_interval_miles": req.checkpoint_interval_miles,
        "routes": out_routes,
        "warning": ranking.warning,
        "corridor_bbox": [round(v, 4) for v in geo.bbox(all_lats, all_lons)],
        "forecast_horizon_end": _iso(horizon_end),
        "risk_rules": {"wind_source": risk.WIND_SOURCE},
        "weather_grid_deg": step,
        "weather_locations": len(all_points),
        "timings_ms": timings,
        "cached": False,
    }
    cache.set(f"analysis:{analysis_id}", result, ANALYSIS_CACHE_SECONDS)
    return result


def heatmap_for(analysis_id: str) -> dict:
    key = f"heatmap:{analysis_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    grid = cache.get(f"heatgrid:{analysis_id}")
    if grid is None:
        raise NotFound("Analysis expired. Run the route analysis again.")
    data = heatmap.build(grid["lats"], grid["lons"], grid["dlat"], grid["dlon"], grid["start"], grid["load"])
    cache.set(key, data, settings.WEATHER_CACHE_SECONDS)
    return data
