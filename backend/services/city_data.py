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

logger = logging.getLogger(__name__)

# Bounding box radius (~0.5 miles)
LAT_DELTA = 0.007
LNG_DELTA = 0.010

# NYC Open Data (Socrata) base URL
SOCRATA_BASE = "https://data.cityofnewyork.us/resource"


_supabase_reachable: bool | None = None  # None = untested, True/False = known

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
    return {
        "lat_min": coord.lat - LAT_DELTA,
        "lat_max": coord.lat + LAT_DELTA,
        "lng_min": coord.lng - LNG_DELTA,
        "lng_max": coord.lng + LNG_DELTA,
    }


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
        result = (
            client.table("crime_reports")
            .select("lat, lng, crime_type, description, occurred_at")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .limit(200)
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
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}'"
    )
    raw = await _socrata_fetch_async("5uac-w243.json", where, limit=200)
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
        result = (
            client.table("reports_311")
            .select("lat, lng, complaint_type, descriptor, created_at")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .limit(300)
            .execute()
        )
        rows = result.data or []
        if rows:
            logger.info(f"311: {len(rows)} rows from Supabase.")
            return rows
    except Exception as e:
        logger.warning(f"Supabase 311 query failed: {e}")

    # Live fallback
    logger.info("311: Supabase empty — fetching live from NYC Open Data.")
    bb = _bbox(coord)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}' "
        f"AND created_date >= '{since}'"
    )
    raw = await _socrata_fetch_async("erm2-nwe9.json", where, limit=300)
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
    logger.info(f"311: {len(result)} rows from live fetch.")
    return result


# ─── Building Permits ─────────────────────────────────────────────────────────

async def get_nearby_permits(coord: Coordinate) -> list[dict]:
    """DOB building permits near the address (last 90 days)."""
    try:
        client = _get_client()
        bb = _bbox(coord)
        result = (
            client.table("building_permits")
            .select("lat, lng, permit_type, permit_status, job_description, filing_date")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .limit(200)
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
    where = (
        f"latitude >= '{bb['lat_min']}' AND latitude <= '{bb['lat_max']}' "
        f"AND longitude >= '{bb['lng_min']}' AND longitude <= '{bb['lng_max']}'"
    )
    raw = await _socrata_fetch_async("ipu4-2q9a.json", where, limit=200)
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
        result = (
            client.table("eviction_records")
            .select("lat, lng, case_type, filing_date")
            .gte("lat", bb["lat_min"])
            .lte("lat", bb["lat_max"])
            .gte("lng", bb["lng_min"])
            .lte("lng", bb["lng_max"])
            .limit(100)
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
    since = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%S")
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
                label=row.get("complaint_type", "311 Report"),
            ))

    for row in permits[:3]:
        if row.get("lat") and row.get("lng"):
            zones.append(Zone(
                lat=row["lat"], lng=row["lng"],
                radius_meters=180, color="#f97316",
                label=f"Permit: {row.get('permit_type', 'Construction')}",
            ))

    return zones


def _classify_311(complaint_type: str) -> tuple[str, str]:
    """Returns (pin_type, label) for a 311 complaint type."""
    c = complaint_type.lower()
    if any(k in c for k in ["rodent", "rat", "mice", "pest"]):
        return "rat", f"311: {complaint_type}"
    if any(k in c for k in ["noise", "loud", "music", "party"]):
        return "noise", f"311: {complaint_type}"
    if any(k in c for k in ["heat", "hot water", "heating", "boiler"]):
        return "fire", f"311: {complaint_type}"
    if any(k in c for k in ["water", "leak", "flood", "sewer", "drain"]):
        return "water", f"311: {complaint_type}"
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
        pin_type, label = _classify_311(row.get("complaint_type", ""))
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
                type="construction",
                label=f"Permit: {row.get('permit_type', 'Construction')}",
            ))

    return swarm
