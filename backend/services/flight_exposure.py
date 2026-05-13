from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from models.schemas import Coordinate, FlightExposure
from services.city_data import _get_client

logger = logging.getLogger(__name__)


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 3958.7613
    p = math.pi / 180
    dlat = (lat2 - lat1) * p
    dlng = (lng2 - lng1) * p
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def compute_exposure(
    coord: Coordinate,
    *,
    days: int = 7,
    radius_miles: float = 1.0,
    max_alt_ft: int = 10000,
) -> FlightExposure | None:
    """
    Prototype exposure score from stored ADS-B samples in Supabase.
    This is intentionally simple: good enough for UX iteration.
    """
    try:
        supabase = _get_client()
    except Exception:
        # Never break /scan if Supabase is unreachable; exposure is optional.
        return FlightExposure(
            night_overflights_per_hour=0.0,
            day_overflights_per_hour=0.0,
            typical_altitude_ft=None,
            trend=None,
            data_quality="unavailable",
        )

    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        since_iso = since.isoformat()

        # Bounding box prefilter (fast)
        dlat = radius_miles / 69.0
        dlng = radius_miles / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
        lat_min, lat_max = coord.lat - dlat, coord.lat + dlat
        lng_min, lng_max = coord.lng - dlng, coord.lng + dlng

        res = (
            supabase.table("adsb_samples")
            .select("observed_at,icao24,lat,lng,baro_alt_m,geo_alt_m,on_ground")
            .gte("observed_at", since_iso)
            .gte("lat", lat_min)
            .lte("lat", lat_max)
            .gte("lng", lng_min)
            .lte("lng", lng_max)
            .limit(5000)
            .execute()
        )
        rows = getattr(res, "data", None) or []
        if not rows:
            return FlightExposure(
                night_overflights_per_hour=0.0,
                day_overflights_per_hour=0.0,
                typical_altitude_ft=None,
                trend=None,
                data_quality="unavailable",
            )

        # Filter by true radius + altitude
        filtered: list[dict] = []
        alt_fts: list[int] = []
        for r in rows:
            try:
                lat = float(r["lat"])
                lng = float(r["lng"])
            except Exception:
                continue
            if _haversine_miles(coord.lat, coord.lng, lat, lng) > radius_miles:
                continue
            if r.get("on_ground") is True:
                continue

            alt_m = r.get("geo_alt_m") if isinstance(r.get("geo_alt_m"), (int, float)) else r.get("baro_alt_m")
            alt_ft = None
            if isinstance(alt_m, (int, float)):
                alt_ft = int(round(float(alt_m) * 3.28084))
                if alt_ft > max_alt_ft:
                    continue
                alt_fts.append(alt_ft)

            r["_alt_ft"] = alt_ft
            filtered.append(r)

        if not filtered:
            return FlightExposure(
                night_overflights_per_hour=0.0,
                day_overflights_per_hour=0.0,
                typical_altitude_ft=None,
                trend=None,
                data_quality="sparse",
            )

        # Convert samples into "overflight minutes" (dedupe by aircraft+minute).
        night_keys = set()
        day_keys = set()
        hours_seen = set()
        for r in filtered:
            try:
                t = datetime.fromisoformat(r["observed_at"].replace("Z", "+00:00"))
            except Exception:
                continue
            icao = str(r.get("icao24") or "")
            minute_bucket = t.replace(second=0, microsecond=0)
            key = (icao, minute_bucket)
            local_hour = t.astimezone(timezone.utc).hour  # keep UTC for prototype
            hours_seen.add(t.replace(minute=0, second=0, microsecond=0))
            if 3 <= local_hour <= 9:  # rough "night" proxy until we add NYC tz
                night_keys.add(key)
            else:
                day_keys.add(key)

        # Rate per hour: keys are per-minute events; convert to per-hour using observed span.
        observed_hours = max(1, len(hours_seen))
        night_per_hr = len(night_keys) / observed_hours
        day_per_hr = len(day_keys) / observed_hours

        typical_alt = None
        if alt_fts:
            alt_fts.sort()
            typical_alt = alt_fts[len(alt_fts) // 2]

        # Data quality: very rough heuristic based on sample volume
        quality = "good" if len(filtered) >= 800 else "sparse"

        return FlightExposure(
            night_overflights_per_hour=round(night_per_hr, 2),
            day_overflights_per_hour=round(day_per_hr, 2),
            typical_altitude_ft=typical_alt,
            trend=None,
            data_quality=quality,
        )
    except Exception:
        logger.exception("flight_exposure: query or compute failed (missing table, RLS, or transient DB error)")
        return FlightExposure(
            night_overflights_per_hour=0.0,
            day_overflights_per_hour=0.0,
            typical_altitude_ft=None,
            trend=None,
            data_quality="unavailable",
        )

