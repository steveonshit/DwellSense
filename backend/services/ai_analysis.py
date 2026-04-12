"""
Google Gemini AI — synthesizes raw city data into the Danger Score
and 9-point threat analysis cards.
"""

import os
import json
import asyncio
import hashlib
import logging
from functools import lru_cache
import google.generativeai as genai
from models.schemas import Coordinate, ThreatCard, FlightPath, LogisticsCard

logger = logging.getLogger(__name__)

# Simple in-memory cache: address hash → analysis result
_analysis_cache: dict[str, dict] = {}


SYSTEM_PROMPT = """You are DwellSense, a brutally honest real estate forensics AI. You are on the renter's side.
You analyze raw municipal data and produce a data-driven Danger Score (0–100) and a 9-point threat analysis.

SCORING GUIDE:
- 80–100 = EXTREME (multiple serious threats)
- 60–79  = HIGH (significant issues)
- 40–59  = MODERATE (some concerns)
- 0–39   = LOW (relatively safe)

TONE: Direct, data-driven, slightly adversarial. Use specific numbers from the data. Write in ALL CAPS for threat titles.
Write bullets that feel like insider knowledge, not generic warnings.

Return ONLY valid JSON matching this exact structure, no markdown, no extra text:
{
  "danger_score": <integer 0-100>,
  "risk_level": "<LOW|MODERATE|HIGH|EXTREME>",
  "risk_label": "<short label like 'EXTREME RISK DETECTED'>",
  "risk_description": "<one sentence summary>",
  "threat_cards": [
    {
      "id": "<snake_case_id>",
      "emoji": "<single emoji>",
      "title": "<ALL CAPS title>",
      "subtitle": "<one punchy sentence>",
      "border_color": "<hex color>",
      "text_color": "<hex color>",
      "bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"]
    }
  ]
}

Always produce exactly 9 threat cards in this order:
1. high_churn (🏃‍♂️, rose, #f43f5e/#fda4af)
2. police_calls (🚓, blue, #3b82f6/#93c5fd)
3. area_safety (🛡️, teal, #14b8a6/#5eead4)
4. tenant_warnings (🗣️, fuchsia, #d946ef/#f0abfc)
5. demolitions (🚧, orange, #f97316/#fdba74)
6. noise_schedule (🚛, yellow, #eab308/#fde047)
7. flight_path (✈️, cyan, #06b6d4/#67e8f9)
8. reports_311 (🐀, purple, #a855f7/#d8b4fe)
9. oven_effect (☀️, red, #ef4444/#fca5a5)
"""


def _summarize_crime(data: list[dict]) -> str:
    if not data:
        return "No crime data available in database (run daily refresh job)."
    types: dict[str, int] = {}
    for row in data:
        t = row.get("crime_type", "Unknown")
        types[t] = types.get(t, 0) + 1
    top = sorted(types.items(), key=lambda x: x[1], reverse=True)[:5]
    lines = [f"- {t}: {c} incidents" for t, c in top]
    return f"Total: {len(data)} incidents in last 30 days.\n" + "\n".join(lines)


def _summarize_311(data: list[dict]) -> str:
    if not data:
        return "No 311 data available in database (run daily refresh job)."
    types: dict[str, int] = {}
    for row in data:
        t = row.get("complaint_type", "Unknown")
        types[t] = types.get(t, 0) + 1
    top = sorted(types.items(), key=lambda x: x[1], reverse=True)[:5]
    lines = [f"- {t}: {c} reports" for t, c in top]
    return f"Total: {len(data)} reports in last 30 days.\n" + "\n".join(lines)


def _summarize_permits(data: list[dict]) -> str:
    if not data:
        return "No permit data available in database (run daily refresh job)."
    active = [r for r in data if r.get("permit_status", "").lower() in ("issued", "active", "renewed")]
    types: dict[str, int] = {}
    for row in active:
        t = row.get("permit_type", "Unknown")
        types[t] = types.get(t, 0) + 1
    lines = [f"- {t}: {c} active permits" for t, c in sorted(types.items(), key=lambda x: x[1], reverse=True)]
    return f"Total active: {len(active)} permits.\n" + "\n".join(lines)


def _summarize_logistics(logistics: list[LogisticsCard]) -> str:
    lines = []
    for card in logistics:
        lines.append(f"- {card.category} ({card.emoji} {card.name}): {card.distance_value} {card.distance_unit}")
    return "\n".join(lines) if lines else "No logistics data."


async def analyze(
    address: str,
    coord: Coordinate,
    crime: list[dict],
    reports_311: list[dict],
    permits: list[dict],
    evictions: list[dict],
    logistics: list[LogisticsCard],
    flight_path: FlightPath | None,
) -> dict:
    """
    Calls Gemini 2.0 Flash with all available data.
    Returns parsed JSON dict with danger_score, risk_level, threat_cards, etc.
    Falls back to a structured fallback dict if Gemini is unavailable.
    """
    # Cache key: address + rough crime/311 counts (invalidates if data changes)
    cache_key = hashlib.md5(
        f"{address}:{len(crime)}:{len(reports_311)}:{len(permits)}".encode()
    ).hexdigest()
    if cache_key in _analysis_cache:
        return _analysis_cache[cache_key]

    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_api_key:
        return _fallback_analysis(crime, reports_311, permits)

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    flight_text = (
        f"Flight path: {flight_path.label}"
        if flight_path
        else "No major flight corridor detected near this address."
    )

    prompt = f"""ADDRESS: {address}
COORDINATES: {coord.lat:.5f}, {coord.lng:.5f}

CRIME DATA (last 30 days, within 0.5 miles):
{_summarize_crime(crime)}

311 SERVICE REQUESTS (last 30 days, within 0.5 miles):
{_summarize_311(reports_311)}

BUILDING PERMITS (last 90 days, within 0.5 miles):
{_summarize_permits(permits)}

EVICTION RECORDS (nearby, all time):
{len(evictions)} eviction filings found near this address.

TRANSIT & GROCERY LOGISTICS:
{_summarize_logistics(logistics)}

FLIGHT PATH ANALYSIS:
{flight_text}

Generate the Danger Score and 9-point threat analysis based on this real data."""

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, prompt),
            timeout=45.0,
        )
        raw = response.text.strip()
        # Strip any accidental markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        _analysis_cache[cache_key] = result
        return result
    except asyncio.TimeoutError:
        logger.warning("Gemini timed out after 45s — using fallback analysis.")
        return _fallback_analysis(crime, reports_311, permits)
    except Exception as e:
        logger.warning(f"Gemini error: {e} — using fallback analysis.")
        return _fallback_analysis(crime, reports_311, permits)


def _fallback_analysis(crime: list[dict], reports_311: list[dict], permits: list[dict]) -> dict:
    """
    Returns a basic analysis when Gemini is not available.
    Scores are estimated from raw data counts.
    """
    crime_count = len(crime)
    reports_count = len(reports_311)
    permit_count = len(permits)

    score = min(100, int((crime_count * 0.4) + (reports_count * 0.3) + (permit_count * 0.5)))
    score = max(10, score)

    if score >= 80:
        risk_level, risk_label = "EXTREME", "EXTREME RISK DETECTED"
    elif score >= 60:
        risk_level, risk_label = "HIGH", "HIGH RISK DETECTED"
    elif score >= 40:
        risk_level, risk_label = "MODERATE", "MODERATE RISK"
    else:
        risk_level, risk_label = "LOW", "LOW RISK"

    return {
        "danger_score": score,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "risk_description": f"Analysis based on {crime_count} crime reports, {reports_count} 311 calls, and {permit_count} permits nearby.",
        "threat_cards": [
            {
                "id": "high_churn", "emoji": "🏃‍♂️", "title": "TENANT CHURN",
                "subtitle": "Historical turnover data from NYC court records.",
                "border_color": "#f43f5e", "text_color": "#fda4af",
                "bullets": ["Eviction records found nearby.", "High turnover signals problem landlords.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "police_calls", "emoji": "🚓", "title": "POLICE CALLS",
                "subtitle": "NYPD dispatch activity in the area.",
                "border_color": "#3b82f6", "text_color": "#93c5fd",
                "bullets": [f"{crime_count} incidents logged in last 30 days.", "See blue zones on the threat map.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "area_safety", "emoji": "🛡️", "title": "AREA SAFETY",
                "subtitle": "Property and violent crime density.",
                "border_color": "#14b8a6", "text_color": "#5eead4",
                "bullets": ["Crime data pulled from NYC Open Data.", "See red zones on the threat map.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "tenant_warnings", "emoji": "🗣️", "title": "TENANT WARNINGS",
                "subtitle": "NYC HPD housing violation records.",
                "border_color": "#d946ef", "text_color": "#f0abfc",
                "bullets": ["Check HPD building violations for this address.", "Past violations indicate maintenance neglect.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "demolitions", "emoji": "🚧", "title": "DEMOLITIONS",
                "subtitle": "Active DOB permits near the property.",
                "border_color": "#f97316", "text_color": "#fdba74",
                "bullets": [f"{permit_count} active permits found nearby.", "Heavy equipment possible during business hours.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "noise_schedule", "emoji": "🚛", "title": "NOISE SCHEDULE",
                "subtitle": "Commercial and municipal noise sources.",
                "border_color": "#eab308", "text_color": "#fde047",
                "bullets": ["311 noise complaints logged nearby.", "Check for commercial loading docks on the block.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "flight_path", "emoji": "✈️", "title": "FLIGHT PATH",
                "subtitle": "Proximity to NYC airport approach corridors.",
                "border_color": "#06b6d4", "text_color": "#67e8f9",
                "bullets": ["Flight corridor analysis computed.", "See cyan flight path line on map.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "reports_311", "emoji": "🐀", "title": "311 REPORTS",
                "subtitle": "City service complaints from neighbors.",
                "border_color": "#a855f7", "text_color": "#d8b4fe",
                "bullets": [f"{reports_count} 311 reports filed nearby.", "Primary complaints visible on map.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
            {
                "id": "oven_effect", "emoji": "☀️", "title": "OVEN EFFECT",
                "subtitle": "Sun exposure and AC cost risk.",
                "border_color": "#ef4444", "text_color": "#fca5a5",
                "bullets": ["West-facing units trap afternoon heat.", "Check unit orientation before signing.", "Add GEMINI_API_KEY for detailed AI analysis."],
            },
        ],
    }
