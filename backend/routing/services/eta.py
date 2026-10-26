"""ETA along a route (pure, no Django)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np


def cumulative_seconds(segment_seconds: np.ndarray | None, cum_miles: np.ndarray, total_seconds: float) -> np.ndarray:
    """Cumulative travel time at every route vertex.

    Uses per-segment durations from the routing engine when available (so slow city stretches and fast
    interstate stretches get realistic ETAs). Otherwise falls back to scaling linearly by distance.
    """
    if segment_seconds is not None and len(segment_seconds) == len(cum_miles) - 1:
        out = np.zeros(len(cum_miles))
        out[1:] = np.cumsum(segment_seconds)
        # Keep the engine's headline duration authoritative (annotation sums can drift by a few seconds).
        if out[-1] > 0:
            out *= total_seconds / out[-1]
        return out
    if cum_miles[-1] <= 0:
        return np.zeros(len(cum_miles))
    return cum_miles / cum_miles[-1] * total_seconds


def eta_at_miles(departure: datetime, cum_miles: np.ndarray, cum_secs: np.ndarray, at_miles) -> list[datetime]:
    secs = np.interp(np.asarray(at_miles, dtype=float), cum_miles, cum_secs)
    return [departure + timedelta(seconds=float(s)) for s in np.atleast_1d(secs)]


def round_to_hour(dt: datetime) -> datetime:
    """Nearest whole hour (forecasts are hourly)."""
    base = dt.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(hours=1) if dt - base >= timedelta(minutes=30) else base
