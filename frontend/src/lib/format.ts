import type { RiskLevel } from "../types/api";

export const RISK_LEVELS: RiskLevel[] = ["Low", "Moderate", "High", "Severe", "No Travel"];

/** Index = risk score (0..4). Kept in sync with the CSS custom properties. */
export const RISK_COLORS = ["#3FA45B", "#E9C02A", "#EE8A22", "#D3263A", "#3E1A55"];
export const NO_DATA_COLOR = "#9AA5AD";

export function riskColor(level: RiskLevel | null | undefined): string {
  if (!level) return NO_DATA_COLOR;
  return RISK_COLORS[RISK_LEVELS.indexOf(level)];
}

const timeFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
const hourFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric" });
const dayFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

export const formatTime = (iso: string) => timeFmt.format(new Date(iso));
export const formatHour = (iso: string) => hourFmt.format(new Date(iso));
export const formatDay = (iso: string) => dayFmt.format(new Date(iso));

export function formatDuration(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return m === 60 ? `${h + 1} h` : h === 0 ? `${m} min` : `${h} h ${m.toString().padStart(2, "0")} min`;
}

export const formatMiles = (mi: number) => `${Math.round(mi).toLocaleString()} mi`;
/** Value for <input type="datetime-local"> in the browser's zone. */
export function toLocalInputValue(d: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** "2026-10-25T08:00" (local) -> "2026-10-25T08:00:00-05:00" so the server keeps the driver's offset. */
export function localInputToIso(value: string): string {
  const d = new Date(value);
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${value.length === 16 ? `${value}:00` : value}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}
