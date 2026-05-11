from pydantic import BaseModel
from typing import Literal


class ScanRequest(BaseModel):
    address: str


class Coordinate(BaseModel):
    lat: float
    lng: float


class LogisticsCard(BaseModel):
    type: str
    name: str
    category: str
    emoji: str
    distance_value: float
    distance_unit: Literal["feet", "miles"]
    color: str
    coordinates: Coordinate


class ThreatCard(BaseModel):
    id: str
    emoji: str
    title: str
    subtitle: str
    border_color: str
    text_color: str
    bullets: list[str]


class Zone(BaseModel):
    lat: float
    lng: float
    radius_meters: int
    color: str
    label: str


class SwarmPin(BaseModel):
    lat: float
    lng: float
    type: Literal["police", "rat", "permit", "truck", "bus", "noise", "fire", "water", "trash", "graffiti", "construction", "report"]
    label: str


class FlightPath(BaseModel):
    start: Coordinate
    end: Coordinate
    label: str
    # Optional polyline for "real" tracks (ADS-B), ordered points.
    path: list[Coordinate] | None = None
    # Optional per-track stats (best-effort).
    closest_miles: float | None = None
    median_altitude_ft: int | None = None
    sample_count: int | None = None
    callsign: str | None = None
    airline: str | None = None
    flight_number: str | None = None
    last_seen_utc: str | None = None


class FlightExposure(BaseModel):
    # Approx overflights per hour within the chosen radius/altitude band.
    night_overflights_per_hour: float
    day_overflights_per_hour: float
    # Typical altitude of nearby overflights (median), if available.
    typical_altitude_ft: int | None = None
    # "stable" vs "variable" based on recent history.
    trend: Literal["stable", "variable"] | None = None
    # "good" when we have consistent sampling; "sparse" when gaps are common.
    data_quality: Literal["good", "sparse", "unavailable"]


class MapData(BaseModel):
    target: Coordinate
    zones: list[Zone]
    swarm: list[SwarmPin]
    # Multiple nearby corridors (nearest first). `flight_path` is kept for backwards compatibility.
    flight_paths: list[FlightPath] = []
    flight_path: FlightPath | None = None


class ScanResponse(BaseModel):
    address: str
    formatted_address: str
    coordinates: Coordinate
    danger_score: int
    risk_level: Literal["LOW", "MODERATE", "HIGH", "EXTREME"]
    risk_label: str
    risk_description: str
    logistics: list[LogisticsCard]
    threat_cards: list[ThreatCard]
    map_data: MapData
    flight_exposure: FlightExposure | None = None
    # True when backend loaded a non-placeholder GEMINI_API_KEY for this scan (see /scan JSON in DevTools).
    gemini_configured: bool = False
    # Gemini call outcome — always present so callers can diagnose fallback reasons without reading logs.
    # gemini_status: "no_key" | "placeholder" | "timeout" | "error" | "ok"
    gemini_status: str | None = None
    gemini_latency_ms: int | None = None
    gemini_timeout_seconds: float | None = None
    # gemini_error_kind: "empty" | "json_parse" | "auth" | "quota" | "unknown" (set only on status="error")
    gemini_error_kind: str | None = None
    # Short, sanitized summary of the underlying exception (set only on status="error")
    gemini_error_detail: str | None = None
