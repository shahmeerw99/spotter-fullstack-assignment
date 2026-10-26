import { RISK_COLORS, RISK_LEVELS } from "../lib/format";

export function Legend() {
  return (
    <div className="legend" aria-label="Risk levels">
      {RISK_LEVELS.map((lvl, i) => (
        <span key={lvl}>
          <i style={{ background: RISK_COLORS[i] }} />
          {lvl}
        </span>
      ))}
    </div>
  );
}
