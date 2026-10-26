import type { Analysis, Heatmap, TripInput } from "../types/api";

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection, or wait a moment if the server is waking up.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(describeError(body, res.status));
  }
  return body as T;
}

function describeError(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const b = body as { error?: string; fields?: Record<string, string[]> };
    if (b.fields) {
      const first = Object.entries(b.fields)[0];
      if (first) return `${first[0] === "non_field_errors" ? "" : `${first[0].replace(/_/g, " ")}: `}${first[1][0]}`;
    }
    if (b.error) return b.error;
  }
  return `Request failed (HTTP ${status}).`;
}

export function analyzeTrip(input: TripInput, signal?: AbortSignal): Promise<Analysis> {
  return request<Analysis>("/api/routes/analyze", { method: "POST", body: JSON.stringify(input), signal });
}

export function fetchHeatmap(analysisId: string, signal?: AbortSignal): Promise<Heatmap> {
  return request<Heatmap>(`/api/heatmap?analysis_id=${encodeURIComponent(analysisId)}`, { signal });
}
