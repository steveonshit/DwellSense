import type { FlightPath } from "./types";

/** Cap on densified vertices (Mapbox line paint stays fast). */
const MAX_SPLINE_VERTICES = 360;

const RAD = Math.PI / 180;

function dist(a: [number, number], b: [number, number]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Central angle (radians) between two lng/lat points on the unit sphere. */
function centralAngleRad(a: [number, number], b: [number, number]): number {
  const lat1 = a[1] * RAD;
  const lat2 = b[1] * RAD;
  const dlat = lat2 - lat1;
  const dlng = (b[0] - a[0]) * RAD;
  const s =
    Math.sin(dlat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlng / 2) ** 2;
  return 2 * Math.asin(Math.min(1, Math.sqrt(Math.max(0, s))));
}

function toUnitVec(latDeg: number, lngDeg: number): [number, number, number] {
  const phi = latDeg * RAD;
  const theta = lngDeg * RAD;
  const cp = Math.cos(phi);
  return [cp * Math.cos(theta), cp * Math.sin(theta), Math.sin(phi)];
}

function normalizeVec(x: number, y: number, z: number): [number, number, number] {
  const len = Math.hypot(x, y, z) || 1;
  return [x / len, y / len, z / len];
}

function vecToLngLat(x: number, y: number, z: number): [number, number] {
  const [nx, ny, nz] = normalizeVec(x, y, z);
  const lat = Math.atan2(nz, Math.hypot(nx, ny)) / RAD;
  const lng = Math.atan2(ny, nx) / RAD;
  return [lng, lat];
}

function slerpVec(
  a: [number, number, number],
  b: [number, number, number],
  t: number
): [number, number, number] {
  const dot = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const omega = Math.acos(dot);
  if (omega < 1e-8) return a;
  const so = Math.sin(omega);
  const wa = Math.sin((1 - t) * omega) / so;
  const wb = Math.sin(t * omega) / so;
  return normalizeVec(wa * a[0] + wb * b[0], wa * a[1] + wb * b[1], wa * a[2] + wb * b[2]);
}

function parseIntEnv(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") return fallback;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

function parseBoolEnv(raw: string | undefined, defaultTrue: boolean): boolean {
  if (raw === undefined || raw === "") return defaultTrue;
  const v = raw.trim().toLowerCase();
  if (v === "0" || v === "false" || v === "no" || v === "off") return false;
  if (v === "1" || v === "true" || v === "yes" || v === "on") return true;
  return defaultTrue;
}

/** Densify each edge along a great circle so Mapbox draws smooth arcs (not plate‑carée kinks). */
function densifyRingGreatCircle(
  ring: [number, number][],
  minPerEdge: number,
  maxPerEdge: number,
  maxTotal: number
): [number, number][] {
  if (ring.length < 2) return ring;
  const out: [number, number][] = [];
  for (let i = 0; i < ring.length - 1; i++) {
    const a = ring[i]!;
    const b = ring[i + 1]!;
    const rad = centralAngleRad(a, b);
    if (rad < 1e-9) {
      if (out.length === 0 || dist(out[out.length - 1]!, a) > 1e-9) out.push(a);
      continue;
    }
    const deg = (180 / Math.PI) * rad;
    let steps = Math.round(6 + deg * 0.55);
    steps = Math.min(maxPerEdge, Math.max(minPerEdge, steps));
    const v1 = toUnitVec(a[1], a[0]);
    const v2 = toUnitVec(b[1], b[0]);
    for (let s = 0; s < steps; s++) {
      const t = s / steps;
      const w = slerpVec(v1, v2, t);
      out.push(vecToLngLat(w[0], w[1], w[2]));
    }
  }
  out.push(ring[ring.length - 1]!);

  if (out.length <= maxTotal) return out;
  const idxs = uniformDecimateIndices(out.length, maxTotal);
  return idxs.map((j) => out[j]!);
}

function uniformDecimateIndices(n: number, maxPoints: number): number[] {
  if (n <= maxPoints || n < 2) return Array.from({ length: n }, (_, i) => i);
  const step = (n - 1) / (maxPoints - 1);
  const idxs: number[] = [];
  for (let k = 0; k < maxPoints - 1; k++) {
    idxs.push(Math.min(n - 2, Math.round(k * step)));
  }
  idxs.push(n - 1);
  const seen = new Set<number>();
  return idxs.filter((i) => (seen.has(i) ? false : (seen.add(i), true)));
}

/**
 * Chaikin corner-cutting on an open polyline (lng, lat).
 * Rounds kinks after great-circle densification.
 */
function chaikinOpenLngLat(ring: [number, number][], passes: number): [number, number][] {
  if (passes <= 0 || ring.length < 3) return ring;
  let cur = ring;
  for (let p = 0; p < passes; p++) {
    if (cur.length < 2) break;
    const next: [number, number][] = [cur[0]!];
    for (let i = 0; i < cur.length - 1; i++) {
      const a = cur[i]!;
      const b = cur[i + 1]!;
      next.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]]);
      next.push([0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]]);
    }
    next.push(cur[cur.length - 1]!);
    cur = next;
  }
  return cur;
}

function lerp2(a: [number, number], b: [number, number], t: number): [number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function paramLerp2(
  a: [number, number],
  b: [number, number],
  ta: number,
  tb: number,
  t: number
): [number, number] {
  return lerp2(a, b, (t - ta) / Math.max(1e-8, tb - ta));
}

function centripetalCatmullRomPoint(
  p0: [number, number],
  p1: [number, number],
  p2: [number, number],
  p3: [number, number],
  t: number,
  alpha: number
): [number, number] {
  const eps = 1e-8;
  const t0 = 0;
  const t1 = t0 + Math.max(eps, dist(p0, p1)) ** alpha;
  const t2 = t1 + Math.max(eps, dist(p1, p2)) ** alpha;
  const t3 = t2 + Math.max(eps, dist(p2, p3)) ** alpha;

  const A1 = paramLerp2(p0, p1, t0, t1, t);
  const A2 = paramLerp2(p1, p2, t1, t2, t);
  const A3 = paramLerp2(p2, p3, t2, t3, t);

  const B1 = paramLerp2(A1, A2, t0, t2, t);
  const B2 = paramLerp2(A2, A3, t1, t3, t);

  return paramLerp2(B1, B2, t1, t2, t);
}

export function centripetalCatmullRomSplineLngLat(
  ring: [number, number][],
  subdivisionsPerSpan: number,
  alpha: number
): [number, number][] {
  const n = ring.length;
  if (n < 3 || subdivisionsPerSpan < 1) return ring;

  let subdiv = Math.max(1, Math.floor(subdivisionsPerSpan));
  const est = (n - 1) * subdiv;
  if (est > MAX_SPLINE_VERTICES) {
    subdiv = Math.max(1, Math.floor(MAX_SPLINE_VERTICES / Math.max(1, n - 1)));
  }

  const get = (i: number) => ring[Math.max(0, Math.min(n - 1, i))];

  const out: [number, number][] = [];
  for (let i = 0; i < n - 1; i++) {
    const p0 = get(i - 1);
    const p1 = get(i);
    const p2 = get(i + 1);
    const p3 = get(i + 2);
    const t0 = 0;
    const t1 = t0 + Math.max(1e-8, dist(p0, p1)) ** alpha;
    const t2 = t1 + Math.max(1e-8, dist(p1, p2)) ** alpha;
    for (let s = 0; s < subdiv; s++) {
      const u = s / subdiv;
      const t = t1 + u * (t2 - t1);
      out.push(centripetalCatmullRomPoint(p0, p1, p2, p3, t, alpha));
    }
  }
  out.push(ring[n - 1]!);
  return out;
}

/** @deprecated kept for callers/tests; uses centripetal α=0.5 */
export function catmullRomSplineLngLat(
  ring: [number, number][],
  subdivisionsPerSpan: number
): [number, number][] {
  return centripetalCatmullRomSplineLngLat(ring, subdivisionsPerSpan, 0.5);
}

function splineSegmentsDefault(): number {
  const n = parseIntEnv(process.env.NEXT_PUBLIC_FLIGHT_PATH_SPLINE_SEGMENTS, 14);
  return Math.max(0, n);
}

function chaikinPassesDefault(): number {
  const n = parseIntEnv(process.env.NEXT_PUBLIC_FLIGHT_PATH_CHAIKIN_PASSES, 2);
  return Math.max(0, Math.min(4, n));
}

function splineAlphaDefault(): number {
  const raw = process.env.NEXT_PUBLIC_FLIGHT_PATH_SPLINE_ALPHA;
  if (raw === undefined || raw === "") return 0.5;
  const a = parseFloat(raw);
  if (!Number.isFinite(a)) return 0.5;
  return Math.min(1, Math.max(0.25, a));
}

function greatCircleDefaults(): { minPerEdge: number; maxPerEdge: number; maxTotal: number; enabled: boolean } {
  return {
    enabled: parseBoolEnv(process.env.NEXT_PUBLIC_FLIGHT_PATH_GREAT_CIRCLE, true),
    minPerEdge: Math.max(4, Math.min(24, parseIntEnv(process.env.NEXT_PUBLIC_FLIGHT_PATH_GC_MIN_STEPS, 8))),
    maxPerEdge: Math.max(6, Math.min(36, parseIntEnv(process.env.NEXT_PUBLIC_FLIGHT_PATH_GC_MAX_STEPS, 24))),
    maxTotal: Math.max(120, Math.min(600, parseIntEnv(process.env.NEXT_PUBLIC_FLIGHT_PATH_GC_MAX_VERTICES, 380))),
  };
}

/**
 * Lng/lat ring for Mapbox LineString:
 * 1) Use backend-provided ADS-B polyline points when present,
 * 2) Otherwise use backend corridor start/end only,
 * 3) Great-circle densify each segment so known endpoints are displayed on the globe path.
 */
export function flightPathToLineLngLat(path: FlightPath): [number, number][] {
  const poly = path.path?.filter(Boolean) ?? [];
  let ring: [number, number][] =
    poly.length >= 2
      ? poly.map((c) => [c.lng, c.lat] as [number, number])
      : [
          [path.start.lng, path.start.lat],
          [path.end.lng, path.end.lat],
        ];

  if (ring.length < 2) {
    return [[path.start.lng, path.start.lat], [path.end.lng, path.end.lat]];
  }

  const gc = greatCircleDefaults();
  if (gc.enabled) {
    ring = densifyRingGreatCircle(ring, gc.minPerEdge, gc.maxPerEdge, gc.maxTotal);
  }

  return ring;
}

/** Same geometry as the map line, for plane markers along the visible path. */
export function flightPathToRouteLatLng(path: FlightPath): { lat: number; lng: number }[] {
  return flightPathToLineLngLat(path).map(([lng, lat]) => ({ lat, lng }));
}
