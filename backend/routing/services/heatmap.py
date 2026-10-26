"""Weather-risk heatmap over the trip corridor for hours 0–48.

The grid is a set of square-ish cells covering every point within CORRIDOR_MILES of any route.
The spacing grows until the grid has at most MAX_POINTS cells, so long trips stay a few hundred points
(one or a few batched Open-Meteo requests). The client gets compact arrays and only swaps the hour
index when the slider moves, so sliding never touches the network.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from . import geo, risk, weather_client

CORRIDOR_MILES = 40.0
MAX_POINTS = 220  # keeps checkpoints + heatmap under Open-Meteo's free per-minute limit
HOURS = 49  # 0..48 inclusive


def corridor_grid(route_samples: list[tuple[np.ndarray, np.ndarray]], corridor_miles: float = CORRIDOR_MILES, max_points: int = MAX_POINTS):
    """Grid cell centres near any route. Returns (lats, lons, cell_dlat, cell_dlon)."""
    all_lats = np.concatenate([s[0] for s in route_samples])
    all_lons = np.concatenate([s[1] for s in route_samples])
    box = geo.expand_bbox(geo.bbox(all_lats, all_lons), corridor_miles)
    mid_lat = math.radians((box[1] + box[3]) / 2)

    spacing = 12.0  # miles
    while True:
        dlat = spacing / 69.0
        dlon = spacing / (69.0 * max(math.cos(mid_lat), 0.2))
        g_lats = np.arange(box[1] + dlat / 2, box[3], dlat)
        g_lons = np.arange(box[0] + dlon / 2, box[2], dlon)
        mesh_lat, mesh_lon = np.meshgrid(g_lats, g_lons, indexing="ij")
        flat_lat, flat_lon = mesh_lat.ravel(), mesh_lon.ravel()
        _, dist = geo.nearest_on_route(flat_lat, flat_lon, all_lats, all_lons)
        # Half a cell diagonal of slack so cells straddling the corridor edge are kept.
        keep = dist <= corridor_miles + spacing * 0.7
        if keep.sum() <= max_points:
            return flat_lat[keep], flat_lon[keep], dlat, dlon
        spacing *= 1.2


def build(
    lats: np.ndarray,
    lons: np.ndarray,
    cell_dlat: float,
    cell_dlon: float,
    start: datetime,
    load_lb: float,
) -> dict:
    start = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=HOURS - 1)
    points = [(round(float(a), 4), round(float(b), 4)) for a, b in zip(lats, lons)]
    # Grid points are already ≥ 10 miles apart, so they are not rounded to the 0.1° weather grid.
    grid = weather_client.fetch(points, start, end)
    scores = risk.score_grid(grid.wind, grid.gust, grid.rain, grid.snow, load_lb)  # (points, hours)
    hours = [(start + timedelta(hours=h)).isoformat().replace("+00:00", "Z") for h in range(HOURS)]
    return {
        "points": [[p[0], p[1]] for p in points],
        "cell": {"dlat": round(cell_dlat, 5), "dlon": round(cell_dlon, 5)},
        "hours": hours,
        # values[h][i] = risk score (0 Low .. 4 No Travel, -1 no data) of point i at hour h
        "values": scores.T.tolist(),
        "wind_mph": np.round(np.nan_to_num(grid.wind.T, nan=-1), 0).astype(int).tolist(),
        "load_weight_lb": load_lb,
    }
