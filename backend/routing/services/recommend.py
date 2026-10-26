"""Route summaries and ranking (pure, no Django).

Ranking order from the brief: fewest Severe miles, fewest High miles, lowest average risk, shortest time.
"No Travel" is worse than Severe, so it is compared first: (no_travel, severe, high, avg_risk, duration).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .risk import LEVEL_ORDER

# Differences smaller than this are treated as ties so the reason text never says "fewer by 0.0 miles".
MILES_EPS = 0.05
RISK_EPS = 0.005


@dataclass
class RouteSummary:
    route_id: str
    duration_hours: float
    miles_by_level: dict[str, float]
    unknown_miles: float
    average_risk: float
    max_level: str | None

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level["No Travel"]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level["Severe"]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level["High"]

    def as_dict(self) -> dict:
        return {
            "miles_by_level": {k: round(v, 1) for k, v in self.miles_by_level.items()},
            "unknown_miles": round(self.unknown_miles, 1),
            "no_travel_miles": round(self.no_travel_miles, 1),
            "severe_miles": round(self.severe_miles, 1),
            "high_miles": round(self.high_miles, 1),
            "average_risk": round(self.average_risk, 3),
            "max_level": self.max_level,
            "has_no_travel": self.no_travel_miles > MILES_EPS,
        }


def summarize(route_id: str, duration_hours: float, checkpoints: list[tuple[float, int | None]]) -> RouteSummary:
    """checkpoints: (represented_miles, score) where score is 0–4 or None if the forecast is unavailable."""
    miles = {label: 0.0 for label in LEVEL_ORDER}
    unknown = 0.0
    weighted = 0.0
    known = 0.0
    worst = -1
    for seg, score in checkpoints:
        if score is None:
            unknown += seg
            continue
        miles[LEVEL_ORDER[score]] += seg
        weighted += seg * score
        known += seg
        worst = max(worst, score)
    return RouteSummary(
        route_id=route_id,
        duration_hours=duration_hours,
        miles_by_level=miles,
        unknown_miles=unknown,
        average_risk=weighted / known if known > 0 else 0.0,
        max_level=LEVEL_ORDER[worst] if worst >= 0 else None,
    )


def _q(value: float, eps: float) -> int:
    """Quantise so values closer than `eps` compare equal (used by both sorting and reasons)."""
    return round(value / eps)


def _key(s: RouteSummary):
    return (
        _q(s.no_travel_miles, MILES_EPS),
        _q(s.severe_miles, MILES_EPS),
        _q(s.high_miles, MILES_EPS),
        _q(s.average_risk, RISK_EPS),
        s.duration_hours,
    )


@dataclass
class Ranking:
    order: list[RouteSummary]
    reasons: dict[str, str] = field(default_factory=dict)
    warning: str | None = None


def _deciding_reason(better: RouteSummary, worse: RouteSummary) -> tuple[str, str]:
    """Why `better` beats `worse`, as (comparison, detail), using the first ranking criterion that differs.

    e.g. ("fewer High miles", "0 vs 25 mi") or ("same weather risk", "51 min faster").
    """
    checks = [
        ("No Travel miles", better.no_travel_miles, worse.no_travel_miles, MILES_EPS),
        ("Severe miles", better.severe_miles, worse.severe_miles, MILES_EPS),
        ("High miles", better.high_miles, worse.high_miles, MILES_EPS),
    ]
    for name, a, b, eps in checks:
        if _q(a, eps) != _q(b, eps):
            return f"fewer {name}", f"{a:.0f} vs {b:.0f} mi"
    if _q(better.average_risk, RISK_EPS) != _q(worse.average_risk, RISK_EPS):
        return "lower average risk", f"{better.average_risk:.3f} vs {worse.average_risk:.3f}"
    delta_min = (worse.duration_hours - better.duration_hours) * 60
    return "same weather risk", f"{delta_min:.0f} min faster"


def rank(summaries: list[RouteSummary]) -> Ranking:
    order = sorted(summaries, key=_key)
    reasons: dict[str, str] = {}
    if order:
        best = order[0]
        if len(order) == 1:
            reasons[best.route_id] = "Only route available"
        else:
            what, detail = _deciding_reason(best, order[1])
            if what == "same weather risk":
                reasons[best.route_id] = f"Same weather risk as the next option, but {detail}"
            else:
                reasons[best.route_id] = f"{what[0].upper()}{what[1:]} than the next option ({detail})"
        for n, (prev, cur) in enumerate(zip(order, order[1:]), start=1):
            what, detail = _deciding_reason(prev, cur)
            if what == "same weather risk":
                reasons[cur.route_id] = f"Same weather risk as #{n}, which is {detail}"
            else:
                reasons[cur.route_id] = f"#{n} has {what} ({detail})"

    warning = None
    if order and all(s.no_travel_miles > MILES_EPS for s in order):
        warning = "No safe route at this departure time: every option crosses No Travel conditions. Consider delaying."
    elif order and order[0].unknown_miles > MILES_EPS:
        warning = "Part of the trip is beyond the forecast horizon, so those miles are not scored."
    return Ranking(order=order, reasons=reasons, warning=warning)
