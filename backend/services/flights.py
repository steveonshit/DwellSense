"""
Determines flight geometry for /scan map_data.

- Default ``FLIGHT_MODE=auto`` builds polylines from Supabase ``adsb_samples`` (filled by
  optional ingest) so user scans do not call OpenSky. Falls back to static NYC corridors.
- ``FLIGHT_MODE=live_adsb`` uses OpenSky with strict per-request timeouts (optional).
"""

import os
import math
import time
import asyncio
import httpx
import logging
from datetime import datetime, timedelta, timezone

from models.schemas import Coordinate, FlightPath
from services.city_data import _get_client

OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")
# auto: Supabase adsb_samples polylines (no per-scan OpenSky), then static corridors.
# static: corridor segments only. live_adsb: capped OpenSky track API (may still be slow/unavailable).
# "adsb" is treated as "auto" for backward compatibility (old adsb hammered OpenSky every scan).
FLIGHT_MODE = (os.getenv("FLIGHT_MODE", "auto") or "auto").strip().lower()
logger = logging.getLogger(__name__)

# Minimal airline mapping from common ICAO airline designators.
ICAO_AIRLINE_NAMES = {
    "DAL": "Delta",
    "AAL": "American",
    "UAL": "United",
    "JBU": "JetBlue",
    "SWA": "Southwest",
    "NKS": "Spirit",
    "FFT": "Frontier",
    "ASA": "Alaska",
    # Common US regionals (still "commercial" to users)
    "EDV": "Delta Connection",   # Endeavor
    "SKW": "United Express",     # SkyWest
    "RPA": "American Eagle",     # Republic
    "ASH": "American Eagle",     # Envoy/legacy
    "ENY": "American Eagle",     # Envoy
    "JIA": "American Eagle",     # PSA
}


def _parse_callsign(cs: str | None) -> tuple[str | None, str | None, str | None]:
    """
    OpenSky callsigns often look like 'DAL1234' (ICAO airline + digits).
    Returns (callsign, airline_name, flight_number).
    """
    if not cs:
        return None, None, None
    c = "".join(str(cs).split()).upper()
    if not c:
        return None, None, None
    prefix = c[:3] if len(c) >= 3 else None
    num = c[3:] if len(c) > 3 else None
    airline = ICAO_AIRLINE_NAMES.get(prefix) if prefix else None
    flight_number = None
    if prefix and num and any(ch.isdigit() for ch in num):
        # Prefer human-friendly numeric flight number when airline known.
        digits = "".join(ch for ch in num if ch.isdigit())
        flight_number = digits or None
    return c, airline, flight_number

# Small helper set for labeling ADS-B tracks (not used to fabricate geometry).
NYC_AIRPORTS = {
    "EWR": Coordinate(lat=40.6895, lng=-74.1745),
    "LGA": Coordinate(lat=40.7769, lng=-73.8740),
    "JFK": Coordinate(lat=40.6413, lng=-73.7781),
}

def _nearest_airport(point: Coordinate) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for code, ap in NYC_AIRPORTS.items():
        d = _haversine_miles(point.lat, point.lng, ap.lat, ap.lng)
        if best is None or d < best[1]:
            best = (code, d)
    return best

# NYC airport approach/departure corridors (very simplified straight-line segments).
# NOTE: This is heuristic corridor modeling, not FAA track data. We keep the list small
# and return multiple nearby corridors to reduce false certainty.
# start = where the plane comes from (far out), end = the airport.
NYC_FLIGHT_CORRIDORS = [
    {
        "airport": "JFK",
        "runway": "31L/R (E approach)",
        "start": Coordinate(lat=40.8500, lng=-72.8000),  # East approach over the Atlantic
        "end": Coordinate(lat=40.6413, lng=-73.7781),
        "description": "JFK approach corridor — planes fly low over Queens from the east.",
    },
    {
        "airport": "JFK",
        "runway": "13L/R (W approach)",
        "start": Coordinate(lat=40.7700, lng=-74.2500),  # West approach over NJ / Lower Bay
        "end": Coordinate(lat=40.6413, lng=-73.7781),
        "description": "JFK approach corridor — planes can approach from the west.",
    },
    {
        "airport": "JFK",
        "runway": "04L/R (SW approach)",
        "start": Coordinate(lat=40.4300, lng=-74.2500),  # Southwest approach over Staten Island / Raritan
        "end": Coordinate(lat=40.6413, lng=-73.7781),
        "description": "JFK approach corridor — planes can approach from the southwest.",
    },
    {
        "airport": "LGA",
        "runway": "13/31 (NE approach)",
        "start": Coordinate(lat=40.9000, lng=-73.5000),  # Northeast approach
        "end": Coordinate(lat=40.7769, lng=-73.8740),
        "description": "LaGuardia approach — low over Flushing Bay and northern Queens.",
    },
    {
        "airport": "LGA",
        "runway": "22/04 (SW approach)",
        "start": Coordinate(lat=40.6000, lng=-74.1500),  # Southwest approach over Upper Bay
        "end": Coordinate(lat=40.7769, lng=-73.8740),
        "description": "LaGuardia approach — planes can arrive from the southwest.",
    },
    {
        "airport": "EWR",
        "runway": "22L/R (E approach)",
        "start": Coordinate(lat=40.8000, lng=-73.9000),  # Approach from Manhattan
        "end": Coordinate(lat=40.6895, lng=-74.1745),
        "description": "Newark approach — planes cross upper Manhattan and the Hudson.",
    },
    {
        "airport": "EWR",
        "runway": "04L/R (W approach)",
        "start": Coordinate(lat=40.7200, lng=-74.7000),  # West approach over NJ
        "end": Coordinate(lat=40.6895, lng=-74.1745),
        "description": "Newark approach — planes can approach from the west.",
    },
]


EARTH_RADIUS_MILES = 3958.7613


def _to_rad(c: Coordinate) -> tuple[float, float]:
    return math.radians(c.lat), math.radians(c.lng)


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points (miles)."""
    a = Coordinate(lat=float(lat1), lng=float(lng1))
    b = Coordinate(lat=float(lat2), lng=float(lng2))
    return _angular_distance(a, b) * EARTH_RADIUS_MILES


def _angular_distance(a: Coordinate, b: Coordinate) -> float:
    """Great-circle angular distance (radians)."""
    lat1, lon1 = _to_rad(a)
    lat2, lon2 = _to_rad(b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (math.sin(dlat / 2) ** 2) + math.cos(lat1) * math.cos(lat2) * (math.sin(dlon / 2) ** 2)
    return 2 * math.asin(min(1.0, math.sqrt(h)))


def _best_within_segment_indices(within: list[bool], min_idx: int, pad: int) -> tuple[int, int] | None:
    """
    Choose the longest contiguous True-run that includes min_idx if possible.
    Otherwise choose the longest True-run overall.
    Returns slice indices [start_i, end_i) into coords.
    """
    n = len(within)
    runs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if not within[i]:
            i += 1
            continue
        j = i
        while j < n and within[j]:
            j += 1
        runs.append((i, j))  # [i, j)
        i = j

    if not runs:
        return None

    chosen = None
    for a, b in runs:
        if a <= min_idx < b:
            chosen = (a, b)
            break
    if chosen is None:
        chosen = max(runs, key=lambda ab: (ab[1] - ab[0], -abs(((ab[0] + ab[1]) // 2) - min_idx)))

    a, b = chosen
    start_i = max(0, a - pad)
    end_i = min(n, b + pad)
    return start_i, end_i


def _bearing(a: Coordinate, b: Coordinate) -> float:
    """Initial bearing from a to b (radians)."""
    lat1, lon1 = _to_rad(a)
    lat2, lon2 = _to_rad(b)
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.atan2(y, x)


def _distance_point_to_segment_miles(point: Coordinate, start: Coordinate, end: Coordinate) -> float:
    """
    Minimum great-circle distance from `point` to the segment `start`→`end` (miles).
    Uses cross-track distance with endpoint fallback when projection is outside segment.
    """
    if start.lat == end.lat and start.lng == end.lng:
        return _angular_distance(point, start) * EARTH_RADIUS_MILES

    δ13 = _angular_distance(start, point)
    δ12 = _angular_distance(start, end)
    if δ12 == 0:
        return δ13 * EARTH_RADIUS_MILES

    θ13 = _bearing(start, point)
    θ12 = _bearing(start, end)

    # Cross-track angular distance
    δxt = math.asin(max(-1.0, min(1.0, math.sin(δ13) * math.sin(θ13 - θ12))))

    # Along-track angular distance from start to closest point
    # Guard against numerical issues if cos(δxt) is ~0
    cos_δxt = math.cos(δxt)
    if abs(cos_δxt) < 1e-12:
        # essentially orthogonal at the pole-ish edge case; fall back to endpoints
        return min(
            _angular_distance(point, start),
            _angular_distance(point, end),
        ) * EARTH_RADIUS_MILES

    δat = math.acos(max(-1.0, min(1.0, math.cos(δ13) / cos_δxt)))

    # If closest point lies beyond the segment endpoints, use endpoint distance
    if δat < 0 or δat > δ12:
        return min(
            _angular_distance(point, start),
            _angular_distance(point, end),
        ) * EARTH_RADIUS_MILES

    return abs(δxt) * EARTH_RADIUS_MILES


def get_nearest_flight_corridor(coord: Coordinate) -> FlightPath | None:
    """
    Returns the nearest flight corridor within 3 miles of the address.
    Returns None if the address is not under a flight path.
    """
    paths = get_nearby_flight_corridors(coord, limit=1, max_distance_miles=3.0)
    return paths[0] if paths else None


def get_nearby_flight_corridors(
    coord: Coordinate,
    *,
    limit: int = 3,
    max_distance_miles: float = 3.0,
) -> list[FlightPath]:
    """
    Returns up to `limit` nearby corridors (nearest first) within `max_distance_miles`.
    """
    scored: list[tuple[float, dict]] = []
    for corridor in NYC_FLIGHT_CORRIDORS:
        dist = _distance_point_to_segment_miles(coord, corridor["start"], corridor["end"])
        if dist <= max_distance_miles:
            scored.append((dist, corridor))

    scored.sort(key=lambda x: x[0])
    out: list[FlightPath] = []
    for dist, corridor in scored[: max(0, int(limit))]:
        out.append(
            FlightPath(
                start=corridor["start"],
                end=corridor["end"],
                label=f"{corridor['airport']} Corridor — {corridor['runway']} ({dist:.1f} mi)",
            )
        )
    return out


def _bbox_from_center(coord: Coordinate, radius_miles: float) -> tuple[float, float, float, float]:
    # Approx conversion near the point.
    dlat = radius_miles / 69.0
    dlng = radius_miles / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
    return coord.lat - dlat, coord.lat + dlat, coord.lng - dlng, coord.lng + dlng


def _decimate_indices(n: int, max_points: int) -> list[int]:
    """Evenly-spaced indices preserving endpoints when n > max_points."""
    if n <= max_points or n < 2:
        return list(range(n))
    step = (n - 1) / (max_points - 1)
    out = [0]
    for i in range(1, max_points - 1):
        out.append(min(n - 2, int(round(i * step))))
    out.append(n - 1)
    # de-dupe preserving order
    seen: set[int] = set()
    uniq: list[int] = []
    for i in out:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq


def get_stored_sample_flight_paths(
    coord: Coordinate,
    *,
    limit: int = 3,
) -> list[FlightPath]:
    """
    Build map polylines from Supabase `adsb_samples` (same source as flight_exposure).
    One DB round-trip per scan — no OpenSky calls here, so no ingest-induced timeouts.
    """
    try:
        days = max(1, min(14, int(os.getenv("ADSB_PATH_DAYS", "7"))))
    except ValueError:
        days = 7
    try:
        bbox_radius = max(5.0, min(40.0, float(os.getenv("ADSB_PATH_BBOX_MILES", "22"))))
    except ValueError:
        bbox_radius = 22.0
    try:
        # Hourly ingest → most aircraft get ≤1 row per run; requiring 4+ points per ICAO
        # almost always yields zero polylines → static corridor fallback. 2 = minimum line.
        min_points = max(2, min(20, int(os.getenv("ADSB_PATH_MIN_POINTS", "2"))))
    except ValueError:
        min_points = 2
    try:
        max_points = max(8, min(80, int(os.getenv("ADSB_PATH_MAX_POINTS", "40"))))
    except ValueError:
        max_points = 40
    try:
        row_limit = max(2000, min(25000, int(os.getenv("ADSB_PATH_ROW_LIMIT", "15000"))))
    except ValueError:
        row_limit = 15000

    try:
        supabase = _get_client()
    except Exception:
        return []

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    lat_min, lat_max, lng_min, lng_max = _bbox_from_center(coord, bbox_radius)

    try:
        res = (
            supabase.table("adsb_samples")
            .select("observed_at,icao24,lat,lng,baro_alt_m,geo_alt_m,on_ground")
            .gte("observed_at", since_iso)
            .gte("lat", lat_min)
            .lte("lat", lat_max)
            .gte("lng", lng_min)
            .lte("lng", lng_max)
            .order("observed_at", desc=True)
            .limit(row_limit)
            .execute()
        )
        rows = getattr(res, "data", None) or []
    except Exception:
        logger.exception("stored sample flight paths: Supabase query failed")
        return []

    if not rows:
        return []

    by_icao: dict[str, list[dict]] = {}
    for r in rows:
        icao = str(r.get("icao24") or "").strip().lower()
        if not icao:
            continue
        if r.get("on_ground") is True:
            continue
        try:
            lat = float(r["lat"])
            lng = float(r["lng"])
        except Exception:
            continue
        by_icao.setdefault(icao, []).append(r)

    candidates: list[tuple[float, str, list[Coordinate], list[float]]] = []
    for icao, pts in by_icao.items():
        if len(pts) < 1:
            continue
        pts_sorted = sorted(pts, key=lambda x: str(x.get("observed_at") or ""))
        series: list[tuple[Coordinate, float | None]] = []
        for p in pts_sorted:
            try:
                la = float(p["lat"])
                lo = float(p["lng"])
            except Exception:
                continue
            alt_m = p.get("geo_alt_m") if isinstance(p.get("geo_alt_m"), (int, float)) else p.get("baro_alt_m")
            alt_f = float(alt_m) if isinstance(alt_m, (int, float)) else None
            series.append((Coordinate(lat=la, lng=lo), alt_f))

        if len(series) < 1:
            continue
        raw_count = len(series)
        # Hourly ingest: many aircraft only have one row until the next run. Map needs ≥2
        # vertices; add a short east-west stub (~100m) so we never lie about position.
        if raw_count == 1:
            c, a = series[0]
            dlng = 0.0014 / max(0.2, math.cos(math.radians(c.lat)))
            series.append((Coordinate(lat=c.lat, lng=c.lng + dlng), a))
        elif raw_count < min_points:
            continue

        coords_full = [t[0] for t in series]
        alts_m = [t[1] for t in series]

        idxs = _decimate_indices(len(coords_full), max_points)
        coords = [coords_full[i] for i in idxs]
        alts_track = [alts_m[i] for i in idxs]
        dists = [_haversine_miles(coord.lat, coord.lng, c.lat, c.lng) for c in coords]
        min_d = min(dists) if dists else 999.0
        # Skip aircraft that never came reasonably close (reduces clutter / bogus lines)
        if min_d > min(bbox_radius * 0.85, 18.0):
            continue

        candidates.append((min_d, icao, coords, alts_track, raw_count))

    candidates.sort(key=lambda x: x[0])
    out: list[FlightPath] = []
    for min_d, icao, coords, alts_track, raw_count in candidates:
        if len(coords) < 2:
            continue
        cleaned_alts = [float(a) for a in alts_track if isinstance(a, (int, float)) and float(a) > 1.0]
        median_alt_ft = None
        if cleaned_alts:
            cleaned_alts.sort()
            med_m = cleaned_alts[len(cleaned_alts) // 2]
            median_alt_ft = int(round(med_m * 3.28084))

        alt_txt = f", ~{median_alt_ft} ft" if median_alt_ft is not None else ""
        snap = " — single snapshot" if raw_count == 1 else ""
        label = f"Recent ADS-B track ({icao.upper()}{alt_txt}, closest {min_d:.1f} mi){snap}"
        out.append(
            FlightPath(
                start=coords[0],
                end=coords[-1],
                label=label,
                path=coords,
                closest_miles=float(round(min_d, 2)),
                median_altitude_ft=median_alt_ft,
                sample_count=len(coords),
                callsign=None,
                airline=None,
                flight_number=None,
                last_seen_utc=None,
            )
        )
        if len(out) >= limit:
            break

    return out


def _fit_corridor_through_property(
    coord: Coordinate,
    points: list[tuple[float, float]],
    *,
    half_len_miles: float = 25.0,
) -> tuple[Coordinate, Coordinate]:
    """
    Fit a dominant direction from points (lat,lng) and return a segment centered on the property.
    Uses PCA on a local miles-projection.
    """
    if len(points) < 2:
        return coord, coord

    lat0 = coord.lat
    lng0 = coord.lng
    scale_lng = max(0.2, math.cos(math.radians(lat0)))

    xs: list[float] = []
    ys: list[float] = []
    for lat, lng in points:
        xs.append((lng - lng0) * scale_lng * 69.0)
        ys.append((lat - lat0) * 69.0)

    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cx = [x - mx for x in xs]
    cy = [y - my for y in ys]

    sxx = sum(x * x for x in cx) / max(1, len(cx))
    syy = sum(y * y for y in cy) / max(1, len(cy))
    sxy = sum(x * y for x, y in zip(cx, cy)) / max(1, len(cx))

    # Largest-eigenvector of [[sxx,sxy],[sxy,syy]]
    trace = sxx + syy
    det = sxx * syy - sxy * sxy
    disc = max(0.0, trace * trace - 4.0 * det)
    lam1 = 0.5 * (trace + math.sqrt(disc))

    vx = sxy
    vy = lam1 - sxx
    if abs(vx) < 1e-9 and abs(vy) < 1e-9:
        # degenerate / perfectly axis-aligned; pick the axis with larger variance
        vx, vy = (1.0, 0.0) if sxx >= syy else (0.0, 1.0)

    vlen = math.hypot(vx, vy) or 1.0
    ux, uy = vx / vlen, vy / vlen

    dlat = (half_len_miles * uy) / 69.0
    dlng = (half_len_miles * ux) / (69.0 * scale_lng)

    start = Coordinate(lat=lat0 - dlat, lng=lng0 - dlng)
    end = Coordinate(lat=lat0 + dlat, lng=lng0 + dlng)
    return start, end


async def get_adsb_flight_corridors(
    coord: Coordinate,
    *,
    limit: int = 3,
    radius_miles: float = 25.0,
    min_points_per_corridor: int = 3,
) -> list[FlightPath]:
    """Deprecated: corridor clustering from a single ADS-B snapshot."""
    lat_min, lat_max, lng_min, lng_max = _bbox_from_center(coord, radius_miles)
    auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD) if OPENSKY_USERNAME else None

    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            "https://opensky-network.org/api/states/all",
            params={"lamin": lat_min, "lamax": lat_max, "lomin": lng_min, "lomax": lng_max},
            auth=auth,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    states = data.get("states") or []
    if not isinstance(states, list) or not states:
        return []

    # Bucket by track heading (mod 180 => same corridor both directions).
    buckets: dict[int, list[dict]] = {}
    for s in states:
        if not isinstance(s, list) or len(s) < 11:
            continue
        lng = s[5]
        lat = s[6]
        alt_m = s[7]
        on_ground = s[8]
        track = s[10]
        if lat is None or lng is None or track is None:
            continue
        if on_ground is True:
            continue
        # Keep low-ish aircraft (noise-relevant) but not ground clutter.
        if isinstance(alt_m, (int, float)):
            if alt_m < 150 or alt_m > 9000:  # ~500 ft .. ~30k ft
                continue
        # 10° bins over 0..180 (more separation with modest point counts)
        t = float(track) % 180.0
        bin_id = int(t // 10)
        buckets.setdefault(bin_id, []).append(
            {"lat": float(lat), "lng": float(lng), "alt_m": float(alt_m) if isinstance(alt_m, (int, float)) else None}
        )

    if not buckets:
        return []

    # Pick top bins by count
    ranked = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)[: max(0, int(limit))]
    out: list[FlightPath] = []
    for bin_id, rows in ranked:
        if len(rows) < min_points_per_corridor:
            continue
        pts = [(r["lat"], r["lng"]) for r in rows]
        start, end = _fit_corridor_through_property(coord, pts, half_len_miles=25.0)
        alts = [r["alt_m"] for r in rows if isinstance(r.get("alt_m"), (int, float))]
        med_alt_ft = None
        if alts:
            alts_sorted = sorted(alts)
            med_alt_m = alts_sorted[len(alts_sorted) // 2]
            med_alt_ft = int(round(med_alt_m * 3.28084))

        lo = bin_id * 10
        hi = lo + 10
        alt_txt = f", ~{med_alt_ft} ft" if med_alt_ft is not None else ""
        label = f"ADS-B corridor ({len(rows)} planes, {lo}–{hi}°{alt_txt})"
        out.append(FlightPath(start=start, end=end, label=label))

    return out


async def get_adsb_tracks_near_property(
    coord: Coordinate,
    *,
    limit: int = 3,
    radius_miles: float = 25.0,
    near_miles: float = 10.0,
    max_tracks: int = 3,
) -> list[FlightPath]:
    """
    Return up to `limit` REAL ADS-B tracks near the property (OpenSky live API).

    Strategy:
    - Pull current aircraft states in a bounding box (OpenSky `states/all`)
    - Keep aircraft reasonably close to the property (<= near_miles) and in-air
    - For the closest few ICAOs, fetch OpenSky `tracks/all` **sequentially** with a short
      per-request timeout so `/scan` does not fan out dozens of parallel calls.
    """
    try:
        max_tracks = max(1, min(5, int(os.getenv("OPENSKY_MAX_TRACK_FETCHES", str(max_tracks)))))
    except ValueError:
        max_tracks = 3

    lat_min, lat_max, lng_min, lng_max = _bbox_from_center(coord, radius_miles)
    auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD) if OPENSKY_USERNAME else None

    timeout = httpx.Timeout(12.0, connect=6.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            "https://opensky-network.org/api/states/all",
            params={"lamin": lat_min, "lamax": lat_max, "lomin": lng_min, "lomax": lng_max},
            auth=auth,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

        states = data.get("states") or []
        if not isinstance(states, list) or not states:
            return []

        # Pick closest aircraft to the property.
        # Track callsign too so we can label flights in a human-friendly way.
        candidates: list[tuple[float, str, str | None]] = []
        for s in states:
            if not isinstance(s, list) or len(s) < 11:
                continue
            icao24 = s[0]
            callsign = s[1] if len(s) > 1 else None
            lng = s[5]
            lat = s[6]
            on_ground = s[8]
            alt_m = s[7]
            if not icao24 or lat is None or lng is None:
                continue
            if on_ground is True:
                continue
            # Ignore very high overflights; keep broadly "noise relevant" band.
            if isinstance(alt_m, (int, float)) and alt_m > 12000:
                continue
            d = _haversine_miles(coord.lat, coord.lng, float(lat), float(lng))
            if d <= near_miles:
                candidates.append((d, str(icao24), str(callsign) if isinstance(callsign, str) else None))

        if not candidates:
            return []

        candidates.sort(key=lambda x: x[0])
        top = candidates[:max_tracks]

        now = int(time.time())

        async def _fetch_track(icao24: str) -> dict | None:
            try:
                r = await client.get(
                    "https://opensky-network.org/api/tracks/all",
                    params={"icao24": icao24, "time": now},
                    auth=auth,
                )
                if r.status_code != 200:
                    return None
                return r.json()
            except Exception:
                return None

        tracks: list[dict | None] = []
        try:
            per_track_timeout = max(3.0, min(12.0, float(os.getenv("OPENSKY_TRACK_TIMEOUT_SECONDS", "5"))))
        except ValueError:
            per_track_timeout = 5.0
        for _, icao, _ in top:
            try:
                tr = await asyncio.wait_for(_fetch_track(icao), timeout=per_track_timeout)
            except asyncio.TimeoutError:
                logger.warning("OpenSky track fetch timed out (icao=%s)", icao)
                tr = None
            except Exception:
                tr = None
            tracks.append(tr)

    out: list[FlightPath] = []
    for (dist, icao24, callsign_raw), tdata in zip(top, tracks):
        if not tdata or not isinstance(tdata, dict):
            continue
        path = tdata.get("path")
        if not isinstance(path, list) or len(path) < 2:
            continue

        coords: list[Coordinate] = []
        alts_m: list[float] = []
        times: list[int] = []
        for p in path:
            # OpenSky path entries are typically [time, lat, lon, baro_alt, true_track, on_ground]
            if not isinstance(p, list) or len(p) < 3:
                continue
            if isinstance(p[0], (int, float)):
                times.append(int(p[0]))
            lat = p[1]
            lon = p[2]
            if lat is None or lon is None:
                continue
            try:
                coords.append(Coordinate(lat=float(lat), lng=float(lon)))
            except Exception:
                continue
            # baro_alt in meters is often at index 3 when present
            if len(p) > 3 and isinstance(p[3], (int, float)):
                alts_m.append(float(p[3]))

        if len(coords) < 2:
            continue

        # Keep a longer continuous segment near the property.
        # OpenSky "tracks" can include points far away; we keep the contiguous pass
        # around the closest approach where the aircraft stays within `keep_miles`.
        dists = [_haversine_miles(coord.lat, coord.lng, c.lat, c.lng) for c in coords]
        min_idx = min(range(len(dists)), key=dists.__getitem__)

        keep_miles = 15.0
        pad = 6  # a few samples of context beyond the threshold

        within = [d <= keep_miles for d in dists]
        seg = _best_within_segment_indices(within, min_idx, pad) if any(within) else None
        if seg:
            start_i, end_i = seg
        else:
            # Fallback: fixed window if nothing falls within threshold (rare)
            window = 20
            start_i = max(0, min_idx - window)
            end_i = min(len(coords), min_idx + window + 1)

        coords_near = coords[start_i:end_i]
        if len(coords_near) < 2:
            continue

        min_dist_near = min(dists[start_i:end_i])

        # Median altitude from available samples (best-effort).
        median_alt_ft = None
        if alts_m:
            # Remove obviously invalid values that show up as 0.0
            cleaned = [a for a in alts_m if a and a > 1.0]
            alts_m_sorted = sorted(cleaned)
            if not alts_m_sorted:
                median_alt_ft = None
            else:
                med_m = alts_m_sorted[len(alts_m_sorted) // 2]
                median_alt_ft = int(round(med_m * 3.28084))

        # Infer (when possible) whether this track is arriving/departing a NYC airport.
        # This is labeling only — geometry remains purely the real ADS-B polyline.
        start_full = coords[0]
        end_full = coords[-1]
        start_ap = _nearest_airport(start_full)
        end_ap = _nearest_airport(end_full)
        airport_hint = ""
        # Threshold is intentionally loose; OpenSky track window may not reach the runway.
        if end_ap and end_ap[1] <= 15:
            airport_hint = f" → {end_ap[0]}"
        elif start_ap and start_ap[1] <= 15:
            airport_hint = f" ← {start_ap[0]}"

        # Track endpoints for map line; polyline is the truth.
        start = coords_near[0]
        end = coords_near[-1]
        callsign, airline, flight_number = _parse_callsign(callsign_raw)
        pretty = None
        if airline and flight_number:
            pretty = f"{airline} {flight_number}"
        elif callsign:
            pretty = callsign
        else:
            pretty = f"Flight {icao24}"

        label = f"{pretty}{airport_hint} (closest {min_dist_near:.1f} mi)"
        last_seen_ts = None
        if times:
            # Use the last timestamp that corresponds to the sliced segment, if possible.
            times_near = times[start_i:end_i]
            if times_near:
                last_seen_ts = times_near[-1]

        out.append(
            FlightPath(
                start=start,
                end=end,
                label=label,
                path=coords_near,
                closest_miles=float(round(min_dist_near, 2)),
                median_altitude_ft=median_alt_ft,
                sample_count=len(coords_near),
                callsign=callsign,
                airline=airline,
                flight_number=flight_number,
                # Use the timestamp of the last point in the returned polyline when available.
                last_seen_utc=(
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_seen_ts))
                    if last_seen_ts is not None
                    else None
                ),
            )
        )

        if len(out) >= limit:
            break

    return out


async def get_flight_paths(
    coord: Coordinate,
    *,
    limit: int = 3,
) -> list[FlightPath]:
    """
    Main entry point for scan pipeline.

    - ``auto`` (default): polylines from Supabase ``adsb_samples`` when ingest has data;
      otherwise static NYC corridors. No OpenSky calls on this path.
    - ``static``: simplified hand-authored corridor segments only.
    - ``live_adsb``: capped OpenSky ``states`` + a few sequential ``tracks`` calls; falls
      back to static if empty or slow.
    - ``adsb`` is accepted as an alias for ``auto`` (legacy env files).
    """
    mode = (FLIGHT_MODE or "auto").strip().lower()
    if mode == "adsb":
        mode = "auto"

    def static_paths() -> list[FlightPath]:
        return get_nearby_flight_corridors(coord, limit=limit, max_distance_miles=3.0)

    if mode == "static":
        return static_paths()

    if mode == "auto":
        try:
            paths = await asyncio.to_thread(get_stored_sample_flight_paths, coord, limit=limit)
        except Exception:
            logger.exception("stored sample flight paths failed")
            paths = []
        if paths:
            logger.info("flight paths: returning %d stored-sample track(s)", len(paths))
            return paths
        logger.info("flight paths: no stored samples in window — static corridors")
        return static_paths()

    if mode == "live_adsb":
        try:
            budget = float(os.getenv("OPENSKY_SCAN_BUDGET_SECONDS", "18"))
        except ValueError:
            budget = 18.0
        budget = max(8.0, min(45.0, budget))
        try:
            paths = await asyncio.wait_for(
                get_adsb_tracks_near_property(coord, limit=limit),
                timeout=budget,
            )
        except asyncio.TimeoutError:
            logger.warning("live OpenSky flight path fetch exceeded %.0fs — static fallback", budget)
            paths = []
        except Exception:
            logger.exception("live OpenSky flight paths failed")
            paths = []
        if paths:
            logger.info("live ADS-B: returning %d track(s)", len(paths))
            return paths
        return static_paths()

    logger.warning("unknown FLIGHT_MODE=%s — using auto", FLIGHT_MODE)
    try:
        paths = await asyncio.to_thread(get_stored_sample_flight_paths, coord, limit=limit)
    except Exception:
        paths = []
    return paths if paths else static_paths()


async def get_live_plane_position(
    lat_min: float, lat_max: float,
    lng_min: float, lng_max: float
) -> Coordinate | None:
    """
    Fetches a live plane position from OpenSky Network within a bounding box.
    Returns None if unavailable or no planes in the area.
    """
    try:
        auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD) if OPENSKY_USERNAME else None
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://opensky-network.org/api/states/all",
                params={
                    "lamin": lat_min, "lamax": lat_max,
                    "lomin": lng_min, "lomax": lng_max,
                },
                auth=auth,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            states = data.get("states", [])
            if not states:
                return None
            # Return position of first aircraft found [lat=6, lng=5]
            plane = states[0]
            if plane[6] and plane[5]:
                return Coordinate(lat=plane[6], lng=plane[5])
    except Exception:
        pass
    return None
