"""Vectorised geo helpers (numpy only, no Django).

Coordinates inside this module are (lat, lon) numpy arrays unless stated otherwise.
GeoJSON output is [lon, lat] as the spec requires.
"""

from __future__ import annotations

import math

import numpy as np

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles. Works on scalars or numpy arrays (broadcasting)."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def segment_miles(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Length of each consecutive segment (n-1 values)."""
    return haversine_miles(lats[:-1], lons[:-1], lats[1:], lons[1:])


def cumulative_miles(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Cumulative distance from the first point (n values, starts at 0)."""
    out = np.zeros(len(lats))
    if len(lats) > 1:
        out[1:] = np.cumsum(segment_miles(lats, lons))
    return out


def interpolate_along(cum: np.ndarray, lats: np.ndarray, lons: np.ndarray, at_miles) -> tuple[np.ndarray, np.ndarray]:
    """Position(s) at given distance(s) along a polyline (linear between vertices)."""
    at = np.clip(np.asarray(at_miles, dtype=float), 0.0, cum[-1])
    return np.interp(at, cum, lats), np.interp(at, cum, lons)


def checkpoint_miles(total_miles: float, interval: float) -> np.ndarray:
    """0, interval, 2*interval, ... plus the destination. Origin and destination are always included."""
    if total_miles <= 0:
        return np.array([0.0])
    marks = np.arange(0.0, total_miles, interval)
    if total_miles - marks[-1] < 1e-6:
        marks[-1] = total_miles
    else:
        marks = np.append(marks, total_miles)
    return marks


def represented_miles(marks: np.ndarray) -> np.ndarray:
    """Road length each checkpoint stands for: half the gap before + half the gap after.

    The first and last checkpoint only get the inside half, so the result sums to the route length.
    """
    if len(marks) == 1:
        return np.array([0.0])
    gaps = np.diff(marks)
    out = np.zeros(len(marks))
    out[:-1] += gaps / 2
    out[1:] += gaps / 2
    return out


def downsample_by_distance(cum: np.ndarray, step_miles: float) -> np.ndarray:
    """Indices of vertices spaced roughly `step_miles` apart (always keeps first and last)."""
    if len(cum) <= 2:
        return np.arange(len(cum))
    buckets = np.floor(cum / step_miles)
    keep = np.concatenate(([True], buckets[1:] != buckets[:-1]))
    keep[-1] = True
    return np.flatnonzero(keep)


def _project(lats, lons, ref_lat: float):
    """Equirectangular projection to miles. Accurate to well under 1% over a few dozen miles."""
    k = EARTH_RADIUS_MILES * math.pi / 180.0
    return np.asarray(lons) * k * math.cos(math.radians(ref_lat)), np.asarray(lats) * k


def nearest_on_route(
    pt_lats: np.ndarray,
    pt_lons: np.ndarray,
    route_lats: np.ndarray,
    route_lons: np.ndarray,
    chunk: int = 512,
) -> tuple[np.ndarray, np.ndarray]:
    """For each point, the index of the nearest route vertex and the distance to it in miles.

    The route should be densified/downsampled to about 1 vertex per mile first; with ~1 mile spacing the
    vertex distance is within ~0.5 mile of the true distance to the polyline, which is plenty for a
    40-mile weather corridor.
    """
    n = len(pt_lats)
    if n == 0:
        return np.zeros(0, dtype=int), np.zeros(0)
    ref = float(np.mean(route_lats))
    rx, ry = _project(route_lats, route_lons, ref)
    px, py = _project(pt_lats, pt_lons, ref)
    idx = np.empty(n, dtype=int)
    dist = np.empty(n)
    for start in range(0, n, chunk):
        sl = slice(start, start + chunk)
        d2 = (px[sl, None] - rx[None, :]) ** 2 + (py[sl, None] - ry[None, :]) ** 2
        best = np.argmin(d2, axis=1)
        idx[sl] = best
        dist[sl] = np.sqrt(d2[np.arange(len(best)), best])
    return idx, dist


def densify(lats: np.ndarray, lons: np.ndarray, cum: np.ndarray, step_miles: float = 1.0):
    """Evenly spaced points every `step_miles` along the route (fills long straight segments too)."""
    marks = np.arange(0.0, cum[-1] + step_miles, step_miles)
    marks[-1] = min(marks[-1], cum[-1])
    la, lo = interpolate_along(cum, lats, lons, marks)
    return la, lo, marks


def bbox(lats: np.ndarray, lons: np.ndarray) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat)."""
    return float(np.min(lons)), float(np.min(lats)), float(np.max(lons)), float(np.max(lats))


def expand_bbox(box, miles: float):
    min_lon, min_lat, max_lon, max_lat = box
    dlat = miles / 69.0
    mid = math.radians((min_lat + max_lat) / 2)
    dlon = miles / (69.0 * max(math.cos(mid), 0.2))
    return min_lon - dlon, min_lat - dlat, max_lon + dlon, max_lat + dlat


def simplify(lats: np.ndarray, lons: np.ndarray, tolerance_deg: float = 0.002) -> np.ndarray:
    """Douglas–Peucker simplification (iterative). Returns indices of kept vertices.

    0.002 degrees is ~200 m: invisible at map zoom levels used for long trips, but cuts point count ~10x.
    """
    n = len(lats)
    if n < 3:
        return np.arange(n)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    x, y = lons, lats
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        xs, ys = x[a + 1 : b], y[a + 1 : b]
        dx, dy = x[b] - x[a], y[b] - y[a]
        seg_len2 = dx * dx + dy * dy
        if seg_len2 == 0:
            d = np.hypot(xs - x[a], ys - y[a])
        else:
            t = np.clip(((xs - x[a]) * dx + (ys - y[a]) * dy) / seg_len2, 0, 1)
            d = np.hypot(xs - (x[a] + t * dx), ys - (y[a] + t * dy))
        i = int(np.argmax(d))
        if d[i] > tolerance_deg:
            mid = a + 1 + i
            keep[mid] = True
            stack.append((a, mid))
            stack.append((mid, b))
    return np.flatnonzero(keep)


def perpendicular_offset_point(lat1, lon1, lat2, lon2, fraction: float) -> tuple[float, float]:
    """Midpoint of the straight line A→B shifted sideways by `fraction` of the A→B distance.

    Positive fraction = left of the travel direction. Used to force alternative routes when the
    routing engine returns fewer than 3.
    """
    ref = (lat1 + lat2) / 2
    k = math.cos(math.radians(ref))
    ax, ay = lon1 * k, lat1
    bx, by = lon2 * k, lat2
    mx, my = (ax + bx) / 2, (ay + by) / 2
    dx, dy = bx - ax, by - ay
    # Left normal of (dx, dy) is (-dy, dx); its length equals the A→B length.
    ox, oy = mx - dy * fraction, my + dx * fraction
    return oy, ox / k


def overlap_fraction(a_lats, a_lons, b_lats, b_lons, tolerance_miles: float = 3.0) -> float:
    """Share of route A's (downsampled) points lying within `tolerance_miles` of route B."""
    _, d = nearest_on_route(np.asarray(a_lats), np.asarray(a_lons), np.asarray(b_lats), np.asarray(b_lons))
    if len(d) == 0:
        return 1.0
    return float(np.mean(d <= tolerance_miles))
