"use client";

import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { FlightExposure, MapData, LogisticsCard } from "@/lib/types";

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

// NYC viewport lock (approx city bounds)
const NYC_MAX_BOUNDS: mapboxgl.LngLatBoundsLike = [
  [-74.2591, 40.4774], // SW
  [-73.7004, 40.9176], // NE
];

const SWARM_EMOJI: Record<string, string> = {
  police:       "🚓",
  rat:          "🐀",
  permit:       "🚧",
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
  permit:       "#fb923c",
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
  flightExposure?: FlightExposure | null;
}

export default function MapComponent({ mapData, logistics, activeRoute, flightExposure }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const planeMarkerRef = useRef<mapboxgl.Marker | null>(null);
  const planeProgressRef = useRef(0.5);
  const lastTimeRef = useRef(0);
  const rafRef = useRef<number>();
  const trackPlaneMarkersRef = useRef<mapboxgl.Marker[]>([]);
  const trackProgressRef = useRef<number[]>([]);
  const trackLastTimeRef = useRef(0);
  const trackRafRef = useRef<number>();
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
      maxBounds: NYC_MAX_BOUNDS,
      minZoom: 10.5,
      maxZoom: 17.5,
    });
    map.addControl(new mapboxgl.NavigationControl(), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      addZones(map);
      addSwarm(map);
      addLogisticsPins(map);
      addTargetPin(map);
      const initialPaths = getFlightPaths();
      upsertFlightPaths(map, initialPaths);
      // Per-path plane animations (ADS-B polylines or corridor segments)
      startTrackPlaneAnimations(map, initialPaths);
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
      if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
      trackPlaneMarkersRef.current.forEach((m) => m.remove());
      trackPlaneMarkersRef.current = [];
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

  // ── Update flight corridors when new scan data arrives ──────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const paths = getFlightPaths();

    const apply = () => {
      if (!map.isStyleLoaded()) return;

      upsertFlightPaths(map, paths);

      // Always restart per-path animations on new scan data
      if (!paths.length) {
        planeMarkerRef.current?.remove();
        planeMarkerRef.current = null;
        trackPlaneMarkersRef.current.forEach((m) => m.remove());
        trackPlaneMarkersRef.current = [];
        if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
        trackRafRef.current = undefined;
      } else {
        startTrackPlaneAnimations(map, paths);
        // Legacy single-plane animation only for non-polyline corridors
        startPlaneAnimation(map);
      }
    };

    // If the map isn't ready yet, queue until style loads (common on first scan)
    if (!map.isStyleLoaded()) {
      const onIdle = () => {
        if (!map.isStyleLoaded()) return;
        map.off("idle", onIdle);
        apply();
      };
      map.on("idle", onIdle);
      return () => {
        map.off("idle", onIdle);
      };
    }

    apply();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapData.flight_path, mapData.flight_paths]);

  // ── Recenter map when the scanned property moves ────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!map.isStyleLoaded()) return;
      map.flyTo({ center: [mapData.target.lng, mapData.target.lat], zoom: 14, duration: 800 });
    };

    if (!map.isStyleLoaded()) {
      const onIdle = () => {
        if (!map.isStyleLoaded()) return;
        map.off("idle", onIdle);
        apply();
      };
      map.on("idle", onIdle);
      return () => {
        map.off("idle", onIdle);
      };
    }

    apply();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapData.target.lat, mapData.target.lng]);

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const getFlightPaths = () => {
    const paths = mapData.flight_paths?.filter(Boolean) ?? [];
    if (paths.length) return paths;
    return mapData.flight_path ? [mapData.flight_path] : [];
  };

  const formatSeenAgo = (isoUtc: string) => {
    const t = Date.parse(isoUtc);
    if (!Number.isFinite(t)) return null;
    const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (mins <= 1) return "seen <1m ago";
    if (mins < 60) return `seen ${mins}m ago`;
    const hrs = Math.round(mins / 60);
    return `seen ${hrs}h ago`;
  };

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
      // Outer node: Mapbox sets transform on this element for map position — never set transform here.
      const outer = document.createElement("div");
      outer.style.cssText = `
        width: 22px; height: 22px; cursor: pointer; pointer-events: auto;
        display: flex; align-items: center; justify-content: center;
      `;
      const inner = document.createElement("div");
      inner.style.cssText = `
        font-size: 12px; display: flex; align-items: center; justify-content: center;
        width: 100%; height: 100%;
        background: rgba(15,23,42,0.92); border: 1px solid ${color};
        border-radius: 50%; backdrop-filter: blur(2px);
        transition: transform 0.15s, box-shadow 0.15s;
        transform-origin: center center;
      `;
      inner.textContent = SWARM_EMOJI[pin.type] || "📋";
      outer.appendChild(inner);

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

      outer.addEventListener("mouseenter", () => {
        inner.style.transform = "scale(1.4)";
        outer.style.zIndex = "9999";
        popup.setLngLat([pin.lng, pin.lat]).addTo(map);
      });
      outer.addEventListener("mouseleave", () => {
        inner.style.transform = "";
        outer.style.zIndex = "";
        popup.remove();
      });

      const marker = new mapboxgl.Marker({ element: outer, anchor: "center" })
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
      const outer = document.createElement("div");
      outer.style.cssText = `
        width: 36px; height: 36px; cursor: pointer; pointer-events: auto;
        display: flex; align-items: center; justify-content: center;
      `;
      const inner = document.createElement("div");
      inner.style.cssText = `
        font-size: 20px; display: flex; align-items: center; justify-content: center;
        width: 100%; height: 100%;
        background: rgba(30,41,59,0.9); border: 2px solid ${card.color};
        border-radius: 50%; backdrop-filter: blur(2px);
        box-shadow: 0 0 12px ${card.color}66;
        transition: transform 0.2s, box-shadow 0.2s;
        transform-origin: center center;
      `;
      inner.textContent = PIN_EMOJI[card.type] || "📍";
      outer.appendChild(inner);

      const popup = new mapboxgl.Popup({
        offset: 20,
        closeButton: false,
        closeOnClick: false,
        anchor: "bottom",
      }).setHTML(
        `<div style="font-weight:700;color:${card.color};font-size:12px">${card.emoji} ${card.name}</div>` +
        `<div style="font-size:10px;color:#94a3b8;margin-top:2px">${card.category} · ${card.distance_value} ${card.distance_unit} away</div>`
      );

      outer.addEventListener("mouseenter", () => {
        inner.style.transform = "scale(1.15)";
        popup.setLngLat([card.coordinates.lng, card.coordinates.lat]).addTo(map);
      });
      outer.addEventListener("mouseleave", () => {
        inner.style.transform = "";
        popup.remove();
      });

      const marker = new mapboxgl.Marker({ element: outer, anchor: "center" })
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
    marker.getPopup()?.addTo(map);
    markersRef.current.push(marker);
  };

  const upsertFlightPaths = (map: mapboxgl.Map, paths: ReturnType<typeof getFlightPaths>) => {
    const toLineCoords = (p: (typeof paths)[number]) => {
      // Prefer real ADS-B track polylines when present.
      const poly = p.path?.filter(Boolean) ?? [];
      if (poly.length >= 2) {
        return poly.map((c) => [c.lng, c.lat]) as [number, number][];
      }
      return [[p.start.lng, p.start.lat], [p.end.lng, p.end.lat]] as [number, number][];
    };

    const data = {
      type: "FeatureCollection" as const,
      features: paths.map((p) => ({
        type: "Feature" as const,
        properties: { label: p.label },
        geometry: {
          type: "LineString" as const,
          coordinates: toLineCoords(p),
        },
      })),
    };

    const existing = map.getSource("flight-paths") as mapboxgl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      const hasRealTracks = paths.some((p) => (p.path?.length ?? 0) >= 2);
      // Real ADS-B tracks should read as continuous paths; corridors stay dashed.
      map.setPaintProperty(
        "flight-paths-line",
        "line-dasharray",
        hasRealTracks ? undefined : [2, 3]
      );
      return;
    }

    map.addSource("flight-paths", { type: "geojson", data });
    const hasRealTracks = paths.some((p) => (p.path?.length ?? 0) >= 2);
    map.addLayer({
      id: "flight-paths-line",
      type: "line",
      source: "flight-paths",
      paint: {
        "line-color": "#06b6d4",
        "line-width": 3,
        ...(hasRealTracks ? {} : { "line-dasharray": [2, 3] }),
        "line-opacity": 0.8,
      },
    });
  };

  const startTrackPlaneAnimations = useCallback((map: mapboxgl.Map, paths: ReturnType<typeof getFlightPaths>) => {
    // Clean up any previous markers/raf
    if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
    trackRafRef.current = undefined;
    trackPlaneMarkersRef.current.forEach((m) => m.remove());
    trackPlaneMarkersRef.current = [];

    const routes = paths
      .slice(0, 3)
      .map((p) => {
        const poly = p.path?.filter(Boolean) ?? [];
        const coords =
          poly.length >= 2
            ? poly.map((c) => ({ lat: c.lat, lng: c.lng }))
            : [{ lat: p.start.lat, lng: p.start.lng }, { lat: p.end.lat, lng: p.end.lng }];
        return coords;
      })
      .filter((c) => c.length >= 2);

    if (!routes.length) return;

    trackProgressRef.current = routes.map(() => 0);
    trackLastTimeRef.current = 0;

    // Create a plane marker per route
    trackPlaneMarkersRef.current = routes.map((r) => {
      const el = document.createElement("div");
      el.style.cssText =
        "font-size: 18px; line-height: 1; filter: drop-shadow(0 0 6px rgba(6,182,212,0.7));";
      el.textContent = "✈️";
      return new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([r[0].lng, r[0].lat])
        .addTo(map);
    });

    const step = (time: number) => {
      if (!trackLastTimeRef.current) trackLastTimeRef.current = time;
      const delta = Math.min(time - trackLastTimeRef.current, 100);
      trackLastTimeRef.current = time;

      const zoom = map.getZoom();
      // Keep it subtle; faster when zoomed out.
      const speedMultiplier = Math.pow(2, 14 - zoom);
      const baseSpeed = 1 / 90000; // progress per ms

      routes.forEach((route, idx) => {
        const segCount = route.length - 1;
        const total = Math.max(1, segCount);
        let p = trackProgressRef.current[idx] ?? 0;
        p += delta * baseSpeed * speedMultiplier;
        if (p > 1) p -= 1;
        trackProgressRef.current[idx] = p;

        // Map 0..1 to route segments
        const t = p * total;
        const i = Math.min(segCount - 1, Math.floor(t));
        const f = t - i;
        const a = route[i];
        const b = route[i + 1];
        const lat = a.lat + (b.lat - a.lat) * f;
        const lng = a.lng + (b.lng - a.lng) * f;
        trackPlaneMarkersRef.current[idx]?.setLngLat([lng, lat]);
      });

      trackRafRef.current = requestAnimationFrame(step);
    };

    trackRafRef.current = requestAnimationFrame(step);
  }, []);

  const startPlaneAnimation = useCallback((map: mapboxgl.Map) => {
    const paths = getFlightPaths();
    if (!paths.length) return;
    // If we're rendering real ADS-B polylines, don't animate a fake plane.
    if (paths.some((p) => (p.path?.length ?? 0) >= 2)) return;

    // Restart cleanly (avoid stacking RAF loops)
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = undefined;
    planeMarkerRef.current?.remove();
    planeMarkerRef.current = null;

    const { start, end } = paths[0];

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
  }, [mapData.flight_path, mapData.flight_paths]);

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

      {(getFlightPaths().length > 0 || flightExposure) && (
        <div className="mt-3 px-2 text-[10px] md:text-[11px] font-bold text-slate-400">
          <div className="flex items-center justify-between gap-3">
            <div className="text-slate-200 font-black uppercase tracking-widest text-[11px]">
              ✈️ Flight Activity
            </div>
            <div className="text-slate-500">
              Paths: <span className="text-cyan-300">{getFlightPaths().length}</span>
            </div>
          </div>

          {flightExposure && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {flightExposure.data_quality !== "unavailable" ? (
                <>
                  <span className="px-2 py-1 rounded-full bg-slate-900 border border-slate-700 text-slate-300">
                    Night: <span className="text-white">{flightExposure.night_overflights_per_hour}/hr</span>
                  </span>
                  <span className="px-2 py-1 rounded-full bg-slate-900 border border-slate-700 text-slate-300">
                    Day: <span className="text-white">{flightExposure.day_overflights_per_hour}/hr</span>
                  </span>
                  {flightExposure.typical_altitude_ft != null && (
                    <span className="px-2 py-1 rounded-full bg-slate-900 border border-slate-700 text-slate-300">
                      Typical: <span className="text-white">~{flightExposure.typical_altitude_ft.toLocaleString()} ft</span>
                    </span>
                  )}
                  <span
                    className={[
                      "px-2 py-1 rounded-full border text-slate-200",
                      flightExposure.data_quality === "good"
                        ? "bg-emerald-950/40 border-emerald-700 text-emerald-200"
                        : "bg-amber-950/40 border-amber-700 text-amber-200",
                    ].join(" ")}
                  >
                    Data: <span className="text-white">{flightExposure.data_quality}</span>
                  </span>
                </>
              ) : (
                <span className="px-2 py-1 rounded-full bg-slate-900 border border-slate-700 text-slate-300">
                  Exposure: <span className="text-white">unavailable</span>
                </span>
              )}
            </div>
          )}

          {getFlightPaths().length > 0 && (
            <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
              {getFlightPaths().slice(0, 3).map((p, idx) => (
                <div
                  key={idx}
                  className="min-w-[220px] shrink-0 rounded-xl bg-slate-900/60 border border-slate-700 px-3 py-2"
                >
                  <div className="text-slate-200 font-black text-[11px] truncate">{p.label}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-slate-400">
                    {p.median_altitude_ft != null && <span>~{p.median_altitude_ft.toLocaleString()} ft</span>}
                    {p.closest_miles != null && <span>closest {p.closest_miles} mi</span>}
                    {p.last_seen_utc && <span>{formatSeenAgo(p.last_seen_utc) ?? ""}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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
        {getFlightPaths().length > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-6 h-1 bg-cyan-500 border-y border-dashed border-cyan-200 inline-block" /> Flight Route
          </span>
        )}
      </div>

      {getFlightPaths().some((p) => (p.path?.length ?? 0) >= 2) && (
        <div className="mt-2 px-2 text-[10px] md:text-[11px] font-bold text-slate-500">
          Live flight tracks (recent).
        </div>
      )}
    </div>
  );
}
