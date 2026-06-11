"""
Fixed threat-card chrome: ids, emoji, titles, subtitles, hex colors.
Danger score and risk band are computed from counts in Python so Gemini
only has to write bullet text (see ai_analysis.py).
"""

from __future__ import annotations

import math
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
    *,
    crime_capped: bool = False,
    reports_capped: bool = False,
    permits_capped: bool = False,
    evictions_capped: bool = False,
) -> dict[str, Any]:
    """
    Percentile-style scoring (Option C), inverted for UX:

    - Internally we estimate a 0..100 "raw hazard" from municipal counts.
    - We return `danger_score` as a **0..100 wellness-oriented score** where **100 is best** and **0 is worst**.
    """

    def _percentile_from_count(
        x: int,
        *,
        median_count: float,
        p90_count: float,
    ) -> float:
        x = max(0, int(x))
        # logistic over log1p(x); ensures diminishing returns and smooth percentiles
        lx = math.log1p(x)
        l50 = math.log1p(max(0.0, float(median_count)))
        l90 = math.log1p(max(1e-6, float(p90_count)))
        # Choose k so that p90 roughly maps near 0.90 (not exactly, but close)
        denom = max(1e-6, (l90 - l50))
        k = 2.2 / denom
        z = (lx - l50) * k
        return 1.0 / (1.0 + math.exp(-z))

    # Baselines (approx NYC-wide) — tune after we test a few addresses.
    crime_p = _percentile_from_count(crime_count, median_count=8, p90_count=45)
    reports_p = _percentile_from_count(reports_count, median_count=12, p90_count=70)
    permits_p = _percentile_from_count(permit_count, median_count=1, p90_count=8)
    evict_p = _percentile_from_count(eviction_count, median_count=0.5, p90_count=3)

    # Weighting (sums to 1.0)
    score_01 = (
        (0.40 * crime_p)
        + (0.25 * reports_p)
        + (0.15 * permits_p)
        + (0.20 * evict_p)
    )

    raw_hazard = int(round(max(0.0, min(1.0, score_01)) * 100))

    capped = crime_capped or reports_capped or permits_capped or evictions_capped

    safety_score = int(round(max(0.0, min(100.0, 100 - raw_hazard))))

    # If any dataset hits our fetch cap, the true neighborhood density may be higher than
    # the counted rows. Don't claim a "perfect" safety score when we're truncated.
    if capped:
        safety_score = min(safety_score, 90)

    # Bands are based on SAFETY (higher is better).
    if safety_score <= 20:
        risk_level, risk_label = "EXTREME", "WEAK SIGNALS"
    elif safety_score <= 40:
        risk_level, risk_label = "HIGH", "BELOW-AVERAGE"
    elif safety_score <= 60:
        risk_level, risk_label = "MODERATE", "MIXED SIGNALS"
    else:
        risk_level, risk_label = "LOW", "STRONG SIGNALS"

    suffix_parts: list[str] = []
    if capped:
        suffix_parts.append("Counts may be capped by our data sample limits in very dense areas.")

    risk_description = (
        f"Analysis based on {crime_count} crime reports, {reports_count} 311 calls, "
        f"{permit_count} active permits, and {eviction_count} eviction filings within ~1 mile."
        + (" " + " ".join(suffix_parts) if suffix_parts else "")
    )

    return {
        "danger_score": safety_score,
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
