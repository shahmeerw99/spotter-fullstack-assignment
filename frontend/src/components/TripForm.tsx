import { useState, type FormEvent } from "react";
import { localInputToIso, toLocalInputValue } from "../lib/format";
import type { TripInput } from "../types/api";

interface Props {
  loading: boolean;
  onSubmit: (input: TripInput) => void;
}

const INTERVALS = [10, 25, 50] as const;

const EXAMPLES: { label: string; origin: string; destination: string }[] = [
  { label: "Dallas to Denver", origin: "Dallas, TX", destination: "Denver, CO" },
  { label: "Chicago to Salt Lake City", origin: "Chicago, IL", destination: "Salt Lake City, UT" },
  { label: "Seattle to Boise", origin: "Seattle, WA", destination: "Boise, ID" },
];

export function TripForm({ loading, onSubmit }: Props) {
  const [origin, setOrigin] = useState("Dallas, TX");
  const [destination, setDestination] = useState("Denver, CO");
  const [departure, setDeparture] = useState(() => {
    const d = new Date();
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + 1);
    return toLocalInputValue(d);
  });
  const [load, setLoad] = useState("42000");
  const [interval, setInterval] = useState<(typeof INTERVALS)[number]>(25);

  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit({
      origin: origin.trim(),
      destination: destination.trim(),
      departure_time: localInputToIso(departure),
      load_weight_lb: Number(load),
      checkpoint_interval_miles: interval,
    });
  }

  function swap() {
    setOrigin(destination);
    setDestination(origin);
  }

  return (
    <form className="trip-form" onSubmit={submit} aria-busy={loading}>
      <div className="od">
        <label className="field">
          <span>From</span>
          <input value={origin} onChange={(e) => setOrigin(e.target.value)} required placeholder="City, ST or lat,lon" autoComplete="off" />
        </label>
        <button type="button" className="swap" onClick={swap} aria-label="Swap origin and destination" title="Swap">
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
            <path d="M6 3v12M6 15l-3-3M6 15l3-3M14 17V5M14 5l-3 3M14 5l3 3" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round" />
          </svg>
        </button>
        <label className="field">
          <span>To</span>
          <input value={destination} onChange={(e) => setDestination(e.target.value)} required placeholder="City, ST or lat,lon" autoComplete="off" />
        </label>
      </div>

      <label className="field">
        <span>Departure</span>
        <input type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)} required />
      </label>

      <div className="row">
        <label className="field">
          <span>Load (lb)</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={200000}
            step={500}
            value={load}
            onChange={(e) => setLoad(e.target.value)}
            required
          />
        </label>
        <fieldset className="interval">
          <legend>Check weather every</legend>
          <div className="segmented">
            {INTERVALS.map((n) => (
              <label key={n} className={interval === n ? "on" : ""}>
                <input type="radio" name="interval" value={n} checked={interval === n} onChange={() => setInterval(n)} />
                {n} mi
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <button className="primary" type="submit" disabled={loading}>
        {loading ? "Checking routes…" : "Compare routes"}
      </button>

      <p className="examples">
        Try{" "}
        {EXAMPLES.map((ex, i) => (
          <span key={ex.label}>
            <button
              type="button"
              className="link"
              onClick={() => {
                setOrigin(ex.origin);
                setDestination(ex.destination);
              }}
            >
              {ex.label}
            </button>
            {i < EXAMPLES.length - 1 ? ", " : ""}
          </span>
        ))}
      </p>
    </form>
  );
}
