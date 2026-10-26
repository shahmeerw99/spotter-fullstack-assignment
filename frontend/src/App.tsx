import { useCallback, useEffect, useState } from "react";
import { Legend } from "./components/Legend";
import { RouteCard } from "./components/RouteCard";
import { RouteMap } from "./components/RouteMap";
import { TimeSlider } from "./components/TimeSlider";
import { TripForm } from "./components/TripForm";
import { useTripAnalysis } from "./hooks/useTripAnalysis";
import { formatTime } from "./lib/format";

export default function App() {
  const { status, analysis, error, heatmap, heatmapError, run } = useTripAnalysis();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hour, setHour] = useState(0);
  const [heatVisible, setHeatVisible] = useState(true);

  useEffect(() => {
    if (analysis) setSelectedId(analysis.routes[0]?.id ?? null);
    setHour(0);
  }, [analysis]);

  const onSelect = useCallback((id: string) => setSelectedId(id), []);
  const loading = status === "loading";

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
            <rect x="1" y="1" width="30" height="30" rx="6" fill="#0B6B4B" />
            <path d="M8 23 L14 10 L18 17 L24 8" stroke="#fff" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <h1>Safe Haul</h1>
            <p>Pick the safest of three routes using the forecast at the hour you'll reach each stretch.</p>
          </div>
        </header>

        <TripForm loading={loading} onSubmit={run} />

        <div className="results" aria-live="polite" aria-busy={loading}>
          {status === "error" && error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}
          {loading && <LoadingCards />}
          {!loading && analysis && (
            <>
              <div className="results-head">
                <h2>
                  {analysis.routes.length} {analysis.routes.length === 1 ? "route" : "routes"} from{" "}
                  {short(analysis.origin.label)} to {short(analysis.destination.label)}
                </h2>
                <p>
                  Leaving {formatTime(analysis.departure_time)} with {analysis.load_weight_lb.toLocaleString()} lb, weather
                  checked every {analysis.checkpoint_interval_miles} mi.
                </p>
              </div>
              {analysis.warning && <div className="notice warn">{analysis.warning}</div>}
              {analysis.routes.length < 3 && (
                <div className="notice">Only {analysis.routes.length} distinct road options exist between these points.</div>
              )}
              {analysis.routes.map((r) => (
                <RouteCard key={r.id} route={r} selected={r.id === selectedId} onSelect={onSelect} />
              ))}
              <details className="assumptions">
                <summary>How routes are scored</summary>
                <ul>
                  <li>Each checkpoint uses the hourly forecast for the hour the truck reaches it, and stands for the road halfway to its neighbours.</li>
                  <li>Wind uses sustained 10 m speed. Gusts are shown for reference. Heavy loads raise wind risk: over 30,000 lb in 45–54 mph wind is No Travel, and over 40,000 lb in 35–44 mph wind is Severe.</li>
                  {analysis.weather_grid_deg > 0.1 && (
                    <li>
                      This is a long trip, so nearby checkpoints share forecast cells about{" "}
                      {Math.round(analysis.weather_grid_deg * 69)} miles across. That keeps the analysis within the free
                      weather service's limits.
                    </li>
                  )}
                  <li>Routes are ranked by No Travel miles, then Severe miles, High miles, average risk and drive time.</li>
                  <li>Drive times come from a car routing profile (OSRM). Real truck times will be somewhat longer.</li>
                </ul>
              </details>
            </>
          )}
          {status === "idle" && (
            <div className="empty">
              <p>Enter a trip to compare three routes by the weather each one will meet along the way.</p>
            </div>
          )}
        </div>
      </aside>

      <main className="map-area">
        <RouteMap
          analysis={analysis}
          selectedId={selectedId}
          onSelect={onSelect}
          heatmap={heatmap}
          heatmapVisible={heatVisible}
          hour={hour}
        />
        <div className="map-overlay">
          <Legend />
          <TimeSlider
            data={heatmap}
            error={heatmapError}
            loading={status === "done" && !heatmap && !heatmapError}
            hour={hour}
            onHour={setHour}
            visible={heatVisible}
            onVisible={setHeatVisible}
          />
        </div>
      </main>
    </div>
  );
}

function short(label: string) {
  return label.split(",")[0];
}

function LoadingCards() {
  return (
    <div className="loading">
      <p>Finding routes and reading the forecast along each one…</p>
      {[0, 1, 2].map((i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  );
}
