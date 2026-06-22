from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_NYC_TZ = ZoneInfo("America/New_York")
# Renter-facing "night" window for aircraft noise (local NYC time).
_NIGHT_HOUR_START = 22  # 10 PM
_NIGHT_HOUR_END = 7  # before 7 AM

from models.schemas import Coordinate, FlightExposure
from services.city_data import _get_client, get_scan_radius_miles

logger = logging.getLogger(__name__)

# NYC ~2 mi calibration: typical vs elevated overflight rates (ADS-B samples, ≤10k ft).
_NIGHT_RATE_MEDIAN = 0.35
_NIGHT_RATE_P90 = 1.85
_DAY_RATE_MEDIAN = 1.15
_DAY_RATE_P90 = 5.8
_NIGHT_WEIGHT = 0.58
_DAY_WEIGHT = 0.42
_SHOW_COMBINED_MIN = 0.54
_SHOW_NIGHT_MIN = 0.60
_SHOW_DAY_MIN = 0.68
_HIGH_COMBINED_MIN = 0.72
_HIGH_NIGHT_MIN = 0.78
_MIN_SAMPLES_TO_SHOW = 40


def _percentile_from_rate(
    rate: float,
    *,
    median_rate: float,
    p90_rate: float,
) -> float:
    x = max(0.0, float(rate))
    lx = math.log1p(x)
    l50 = math.log1p(max(0.0, median_rate))
    l90 = math.log1p(max(1e-6, p90_rate))
    denom = max(1e-6, l90 - l50)
    k = 2.2 / denom
    z = (lx - l50) * k
    return 1.0 / (1.0 + math.exp(-z))


def _comparison_label(percentile: float) -> str:
    if percentile >= 0.85:
        return "among the highest we see in NYC"
    if percentile >= 0.70:
        return "higher than most NYC blocks"
    return "above typical NYC levels"


def _elevation_level(combined: float, night_p: float) -> str:
    if combined >= _HIGH_COMBINED_MIN or night_p >= _HIGH_NIGHT_MIN:
        return "high"
    if combined >= _SHOW_COMBINED_MIN or night_p >= _SHOW_NIGHT_MIN:
        return "elevated"
    return "typical"


def _should_show_flight_feature(
    *,
    data_quality: str,
    sample_count: int,
    combined_percentile: float,
    night_percentile: float,
    day_percentile: float,
) -> bool:
    if data_quality == "unavailable" or sample_count < _MIN_SAMPLES_TO_SHOW:
        return False
    return (
        combined_percentile >= _SHOW_COMBINED_MIN
        or night_percentile >= _SHOW_NIGHT_MIN
        or day_percentile >= _SHOW_DAY_MIN
    )


def _rate_word(rate: float) -> str:
    if rate < 0.2:
        return "rare"
    if rate < 0.7:
        return "occasional"
    if rate < 2:
        return "fairly common"
    return "frequent"


def _build_headline(
    *,
    night_per_hr: float,
    day_per_hr: float,
    night_percentile: float,
    day_percentile: float,
    combined_percentile: float,
    radius_miles: float,
    observation_days: int,
) -> tuple[str, str]:
    _ = combined_percentile, radius_miles  # used for elevation elsewhere

    if night_percentile >= _HIGH_NIGHT_MIN:
        headline = "Planes fly over often at night — more than in most NYC neighborhoods."
    elif night_percentile >= _SHOW_NIGHT_MIN:
        headline = "More overnight flight noise than in most NYC neighborhoods."
    elif day_percentile >= _SHOW_DAY_MIN:
        headline = "Busier daytime air traffic than in most of NYC."
    else:
        headline = "More flight activity here than typical for NYC."

    detail = (
        f"Overnight: {_rate_word(night_per_hr)}; daytime: {_rate_word(day_per_hr)} "
        f"(last {observation_days} days)."
    )
    return headline, detail


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
    radius_miles: float | None = None,
    max_alt_ft: int = 10000,
) -> FlightExposure:
    """
    Address-relative flight noise exposure from stored ADS-B samples.

    Returns comparative percentiles vs NYC baselines. ``show_flight_feature`` is true only
    when exposure is materially above typical — otherwise the UI hides flight paths/cards.
    """
    try:
        days = max(1, min(30, int(os.getenv("EXPOSURE_DAYS", str(days)))))
    except ValueError:
        days = 7
    default_radius = get_scan_radius_miles()
    if radius_miles is not None:
        default_radius = radius_miles
    try:
        radius_miles = max(
            0.25,
            min(10.0, float(os.getenv("EXPOSURE_RADIUS_MILES", str(default_radius)))),
        )
    except ValueError:
        radius_miles = get_scan_radius_miles()

    unavailable = FlightExposure(
        night_overflights_per_hour=0.0,
        day_overflights_per_hour=0.0,
        typical_altitude_ft=None,
        trend=None,
        data_quality="unavailable",
        show_flight_feature=False,
        elevation_level="unavailable",
        night_percentile=None,
        day_percentile=None,
        combined_percentile=None,
        headline=None,
        detail=None,
        observation_days=days,
        radius_miles=radius_miles,
        sample_count=0,
    )

    try:
        supabase = _get_client()
    except Exception:
        return unavailable

    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        since_iso = since.isoformat()

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
            return unavailable

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
                show_flight_feature=False,
                elevation_level="typical",
                night_percentile=0.0,
                day_percentile=0.0,
                combined_percentile=0.0,
                headline=None,
                detail=None,
                observation_days=days,
                radius_miles=radius_miles,
                sample_count=0,
            )

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
            local_hour = t.astimezone(_NYC_TZ).hour
            hours_seen.add(t.replace(minute=0, second=0, microsecond=0))
            if local_hour >= _NIGHT_HOUR_START or local_hour < _NIGHT_HOUR_END:
                night_keys.add(key)
            else:
                day_keys.add(key)

        observed_hours = max(1, len(hours_seen))
        night_per_hr = len(night_keys) / observed_hours
        day_per_hr = len(day_keys) / observed_hours

        typical_alt = None
        if alt_fts:
            alt_fts.sort()
            typical_alt = alt_fts[len(alt_fts) // 2]

        sample_count = len(filtered)
        quality = "good" if sample_count >= 800 else "sparse"

        night_p = _percentile_from_rate(
            night_per_hr, median_rate=_NIGHT_RATE_MEDIAN, p90_rate=_NIGHT_RATE_P90
        )
        day_p = _percentile_from_rate(
            day_per_hr, median_rate=_DAY_RATE_MEDIAN, p90_rate=_DAY_RATE_P90
        )
        combined_p = _NIGHT_WEIGHT * night_p + _DAY_WEIGHT * day_p

        show = _should_show_flight_feature(
            data_quality=quality,
            sample_count=sample_count,
            combined_percentile=combined_p,
            night_percentile=night_p,
            day_percentile=day_p,
        )
        elevation = _elevation_level(combined_p, night_p) if show else "typical"

        headline = None
        detail = None
        if show:
            headline, detail = _build_headline(
                night_per_hr=night_per_hr,
                day_per_hr=day_per_hr,
                night_percentile=night_p,
                day_percentile=day_p,
                combined_percentile=combined_p,
                radius_miles=radius_miles,
                observation_days=days,
            )
            if typical_alt is not None and typical_alt <= 3200:
                detail = (
                    f"{detail} Many planes pass around {typical_alt:,} ft — "
                    "low enough to hear from the street."
                )

        return FlightExposure(
            night_overflights_per_hour=round(night_per_hr, 2),
            day_overflights_per_hour=round(day_per_hr, 2),
            typical_altitude_ft=typical_alt,
            trend=None,
            data_quality=quality,
            show_flight_feature=show,
            elevation_level=elevation,
            night_percentile=round(night_p, 3),
            day_percentile=round(day_p, 3),
            combined_percentile=round(combined_p, 3),
            headline=headline,
            detail=detail,
            observation_days=days,
            radius_miles=radius_miles,
            sample_count=sample_count,
        )
    except Exception:
        logger.exception("flight_exposure: query or compute failed (missing table, RLS, or transient DB error)")
        return unavailable
