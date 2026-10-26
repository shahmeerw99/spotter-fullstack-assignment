import { useCallback, useRef, useState } from "react";
import { analyzeTrip, ApiError, fetchHeatmap } from "../api/client";
import type { Analysis, Heatmap, TripInput } from "../types/api";

type Status = "idle" | "loading" | "done" | "error";

/** Runs an analysis, then loads the corridor heatmap in the background. Older requests are aborted. */
export function useTripAnalysis() {
  const [status, setStatus] = useState<Status>("idle");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  const run = useCallback(async (input: TripInput) => {
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    setStatus("loading");
    setError(null);
    setHeatmap(null);
    setHeatmapError(null);
    try {
      const result = await analyzeTrip(input, ctrl.signal);
      if (ctrl.signal.aborted) return;
      setAnalysis(result);
      setStatus("done");
      fetchHeatmap(result.analysis_id, ctrl.signal)
        .then((h) => !ctrl.signal.aborted && setHeatmap(h))
        .catch((e) => !ctrl.signal.aborted && setHeatmapError(e instanceof ApiError ? e.message : "Heatmap failed to load."));
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setStatus("error");
      setError(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
    }
  }, []);

  return { status, analysis, error, heatmap, heatmapError, run };
}
