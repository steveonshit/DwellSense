"""
Queries pre-stored NYC municipal data from Supabase.
Tables are populated daily by jobs/daily_refresh.py.

If Supabase returns 0 results (e.g. daily refresh hasn't run yet),
the functions fall back to fetching live from NYC Open Data (Socrata).
"""

import os
import asyncio
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
# 2mi radius is 4x the 1mi area; caps are raised to reduce premature truncation.
CRIME_FETCH_LIMIT = 1200
REPORTS_FETCH_LIMIT = 1800
PERMITS_FETCH_LIMIT = 1200
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
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Socrata live fetch failed for {endpoint}: {e}")
        return []


async def _socrata_fetch_async(endpoint: str, where: str, order: str = "", limit: int = 200) -> list[dict]:
    """Async wrapper — runs the blocking Socrata fetch in a thread pool."""
    return await asyncio.to_thread(_socrata_fetch, endpoint, where, order, limit)


# ─── Crime ────────────────────────────────────────────────────────────────────

async def get_nearby_crime(coord: Coordinate) -> list[dict]:
    """NYPD complaint records near the address."""
    global _supabase_reachable
    try:
        client = _get_client()
        bb = _bbox(coord)
        since = _since_iso(CRIME_DAYS_BACK)
        result = (
            client.table("crime_reports")
            .select("lat, lng, crime_type, description, occurred_at")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .gte("occurred_at", since)
            .limit(CRIME_FETCH_LIMIT)
            .execute()
        )
        _supabase_reachable = True
        rows = result.data or []
        if rows:
            logger.info(f"Crime: {len(rows)} rows from Supabase.")
            return rows
    except Exception as e:
        if "nodename nor servname" in str(e) or "DNS" in str(e).upper():
            _supabase_reachable = False
        logger.warning(f"Supabase crime query failed: {e}")

    # Live fallback — filter only by location, sorted by most recent
    logger.info("Crime: Supabase empty — fetching live from NYC Open Data.")
    bb = _bbox(coord)
    since = _since_socrata(CRIME_DAYS_BACK)
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}' "
        f"AND cmplnt_fr_dt >= '{since}'"
    )
    raw = await _socrata_fetch_async("5uac-w243.json", where, limit=CRIME_FETCH_LIMIT)
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
        bb = _bbox(coord)
        since = _since_iso(REPORTS_311_DAYS_BACK)
        result = (
            client.table("reports_311")
            .select("lat, lng, complaint_type, descriptor, created_at")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .gte("created_at", since)
            .limit(REPORTS_FETCH_LIMIT)
            .execute()
        )
        rows = result.data or []
        if rows:
            filtered = _filter_311_rows(rows)
            logger.info(f"311: {len(rows)} rows from Supabase ({len(filtered)} after parking/vehicle filter).")
            return filtered
    except Exception as e:
        logger.warning(f"Supabase 311 query failed: {e}")

    # Live fallback
    logger.info("311: Supabase empty — fetching live from NYC Open Data.")
    bb = _bbox(coord)
    since = _since_socrata(REPORTS_311_DAYS_BACK)
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}' "
        f"AND created_date >= '{since}'"
    )
    raw = await _socrata_fetch_async("erm2-nwe9.json", where, limit=REPORTS_FETCH_LIMIT)
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
        bb = _bbox(coord)
        since = _since_iso(PERMIT_DAYS_BACK)
        result = (
            client.table("building_permits")
            .select("lat, lng, permit_type, permit_status, job_description, filing_date")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .gte("filing_date", since)
            .limit(PERMITS_FETCH_LIMIT)
            .execute()
        )
        rows = result.data or []
        if rows:
            logger.info(f"Permits: {len(rows)} rows from Supabase.")
            return rows
    except Exception as e:
        logger.warning(f"Supabase permits query failed: {e}")

    # Live fallback — DOB permit issuances, filter by location
    logger.info("Permits: Supabase empty — fetching live from NYC Open Data.")
    bb = _bbox(coord)
    since = _since_socrata(PERMIT_DAYS_BACK)
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}' "
        f"AND filing_date >= '{since}'"
    )
    raw = await _socrata_fetch_async("ipu4-2q9a.json", where, limit=PERMITS_FETCH_LIMIT)
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
        bb = _bbox(coord)
        since = _since_iso(EVICTION_DAYS_BACK)
        result = (
            client.table("eviction_records")
            .select("lat, lng, case_type, filing_date")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .gte("filing_date", since)
            .limit(EVICTIONS_FETCH_LIMIT)
            .execute()
        )
        rows = result.data or []
        if rows:
            logger.info(f"Evictions: {len(rows)} rows from Supabase.")
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


def build_swarm(crime: list[dict], reports_311: list[dict], permits: list[dict]) -> list[SwarmPin]:
    """Builds a diverse micro-pin swarm for the map (max 100 pins total)."""
    swarm: list[SwarmPin] = []

    # Crime pins — up to 30
    for row in crime[:30]:
        if row.get("lat") and row.get("lng"):
            swarm.append(SwarmPin(
                lat=row["lat"], lng=row["lng"],
                type="police",
                label=f"NYPD: {row.get('crime_type', 'Police Activity')}",
            ))

    # 311 pins — categorized, up to 50 total, max 15 per type
    type_counts: dict[str, int] = {}
    for row in reports_311:
        if not row.get("lat") or not row.get("lng"):
            continue
        pin_type, label = _classify_311(row)
        if type_counts.get(pin_type, 0) >= 15:
            continue
        type_counts[pin_type] = type_counts.get(pin_type, 0) + 1
        swarm.append(SwarmPin(lat=row["lat"], lng=row["lng"], type=pin_type, label=label))
        if sum(type_counts.values()) >= 50:
            break

    # Permit pins — up to 20
    for row in permits[:20]:
        if row.get("lat") and row.get("lng"):
            swarm.append(SwarmPin(
                lat=row["lat"], lng=row["lng"],
                type="permit",
                label=f"Permit: {row.get('permit_type', 'Construction')}",
            ))

    return swarm
