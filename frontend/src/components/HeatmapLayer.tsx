import L from "leaflet";
import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import { NO_DATA_COLOR, RISK_COLORS } from "../lib/format";
import type { Heatmap } from "../types/api";

interface Props {
  data: Heatmap;
  hour: number;
  visible: boolean;
}

const PANE = "heat";

/**
 * Corridor heatmap: one canvas rectangle per grid cell, created once per dataset.
 * Moving the slider only restyles existing cells (no React re-render of map layers, no network);
 * Leaflet's canvas renderer batches the redraw into a single animation frame.
 */
export function HeatmapLayer({ data, hour, visible }: Props) {
  const map = useMap();
  const cells = useRef<L.Rectangle[]>([]);
  const group = useRef<L.LayerGroup | null>(null);

  // Build cells once per dataset.
  useEffect(() => {
    if (!map.getPane(PANE)) {
      const pane = map.createPane(PANE);
      pane.style.zIndex = "350"; // above tiles, below routes (overlayPane = 400)
      pane.style.pointerEvents = "none";
    }
    const renderer = L.canvas({ pane: PANE, padding: 0.3 });
    const { dlat, dlon } = data.cell;
    const layerGroup = L.layerGroup();
    cells.current = data.points.map(([lat, lon]) => {
      const rect = L.rectangle(
        [
          [lat - dlat / 2, lon - dlon / 2],
          [lat + dlat / 2, lon + dlon / 2],
        ],
        { renderer, pane: PANE, stroke: false, fillOpacity: 0, interactive: false },
      );
      layerGroup.addLayer(rect);
      return rect;
    });
    group.current = layerGroup;
    return () => {
      layerGroup.remove();
      cells.current = [];
      group.current = null;
    };
  }, [map, data]);

  useEffect(() => {
    const g = group.current;
    if (!g) return;
    if (visible && !map.hasLayer(g)) g.addTo(map);
    if (!visible && map.hasLayer(g)) g.remove();
  }, [map, visible, data]);

  // Restyle on hour change.
  useEffect(() => {
    if (!visible) return;
    const row = data.values[hour] ?? [];
    cells.current.forEach((rect, i) => {
      const score = row[i] ?? -1;
      rect.setStyle(
        score < 0
          ? { fillColor: NO_DATA_COLOR, fillOpacity: 0.12 }
          : { fillColor: RISK_COLORS[score], fillOpacity: score === 0 ? 0.14 : 0.42 + score * 0.06 },
      );
    });
  }, [data, hour, visible]);

  return null;
}

export function worstPerHour(data: Heatmap): number[] {
  return data.values.map((row) => row.reduce((m, v) => (v > m ? v : m), -1));
}
