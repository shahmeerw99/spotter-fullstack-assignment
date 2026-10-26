"""Open-Meteo hourly forecasts, batched (many coordinates per request) and cached.

Units: wind_speed_unit=mph, precipitation_unit=inch. With precipitation_unit=inch Open-Meteo also
returns `snowfall` in inches (checked via `hourly_units`), so values map directly onto the rule table.
Rain = `rain` + `showers` (liquid only; `precipitation` would double-count snow).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
from django.conf import settings
from django.core.cache import cache

from .errors import ServiceError, UpstreamError
from .http import get_json

logger = logging.getLogger("routing")

VARIABLES = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
CHUNK = 100  # locations per request; keeps URLs short and requests fast
ROUND_DEG = 0.1  # ~7 miles: finest grid we sample; weather models are about this coarse anyway
# Open-Meteo's free tier allows ~600 locations per minute. One analysis may use at most this many unique
# checkpoint locations (the heatmap uses the rest). Very long trips at 10-mile spacing get a coarser grid.
CHECKPOINT_LOCATION_BUDGET = 350
GRID_STEPS = (0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5)
FORECAST_DAYS = 16  # Open-Meteo horizon
PAST_DAYS = 92


def round_coord(v: float, step: float = ROUND_DEG) -> float:
    return round(round(v / step) * step, 4)


def choose_grid_step(coords: list[tuple[float, float]], budget: int = CHECKPOINT_LOCATION_BUDGET) -> float:
    """Finest weather grid (degrees) that keeps the number of unique locations within budget."""
    for step in GRID_STEPS:
        if len({(round_coord(a, step), round_coord(b, step)) for a, b in coords}) <= budget:
            return step
    return GRID_STEPS[-1]


def horizon() -> tuple[datetime, datetime]:
    """First and last hour Open-Meteo can serve (UTC)."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return now - timedelta(days=PAST_DAYS), now + timedelta(days=FORECAST_DAYS) - timedelta(hours=1)


class HourlyGrid:
    """Hourly arrays for many points over one shared UTC hour window."""

    def __init__(self, start: datetime, hours: int, points: list[tuple[float, float]]):
        self.start = start
        self.hours = hours
        self.points = points
        shape = (len(points), hours)
        self.wind = np.full(shape, np.nan)
        self.gust = np.full(shape, np.nan)
        self.rain = np.full(shape, np.nan)
        self.snow = np.full(shape, np.nan)
        self.index = {p: i for i, p in enumerate(points)}

    def hour_index(self, when: datetime) -> int | None:
        k = int(round((when - self.start).total_seconds() / 3600))
        return k if 0 <= k < self.hours else None

    def at(self, point: tuple[float, float], when: datetime) -> dict | None:
        i = self.index.get(point)
        k = self.hour_index(when)
        if i is None or k is None or np.isnan(self.wind[i, k]):
            return None
        return {
            "wind_mph": float(self.wind[i, k]),
            "gust_mph": float(self.gust[i, k]),
            "rain_in_hr": float(self.rain[i, k]),
            "snow_in_hr": float(self.snow[i, k]),
        }


def fetch(points: list[tuple[float, float]], start: datetime, end: datetime) -> HourlyGrid:
    """Hourly weather for `points` (already rounded) from `start` to `end` inclusive (UTC, whole hours).

    The window is clipped to what Open-Meteo can serve; hours outside stay NaN ("forecast unavailable").
    """
    lo, hi = horizon()
    start = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = end.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = int((end - start).total_seconds() // 3600) + 1
    grid = HourlyGrid(start, hours, points)
    q_start, q_end = max(start, lo), min(end, hi)
    if q_start > q_end or not points:
        return grid

    window_key = f"{q_start:%Y%m%d%H}-{q_end:%Y%m%d%H}"
    missing = []
    for p in points:
        hit = cache.get(f"wx:{p[0]},{p[1]}:{window_key}")
        if hit is None:
            missing.append(p)
        else:
            _fill(grid, p, hit, q_start)

    chunks = [missing[i : i + CHUNK] for i in range(0, len(missing), CHUNK)]
    if chunks:
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
            results = list(pool.map(lambda c: _request(c, q_start, q_end), chunks))
        for chunk, series_list in zip(chunks, results):
            for p, series in zip(chunk, series_list):
                cache.set(f"wx:{p[0]},{p[1]}:{window_key}", series, settings.WEATHER_CACHE_SECONDS)
                _fill(grid, p, series, q_start)
    logger.debug("weather: %d points, %d fetched in %d requests", len(points), len(missing), len(chunks))
    return grid


def _fill(grid: HourlyGrid, p, series: dict, q_start: datetime) -> None:
    i = grid.index[p]
    offset = int((q_start - grid.start).total_seconds() // 3600)
    n = len(series["wind"])
    sl = slice(offset, offset + n)
    grid.wind[i, sl] = series["wind"]
    grid.gust[i, sl] = series["gust"]
    grid.rain[i, sl] = series["rain"]
    grid.snow[i, sl] = series["snow"]


def _request(chunk: list[tuple[float, float]], start: datetime, end: datetime) -> list[dict]:
    data, status = get_json(
        settings.OPEN_METEO_URL,
        params={
            "latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
            "longitude": ",".join(f"{p[1]:.4f}" for p in chunk),
            "hourly": VARIABLES,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "start_hour": f"{start:%Y-%m-%dT%H:00}",
            "end_hour": f"{end:%Y-%m-%dT%H:00}",
        },
        service="Weather service (Open-Meteo)",
    )
    if status == 429:
        raise ServiceError("The free weather service is busy (per-minute limit). Please try again in a minute.", 503)
    if status >= 400:
        reason = data.get("reason") if isinstance(data, dict) else ""
        raise UpstreamError(f"Weather service error: {reason or status}")
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items:
        h = item["hourly"]
        units = item.get("hourly_units", {})
        snow_factor = 1.0 if units.get("snowfall", "inch") == "inch" else 1 / 2.54  # cm -> inch safeguard

        def arr(name):
            return np.array([np.nan if v is None else v for v in h[name]], dtype=float)

        out.append(
            {
                "wind": arr("wind_speed_10m"),
                "gust": arr("wind_gusts_10m"),
                "rain": arr("rain") + np.nan_to_num(arr("showers")),
                "snow": arr("snowfall") * snow_factor,
            }
        )
    if len(out) != len(chunk):
        raise UpstreamError("Weather service returned an unexpected number of locations.")
    return out
