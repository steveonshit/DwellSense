"use client";

import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { FlightExposure, MapData, LogisticsCard } from "@/lib/types";
import { flightPathToLineLngLat, flightPathToRouteLatLng } from "@/lib/flightPathDisplay";
import { scanRadiusPolygon } from "@/lib/scanRadiusCircle";

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

// NYC viewport lock (approx city bounds)
const NYC_MAX_BOUNDS: mapboxgl.LngLatBoundsLike = [
  [-74.2591, 40.4774], // SW
  [-73.7004, 40.9176], // NE
];

/** Minimum real ADS-B vertices required to render a track (matches backend ADSB_PATH_MIN_POINTS). */
const MIN_FLIGHT_PATH_POINTS = 5;
const DEFAULT_SCAN_RADIUS_MILES = 3;

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
  const trackPlaneMarkersRef = useRef<mapboxgl.Marker[]>([]);
  const trackProgressRef = useRef<number[]>([]);
  const trackLastTimeRef = useRef(0);
  const trackRafRef = useRef<number>();
  const markersRef = useRef<mapboxgl.Marker[]>([]);
  const flightVertexMarkersRef = useRef<mapboxgl.Marker[]>([]);

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
      upsertScanRadius(map);
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
      if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
      trackPlaneMarkersRef.current.forEach((m) => m.remove());
      trackPlaneMarkersRef.current = [];
      flightVertexMarkersRef.current.forEach((m) => m.remove());
      flightVertexMarkersRef.current = [];
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
  }, [activeRoute, logistics, mapData.target.lat, mapData.target.lng]);

  // ── Update flight corridors when new scan data arrives ──────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const paths = getFlightPaths();

    const apply = () => {
      if (!map.isStyleLoaded()) return;

      upsertFlightPaths(map, paths);
      upsertFlightPathVertices(map, paths);

      // Always restart per-path animations on new scan data
      if (!paths.length) {
        trackPlaneMarkersRef.current.forEach((m) => m.remove());
        trackPlaneMarkersRef.current = [];
        flightVertexMarkersRef.current.forEach((m) => m.remove());
        flightVertexMarkersRef.current = [];
        if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
        trackRafRef.current = undefined;
      } else {
        startTrackPlaneAnimations(map, paths);
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

  // ── Update 2-mile search circle when scan center or radius changes ───────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!map.isStyleLoaded()) return;
      upsertScanRadius(map);
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
  }, [mapData.target.lat, mapData.target.lng, mapData.scan_radius_miles]);

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const getScanRadiusMiles = () =>
    mapData.scan_radius_miles && mapData.scan_radius_miles > 0
      ? mapData.scan_radius_miles
      : DEFAULT_SCAN_RADIUS_MILES;

  /** Only observed ADS-B polylines — never heuristic corridor segments. */
  const getFlightPaths = () => {
    const raw = mapData.flight_paths?.filter(Boolean) ?? [];
    const paths = raw.length ? raw : mapData.flight_path ? [mapData.flight_path] : [];
    return paths.filter((p) => {
      if (p.source === "corridor") return false;
      const pts = p.path?.filter(Boolean) ?? [];
      return pts.length >= MIN_FLIGHT_PATH_POINTS;
    });
  };

  const upsertScanRadius = (map: mapboxgl.Map) => {
    const radiusMiles = getScanRadiusMiles();
    const geometry = scanRadiusPolygon(
      mapData.target.lat,
      mapData.target.lng,
      radiusMiles
    );
    const data: GeoJSON.Feature = {
      type: "Feature",
      properties: { radius_miles: radiusMiles },
      geometry,
    };

    const existing = map.getSource("scan-radius") as mapboxgl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      return;
    }

    map.addSource("scan-radius", { type: "geojson", data });
    map.addLayer({
      id: "scan-radius-fill",
      type: "fill",
      source: "scan-radius",
      paint: { "fill-color": "#f43f5e", "fill-opacity": 0.09 },
    });
    map.addLayer({
      id: "scan-radius-line",
      type: "line",
      source: "scan-radius",
      paint: {
        "line-color": "#fb7185",
        "line-width": 2.5,
        "line-dasharray": [2, 2],
        "line-opacity": 0.9,
      },
    });
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
      const pinEmoji = card.type.startsWith("dining-") ? (card.emoji || "🍽️") : (PIN_EMOJI[card.type] || "📍");
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
      inner.textContent = pinEmoji;
      outer.appendChild(inner);

      const ratingLine =
        card.type.startsWith("dining-") && card.rating != null
          ? `<div style="font-size:10px;color:#fbbf24;margin-top:2px">★ ${card.rating.toFixed(1)}` +
            `${card.review_count != null ? ` · ${card.review_count} reviews` : ""}</div>`
          : "";

      const popup = new mapboxgl.Popup({
        offset: 20,
        closeButton: false,
        closeOnClick: false,
        anchor: "bottom",
      }).setHTML(
        `<div style="font-weight:700;color:${card.color};font-size:12px">${card.emoji} ${card.name}</div>` +
        `<div style="font-size:10px;color:#94a3b8;margin-top:2px">${card.category} · ${card.distance_value} ${card.distance_unit} away</div>` +
        ratingLine
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

  const upsertFlightPathVertices = (map: mapboxgl.Map, paths: ReturnType<typeof getFlightPaths>) => {
    flightVertexMarkersRef.current.forEach((m) => m.remove());
    flightVertexMarkersRef.current = [];

    paths.forEach((p) => {
      const verts = p.path?.filter(Boolean) ?? [];
      if (verts.length < MIN_FLIGHT_PATH_POINTS) return;

      verts.forEach((c) => {
        const outer = document.createElement("div");
        outer.style.cssText =
          "width: 10px; height: 10px; display: flex; align-items: center; justify-content: center; pointer-events: none;";
        const inner = document.createElement("div");
        inner.style.cssText = `
          width: 6px; height: 6px; border-radius: 50%;
          background: #22d3ee; border: 1px solid rgba(255,255,255,0.9);
          box-shadow: 0 0 6px rgba(34,211,238,0.85);
        `;
        outer.appendChild(inner);

        const marker = new mapboxgl.Marker({ element: outer, anchor: "center" })
          .setLngLat([c.lng, c.lat])
          .addTo(map);
        flightVertexMarkersRef.current.push(marker);
      });
    });
  };

  const upsertFlightPaths = (map: mapboxgl.Map, paths: ReturnType<typeof getFlightPaths>) => {
    const toLineCoords = (p: (typeof paths)[number]) => flightPathToLineLngLat(p);

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
      return;
    }

    map.addSource("flight-paths", { type: "geojson", data });
    const lineLayout = { "line-cap": "round" as const, "line-join": "round" as const };

    map.addLayer({
      id: "flight-paths-glow",
      type: "line",
      source: "flight-paths",
      layout: lineLayout,
      paint: {
        "line-color": "#22d3ee",
        "line-width": 11,
        "line-opacity": 0.2,
        "line-blur": 2.5,
      },
    });
    map.addLayer({
      id: "flight-paths-line",
      type: "line",
      source: "flight-paths",
      layout: lineLayout,
      paint: {
        "line-color": "#06b6d4",
        "line-width": 3,
        "line-opacity": 0.88,
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
        const coords = flightPathToRouteLatLng(p);
        return coords.length >= 2 ? coords : [];
      })
      .filter((c) => c.length >= 2);

    if (!routes.length) return;

    const routeMetrics = routes
      .map((route) => {
        const cumulative: number[] = [0];
        for (let i = 1; i < route.length; i++) {
          const prev = route[i - 1];
          const cur = route[i];
          const meters = new mapboxgl.LngLat(prev.lng, prev.lat).distanceTo(
            new mapboxgl.LngLat(cur.lng, cur.lat)
          );
          cumulative.push(cumulative[i - 1] + meters);
        }
        const totalMeters = cumulative[cumulative.length - 1] ?? 0;
        return totalMeters > 0 ? { route, cumulative, totalMeters } : null;
      })
      .filter((m): m is { route: { lat: number; lng: number }[]; cumulative: number[]; totalMeters: number } => Boolean(m));

    if (!routeMetrics.length) return;

    trackProgressRef.current = routes.map(() => 0);
    trackLastTimeRef.current = 0;

    // Create a plane marker per route
    trackPlaneMarkersRef.current = routeMetrics.map(({ route }) => {
      const el = document.createElement("div");
      el.style.cssText =
        "font-size: 18px; line-height: 1; filter: drop-shadow(0 0 6px rgba(6,182,212,0.7));";
      el.textContent = "✈️";
      return new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([route[0].lng, route[0].lat])
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

      routeMetrics.forEach(({ route, cumulative, totalMeters }, idx) => {
        let p = trackProgressRef.current[idx] ?? 0;
        p += delta * baseSpeed * speedMultiplier;
        if (p > 1) p %= 1;
        trackProgressRef.current[idx] = p;

        const targetMeters = p * totalMeters;
        let i = 0;
        while (i < cumulative.length - 2 && cumulative[i + 1] < targetMeters) {
          i++;
        }

        const a = route[i];
        const b = route[i + 1];
        const segStart = cumulative[i];
        const segEnd = cumulative[i + 1];
        const f = (targetMeters - segStart) / Math.max(1, segEnd - segStart);
        const lat = a.lat + (b.lat - a.lat) * f;
        const lng = a.lng + (b.lng - a.lng) * f;
        trackPlaneMarkersRef.current[idx]?.setLngLat([lng, lat]);
      });

      trackRafRef.current = requestAnimationFrame(step);
    };

    trackRafRef.current = requestAnimationFrame(step);
  }, []);

  return (
    <div className="w-full bg-slate-800 rounded-3xl border border-slate-700 shadow-2xl p-4 fade-in" style={{ animationDelay: "0.2s" }}>
      <div className="flex justify-between items-center mb-4 px-2">
        <h3 className="text-white font-black uppercase tracking-widest text-sm flex items-center gap-2">
          🗺️ Live Threat Density Map{" "}
          <span className="text-rose-500 animate-pulse">● Live Swarm</span>
        </h3>
        <span className="text-slate-400 text-[10px] font-bold bg-slate-900 px-3 py-1 rounded-full border border-slate-700 italic hidden md:block">
          {getScanRadiusMiles()}-mile search radius · Each pin is a real NYC record · Scroll to zoom
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
                    {(p.path?.length ?? p.sample_count ?? 0) > 0 && (
                      <span className="text-cyan-300 font-black">
                        {p.sample_count ?? p.path?.length ?? 0} pts
                      </span>
                    )}
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

      {getFlightPaths().some((p) => (p.path?.length ?? 0) >= MIN_FLIGHT_PATH_POINTS) && (
        <div className="mt-2 px-2 text-[10px] md:text-[11px] font-bold text-slate-500">
          Flight tracks are observed ADS-B positions only (min {MIN_FLIGHT_PATH_POINTS} points per path). Cyan dots mark each recorded position. Count varies with recent traffic — synthetic corridors are never shown.
        </div>
      )}
    </div>
  );
}
