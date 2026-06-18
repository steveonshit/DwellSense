"""
Queries pre-stored NYC municipal data from Supabase.
Tables are populated daily by jobs/daily_refresh.py.

If Supabase returns 0 results (e.g. daily refresh hasn't run yet),
the functions fall back to fetching live from NYC Open Data (Socrata).
"""

import os
import asyncio
import hashlib
import logging
import requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from models.schemas import Coordinate, Zone, SwarmPin
import math

logger = logging.getLogger(__name__)


def get_scan_radius_miles() -> float:
    """Haversine search radius for crime / 311 / permits / evictions (address at center)."""
    try:
        return max(0.25, min(10.0, float(os.getenv("SCAN_RADIUS_MILES", "2"))))
    except ValueError:
        return 2.0


def get_scan_radius_meters() -> float:
    return get_scan_radius_miles() * 1609.344


# Legacy aliases — prefer get_scan_radius_miles() at runtime.
RADIUS_MILES = get_scan_radius_miles()
RADIUS_METERS = get_scan_radius_meters()

# Intended recency windows (must match how we describe scoring/UI)
CRIME_DAYS_BACK = 30
REPORTS_311_DAYS_BACK = 30
PERMIT_DAYS_BACK = 90
EVICTION_DAYS_BACK = 180

# Socrata/Supabase fetch caps (used to detect truncated samples).
# 2mi disk in dense NYC can exceed a single bbox page — use grid fetches below.
CRIME_FETCH_LIMIT = 3000
REPORTS_FETCH_LIMIT = 6000
PERMITS_FETCH_LIMIT = 2000
EVICTIONS_FETCH_LIMIT = 600

# NYC Open Data (Socrata) base URL
SOCRATA_BASE = "https://data.cityofnewyork.us/resource"


_supabase_reachable: bool | None = None  # None = untested, True/False = known


def _is_parking_vehicle_noise_complaint(row: dict) -> bool:
    """
    NYC 311 includes a huge volume of parking / vehicle / traffic complaints.
    These are not renter safety signals for lease decisions, so we exclude them
    from scoring, map pins, and AI briefs.
    """
    ctype = (row.get("complaint_type") or "").lower()
    desc = (row.get("descriptor") or "").lower()
    blob = f"{ctype} {desc}"

    # Strong signal: complaint type names are usually explicit in NYC 311.
    if any(
        k in ctype
        for k in (
            "parking",
            "vehicle",
            "traffic",
            "highway",
            "gridlock",
            "taxi",
            "tlc",
            "for-hire",
            "for hire",
            "commuter van",
            "tow",
            "license plate",
            "abandoned vehicle",
            "blocked driveway",
            "hydrant",
        )
    ):
        return True

    # Descriptor-only cases (still clearly parking/vehicle enforcement noise).
    desc_keys = (
        "illegal parking",
        "no parking",
        "double parked",
        "double-parked",
        "hydrant",
        "blocked hydrant",
        "blocked driveway",
        "commercial vehicle",
        "gridlock",
        "traffic",
        "tlc",
        "taxi",
        "tow",
        "abandoned vehicle",
    )
    if any(k in desc for k in desc_keys):
        return True

    # Avoid overly-broad substring matches on generic words like "car"/"truck".
    if "parking" in blob or "parked" in blob:
        return True

    return False


def _filter_311_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not _is_parking_vehicle_noise_complaint(r)]


def _get_client() -> Client:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase credentials are not set in environment variables.")
    global _supabase_reachable
    if _supabase_reachable is False:
        raise RuntimeError("Supabase DNS unavailable (cached failure).")
    return create_client(url, key)


def _bbox(coord: Coordinate) -> dict:
    radius = get_scan_radius_miles()
    lat_delta = radius / 69.0
    lng_delta = radius / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
    return {
        "lat_min": coord.lat - lat_delta,
        "lat_max": coord.lat + lat_delta,
        "lng_min": coord.lng - lng_delta,
        "lng_max": coord.lng + lng_delta,
    }


def _grid_bboxes(coord: Coordinate, radius_miles: float, *, n: int = 4) -> list[dict]:
    """Split the scan bbox into an N×N grid so fetches cover the whole disk, not one corner."""
    lat_delta = radius_miles / 69.0
    lng_delta = radius_miles / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
    lat_min = coord.lat - lat_delta
    lat_max = coord.lat + lat_delta
    lng_min = coord.lng - lng_delta
    lng_max = coord.lng + lng_delta
    lat_step = (lat_max - lat_min) / n
    lng_step = (lng_max - lng_min) / n
    boxes: list[dict] = []
    for i in range(n):
        for j in range(n):
            boxes.append({
                "lat_min": lat_min + i * lat_step,
                "lat_max": lat_min + (i + 1) * lat_step,
                "lng_min": lng_min + j * lng_step,
                "lng_max": lng_min + (j + 1) * lng_step,
            })
    return boxes


def _row_dedupe_key(row: dict) -> tuple[str, float, float, str]:
    return (
        str(row.get("source_id") or ""),
        round(float(row.get("lat", 0)), 5),
        round(float(row.get("lng", 0)), 5),
        str(
            row.get("created_at")
            or row.get("occurred_at")
            or row.get("filing_date")
            or ""
        ),
    )


def _merge_rows(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str, float, float, str]] = set()
    out: list[dict] = []
    for row in rows:
        try:
            key = _row_dedupe_key(row)
        except (TypeError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _supabase_grid_fetch(
    client: Client,
    table: str,
    select: str,
    coord: Coordinate,
    *,
    date_col: str,
    since: str,
    max_total: int,
    grid_n: int = 4,
) -> list[dict]:
    """
    Fetch municipal rows from Supabase across a grid inside the scan bbox.
    A single .limit() on the full bbox can return thousands of rows from one corridor
    and miss the rest of the 2-mile disk.
    """
    cells = _grid_bboxes(coord, get_scan_radius_miles(), n=grid_n)
    per_cell = max(150, (max_total + len(cells) - 1) // len(cells))
    merged: list[dict] = []
    for bb in cells:
        result = (
            client.table(table)
            .select(select)
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .gte(date_col, since)
            .limit(per_cell)
            .execute()
        )
        merged.extend(result.data or [])
    return _merge_rows(merged)[:max_total]


def _socrata_within_circle_where(
    coord: Coordinate,
    radius_miles: float,
    location_col: str,
    date_col: str,
    since: str,
) -> str:
    meters = radius_miles * 1609.344
    return (
        f"within_circle({location_col}, {coord.lat}, {coord.lng}, {meters}) "
        f"AND {date_col} >= '{since}'"
    )


def _since_iso(days_back: int) -> str:
    """UTC ISO timestamp used for Supabase timestamptz comparisons."""
    return (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()


def _since_socrata(days_back: int) -> str:
    """Socrata expects an ISO-ish string without timezone suffix."""
    return (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def filter_rows_within_radius(
    coord: Coordinate,
    rows: list[dict],
    *,
    radius_meters: float | None = None,
) -> list[dict]:
    """Keep rows with valid lat/lng within radius_meters of coord."""
    limit_m = radius_meters if radius_meters is not None else get_scan_radius_meters()
    out: list[dict] = []
    for row in rows:
        try:
            lat = float(row.get("lat"))
            lng = float(row.get("lng"))
        except (TypeError, ValueError):
            continue
        if not lat or not lng:
            continue
        if _haversine_meters(coord.lat, coord.lng, lat, lng) <= limit_m:
            out.append(row)
    return out


def _socrata_fetch(endpoint: str, where: str, order: str = "", limit: int = 200) -> list[dict]:
    """Fetch from NYC Open Data Socrata API (blocking — wrap in asyncio.to_thread for async use)."""
    params: dict = {"$where": where, "$limit": limit}
    if order:
        params["$order"] = order
    try:
        resp = requests.get(
            f"{SOCRATA_BASE}/{endpoint}",
            params=params,
            headers={"Accept": "application/json"},
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Socrata live fetch failed for {endpoint}: {e}")
        return []


def _socrata_fetch_paginated(
    endpoint: str,
    where: str,
    *,
    max_rows: int,
    page_size: int = 2000,
) -> list[dict]:
    """Page through Socrata until max_rows or no more data."""
    out: list[dict] = []
    offset = 0
    while len(out) < max_rows:
        chunk = min(page_size, max_rows - len(out))
        params = {"$where": where, "$limit": chunk, "$offset": offset}
        try:
            resp = requests.get(
                f"{SOCRATA_BASE}/{endpoint}",
                params=params,
                headers={"Accept": "application/json"},
                timeout=45,
            )
            resp.raise_for_status()
            batch = resp.json()
        except Exception as e:
            logger.warning(f"Socrata paginated fetch failed for {endpoint}: {e}")
            break
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < chunk:
            break
        offset += chunk
    return out


async def _socrata_fetch_async(endpoint: str, where: str, order: str = "", limit: int = 200) -> list[dict]:
    """Async wrapper — runs the blocking Socrata fetch in a thread pool."""
    return await asyncio.to_thread(_socrata_fetch, endpoint, where, order, limit)


async def _socrata_fetch_paginated_async(
    endpoint: str,
    where: str,
    *,
    max_rows: int,
    page_size: int = 2000,
) -> list[dict]:
    return await asyncio.to_thread(
        _socrata_fetch_paginated,
        endpoint,
        where,
        max_rows=max_rows,
        page_size=page_size,
    )


# ─── Crime ────────────────────────────────────────────────────────────────────

async def get_nearby_crime(coord: Coordinate) -> list[dict]:
    """NYPD complaint records near the address."""
    global _supabase_reachable
    try:
        client = _get_client()
        since = _since_iso(CRIME_DAYS_BACK)
        rows = _supabase_grid_fetch(
            client,
            "crime_reports",
            "lat, lng, crime_type, description, occurred_at, source_id",
            coord,
            date_col="occurred_at",
            since=since,
            max_total=CRIME_FETCH_LIMIT,
        )
        _supabase_reachable = True
        if rows:
            logger.info(f"Crime: {len(rows)} rows from Supabase (grid fetch).")
            return rows
    except Exception as e:
        if "nodename nor servname" in str(e) or "DNS" in str(e).upper():
            _supabase_reachable = False
        logger.warning(f"Supabase crime query failed: {e}")

    # Live fallback — true circle query on NYC Open Data (not bbox-only).
    logger.info("Crime: Supabase empty — fetching live from NYC Open Data.")
    since = _since_socrata(CRIME_DAYS_BACK)
    where = _socrata_within_circle_where(
        coord, get_scan_radius_miles(), "lat_lon", "cmplnt_fr_dt", since
    )
    raw = await _socrata_fetch_paginated_async("5uac-w243.json", where, max_rows=CRIME_FETCH_LIMIT)
    result = []
    for r in raw:
        try:
            lat = float(r.get("latitude") or r.get("lat_lon", {}).get("latitude", 0))
            lng = float(r.get("longitude") or r.get("lat_lon", {}).get("longitude", 0))
            if not lat or not lng:
                continue
            result.append({
                "lat": lat,
                "lng": lng,
                "crime_type": r.get("ofns_desc", r.get("ky_cd", "UNKNOWN")),
                "description": r.get("pd_desc", ""),
                "occurred_at": r.get("cmplnt_fr_dt", ""),
            })
        except (KeyError, ValueError, TypeError):
            continue
    logger.info(f"Crime: {len(result)} rows from live fetch.")
    return result


# ─── 311 Reports ──────────────────────────────────────────────────────────────

async def get_nearby_311(coord: Coordinate) -> list[dict]:
    """311 service requests near the address."""
    try:
        client = _get_client()
        since = _since_iso(REPORTS_311_DAYS_BACK)
        rows = _supabase_grid_fetch(
            client,
            "reports_311",
            "lat, lng, complaint_type, descriptor, created_at, source_id",
            coord,
            date_col="created_at",
            since=since,
            max_total=REPORTS_FETCH_LIMIT,
        )
        if rows:
            filtered = _filter_311_rows(rows)
            logger.info(f"311: {len(rows)} rows from Supabase grid ({len(filtered)} after parking/vehicle filter).")
            return filtered
    except Exception as e:
        logger.warning(f"Supabase 311 query failed: {e}")

    # Live fallback — true circle on NYC Open Data.
    logger.info("311: Supabase empty — fetching live from NYC Open Data.")
    since = _since_socrata(REPORTS_311_DAYS_BACK)
    where = _socrata_within_circle_where(
        coord, get_scan_radius_miles(), "location", "created_date", since
    )
    raw = await _socrata_fetch_paginated_async("erm2-nwe9.json", where, max_rows=REPORTS_FETCH_LIMIT)
    result = []
    for r in raw:
        try:
            result.append({
                "lat": float(r["latitude"]),
                "lng": float(r["longitude"]),
                "complaint_type": r.get("complaint_type", "UNKNOWN"),
                "descriptor": r.get("descriptor", ""),
                "created_at": r.get("created_date", ""),
            })
        except (KeyError, ValueError):
            continue
    filtered = _filter_311_rows(result)
    logger.info(f"311: {len(result)} rows from live fetch ({len(filtered)} after parking/vehicle filter).")
    return filtered


# ─── Building Permits ─────────────────────────────────────────────────────────

async def get_nearby_permits(coord: Coordinate) -> list[dict]:
    """DOB building permits near the address (last 90 days)."""
    try:
        client = _get_client()
        since = _since_iso(PERMIT_DAYS_BACK)
        rows = _supabase_grid_fetch(
            client,
            "building_permits",
            "lat, lng, permit_type, permit_status, job_description, filing_date, source_id",
            coord,
            date_col="filing_date",
            since=since,
            max_total=PERMITS_FETCH_LIMIT,
        )
        if rows:
            logger.info(f"Permits: {len(rows)} rows from Supabase (grid fetch).")
            return rows
    except Exception as e:
        logger.warning(f"Supabase permits query failed: {e}")

    # Live fallback — bbox grid via paginated Socrata (permits lack a stable circle column).
    logger.info("Permits: Supabase empty — fetching live from NYC Open Data.")
    bb = _bbox(coord)
    since = _since_socrata(PERMIT_DAYS_BACK)
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}' "
        f"AND filing_date >= '{since}'"
    )
    raw = await _socrata_fetch_paginated_async("ipu4-2q9a.json", where, max_rows=PERMITS_FETCH_LIMIT)
    result = []
    for r in raw:
        try:
            lat = float(r.get("latitude") or 0)
            lng = float(r.get("longitude") or 0)
            if not lat or not lng:
                continue
            result.append({
                "lat": lat,
                "lng": lng,
                "permit_type": r.get("permit_type", r.get("permit_type_description", "UNKNOWN")),
                "permit_status": r.get("permit_status", "ISSUED"),
                "job_description": r.get("job_description", r.get("work_type", "")),
                "filing_date": r.get("filing_date", r.get("issuance_date", "")),
            })
        except (KeyError, ValueError, TypeError):
            continue
    logger.info(f"Permits: {len(result)} rows from live fetch.")
    return result


# ─── Evictions ────────────────────────────────────────────────────────────────

async def get_nearby_evictions(coord: Coordinate) -> list[dict]:
    """Housing court eviction records near the address."""
    try:
        client = _get_client()
        since = _since_iso(EVICTION_DAYS_BACK)
        rows = _supabase_grid_fetch(
            client,
            "eviction_records",
            "lat, lng, case_type, filing_date, source_id",
            coord,
            date_col="filing_date",
            since=since,
            max_total=EVICTIONS_FETCH_LIMIT,
        )
        if rows:
            logger.info(f"Evictions: {len(rows)} rows from Supabase (grid fetch).")
            return rows
    except Exception as e:
        logger.warning(f"Supabase evictions query failed: {e}")

    # Live fallback — NYC marshal evictions
    logger.info("Evictions: Supabase empty — fetching live from NYC Open Data.")
    bb = _bbox(coord)
    since = _since_socrata(EVICTION_DAYS_BACK)
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}' "
        f"AND executed_date >= '{since}'"
    )
    raw = await _socrata_fetch_async("6z8x-wfk4.json", where, limit=100)
    result = []
    for r in raw:
        try:
            result.append({
                "lat": float(r["latitude"]),
                "lng": float(r["longitude"]),
                "case_type": r.get("eviction_possession", "Residential"),
                "filing_date": r.get("executed_date", ""),
            })
        except (KeyError, ValueError):
            continue
    logger.info(f"Evictions: {len(result)} rows from live fetch.")
    return result


# ─── Map Builders ─────────────────────────────────────────────────────────────

def build_zones(crime: list[dict], reports_311: list[dict], permits: list[dict]) -> list[Zone]:
    """Converts raw data rows into map zone circles."""
    zones: list[Zone] = []

    for row in crime[:6]:
        if row.get("lat") and row.get("lng"):
            zones.append(Zone(
                lat=row["lat"], lng=row["lng"],
                radius_meters=250, color="#ef4444",
                label=row.get("crime_type", "Crime Report"),
            ))

    for row in reports_311[:4]:
        if row.get("lat") and row.get("lng"):
            ctype = row.get("complaint_type", "").lower()
            color = "#a855f7" if "rodent" in ctype else "#3b82f6"
            zones.append(Zone(
                lat=row["lat"], lng=row["lng"],
                radius_meters=200, color=color,
                label=_format_311_label(row),
            ))

    for row in permits[:3]:
        if row.get("lat") and row.get("lng"):
            zones.append(Zone(
                lat=row["lat"], lng=row["lng"],
                radius_meters=180, color="#f97316",
                label=f"Permit: {row.get('permit_type', 'Construction')}",
            ))

    return zones


def _clean_311_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _format_water_311_label(complaint_type: str, descriptor: str) -> str:
    c = complaint_type.lower()
    d = descriptor.lower()
    blob = f"{c} {d}"

    if "sewer" in blob:
        if any(k in blob for k in ["odor", "smell", "stench"]):
            issue = "Sewer Odor"
        elif any(k in blob for k in ["backup", "back up", "back-up", "overflow"]):
            issue = "Sewer Backup"
        elif any(k in blob for k in ["clog", "block", "catch basin", "drain"]):
            issue = "Drain Blockage"
        else:
            issue = "Sewer Issue"
    elif any(k in blob for k in ["contamin", "dirty", "brown", "discolor", "quality"]):
        issue = "Water Quality Issue"
    elif any(k in blob for k in ["leak", "flood"]):
        issue = "Water Leak"
    elif any(k in blob for k in ["no water", "pressure", "hydrant"]):
        issue = "Water Pressure"
    else:
        issue = "Water Issue"

    return issue


def _format_311_label(row: dict) -> str:
    complaint_type = _clean_311_text(row.get("complaint_type")) or "311 Report"
    descriptor = _clean_311_text(row.get("descriptor"))
    c = complaint_type.lower()

    if any(k in c for k in ["water", "leak", "flood", "sewer", "drain"]):
        return _format_water_311_label(complaint_type, descriptor)

    return f"311: {complaint_type}"


def _classify_311(row: dict) -> tuple[str, str]:
    """Returns (pin_type, label) for a 311 complaint type."""
    complaint_type = _clean_311_text(row.get("complaint_type"))
    c = complaint_type.lower()
    if any(k in c for k in ["rodent", "rat", "mice", "pest"]):
        return "rat", f"311: {complaint_type}"
    if any(k in c for k in ["noise", "loud", "music", "party"]):
        return "noise", f"311: {complaint_type}"
    if any(k in c for k in ["heat", "hot water", "heating", "boiler"]):
        return "fire", f"311: {complaint_type}"
    if any(k in c for k in ["water", "leak", "flood", "sewer", "drain"]):
        return "water", _format_311_label(row)
    if any(k in c for k in ["garbage", "sanitation", "litter", "trash", "waste", "dirty"]):
        return "trash", f"311: {complaint_type}"
    if any(k in c for k in ["graffiti", "paint", "vandal"]):
        return "graffiti", f"311: {complaint_type}"
    if any(k in c for k in ["construction", "building", "scaffold", "demolition", "crane"]):
        return "construction", f"311: {complaint_type}"
    if any(k in c for k in ["drug", "illegal", "weapon", "assault"]):
        return "police", f"311: {complaint_type}"
    if any(k in c for k in ["parking", "vehicle", "traffic", "truck"]):
        return "truck", f"311: {complaint_type}"
    return "report", f"311: {complaint_type}"


# Lower = higher priority when multiple record types share one geocode.
_PIN_TYPE_RANK: dict[str, int] = {
    "police": 0,
    "fire": 1,
    "construction": 2,
    "permit": 3,
    "water": 4,
    "rat": 5,
    "noise": 6,
    "trash": 7,
    "graffiti": 8,
    "truck": 9,
    "bus": 10,
    "report": 11,
}


def get_map_swarm_max_pins() -> int:
    """Max map pins to render (all are real; scoring still uses full in-radius counts)."""
    try:
        return max(20, min(200, int(os.getenv("MAP_SWARM_MAX_PINS", "100"))))
    except ValueError:
        return 100


def _swarm_pin_shuffle_key(pin: SwarmPin, center: Coordinate) -> str:
    """Stable per-property ordering (rescans show the same subset)."""
    payload = (
        f"{center.lat:.5f}|{center.lng:.5f}|"
        f"{pin.lat:.5f}|{pin.lng:.5f}|{pin.type}|{pin.label[:48]}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sample_swarm_pins(
    pins: list[SwarmPin],
    center: Coordinate,
    limit: int,
) -> list[SwarmPin]:
    """
    Pick a subset of real pins for map readability.

    Uses a deterministic shuffle (not a spatial grid) so displayed pins keep
    natural NYC clustering — coordinates are never modified.
    """
    if len(pins) <= limit:
        return pins
    shuffled = sorted(pins, key=lambda p: _swarm_pin_shuffle_key(p, center))
    return shuffled[:limit]


def build_swarm(
    crime: list[dict],
    reports_311: list[dict],
    permits: list[dict],
    center: Coordinate,
) -> tuple[list[SwarmPin], int]:
    """
    Build map pins from real municipal rows (already Haversine-filtered).
    Returns (pins to render, total unique locations in radius).
    """
    grouped: dict[tuple[float, float], list[tuple[str, str, float, float]]] = {}

    def _add(lat: float, lng: float, pin_type: str, label: str) -> None:
        key = (round(lat, 5), round(lng, 5))
        grouped.setdefault(key, []).append((pin_type, label, lat, lng))

    for row in crime:
        if not row.get("lat") or not row.get("lng"):
            continue
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
        except (TypeError, ValueError):
            continue
        _add(lat, lng, "police", f"NYPD: {row.get('crime_type', 'Police Activity')}")

    for row in reports_311:
        if not row.get("lat") or not row.get("lng"):
            continue
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
        except (TypeError, ValueError):
            continue
        pin_type, label = _classify_311(row)
        _add(lat, lng, pin_type, label)

    for row in permits:
        if not row.get("lat") or not row.get("lng"):
            continue
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
        except (TypeError, ValueError):
            continue
        _add(lat, lng, "permit", f"Permit: {row.get('permit_type', 'Construction')}")

    swarm: list[SwarmPin] = []
    for entries in grouped.values():
        pin_type, label, lat, lng = min(
            entries,
            key=lambda e: (_PIN_TYPE_RANK.get(e[0], 99), e[1]),
        )
        count = len(entries)
        if count > 1:
            label = f"{label} ({count} records at this location)"
        swarm.append(SwarmPin(lat=lat, lng=lng, type=pin_type, label=label))

    total = len(swarm)
    max_pins = get_map_swarm_max_pins()
    if total > max_pins:
        swarm = _sample_swarm_pins(swarm, center, max_pins)
    return swarm, total
