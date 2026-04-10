"""
POST /scan — the main endpoint.
Takes an address, runs all data lookups in parallel, and returns the full ScanResponse.
"""

import asyncio
from fastapi import APIRouter, HTTPException
from models.schemas import ScanRequest, ScanResponse, MapData, ThreatCard, LogisticsCard
from services import geocoding, city_data, places, flights, ai_analysis

router = APIRouter()


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

    # ── 3. Flight path (sync — pure math) ────────────────────────────────────
    flight_path = flights.get_nearest_flight_corridor(coord)

    # ── 4. Build map data ────────────────────────────────────────────────────
    zones = city_data.build_zones(crime, reports_311, permits)
    swarm = city_data.build_swarm(crime, reports_311, permits)
    map_data = MapData(
        target=coord,
        zones=zones,
        swarm=swarm,
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
    )

    # ── 6. Parse AI result into typed models ──────────────────────────────────
    threat_cards = [
        ThreatCard(
            id=card["id"],
            emoji=card["emoji"],
            title=card["title"],
            subtitle=card["subtitle"],
            border_color=card["border_color"],
            text_color=card["text_color"],
            bullets=card["bullets"],
        )
        for card in ai_result.get("threat_cards", [])
    ]

    danger_score = int(ai_result.get("danger_score", 50))
    risk_level = ai_result.get("risk_level", "MODERATE")

    # Risk level color label
    risk_emoji_map = {
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
    )
