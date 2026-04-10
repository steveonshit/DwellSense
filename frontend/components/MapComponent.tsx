"use client";

import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { MapData, LogisticsCard } from "@/lib/types";

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

const SWARM_EMOJI: Record<string, string> = {
  police:       "🚓",
  rat:          "🐀",
  construction: "🚧",
  truck:        "🚛",
  bus:          "🚌",
  noise:        "🔊",
  fire:         "🔥",
  water:        "💧",
  trash:        "🗑️",
  graffiti:     "🎨",
  report:       "📋",
};

const SWARM_COLOR: Record<string, string> = {
  police:       "#60a5fa",
  rat:          "#c084fc",
  construction: "#fb923c",
  truck:        "#facc15",
  bus:          "#d9f99d",
  noise:        "#fde047",
  fire:         "#f97316",
  water:        "#38bdf8",
  trash:        "#86efac",
  graffiti:     "#f0abfc",
  report:       "#94a3b8",
};

interface Props {
  mapData: MapData;
  logistics: LogisticsCard[];
  activeRoute: string | null;
}

export default function MapComponent({ mapData, logistics, activeRoute }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const planeMarkerRef = useRef<mapboxgl.Marker | null>(null);
  const planeProgressRef = useRef(0.5);
  const lastTimeRef = useRef(0);
  const rafRef = useRef<number>();
  const markersRef = useRef<mapboxgl.Marker[]>([]);

  // ── Build map on mount ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [mapData.target.lng, mapData.target.lat],
      zoom: 14,
      scrollZoom: true,
    });
    map.addControl(new mapboxgl.NavigationControl(), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      addZones(map);
      addSwarm(map);
      addLogisticsPins(map);
      addTargetPin(map);
      if (mapData.flight_path) {
        addFlightPath(map);
        startPlaneAnimation(map);
      }
      // Route source — empty at first, filled on hover
      map.addSource("route", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "route-glow",
        type: "line",
        source: "route",
        paint: { "line-color": "#ffffff", "line-width": 10, "line-opacity": 0.15 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        paint: { "line-color": "#ffffff", "line-width": 3, "line-dasharray": [2, 2] },
      });
    });

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      markersRef.current.forEach((m) => m.remove());
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Update route when activeRoute changes ───────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource("route") as mapboxgl.GeoJSONSource | undefined;
    if (!source) return;

    if (!activeRoute) {
      source.setData({ type: "FeatureCollection", features: [] });
      map.flyTo({ center: [mapData.target.lng, mapData.target.lat], zoom: 14, duration: 800 });
      // Reset route line colors
      map.setPaintProperty("route-glow", "line-color", "#ffffff");
      map.setPaintProperty("route-line", "line-color", "#ffffff");
      return;
    }

    const card = logistics.find((c) => c.type === activeRoute);
    if (!card) return;

    const color = card.color;
    map.setPaintProperty("route-glow", "line-color", color);
    map.setPaintProperty("route-line", "line-color", color);

    source.setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "LineString",
            coordinates: [
              [mapData.target.lng, mapData.target.lat],
              [card.coordinates.lng, card.coordinates.lat],
            ],
          },
        },
      ],
    });

    map.fitBounds(
      [
        [Math.min(mapData.target.lng, card.coordinates.lng), Math.min(mapData.target.lat, card.coordinates.lat)],
        [Math.max(mapData.target.lng, card.coordinates.lng), Math.max(mapData.target.lat, card.coordinates.lat)],
      ],
      { padding: 80, duration: 800 }
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRoute]);

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const addZones = (map: mapboxgl.Map) => {
    mapData.zones.forEach((zone, i) => {
      const id = `zone-${i}`;
      map.addSource(id, {
        type: "geojson",
        data: {
          type: "Feature",
          properties: { label: zone.label },
          geometry: { type: "Point", coordinates: [zone.lng, zone.lat] },
        },
      });
      map.addLayer({
        id: `${id}-fill`,
        type: "circle",
        source: id,
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            10, zone.radius_meters / 100,
            15, zone.radius_meters / 10,
          ],
          "circle-color": zone.color,
          "circle-opacity": 0.15,
          "circle-stroke-color": zone.color,
          "circle-stroke-width": 2,
          "circle-stroke-opacity": 0.6,
        },
      });
    });
  };

  const addSwarm = (map: mapboxgl.Map) => {
    mapData.swarm.forEach((pin) => {
      const color = SWARM_COLOR[pin.type] || "#94a3b8";
      const el = document.createElement("div");
      el.style.cssText = `
        font-size: 12px; display: flex; align-items: center; justify-content: center;
        width: 22px; height: 22px; cursor: pointer;
        background: rgba(15,23,42,0.92); border: 1px solid ${color};
        border-radius: 50%; backdrop-filter: blur(2px);
        transition: transform 0.15s, box-shadow 0.15s;
        pointer-events: auto;
      `;
      el.textContent = SWARM_EMOJI[pin.type] || "📋";

      // Popup shown on hover only — prevents icons from jumping on click
      const popup = new mapboxgl.Popup({
        offset: 14,
        closeButton: false,
        closeOnClick: false,
        anchor: "bottom",
      }).setHTML(
        `<div style="font-size:11px;font-weight:700;color:${color};margin-bottom:2px">${pin.label}</div>` +
        `<div style="font-size:10px;color:#94a3b8">Reported in last 30 days</div>`
      );

      el.addEventListener("mouseenter", () => {
        el.style.transform = "scale(1.4)";
        el.style.zIndex = "9999";
        popup.setLngLat([pin.lng, pin.lat]).addTo(map);
      });
      el.addEventListener("mouseleave", () => {
        el.style.transform = "scale(1)";
        el.style.zIndex = "";
        popup.remove();
      });

      const marker = new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([pin.lng, pin.lat])
        .addTo(map);
      markersRef.current.push(marker);
    });
  };

  const addLogisticsPins = (map: mapboxgl.Map) => {
    const PIN_EMOJI: Record<string, string> = {
      subway: "🚇", train: "🚆", bus: "🚌",
      airport: "✈️", mall: "🛍️",
      targetstore: "🎯", walmart: "🛒", traderjoes: "🥑",
    };

    logistics.forEach((card) => {
      const el = document.createElement("div");
      el.style.cssText = `
        font-size: 20px; display: flex; align-items: center; justify-content: center;
        width: 36px; height: 36px; cursor: pointer;
        background: rgba(30,41,59,0.9); border: 2px solid ${card.color};
        border-radius: 50%; backdrop-filter: blur(2px);
        box-shadow: 0 0 12px ${card.color}66;
        transition: transform 0.2s, box-shadow 0.2s;
      `;
      el.textContent = PIN_EMOJI[card.type] || "📍";

      const popup = new mapboxgl.Popup({
        offset: 20,
        closeButton: false,
        closeOnClick: false,
        anchor: "bottom",
      }).setHTML(
        `<div style="font-weight:700;color:${card.color};font-size:12px">${card.emoji} ${card.name}</div>` +
        `<div style="font-size:10px;color:#94a3b8;margin-top:2px">${card.category} · ${card.distance_value} ${card.distance_unit} away</div>`
      );

      el.addEventListener("mouseenter", () => {
        el.style.transform = "scale(1.15)";
        popup.setLngLat([card.coordinates.lng, card.coordinates.lat]).addTo(map);
      });
      el.addEventListener("mouseleave", () => {
        el.style.transform = "scale(1)";
        popup.remove();
      });

      const marker = new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([card.coordinates.lng, card.coordinates.lat])
        .addTo(map);
      markersRef.current.push(marker);
    });
  };

  const addTargetPin = (map: mapboxgl.Map) => {
    const el = document.createElement("div");
    el.style.cssText = "font-size: 36px; cursor: pointer; filter: drop-shadow(0 0 8px rgba(244,63,94,0.8)); line-height: 1;";
    el.textContent = "📍";

    const popup = new mapboxgl.Popup({ offset: 36, closeButton: false })
      .setHTML(`<b style="color:#f43f5e">Target Property</b><br><span style="font-size:10px;color:#94a3b8;">${mapData.target.lat.toFixed(5)}, ${mapData.target.lng.toFixed(5)}</span>`);

    const marker = new mapboxgl.Marker({ element: el, anchor: "bottom" })
      .setLngLat([mapData.target.lng, mapData.target.lat])
      .setPopup(popup)
      .addTo(map);
    marker.getPopup().addTo(map);
    markersRef.current.push(marker);
  };

  const addFlightPath = (map: mapboxgl.Map) => {
    if (!mapData.flight_path) return;
    const { start, end } = mapData.flight_path;

    map.addSource("flight-path", {
      type: "geojson",
      data: {
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: [[start.lng, start.lat], [end.lng, end.lat]],
        },
      },
    });
    map.addLayer({
      id: "flight-path-line",
      type: "line",
      source: "flight-path",
      paint: {
        "line-color": "#06b6d4",
        "line-width": 3,
        "line-dasharray": [2, 3],
        "line-opacity": 0.8,
      },
    });
  };

  const startPlaneAnimation = useCallback((map: mapboxgl.Map) => {
    if (!mapData.flight_path) return;
    const { start, end } = mapData.flight_path;

    const el = document.createElement("div");
    el.className = "animated-plane";
    el.textContent = "✈️";

    planeMarkerRef.current = new mapboxgl.Marker({ element: el, anchor: "center" })
      .setLngLat([start.lng, start.lat])
      .addTo(map);

    const animate = (time: number) => {
      if (!lastTimeRef.current) lastTimeRef.current = time;
      const delta = Math.min(time - lastTimeRef.current, 100);
      lastTimeRef.current = time;

      const zoom = map.getZoom();
      const speedMultiplier = Math.pow(2, 14 - zoom);
      planeProgressRef.current += (delta / 80000) * speedMultiplier;
      if (planeProgressRef.current > 1) planeProgressRef.current = 0;

      const lat = start.lat + (end.lat - start.lat) * planeProgressRef.current;
      const lng = start.lng + (end.lng - start.lng) * planeProgressRef.current;
      planeMarkerRef.current?.setLngLat([lng, lat]);

      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
  }, [mapData.flight_path]);

  return (
    <div className="w-full bg-slate-800 rounded-3xl border border-slate-700 shadow-2xl p-4 fade-in" style={{ animationDelay: "0.2s" }}>
      <div className="flex justify-between items-center mb-4 px-2">
        <h3 className="text-white font-black uppercase tracking-widest text-sm flex items-center gap-2">
          🗺️ Live Threat Density Map{" "}
          <span className="text-rose-500 animate-pulse">● Live Swarm</span>
        </h3>
        <span className="text-slate-400 text-[10px] font-bold bg-slate-900 px-3 py-1 rounded-full border border-slate-700 italic hidden md:block">
          Scroll to zoom. Hover pins for details.
        </span>
      </div>

      <div
        ref={containerRef}
        className="w-full h-[450px] md:h-[600px] rounded-2xl border border-slate-800 overflow-hidden"
      />

      <div className="flex flex-wrap justify-center sm:justify-start gap-x-4 gap-y-2 mt-4 px-2 text-[10px] md:text-[11px] font-bold text-slate-300">
        <span className="flex items-center gap-1"><span className="text-rose-500 text-lg">📍</span> Property</span>
        <span className="flex items-center gap-1">🚓 Crime</span>
        <span className="flex items-center gap-1">🐀 Rodents</span>
        <span className="flex items-center gap-1">🔊 Noise</span>
        <span className="flex items-center gap-1">🔥 Heat/Gas</span>
        <span className="flex items-center gap-1">💧 Water</span>
        <span className="flex items-center gap-1">🗑️ Sanitation</span>
        <span className="flex items-center gap-1">🎨 Graffiti</span>
        <span className="flex items-center gap-1">🚧 Permits</span>
        <span className="flex items-center gap-1 text-emerald-400">🚇 Transit</span>
        <span className="flex items-center gap-1 text-amber-400">✈️ Airport</span>
        {mapData.flight_path && (
          <span className="flex items-center gap-1">
            <span className="w-6 h-1 bg-cyan-500 border-y border-dashed border-cyan-200 inline-block" /> Flight Route
          </span>
        )}
      </div>
    </div>
  );
}
