"""Weather risk rules from the assessment brief (pure, no Django).

Table boundaries are written as overlapping integer ranges in the brief (e.g. wind 25–34, 35–44), but
forecast values are decimals, so we use continuous half-open ranges:

    Wind (mph):    <25 Low | 25–<35 Moderate | 35–<45 High | 45–<55 Severe | >=55 No Travel
    Rain (in/hr):  <0.10 Low | 0.10–<0.25 Moderate | 0.25–<0.50 High | 0.50–1.00 Severe | >1.00 No Travel
    Snow (in/hr):  <0.5 Low | 0.5–<1.0 Moderate | 1.0–<2.0 High | 2.0–3.0 Severe | >3.0 No Travel

Load rules (wind + weight) can only make things worse, never better:
    wind >= 55                      -> No Travel (any load)
    45 <= wind < 55 and load > 30k  -> No Travel
    35 <= wind < 45 and load > 40k  -> Severe

The checkpoint level is the worst of wind (after load rules), rain and snow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Level(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self]


LEVEL_LABELS = {
    Level.LOW: "Low",
    Level.MODERATE: "Moderate",
    Level.HIGH: "High",
    Level.SEVERE: "Severe",
    Level.NO_TRAVEL: "No Travel",
}
LEVEL_ORDER = [LEVEL_LABELS[lvl] for lvl in Level]

# Which forecast variable drives the wind rule. Sustained 10 m wind is what the thresholds usually
# refer to; switch to "gust" to be more conservative.
WIND_SOURCE = "sustained"


def wind_level(mph: float) -> Level:
    if mph >= 55:
        return Level.NO_TRAVEL
    if mph >= 45:
        return Level.SEVERE
    if mph >= 35:
        return Level.HIGH
    if mph >= 25:
        return Level.MODERATE
    return Level.LOW


def rain_level(in_hr: float) -> Level:
    if in_hr > 1.0:
        return Level.NO_TRAVEL
    if in_hr >= 0.5:
        return Level.SEVERE
    if in_hr >= 0.25:
        return Level.HIGH
    if in_hr >= 0.10:
        return Level.MODERATE
    return Level.LOW


def snow_level(in_hr: float) -> Level:
    if in_hr > 3.0:
        return Level.NO_TRAVEL
    if in_hr >= 2.0:
        return Level.SEVERE
    if in_hr >= 1.0:
        return Level.HIGH
    if in_hr >= 0.5:
        return Level.MODERATE
    return Level.LOW


def apply_load_rules(wind_mph: float, load_lb: float, base: Level) -> tuple[Level, str | None]:
    """Return the (possibly raised) wind level and a description of the load rule that fired."""
    if wind_mph >= 55:
        return Level.NO_TRAVEL, "Wind ≥ 55 mph: No Travel for any load"
    if 45 <= wind_mph < 55 and load_lb > 30_000:
        return Level.NO_TRAVEL, "Wind 45–54 mph with load > 30,000 lb: No Travel"
    if 35 <= wind_mph < 45 and load_lb > 40_000:
        return max(base, Level.SEVERE), "Wind 35–44 mph with load > 40,000 lb: Severe"
    return base, None


@dataclass(frozen=True)
class Weather:
    wind_mph: float
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float


@dataclass
class Assessment:
    level: Level
    drivers: list[str] = field(default_factory=list)
    load_rule_applied: str | None = None
    by_condition: dict[str, str] = field(default_factory=dict)

    @property
    def score(self) -> int:
        return int(self.level)

    def as_dict(self) -> dict:
        return {
            "level": self.level.label,
            "score": self.score,
            "drivers": self.drivers,
            "load_rule_applied": self.load_rule_applied,
            "by_condition": self.by_condition,
        }


def assess(weather: Weather, load_lb: float) -> Assessment:
    wind_value = weather.gust_mph if WIND_SOURCE == "gust" else weather.wind_mph
    wind, rule = apply_load_rules(wind_value, load_lb, wind_level(wind_value))
    levels = {"wind": wind, "rain": rain_level(weather.rain_in_hr), "snow": snow_level(weather.snow_in_hr)}
    worst = max(levels.values())
    # Only name drivers when something is above Low; "Low because of nothing" isn't useful.
    drivers = [name for name, lvl in levels.items() if lvl == worst and worst > Level.LOW]
    return Assessment(
        level=worst,
        drivers=drivers,
        load_rule_applied=rule,
        by_condition={name: lvl.label for name, lvl in levels.items()},
    )


def score_grid(wind, gust, rain, snow, load_lb: float):
    """Vectorised risk score (0–4) for numpy arrays of any shape. Same rules as `assess`."""
    import numpy as np

    w = np.asarray(gust if WIND_SOURCE == "gust" else wind, dtype=float)
    r = np.asarray(rain, dtype=float)
    s = np.asarray(snow, dtype=float)

    wind_s = np.select([w >= 55, w >= 45, w >= 35, w >= 25], [4, 3, 2, 1], 0)
    if load_lb > 30_000:
        wind_s = np.where((w >= 45) & (w < 55), 4, wind_s)
    if load_lb > 40_000:
        wind_s = np.where((w >= 35) & (w < 45), np.maximum(wind_s, 3), wind_s)
    rain_s = np.select([r > 1.0, r >= 0.5, r >= 0.25, r >= 0.10], [4, 3, 2, 1], 0)
    snow_s = np.select([s > 3.0, s >= 2.0, s >= 1.0, s >= 0.5], [4, 3, 2, 1], 0)
    out = np.maximum(np.maximum(wind_s, rain_s), snow_s)
    # Missing data (NaN) -> -1 so the client can draw it as "no data".
    missing = np.isnan(w) | np.isnan(r) | np.isnan(s)
    return np.where(missing, -1, out).astype(np.int8)
