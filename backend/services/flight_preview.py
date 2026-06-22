"""Local-dev preview for flight noise UI when Supabase ADS-B data is unreachable."""

from __future__ import annotations

import math
import os

from models.schemas import Coordinate, FlightExposure, FlightPath
from services.flight_exposure import _build_headline


def preview_enabled() -> bool:
    return os.getenv("FLIGHT_UI_PREVIEW", "").strip().lower() in ("1", "true", "yes")


def preview_exposure(coord: Coordinate, *, radius_miles: float, days: int) -> FlightExposure:
    """Representative elevated NYC exposure for UI review (not real aircraft data)."""
    _ = coord
    night_per_hr = 0.15
    day_per_hr = 2.7
    night_p = 0.38
    day_p = 0.72
    combined_p = 0.58
    headline, detail = _build_headline(
        night_per_hr=night_per_hr,
        day_per_hr=day_per_hr,
        night_percentile=night_p,
        day_percentile=day_p,
        combined_percentile=combined_p,
        radius_miles=radius_miles,
        observation_days=days,
    )
    detail = (
        f"{detail} Preview data for local UI — connect Supabase for real flight tracking."
    )
    return FlightExposure(
        night_overflights_per_hour=night_per_hr,
        day_overflights_per_hour=day_per_hr,
        typical_altitude_ft=2400,
        trend=None,
        data_quality="good",
        show_flight_feature=True,
        elevation_level="elevated",
        night_percentile=night_p,
        day_percentile=day_p,
        combined_percentile=combined_p,
        headline=headline,
        detail=detail,
        observation_days=days,
        radius_miles=radius_miles,
        sample_count=480,
    )


def preview_flight_paths(coord: Coordinate, *, limit: int = 2) -> list[FlightPath]:
    """Simple cyan-route preview polyline near the scanned address."""
    _ = limit
    dlat = 1.2 / 69.0
    dlng = 1.8 / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
    start = Coordinate(lat=coord.lat + dlat, lng=coord.lng - dlng)
    mid = Coordinate(lat=coord.lat + dlat * 0.35, lng=coord.lng - dlng * 0.35)
    end = Coordinate(lat=coord.lat - dlat * 0.25, lng=coord.lng + dlng * 0.55)
    closest = 1.7
    return [
        FlightPath(
            start=start,
            end=end,
            label="Preview plane route (local dev)",
            path=[start, mid, end],
            closest_miles=closest,
            median_altitude_ft=8500,
            sample_count=4,
        )
    ]
