"""
Fixed threat-card chrome: ids, emoji, titles, subtitles, hex colors.
Danger score and risk band are computed from counts in Python so Gemini
only has to write bullet text (see ai_analysis.py).
"""

from __future__ import annotations

from typing import Any

# Order matches the UI carousel / original Gemini system prompt.
CARD_SPECS: list[dict[str, Any]] = [
    {
        "id": "high_churn",
        "emoji": "🏃‍♂️",
        "title": "TENANT CHURN",
        "subtitle": "Historical turnover data from NYC court records.",
        "border_color": "#f43f5e",
        "text_color": "#fda4af",
    },
    {
        "id": "police_calls",
        "emoji": "🚓",
        "title": "POLICE CALLS",
        "subtitle": "NYPD dispatch activity in the area.",
        "border_color": "#3b82f6",
        "text_color": "#93c5fd",
    },
    {
        "id": "area_safety",
        "emoji": "🛡️",
        "title": "AREA SAFETY",
        "subtitle": "Property and violent crime density.",
        "border_color": "#14b8a6",
        "text_color": "#5eead4",
    },
    {
        "id": "tenant_warnings",
        "emoji": "🗣️",
        "title": "TENANT WARNINGS",
        "subtitle": "NYC HPD housing violation records.",
        "border_color": "#d946ef",
        "text_color": "#f0abfc",
    },
    {
        "id": "demolitions",
        "emoji": "🚧",
        "title": "DEMOLITIONS",
        "subtitle": "Active DOB permits near the property.",
        "border_color": "#f97316",
        "text_color": "#fdba74",
    },
    {
        "id": "noise_schedule",
        "emoji": "🚛",
        "title": "NOISE SCHEDULE",
        "subtitle": "Commercial and municipal noise sources.",
        "border_color": "#eab308",
        "text_color": "#fde047",
    },
    {
        "id": "flight_path",
        "emoji": "✈️",
        "title": "FLIGHT PATH",
        "subtitle": "Proximity to NYC airport approach corridors.",
        "border_color": "#06b6d4",
        "text_color": "#67e8f9",
    },
    {
        "id": "reports_311",
        "emoji": "🐀",
        "title": "311 REPORTS",
        "subtitle": "City service complaints from neighbors.",
        "border_color": "#a855f7",
        "text_color": "#d8b4fe",
    },
    {
        "id": "oven_effect",
        "emoji": "☀️",
        "title": "OVEN EFFECT",
        "subtitle": "Sun exposure and AC cost risk.",
        "border_color": "#ef4444",
        "text_color": "#fca5a5",
    },
]


def ordered_card_ids() -> list[str]:
    return [c["id"] for c in CARD_SPECS]


def compute_risk_from_counts(
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int = 0,
) -> dict[str, Any]:
    """Same scoring band as the legacy fallback analysis."""
    score = min(
        100,
        int((crime_count * 0.4) + (reports_count * 0.3) + (permit_count * 0.5)),
    )
    score = max(10, score)

    if score >= 80:
        risk_level, risk_label = "EXTREME", "EXTREME RISK DETECTED"
    elif score >= 60:
        risk_level, risk_label = "HIGH", "HIGH RISK DETECTED"
    elif score >= 40:
        risk_level, risk_label = "MODERATE", "MODERATE RISK"
    else:
        risk_level, risk_label = "LOW", "LOW RISK"

    risk_description = (
        f"Analysis based on {crime_count} crime reports, {reports_count} 311 calls, "
        f"{permit_count} permits, and {eviction_count} eviction filings nearby."
    )

    return {
        "danger_score": score,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "risk_description": risk_description,
    }


def cards_from_specs_and_bullets(bullets_by_id: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Merge fixed chrome with three bullets per card (order follows CARD_SPECS)."""
    out: list[dict[str, Any]] = []
    for spec in CARD_SPECS:
        cid = spec["id"]
        raw = bullets_by_id.get(cid)
        if not isinstance(raw, list):
            raw = []
        b = [str(x).strip() if x is not None else "" for x in raw[:3]]
        while len(b) < 3:
            b.append("")
        out.append({**spec, "bullets": b})
    return out
