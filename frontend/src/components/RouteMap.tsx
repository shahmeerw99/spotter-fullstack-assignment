import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { memo, useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { positionAt, routeLatLngs, splitByCheckpoints } from "../lib/geometry";
import { formatTime, riskColor } from "../lib/format";
import type { Analysis, Checkpoint, Heatmap, RouteOption } from "../types/api";
import { HeatmapLayer } from "./HeatmapLayer";

interface Props {
  analysis: Analysis | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  heatmap: Heatmap | null;
  heatmapVisible: boolean;
  hour: number;
}

const US_CENTER: [number, number] = [39.5, -98.35];

export function RouteMap({ analysis, selectedId, onSelect, heatmap, heatmapVisible, hour }: Props) {
  const selected = analysis?.routes.find((r) => r.id === selectedId) ?? null;
  const hourIso = heatmap?.hours[hour];

  return (
    <MapContainer center={US_CENTER} zoom={4} preferCanvas zoomControl={false} className="map" worldCopyJump>
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
        className="osm-tiles"
      />
      <ZoomControlRight />
      {heatmap && <HeatmapLayer data={heatmap} hour={hour} visible={heatmapVisible} />}
      {analysis && <RoutesLayer analysis={analysis} selectedId={selectedId} onSelect={onSelect} />}
      {analysis && <Endpoints analysis={analysis} />}
      {selected && hourIso && heatmapVisible && <TruckMarker route={selected} iso={hourIso} />}
      <FitTo analysis={analysis} selected={selected} />
    </MapContainer>
  );
}

function ZoomControlRight() {
  const map = useMap();
  useEffect(() => {
    const ctl = L.control.zoom({ position: "topright" }).addTo(map);
    return () => {
      ctl.remove();
    };
  }, [map]);
  return null;
}

/** Fit to all routes on a new analysis, then to the selected route when it changes. */
function FitTo({ analysis, selected }: { analysis: Analysis | null; selected: RouteOption | null }) {
  const map = useMap();
  useEffect(() => {
    if (!selected) return;
    const bounds = L.latLngBounds(routeLatLngs(selected));
    const narrow = window.matchMedia("(max-width: 860px)").matches;
    map.flyToBounds(bounds, {
      paddingTopLeft: [30, 30],
      paddingBottomRight: [30, narrow ? 120 : 150],
      duration: 0.6,
    });
  }, [map, selected, analysis]);
  return null;
}

/** All routes. Memoised so the heatmap slider never re-renders these layers. */
const RoutesLayer = memo(function RoutesLayer({
  analysis,
  selectedId,
  onSelect,
}: {
  analysis: Analysis;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const others = analysis.routes.filter((r) => r.id !== selectedId);
  const selected = analysis.routes.find((r) => r.id === selectedId);
  return (
    <>
      {others.map((r) => (
        <OtherRoute key={r.id} route={r} onSelect={onSelect} />
      ))}
      {selected && <SelectedRoute key={selected.id} route={selected} />}
    </>
  );
});

const OtherRoute = memo(function OtherRoute({ route, onSelect }: { route: RouteOption; onSelect: (id: string) => void }) {
  const latlngs = useMemo(() => routeLatLngs(route), [route]);
  const handlers = useMemo(() => ({ click: () => onSelect(route.id) }), [onSelect, route.id]);
  return (
    <>
      <Polyline positions={latlngs} pathOptions={{ color: "#ffffff", weight: 8, opacity: 0.9 }} eventHandlers={handlers} />
      <Polyline positions={latlngs} pathOptions={{ color: "#6E7D88", weight: 4, opacity: 0.85 }} eventHandlers={handlers}>
        <Tooltip sticky>
          {route.recommended ? "Recommended route" : `Option ${route.rank}`}: click to inspect
        </Tooltip>
      </Polyline>
      {route.checkpoints.map((cp, i) => (
        <CircleMarker
          key={i}
          center={[cp.lat, cp.lon]}
          radius={2.5}
          pathOptions={{ stroke: false, fillColor: riskColor(cp.risk?.level), fillOpacity: 0.9 }}
          eventHandlers={handlers}
        />
      ))}
    </>
  );
});

const SelectedRoute = memo(function SelectedRoute({ route }: { route: RouteOption }) {
  const latlngs = useMemo(() => routeLatLngs(route), [route]);
  const pieces = useMemo(() => splitByCheckpoints(route), [route]);
  return (
    <>
      <Polyline positions={latlngs} pathOptions={{ color: "#1D2A30", weight: 11, opacity: 0.9 }} interactive={false} />
      {pieces.map((p, i) => (
        <Polyline
          key={i}
          positions={p.latlngs}
          pathOptions={{ color: riskColor(p.checkpoint.risk?.level), weight: 6, opacity: 1, lineCap: "butt" }}
          interactive={false}
        />
      ))}
      {route.checkpoints.map((cp, i) => (
        <CircleMarker
          key={i}
          center={[cp.lat, cp.lon]}
          radius={5.5}
          pathOptions={{ color: "#1D2A30", weight: 1.5, fillColor: riskColor(cp.risk?.level), fillOpacity: 1 }}
        >
          <Popup>
            <CheckpointPopup cp={cp} />
          </Popup>
        </CircleMarker>
      ))}
    </>
  );
});

function CheckpointPopup({ cp }: { cp: Checkpoint }) {
  return (
    <div className="cp-popup">
      <div className="cp-head">
        <span className="pill" style={{ background: riskColor(cp.risk?.level) }} data-level={cp.risk?.level ?? "none"}>
          {cp.risk?.level ?? "No forecast"}
        </span>
        <span>Mile {Math.round(cp.mile)}</span>
      </div>
      <p className="cp-eta">Arrive {formatTime(cp.eta)}</p>
      {cp.weather && cp.risk ? (
        <>
          <table>
            <tbody>
              <tr>
                <th>Wind</th>
                <td>
                  {cp.weather.wind_mph.toFixed(0)} mph <small>gusts {cp.weather.gust_mph.toFixed(0)}</small>
                </td>
                <td>{cp.risk.by_condition.wind}</td>
              </tr>
              <tr>
                <th>Rain</th>
                <td>{cp.weather.rain_in_hr.toFixed(2)} in/hr</td>
                <td>{cp.risk.by_condition.rain}</td>
              </tr>
              <tr>
                <th>Snow</th>
                <td>{cp.weather.snow_in_hr.toFixed(2)} in/hr</td>
                <td>{cp.risk.by_condition.snow}</td>
              </tr>
            </tbody>
          </table>
          {cp.risk.drivers.length > 0 && <p className="cp-note">Driven by {cp.risk.drivers.join(" and ")}.</p>}
          {cp.risk.load_rule_applied && <p className="cp-note strong">{cp.risk.load_rule_applied}</p>}
        </>
      ) : (
        <p className="cp-note">This arrival time is beyond the 16-day forecast, so it isn't scored.</p>
      )}
    </div>
  );
}

const Endpoints = memo(function Endpoints({ analysis }: { analysis: Analysis }) {
  return (
    <>
      {[
        { p: analysis.origin, label: "Start" },
        { p: analysis.destination, label: "Finish" },
      ].map(({ p, label }) => (
        <CircleMarker
          key={label}
          center={[p.lat, p.lon]}
          radius={8}
          pathOptions={{ color: "#ffffff", weight: 3, fillColor: "#0B6B4B", fillOpacity: 1 }}
        >
          <Tooltip permanent direction="top" offset={[0, -8]} className="endpoint-label">
            {p.label.split(",")[0]}
          </Tooltip>
        </CircleMarker>
      ))}
    </>
  );
});

function TruckMarker({ route, iso }: { route: RouteOption; iso: string }) {
  const pos = positionAt(route, iso);
  if (!pos) return null;
  return (
    <CircleMarker center={pos} radius={9} pathOptions={{ color: "#1D2A30", weight: 3, fillColor: "#ffffff", fillOpacity: 1 }}>
      <Tooltip direction="right" offset={[10, 0]} className="truck-label">
        Truck position at this hour
      </Tooltip>
    </CircleMarker>
  );
}
