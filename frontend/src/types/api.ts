export type RiskLevel = "Low" | "Moderate" | "High" | "Severe" | "No Travel";

export interface Place {
  query: string;
  label: string;
  lat: number;
  lon: number;
}

export interface Weather {
  wind_mph: number;
  gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
}

export interface Risk {
  level: RiskLevel;
  score: number;
  drivers: string[];
  load_rule_applied: string | null;
  by_condition: Record<"wind" | "rain" | "snow", RiskLevel>;
}

export interface Checkpoint {
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  forecast_hour: string;
  represented_miles: number;
  status: "ok" | "forecast_unavailable";
  weather: Weather | null;
  risk: Risk | null;
}

export interface RouteSummary {
  miles_by_level: Record<RiskLevel, number>;
  unknown_miles: number;
  no_travel_miles: number;
  severe_miles: number;
  high_miles: number;
  average_risk: number;
  max_level: RiskLevel | null;
  has_no_travel: boolean;
}

export interface RouteOption {
  id: string;
  source: "osrm" | "osrm-via";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  distance_miles: number;
  duration_hours: number;
  arrival: string;
  checkpoints: Checkpoint[];
  summary: RouteSummary;
  rank: number;
  recommended: boolean;
  recommendation_reason: string;
}

export interface Analysis {
  analysis_id: string;
  origin: Place;
  destination: Place;
  departure_time: string;
  load_weight_lb: number;
  checkpoint_interval_miles: number;
  routes: RouteOption[];
  warning: string | null;
  corridor_bbox: [number, number, number, number];
  forecast_horizon_end: string;
  weather_grid_deg: number;
  weather_locations: number;
  timings_ms: Record<string, number>;
  cached: boolean;
}

export interface Heatmap {
  points: [number, number][];
  cell: { dlat: number; dlon: number };
  hours: string[];
  /** values[hour][point] = risk score 0..4, -1 = no data */
  values: number[][];
  wind_mph: number[][];
  load_weight_lb: number;
}

export interface TripInput {
  origin: string;
  destination: string;
  departure_time: string;
  load_weight_lb: number;
  checkpoint_interval_miles: 10 | 25 | 50;
}
