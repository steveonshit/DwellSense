"""
POST /scan — the main endpoint.
Takes an address, runs all data lookups in parallel, and returns the full ScanResponse.
"""

import asyncio
import logging
from fastapi import APIRouter, HTTPException
from models.schemas import ScanRequest, ScanResponse, MapData, ThreatCard, LogisticsCard
from services import geocoding, city_data, places, flights, ai_analysis, flight_exposure
from services.threat_card_layout import cards_from_specs_and_bullets, ordered_card_ids
from services.city_data import (
    CRIME_FETCH_LIMIT,
    EVICTIONS_FETCH_LIMIT,
    PERMITS_FETCH_LIMIT,
    REPORTS_FETCH_LIMIT,
)

router = APIRouter()
logger = logging.getLogger(__name__)

NYC_BOUNDS = {
    "lat_min": 40.4774,  # SW corner (approx)
    "lat_max": 40.9176,  # NE corner (approx)
    "lng_min": -74.2591,
    "lng_max": -73.7004,
}


def _is_within_nyc(coord) -> bool:
    return (
        NYC_BOUNDS["lat_min"] <= coord.lat <= NYC_BOUNDS["lat_max"]
        and NYC_BOUNDS["lng_min"] <= coord.lng <= NYC_BOUNDS["lng_max"]
    )


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest):
    address = request.address.strip()
    if not address:
        raise HTTPException(status_code=400, detail="Address cannot be empty.")

    # ── 1. Geocode the address ────────────────────────────────────────────────
    try:
        coord, formatted_address = await geocoding.geocode(address)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # NYC-only guardrail (product scope).
    if not _is_within_nyc(coord):
        raise HTTPException(
            status_code=400,
            detail="Out of reach — NYC addresses only.",
        )

    # ── 2. Fire all data lookups in parallel ──────────────────────────────────
    crime_task = city_data.get_nearby_crime(coord)
    reports_311_task = city_data.get_nearby_311(coord)
    permits_task = city_data.get_nearby_permits(coord)
    evictions_task = city_data.get_nearby_evictions(coord)
    logistics_task = places.get_logistics(coord)

    crime, reports_311, permits, evictions, logistics = await asyncio.gather(
        crime_task,
        reports_311_task,
        permits_task,
        evictions_task,
        logistics_task,
    )

    # Tighten spatial accuracy: bbox queries are a prefilter; scoring should reflect a true ~1mi radius.
    crime_capped = len(crime) >= CRIME_FETCH_LIMIT
    reports_capped = len(reports_311) >= REPORTS_FETCH_LIMIT
    permits_capped = len(permits) >= PERMITS_FETCH_LIMIT
    evictions_capped = len(evictions) >= EVICTIONS_FETCH_LIMIT

    crime = city_data.filter_rows_within_radius(coord, crime)
    reports_311 = city_data.filter_rows_within_radius(coord, reports_311)
    permits = city_data.filter_rows_within_radius(coord, permits)
    evictions = city_data.filter_rows_within_radius(coord, evictions)

    # ── 3. Flight corridors (ADS-B or static) ────────────────────────────────
    flight_paths = await flights.get_flight_paths(coord, limit=3)
    flight_path = flight_paths[0] if flight_paths else None

    # ── 4. Build map data ────────────────────────────────────────────────────
    zones = city_data.build_zones(crime, reports_311, permits)
    swarm = city_data.build_swarm(crime, reports_311, permits)
    map_data = MapData(
        target=coord,
        zones=zones,
        swarm=swarm,
        flight_paths=flight_paths,
        flight_path=flight_path,
    )

    # ── 5. AI analysis (Gemini) ───────────────────────────────────────────────
    ai_result = await ai_analysis.analyze(
        address=formatted_address,
        coord=coord,
        crime=crime,
        reports_311=reports_311,
        permits=permits,
        evictions=evictions,
        logistics=logistics,
        flight_path=flight_path,
        crime_capped=crime_capped,
        reports_capped=reports_capped,
        permits_capped=permits_capped,
        evictions_capped=evictions_capped,
    )

    # ── 6. Parse AI result into typed models ──────────────────────────────────
    threat_cards: list[ThreatCard] = []
    for card in ai_result.get("threat_cards") or []:
        if not isinstance(card, dict):
            continue
        try:
            bullets = card.get("bullets")
            if not isinstance(bullets, list):
                bullets = []
            threat_cards.append(
                ThreatCard(
                    id=str(card.get("id", "")),
                    emoji=str(card.get("emoji", "")),
                    title=str(card.get("title", "")),
                    subtitle=str(card.get("subtitle", "")),
                    border_color=str(card.get("border_color", "")),
                    text_color=str(card.get("text_color", "")),
                    bullets=[str(b) for b in bullets],
                )
            )
        except Exception:
            logger.warning("Skipping malformed threat card", exc_info=True)
    if not threat_cards:
        fb_map = {cid: ["Details unavailable.", "—", "—"] for cid in ordered_card_ids()}
        threat_cards = [ThreatCard(**c) for c in cards_from_specs_and_bullets(fb_map)]

    _ds = ai_result.get("danger_score", 50)
    try:
        danger_score = int(_ds) if _ds is not None else 50
    except (TypeError, ValueError):
        danger_score = 50
    danger_score = max(0, min(100, danger_score))

    _valid_risk = frozenset({"LOW", "MODERATE", "HIGH", "EXTREME"})
    risk_level = ai_result.get("risk_level", "MODERATE")
    if risk_level not in _valid_risk:
        risk_level = "MODERATE"

    # Risk level color label
    risk_emoji_map = {
        # `danger_score` is a wellness-oriented score (100 = best). Risk bands are inverted vs the old hazard UI.
        "EXTREME": "🚨",
        "HIGH": "⚠️",
        "MODERATE": "🟡",
        "LOW": "✅",
    }

    return ScanResponse(
        address=address,
        formatted_address=formatted_address,
        coordinates=coord,
        danger_score=danger_score,
        risk_level=risk_level,
        risk_label=f"{risk_emoji_map.get(risk_level, '⚠️')} {ai_result.get('risk_label', risk_level + ' RISK')}",
        risk_description=ai_result.get("risk_description", ""),
        logistics=logistics,
        threat_cards=threat_cards,
        map_data=map_data,
        flight_exposure=flight_exposure.compute_exposure(coord),
        gemini_configured=bool(ai_result.get("gemini_configured", False)),
        gemini_status=ai_result.get("gemini_status"),
        gemini_latency_ms=ai_result.get("gemini_latency_ms"),
        gemini_timeout_seconds=ai_result.get("gemini_timeout_seconds"),
        gemini_error_kind=ai_result.get("gemini_error_kind"),
        gemini_error_detail=ai_result.get("gemini_error_detail"),
    )
