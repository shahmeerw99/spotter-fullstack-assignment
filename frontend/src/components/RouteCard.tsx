import { memo } from "react";
import { formatDuration, formatMiles, formatTime, riskColor, RISK_LEVELS } from "../lib/format";
import type { RouteOption } from "../types/api";
import { RiskStrip } from "./RiskStrip";

interface Props {
  route: RouteOption;
  selected: boolean;
  onSelect: (id: string) => void;
}

export const RouteCard = memo(function RouteCard({ route, selected, onSelect }: Props) {
  const s = route.summary;
  const cls = ["route-card", selected && "selected", route.recommended && "recommended"].filter(Boolean).join(" ");

  return (
    <article className={cls}>
      <button className="route-card-hit" onClick={() => onSelect(route.id)} aria-pressed={selected}>
        <header>
          <span className="rank" aria-label={`Rank ${route.rank}`}>
            {route.rank}
          </span>
          <div className="headline">
            <strong>{route.recommended ? "Recommended route" : `Option ${route.rank}`}</strong>
            <span className="reason">{route.recommendation_reason}</span>
          </div>
        </header>

        <dl className="facts">
          <div>
            <dt>Distance</dt>
            <dd>{formatMiles(route.distance_miles)}</dd>
          </div>
          <div>
            <dt>Drive time</dt>
            <dd>{formatDuration(route.duration_hours)}</dd>
          </div>
          <div>
            <dt>Arrives</dt>
            <dd>{formatTime(route.arrival)}</dd>
          </div>
        </dl>

        <RiskStrip route={route} />

        <ul className="levels">
          {RISK_LEVELS.map((lvl) => {
            const mi = s.miles_by_level[lvl];
            if (mi < 0.5 && lvl !== "Severe" && lvl !== "High") return null;
            return (
              <li key={lvl} className={mi < 0.5 ? "zero" : ""}>
                <i style={{ background: riskColor(lvl) }} />
                {lvl} <b>{Math.round(mi)}</b> mi
              </li>
            );
          })}
          {s.unknown_miles > 0.5 && (
            <li className="unknown">
              <i style={{ background: riskColor(null) }} />
              No forecast <b>{Math.round(s.unknown_miles)}</b> mi
            </li>
          )}
          <li className="avg">
            Avg risk <b>{s.average_risk.toFixed(2)}</b>
          </li>
        </ul>

      </button>
    </article>
  );
});
