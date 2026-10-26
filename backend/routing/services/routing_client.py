"""Geocoding (Nominatim) and routing (OSRM). The only module that calls those external APIs.

External calls per analysis:
  * 0–2 geocode calls (skipped for coordinates or cached names)
  * 1 OSRM call with alternatives=3
  * if OSRM returns fewer than 3 distinct routes: up to 4 extra via-waypoint calls, run in parallel
"""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from django.core.cache import cache

from . import geo
from .errors import BadInput, NotFound, UpstreamError
from .http import get_json

logger = logging.getLogger("routing")

# Rough boxes for the contiguous US, Alaska and Hawaii (lon_min, lat_min, lon_max, lat_max).
_USA_BOXES = [(-125.0, 24.4, -66.9, 49.5), (-170.0, 51.0, -129.0, 71.5), (-160.5, 18.8, -154.5, 22.4)]
_LATLON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

MAX_ROUTES = 3
# Via-waypoint offsets (fraction of straight-line distance, + is left of travel) used when OSRM returns <3.
FALLBACK_OFFSETS = (0.12, -0.12, 0.22, -0.22)
DUPLICATE_OVERLAP = 0.85  # routes sharing ≥85% of their path are treated as the same route
MAX_DETOUR_RATIO = 1.6  # ignore fallback routes much longer than the fastest one


@dataclass
class Place:
    query: str
    label: str
    lat: float
    lon: float

    def as_dict(self) -> dict:
        return {"query": self.query, "label": self.label, "lat": round(self.lat, 5), "lon": round(self.lon, 5)}


@dataclass
class Route:
    lats: np.ndarray
    lons: np.ndarray
    distance_miles: float
    duration_seconds: float
    segment_seconds: np.ndarray | None
    source: str  # "osrm" or "osrm-via"


def in_usa(lat: float, lon: float) -> bool:
    return any(x0 <= lon <= x1 and y0 <= lat <= y1 for x0, y0, x1, y1 in _USA_BOXES)


def resolve_place(value) -> Place:
    """Accepts {"lat":..,"lon":..}, "lat,lon" or a free-text US address."""
    if isinstance(value, dict):
        try:
            lat, lon = float(value["lat"]), float(value["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BadInput("Coordinates must look like {\"lat\": 41.88, \"lon\": -87.63}.") from exc
        place = Place(query=f"{lat:.5f},{lon:.5f}", label=f"{lat:.4f}, {lon:.4f}", lat=lat, lon=lon)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        m = _LATLON_RE.match(text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            place = Place(query=text, label=f"{lat:.4f}, {lon:.4f}", lat=lat, lon=lon)
        else:
            place = geocode(text)
    else:
        raise BadInput("Location is required.")

    if not in_usa(place.lat, place.lon):
        raise BadInput(f"'{place.query}' is outside the USA. Both locations must be inside the USA.")
    return place


def geocode(text: str) -> Place:
    key = "geo:" + hashlib.sha1(text.lower().encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        return Place(**hit)
    data, status = get_json(
        f"{settings.NOMINATIM_URL}/search",
        params={"q": text, "format": "jsonv2", "countrycodes": "us", "limit": 1},
        service="Geocoding service (Nominatim)",
    )
    if status >= 400 or not isinstance(data, list):
        raise UpstreamError("Geocoding service is unavailable right now.")
    if not data:
        raise NotFound(f"Could not find '{text}' in the USA. Try 'City, ST' or 'lat,lon'.")
    hit = data[0]
    label = hit.get("display_name", text).replace(", United States", "")
    place = Place(query=text, label=label, lat=float(hit["lat"]), lon=float(hit["lon"]))
    cache.set(key, place.__dict__, settings.GEOCODE_CACHE_SECONDS)
    return place


def _osrm(coords: list[tuple[float, float]], alternatives: int) -> list[Route]:
    path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
    data, status = get_json(
        f"{settings.OSRM_URL}/route/v1/driving/{path}",
        params={
            "alternatives": str(alternatives) if alternatives else "false",
            "overview": "full",
            "geometries": "geojson",
            "annotations": "duration",
            "steps": "false",
        },
        service="Routing service (OSRM)",
    )
    if not isinstance(data, dict) or data.get("code") != "Ok":
        code = data.get("code") if isinstance(data, dict) else status
        if code in ("NoRoute", "NoSegment"):
            return []
        raise UpstreamError(f"Routing service error: {code}.")

    routes = []
    for r in data.get("routes", []):
        coords_lonlat = np.asarray(r["geometry"]["coordinates"], dtype=float)
        seg = np.concatenate([np.asarray(leg["annotation"]["duration"], dtype=float) for leg in r["legs"]])
        lats, lons = coords_lonlat[:, 1], coords_lonlat[:, 0]
        routes.append(
            Route(
                lats=lats,
                lons=lons,
                distance_miles=r["distance"] / 1609.344,
                duration_seconds=float(r["duration"]),
                segment_seconds=seg if len(seg) == len(lats) - 1 else None,
                source="osrm" if len(coords) == 2 else "osrm-via",
            )
        )
    return routes


def _sample(route: Route, step: float = 5.0):
    cum = geo.cumulative_miles(route.lats, route.lons)
    idx = geo.downsample_by_distance(cum, step)
    return route.lats[idx], route.lons[idx]


def _is_duplicate(candidate: Route, kept: list[Route]) -> bool:
    c_lat, c_lon = _sample(candidate)
    for k in kept:
        k_lat, k_lon = _sample(k)
        if (
            geo.overlap_fraction(c_lat, c_lon, k_lat, k_lon) >= DUPLICATE_OVERLAP
            and geo.overlap_fraction(k_lat, k_lon, c_lat, c_lon) >= DUPLICATE_OVERLAP
        ):
            return True
    return False


def get_routes(start: Place, finish: Place) -> list[Route]:
    """Up to 3 distinct routes, fastest first. Cached by rounded endpoints."""
    key = f"routes:{start.lat:.4f},{start.lon:.4f}:{finish.lat:.4f},{finish.lon:.4f}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    a, b = (start.lat, start.lon), (finish.lat, finish.lon)
    routes = _osrm([a, b], alternatives=MAX_ROUTES)
    if not routes:
        raise NotFound("No drivable route found between these locations.")

    kept: list[Route] = []
    for r in routes:
        if not _is_duplicate(r, kept):
            kept.append(r)

    if len(kept) < MAX_ROUTES:
        vias = [geo.perpendicular_offset_point(a[0], a[1], b[0], b[1], f) for f in FALLBACK_OFFSETS]
        vias = [v for v in vias if in_usa(*v)]
        with ThreadPoolExecutor(max_workers=len(vias) or 1) as pool:
            results = list(pool.map(lambda v: _safe_osrm([a, v, b]), vias))
        fastest = min(r.duration_seconds for r in kept)
        for candidates in results:
            for r in candidates:
                if len(kept) >= MAX_ROUTES:
                    break
                if r.duration_seconds > fastest * MAX_DETOUR_RATIO:
                    continue
                if not _is_duplicate(r, kept):
                    kept.append(r)

    kept.sort(key=lambda r: r.duration_seconds)
    cache.set(key, kept, settings.ROUTE_CACHE_SECONDS)
    return kept


def _safe_osrm(coords) -> list[Route]:
    try:
        return _osrm(coords, alternatives=0)
    except UpstreamError as exc:  # fallback routes are best-effort
        logger.info("Fallback route failed: %s", exc)
        return []
