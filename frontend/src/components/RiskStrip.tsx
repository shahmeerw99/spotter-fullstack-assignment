import { memo } from "react";
import { riskColor } from "../lib/format";
import type { RouteOption } from "../types/api";

/**
 * A highway strip map: the whole trip as one bar, each checkpoint's stretch coloured by its risk.
 * Lets you compare routes without reading the map.
 */
export const RiskStrip = memo(function RiskStrip({ route }: { route: RouteOption }) {
  const total = route.distance_miles || 1;
  let start = 0;
  const segments = route.checkpoints.map((cp) => {
    const seg = { left: start, width: cp.represented_miles, cp };
    start += cp.represented_miles;
    return seg;
  });

  return (
    <div className="strip" role="img" aria-label={stripLabel(route)}>
      <div className="strip-bar">
        {segments.map(({ left, width, cp }, i) =>
          width > 0 ? (
            <span
              key={i}
              className={cp.risk ? "" : "no-data"}
              style={{ left: `${(left / total) * 100}%`, width: `${(width / total) * 100}%`, background: riskColor(cp.risk?.level) }}
            />
          ) : null,
        )}
      </div>
    </div>
  );
});

function stripLabel(route: RouteOption): string {
  const m = route.summary.miles_by_level;
  const parts = Object.entries(m)
    .filter(([, v]) => v > 0)
    .map(([k, v]) => `${Math.round(v)} miles ${k}`);
  return `Risk along the route: ${parts.join(", ")}`;
}
