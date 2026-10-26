import type { Checkpoint, RouteOption } from "../types/api";

type LatLng = [number, number];

const R_MILES = 3958.7613;
const rad = (d: number) => (d * Math.PI) / 180;

export function haversine(a: LatLng, b: LatLng): number {
  const dLat = rad(b[0] - a[0]);
  const dLon = rad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLon / 2) ** 2;
  return 2 * R_MILES * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function routeLatLngs(route: RouteOption): LatLng[] {
  return route.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
}

/**
 * Split the route line into pieces, one per checkpoint stretch, so the selected route can be drawn in
 * risk colours. Distances are scaled to the routing engine's road distance to match checkpoint miles.
 */
export function splitByCheckpoints(route: RouteOption): { latlngs: LatLng[]; checkpoint: Checkpoint }[] {
  const pts = routeLatLngs(route);
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + haversine(pts[i - 1], pts[i]));
  const scale = cum[cum.length - 1] > 0 ? route.distance_miles / cum[cum.length - 1] : 1;
  for (let i = 0; i < cum.length; i++) cum[i] *= scale;

  const at = (mile: number): LatLng => {
    let i = 1;
    while (i < cum.length - 1 && cum[i] < mile) i++;
    const span = cum[i] - cum[i - 1] || 1;
    const t = Math.min(1, Math.max(0, (mile - cum[i - 1]) / span));
    return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t];
  };

  const pieces: { latlngs: LatLng[]; checkpoint: Checkpoint }[] = [];
  let start = 0;
  for (const cp of route.checkpoints) {
    const end = start + cp.represented_miles;
    if (end > start) {
      const line: LatLng[] = [at(start)];
      for (let i = 0; i < cum.length; i++) if (cum[i] > start && cum[i] < end) line.push(pts[i]);
      line.push(at(end));
      pieces.push({ latlngs: line, checkpoint: cp });
    }
    start = end;
  }
  return pieces;
}

/** Where the truck is at `iso` time, interpolated between checkpoint ETAs. Null before/after the trip. */
export function positionAt(route: RouteOption, iso: string): LatLng | null {
  const t = new Date(iso).getTime();
  const cps = route.checkpoints;
  const times = cps.map((c) => new Date(c.eta).getTime());
  if (t < times[0] || t > times[times.length - 1]) return null;
  for (let i = 1; i < cps.length; i++) {
    if (t <= times[i]) {
      const f = (t - times[i - 1]) / (times[i] - times[i - 1] || 1);
      return [cps[i - 1].lat + (cps[i].lat - cps[i - 1].lat) * f, cps[i - 1].lon + (cps[i].lon - cps[i - 1].lon) * f];
    }
  }
  return null;
}
