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


def _dedupe_track_points(
    coords: list[Coordinate],
    times: list[datetime | None],
    alts: list[float | None],
    min_sep_miles: float,
) -> tuple[list[Coordinate], list[datetime | None], list[float | None]]:
    """Drop consecutive vertices closer than min_sep_miles (duplicate GPS / ingest noise)."""
    if not coords:
        return [], [], []
    if min_sep_miles <= 0:
        return coords, times, alts
    out_c = [coords[0]]
    out_t: list[datetime | None] = [times[0] if times else None]
    out_a: list[float | None] = [alts[0] if alts else None]
    for i in range(1, len(coords)):
        if _haversine_miles(out_c[-1].lat, out_c[-1].lng, coords[i].lat, coords[i].lng) >= min_sep_miles:
            out_c.append(coords[i])
            out_t.append(times[i] if i < len(times) else None)
            out_a.append(alts[i] if i < len(alts) else None)
    return out_c, out_t, out_a


def _filter_impossible_speed(
    coords: list[Coordinate],
    alts: list[float | None],
    times: list[datetime | None],
    *,
    max_mph: float,
) -> tuple[list[Coordinate], list[float | None], list[datetime | None]]:
    """Drop points that imply faster-than-airliner hops between consecutive timestamps."""
    if len(coords) < 2:
        return coords, alts, times
    n = len(coords)
    aln = (alts + [None] * n)[:n]
    tsn = (times + [None] * n)[:n]
    out_c = [coords[0]]
    out_a: list[float | None] = [aln[0]]
    out_t: list[datetime | None] = [tsn[0]]
    t_last = tsn[0]
    for i in range(1, n):
        t = tsn[i]
        dt_h: float | None = None
        if t_last is not None and t is not None:
            try:
                dt_h = abs((t - t_last).total_seconds()) / 3600.0
            except Exception:
                dt_h = None
        dist = _haversine_miles(out_c[-1].lat, out_c[-1].lng, coords[i].lat, coords[i].lng)
        if dt_h is not None and dt_h > 1e-6 and (dist / dt_h) > max_mph:
            continue
        out_c.append(coords[i])
        out_a.append(aln[i])
        out_t.append(t)
        if t is not None:
            t_last = t
    return out_c, out_a, out_t


def _douglas_peucker_indices(points: list[Coordinate], epsilon_miles: float) -> list[int]:
    """Return vertex indices to keep (always includes endpoints)."""
    n = len(points)
    if n < 3 or epsilon_miles <= 0:
        return list(range(n))
    keep = {0, n - 1}
    stack: list[tuple[int, int]] = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        a, b = points[i0], points[i1]
        imax = i0
        dmax = 0.0
        for j in range(i0 + 1, i1):
            d = _distance_point_to_segment_miles(points[j], a, b)
            if d > dmax:
                dmax, imax = d, j
        if dmax >= epsilon_miles:
            keep.add(imax)
            stack.append((i0, imax))
            stack.append((imax, i1))
    return sorted(keep)


def _smooth_coords_3tap(coords: list[Coordinate], passes: int) -> list[Coordinate]:
    """Light moving average on interior points (reduces jagged ADS-B jitter)."""
    if passes <= 0 or len(coords) < 3:
        return coords
    cur = coords[:]
    for _ in range(passes):
        nxt = [cur[0]]
        for i in range(1, len(cur) - 1):
            nxt.append(
                Coordinate(
                    lat=(cur[i - 1].lat + cur[i].lat + cur[i + 1].lat) / 3.0,
                    lng=(cur[i - 1].lng + cur[i].lng + cur[i + 1].lng) / 3.0,
                )
            )
        nxt.append(cur[-1])
        cur = nxt
    return cur


def _split_series_on_discontinuity(
    series: list[tuple[Coordinate, datetime | None, float | None]],
    max_gap_minutes: float,
    max_implied_mph: float,
    blind_jump_miles: float,
) -> list[list[tuple[Coordinate, datetime | None, float | None]]]:
    """
    Split a time-ordered ADS-B series on:
    - long time gaps (different flights / on-ground),
    - impossible implied speed between consecutive samples (bad merges / bogus pings),
    - optional large spatial jumps when either timestamp is missing (off by default).
    """
    if not series:
        return []
    out: list[list[tuple[Coordinate, datetime | None, float | None]]] = []
    cur: list[tuple[Coordinate, datetime | None, float | None]] = [series[0]]
    for i in range(1, len(series)):
        prev = cur[-1]
        this = series[i]
        d = _haversine_miles(prev[0].lat, prev[0].lng, this[0].lat, this[0].lng)
        split = False
        pt, tt = prev[1], this[1]
        if pt is not None and tt is not None:
            try:
                gap_min = abs((tt - pt).total_seconds()) / 60.0
                if max_gap_minutes > 0 and gap_min > max_gap_minutes:
                    split = True
                else:
                    dt_h = gap_min / 60.0
                    if dt_h > 1e-6 and (d / dt_h) > max_implied_mph:
                        split = True
            except Exception:
                pass
        if (
            not split
            and blind_jump_miles > 0
            and (pt is None or tt is None)
            and d > blind_jump_miles
        ):
            split = True
        if split:
            out.append(cur)
            cur = [this]
        else:
            cur.append(this)
    out.append(cur)
    return out


def _trim_track_near_property(
    property_coord: Coordinate,
    coords: list[Coordinate],
    times: list[datetime | None],
    alts: list[float | None],
    *,
    keep_miles: float,
    pad: int,
) -> tuple[list[Coordinate], list[datetime | None], list[float | None]]:
    """
    Keep one contiguous slice where the aircraft is near the scan address (same idea as
    live OpenSky track slicing).     If nothing falls inside ``keep_miles``, return inputs unchanged.
    """
    if len(coords) < 2 or keep_miles <= 0:
        return coords, times, alts
    dists = [_haversine_miles(property_coord.lat, property_coord.lng, c.lat, c.lng) for c in coords]
    min_idx = min(range(len(dists)), key=dists.__getitem__)
    within = [d <= keep_miles for d in dists]
    if not any(within):
        return coords, times, alts
    seg = _best_within_segment_indices(within, min_idx, pad)
    if seg is None:
        return coords, times, alts
    a, b = seg
    if b - a < 2:
        return coords, times, alts
    return coords[a:b], times[a:b], alts[a:b]


def _bearing_delta_rad(b1: float, b2: float) -> float:
    d = b2 - b1
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return abs(d)


def _drop_sharp_local_reversals(
    coords: list[Coordinate],
    times: list[datetime | None],
    alts: list[float | None],
    *,
    min_turn_deg: float,
    max_leg_miles: float,
) -> tuple[list[Coordinate], list[datetime | None], list[float | None]]:
    """
    Remove interior vertices that look like multilateration zig-zag: very sharp heading
    reversal over two very short legs.
    """
    if len(coords) < 3 or min_turn_deg >= 180 or max_leg_miles <= 0:
        return coords, times, alts
    min_turn = math.radians(min_turn_deg)
    c = coords[:]
    t = (times + [None] * len(coords))[: len(coords)]
    a = (alts + [None] * len(coords))[: len(coords)]
    changed = True
    iterations = 0
    while changed and iterations < 30:
        changed = False
        iterations += 1
        i = 1
        while i < len(c) - 1:
            d1 = _haversine_miles(c[i - 1].lat, c[i - 1].lng, c[i].lat, c[i].lng)
            d2 = _haversine_miles(c[i].lat, c[i].lng, c[i + 1].lat, c[i + 1].lng)
            if d1 <= max_leg_miles and d2 <= max_leg_miles:
                b1 = _bearing(c[i - 1], c[i])
                b2 = _bearing(c[i], c[i + 1])
                if _bearing_delta_rad(b1, b2) >= min_turn:
                    del c[i]
                    del t[i]
                    del a[i]
                    changed = True
                    continue
            i += 1
    return c, t, a


def get_stored_sample_flight_paths(
    coord: Coordinate,
    *,
    limit: int = 3,
) -> list[FlightPath]:
    """
    Build map polylines from Supabase `adsb_samples` (same source as flight_exposure).
    One DB round-trip per scan — no OpenSky calls here, so no ingest-induced timeouts.

    Path shaping (tunable via env): ``ADSB_PATH_MAX_GAP_MINUTES`` + implied-speed splits
    (separate flights / bogus legs), ``ADSB_PATH_KEEP_NEAR_MILES`` / ``ADSB_PATH_KEEP_PAD_POINTS``
    (trim to one near-property pass),
    ``ADSB_PATH_DEDUPE_MIN_SEP_MI``, ``ADSB_PATH_MAX_IMPLIED_MPH``, ``ADSB_PATH_BLIND_JUMP_MILES``,
    ``ADSB_PATH_DP_EPSILON_MILES``, ``ADSB_PATH_SMOOTH_PASSES``, ``ADSB_PATH_SPIKE_*`` (drop local multilateration zig-zags).
    """
    try:
        days = max(1, min(14, int(os.getenv("ADSB_PATH_DAYS", "7"))))
    except ValueError:
        days = 7
    try:
        stability_bucket_minutes = max(5, min(1440, int(os.getenv("ADSB_PATH_STABILITY_BUCKET_MINUTES", "60"))))
    except ValueError:
        stability_bucket_minutes = 60
    try:
        stability_lag_minutes = max(0, min(1440, int(os.getenv("ADSB_PATH_STABILITY_LAG_MINUTES", "0"))))
    except ValueError:
        stability_lag_minutes = 0
    try:
        bbox_radius = max(5.0, min(40.0, float(os.getenv("ADSB_PATH_BBOX_MILES", "22"))))
    except ValueError:
        bbox_radius = 22.0
    try:
        min_points = max(5, min(20, int(os.getenv("ADSB_PATH_MIN_POINTS", "5"))))
    except ValueError:
        min_points = 5
    try:
        max_points = max(8, min(80, int(os.getenv("ADSB_PATH_MAX_POINTS", "40"))))
    except ValueError:
        max_points = 40
    try:
        row_limit = max(2000, min(25000, int(os.getenv("ADSB_PATH_ROW_LIMIT", "15000"))))
    except ValueError:
        row_limit = 15000
    try:
        dedupe_min_sep_mi = max(0.0, min(0.5, float(os.getenv("ADSB_PATH_DEDUPE_MIN_SEP_MI", "0.045"))))
    except ValueError:
        dedupe_min_sep_mi = 0.045
    try:
        max_implied_mph = max(200.0, min(900.0, float(os.getenv("ADSB_PATH_MAX_IMPLIED_MPH", "620"))))
    except ValueError:
        max_implied_mph = 620.0
    try:
        dp_epsilon_mi = max(0.0, min(3.0, float(os.getenv("ADSB_PATH_DP_EPSILON_MILES", "0.52"))))
    except ValueError:
        dp_epsilon_mi = 0.52
    try:
        smooth_passes = max(0, min(4, int(os.getenv("ADSB_PATH_SMOOTH_PASSES", "2"))))
    except ValueError:
        smooth_passes = 2
    try:
        max_gap_minutes = max(20.0, min(720.0, float(os.getenv("ADSB_PATH_MAX_GAP_MINUTES", "120"))))
    except ValueError:
        max_gap_minutes = 120.0
    try:
        keep_near_miles = max(5.0, min(40.0, float(os.getenv("ADSB_PATH_KEEP_NEAR_MILES", "18"))))
    except ValueError:
        keep_near_miles = 18.0
    try:
        keep_pad_points = max(0, min(30, int(os.getenv("ADSB_PATH_KEEP_PAD_POINTS", "6"))))
    except ValueError:
        keep_pad_points = 6
    try:
        spike_min_turn = max(90.0, min(175.0, float(os.getenv("ADSB_PATH_SPIKE_MIN_TURN_DEG", "148"))))
    except ValueError:
        spike_min_turn = 148.0
    try:
        spike_max_leg_mi = max(0.0, min(1.0, float(os.getenv("ADSB_PATH_SPIKE_MAX_LEG_MI", "0.22"))))
    except ValueError:
        spike_max_leg_mi = 0.22
    try:
        blind_jump_miles = max(0.0, min(200.0, float(os.getenv("ADSB_PATH_BLIND_JUMP_MILES", "0"))))
    except ValueError:
        blind_jump_miles = 0.0

    try:
        supabase = _get_client()
    except Exception:
        return []

    now = datetime.now(timezone.utc) - timedelta(minutes=stability_lag_minutes)
    bucket_seconds = stability_bucket_minutes * 60
    stable_until_ts = int(now.timestamp()) // bucket_seconds * bucket_seconds
    stable_until = datetime.fromtimestamp(stable_until_ts, timezone.utc)
    since = stable_until - timedelta(days=days)
    since_iso = since.isoformat()
    until_iso = stable_until.isoformat()
    lat_min, lat_max, lng_min, lng_max = _bbox_from_center(coord, bbox_radius)

    try:
        res = (
            supabase.table("adsb_samples")
            .select("observed_at,icao24,lat,lng,baro_alt_m,geo_alt_m,on_ground")
            .gte("observed_at", since_iso)
            .lt("observed_at", until_iso)
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
            float(r["lat"])
            float(r["lng"])
        except Exception:
            continue
        by_icao.setdefault(icao, []).append(r)

    def _parse_obs(o: object) -> datetime:
        if o is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(str(o).replace("Z", "+00:00"))
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    candidates: list[tuple[float, str, list[Coordinate], list[float | None], int]] = []
    for icao, pts in by_icao.items():
        if not pts:
            continue

        pts_sorted = sorted(pts, key=lambda x: _parse_obs(x.get("observed_at")))
        series: list[tuple[Coordinate, datetime | None, float | None]] = []
        for p in pts_sorted:
            try:
                la = float(p["lat"])
                lo = float(p["lng"])
            except Exception:
                continue
            alt_m = p.get("geo_alt_m") if isinstance(p.get("geo_alt_m"), (int, float)) else p.get("baro_alt_m")
            alt_f = float(alt_m) if isinstance(alt_m, (int, float)) else None
            t_obs: datetime | None = None
            try:
                t_obs = datetime.fromisoformat(str(p.get("observed_at", "")).replace("Z", "+00:00"))
            except Exception:
                t_obs = None
            series.append((Coordinate(lat=la, lng=lo), t_obs, alt_f))

        if not series:
            continue

        segments = _split_series_on_discontinuity(
            series, max_gap_minutes, max_implied_mph, blind_jump_miles
        )
        best_for_icao: tuple[float, str, list[Coordinate], list[float | None], int] | None = None

        for seg in segments:
            raw_count_seg = len(seg)
            if raw_count_seg < min_points:
                continue

            work = list(seg)

            coords_full = [s[0] for s in work]
            times_full = [s[1] for s in work]
            alts_m = [s[2] for s in work]

            coords_full, times_full, alts_m = _trim_track_near_property(
                coord,
                coords_full,
                times_full,
                alts_m,
                keep_miles=keep_near_miles,
                pad=keep_pad_points,
            )
            if len(coords_full) < 2:
                coords_full = [s[0] for s in work]
                times_full = [s[1] for s in work]
                alts_m = [s[2] for s in work]

            # Full-resolution cleanup first. Index-decimating *before* simplify aliases sparse
            # ADS-B into zig-zag chords; DP then smooth, then cap vertices if still too dense.
            coords = list(coords_full)
            times = list(times_full)
            alts_track = list(alts_m)

            if dedupe_min_sep_mi > 0:
                coords, times, alts_track = _dedupe_track_points(coords, times, alts_track, dedupe_min_sep_mi)
            else:
                times = (times + [None] * len(coords))[: len(coords)]
                alts_track = (alts_track + [None] * len(coords))[: len(coords)]

            if spike_max_leg_mi > 0 and spike_min_turn < 180.0:
                coords, times, alts_track = _drop_sharp_local_reversals(
                    coords,
                    times,
                    alts_track,
                    min_turn_deg=spike_min_turn,
                    max_leg_miles=spike_max_leg_mi,
                )

            coords, alts_track, times = _filter_impossible_speed(
                coords, alts_track, times, max_mph=max_implied_mph
            )

            if len(coords) >= 3 and dp_epsilon_mi > 0:
                keep_idx = _douglas_peucker_indices(coords, dp_epsilon_mi)
                coords = [coords[i] for i in keep_idx]
                alts_track = [alts_track[i] for i in keep_idx]
                times = [times[i] for i in keep_idx]

            ec = float(dp_epsilon_mi)
            widen_guard = 0
            while len(coords) > max_points and len(coords) >= 3 and ec > 0 and widen_guard < 14:
                widen_guard += 1
                ec = min(3.0, ec * 1.22)
                keep_idx = _douglas_peucker_indices(coords, ec)
                if len(keep_idx) >= len(coords):
                    break
                coords = [coords[i] for i in keep_idx]
                alts_track = [alts_track[i] for i in keep_idx]
                times = [times[i] for i in keep_idx]

            if len(coords) > max_points:
                idxs = _decimate_indices(len(coords), max_points)
                coords = [coords[i] for i in idxs]
                times = [times[i] for i in idxs]
                alts_track = [alts_track[i] for i in idxs]

            if len(coords) < min_points and len(coords_full) >= min_points:
                coords = list(coords_full)
                times = list(times_full)
                alts_track = list(alts_m)
                if len(coords) > max_points:
                    idxs = _decimate_indices(len(coords), max_points)
                    coords = [coords[i] for i in idxs]
                    times = [times[i] for i in idxs]
                    alts_track = [alts_track[i] for i in idxs]

            coords = _smooth_coords_3tap(coords, smooth_passes)

            if len(coords) < min_points:
                continue

            dists = [_haversine_miles(coord.lat, coord.lng, c.lat, c.lng) for c in coords]
            min_d = min(dists) if dists else 999.0
            if min_d > min(bbox_radius * 0.85, 18.0):
                continue

            cand: tuple[float, str, list[Coordinate], list[float | None], int] = (
                min_d,
                icao,
                coords,
                alts_track,
                raw_count_seg,
            )
            if best_for_icao is None:
                best_for_icao = cand
            elif cand[0] < best_for_icao[0] or (
                cand[0] == best_for_icao[0] and raw_count_seg > best_for_icao[4]
            ):
                best_for_icao = cand

        if best_for_icao is not None:
            candidates.append(best_for_icao)

    candidates.sort(key=lambda x: (round(x[0], 3), -x[4], x[1]))
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
        snap_note = " (single snapshot — direction approximate)" if raw_count == 1 else ""
        label = f"Recent ADS-B track ({icao.upper()}{alt_txt}, closest {min_d:.1f} mi){snap_note}"
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
        radius_miles = max(10.0, min(80.0, float(os.getenv("OPENSKY_STATE_BBOX_MILES", str(radius_miles)))))
    except ValueError:
        radius_miles = 25.0
    try:
        near_miles = max(5.0, min(40.0, float(os.getenv("OPENSKY_NEAR_MILES", str(near_miles)))))
    except ValueError:
        near_miles = 10.0
    try:
        max_tracks = max(1, min(5, int(os.getenv("OPENSKY_MAX_TRACK_FETCHES", str(max_tracks)))))
    except ValueError:
        max_tracks = 3

    lat_min, lat_max, lng_min, lng_max = _bbox_from_center(coord, radius_miles)
    auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD) if OPENSKY_USERNAME else None

    timeout = httpx.Timeout(12.0, connect=6.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
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

        samples: list[tuple[Coordinate, int | None, float | None]] = []
        for p in path:
            # OpenSky path entries are typically [time, lat, lon, baro_alt, true_track, on_ground]
            if not isinstance(p, list) or len(p) < 3:
                continue
            observed_ts = int(p[0]) if isinstance(p[0], (int, float)) else None
            lat = p[1]
            lon = p[2]
            if lat is None or lon is None:
                continue
            try:
                sample_coord = Coordinate(lat=float(lat), lng=float(lon))
            except Exception:
                continue
            # baro_alt in meters is often at index 3 when present
            alt_m = float(p[3]) if len(p) > 3 and isinstance(p[3], (int, float)) else None
            samples.append((sample_coord, observed_ts, alt_m))

        if len(samples) < 2:
            continue

        # Keep a longer continuous segment near the property.
        # OpenSky "tracks" can include points far away; we keep the contiguous pass
        # around the closest approach where the aircraft stays within `keep_miles`.
        try:
            keep_miles = max(8.0, min(50.0, float(os.getenv("OPENSKY_TRACK_KEEP_MILES", "15"))))
        except ValueError:
            keep_miles = 15.0
        try:
            pad = max(0, min(60, int(os.getenv("OPENSKY_TRACK_PAD_POINTS", "6"))))
        except ValueError:
            pad = 6
        try:
            max_leg_miles = max(2.0, min(25.0, float(os.getenv("OPENSKY_TRACK_MAX_LEG_MILES", "8"))))
        except ValueError:
            max_leg_miles = 8.0
        try:
            min_track_points = max(5, min(30, int(os.getenv("OPENSKY_TRACK_MIN_POINTS", "5"))))
        except ValueError:
            min_track_points = 5

        continuous_segments: list[list[tuple[Coordinate, int | None, float | None]]] = []
        cur_segment = [samples[0]]
        for sample in samples[1:]:
            prev_coord = cur_segment[-1][0]
            this_coord = sample[0]
            leg_miles = _haversine_miles(prev_coord.lat, prev_coord.lng, this_coord.lat, this_coord.lng)
            if leg_miles > max_leg_miles:
                if len(cur_segment) >= 2:
                    continuous_segments.append(cur_segment)
                cur_segment = [sample]
            else:
                cur_segment.append(sample)
        if len(cur_segment) >= 2:
            continuous_segments.append(cur_segment)

        best_slice: tuple[float, list[tuple[Coordinate, int | None, float | None]]] | None = None
        for segment in continuous_segments:
            segment_coords = [s[0] for s in segment]
            dists = [_haversine_miles(coord.lat, coord.lng, c.lat, c.lng) for c in segment_coords]
            min_idx = min(range(len(dists)), key=dists.__getitem__)
            within = [d <= keep_miles for d in dists]
            seg = _best_within_segment_indices(within, min_idx, pad) if any(within) else None
            if seg:
                start_i, end_i = seg
            else:
                window = 20
                start_i = max(0, min_idx - window)
                end_i = min(len(segment), min_idx + window + 1)
            segment_slice = segment[start_i:end_i]
            if len(segment_slice) < 2:
                continue
            min_dist_slice = min(dists[start_i:end_i])
            if best_slice is None or (min_dist_slice, -len(segment_slice)) < (best_slice[0], -len(best_slice[1])):
                best_slice = (min_dist_slice, segment_slice)

        if best_slice is None:
            continue

        min_dist_near, samples_near = best_slice
        coords_near = [s[0] for s in samples_near]
        if len(coords_near) < min_track_points:
            continue

        # Median altitude from available samples (best-effort).
        median_alt_ft = None
        alts_m = [s[2] for s in samples_near if s[2] is not None]
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
        start_full = samples[0][0]
        end_full = samples[-1][0]
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
        last_seen_ts = next((s[1] for s in reversed(samples_near) if s[1] is not None), None)

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
    - ``static``: simplified hand-authored corridor segments only — same “demo” dashed
      straight segments (no per-aircraft tracks).
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
