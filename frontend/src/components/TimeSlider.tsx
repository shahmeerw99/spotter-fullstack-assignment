import { memo, useEffect, useMemo, useRef, useState } from "react";
import { formatDay, formatHour, NO_DATA_COLOR, RISK_COLORS } from "../lib/format";
import type { Heatmap } from "../types/api";
import { worstPerHour } from "./HeatmapLayer";

interface Props {
  data: Heatmap | null;
  error: string | null;
  loading: boolean;
  hour: number;
  onHour: (h: number) => void;
  visible: boolean;
  onVisible: (v: boolean) => void;
}

/** Forecast hour control docked under the map. Data is already loaded, so scrubbing is purely local. */
export function TimeSlider({ data, error, loading, hour, onHour, visible, onVisible }: Props) {
  const [playing, setPlaying] = useState(false);
  const hourRef = useRef(hour);
  hourRef.current = hour;
  const max = (data?.hours.length ?? 49) - 1;

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const next = hourRef.current >= max ? 0 : hourRef.current + 1;
      onHour(next);
    }, 350);
    return () => window.clearInterval(id);
  }, [playing, max, onHour]);

  useEffect(() => {
    if (!data) setPlaying(false);
  }, [data]);

  const iso = data?.hours[hour];

  return (
    <section className="time-panel" aria-label="Weather forecast timeline">
      <div className="time-top">
        <label className="toggle">
          <input type="checkbox" checked={visible} onChange={(e) => onVisible(e.target.checked)} />
          <span>Weather risk overlay</span>
        </label>
        <div className="time-readout" aria-live="polite">
          {iso ? (
            <>
              <strong>{formatHour(iso)}</strong> <span>{formatDay(iso)}</span>
              <em>{hour === 0 ? "at departure" : `${hour} h after departure`}</em>
              <i className="truck-key" aria-hidden="true" />
              <em>truck</em>
            </>
          ) : loading ? (
            <span>Loading forecast for the corridor…</span>
          ) : error ? (
            <span className="err">{error}</span>
          ) : (
            <span>Compare routes to load the 48-hour forecast</span>
          )}
        </div>
      </div>
      <div className="time-controls">
        <button
          type="button"
          className="play"
          onClick={() => setPlaying((p) => !p)}
          disabled={!data}
          aria-label={playing ? "Pause" : "Play forecast"}
        >
          {playing ? (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <rect x="3" y="2" width="3.5" height="12" rx="1" fill="currentColor" />
              <rect x="9.5" y="2" width="3.5" height="12" rx="1" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M4 2.5v11l9.5-5.5z" fill="currentColor" />
            </svg>
          )}
        </button>
        <div className="slider-wrap">
          {data && <HourTrack data={data} />}
          <input
            type="range"
            min={0}
            max={max}
            step={1}
            value={hour}
            disabled={!data}
            onChange={(e) => {
              setPlaying(false);
              onHour(Number(e.target.value));
            }}
            aria-label="Forecast hour"
            aria-valuetext={iso ? `${formatHour(iso)}, ${hour} hours after departure` : undefined}
          />
          <div className="ticks" aria-hidden="true">
            {[0, 12, 24, 36, 48].map((h) => (
              <span key={h} style={{ left: `${(h / 48) * 100}%` }}>
                {h === 0 ? "Depart" : `+${h} h`}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/** Worst risk anywhere in the corridor for each hour: shows where it's worth scrubbing to. */
const HourTrack = memo(function HourTrack({ data }: { data: Heatmap }) {
  const worst = useMemo(() => worstPerHour(data), [data]);
  return (
    <div className="hour-track" aria-hidden="true">
      {worst.map((w, i) => (
        <span key={i} style={{ background: w < 0 ? NO_DATA_COLOR : RISK_COLORS[w] }} />
      ))}
    </div>
  );
});
