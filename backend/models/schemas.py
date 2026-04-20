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


class MapData(BaseModel):
    target: Coordinate
    zones: list[Zone]
    swarm: list[SwarmPin]
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
