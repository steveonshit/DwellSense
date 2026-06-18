"""
Fixed threat-card chrome: ids, emoji, titles, subtitles, hex colors.
Danger score and risk band are computed from counts in Python so Gemini
only has to write bullet text (see ai_analysis.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from services import city_data

# High 311 volume should temper the wellness label even when crime is low.
_HIGH_311_REPORTS_THRESHOLD = 200

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
        "subtitle": "HPD violation data not ingested; verify on NYC HPD portal.",
        "border_color": "#d946ef",
        "text_color": "#f0abfc",
    },
    {
        "id": "demolitions",
        "emoji": "🚧",
        "title": "CONSTRUCTION & DEMOLITIONS",
        "subtitle": "DOB active permits and 311 building complaints.",
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
        "subtitle": "ADS-B aircraft tracks within the scan radius.",
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


@dataclass(frozen=True)
class CardChromeContext:
    crime_count: int = 0
    reports_count: int = 0
    permit_count: int = 0
    eviction_count: int = 0
    noise_count: int = 0
    construction_311_count: int = 0
    has_flight_path: bool = False


def resolve_card_colors(card_id: str, ctx: CardChromeContext) -> tuple[str, str]:
    """Border + subtitle colors reflect whether this card's primary signal is elevated."""
    calm_blue = ("#3b82f6", "#93c5fd")
    calm_teal = ("#14b8a6", "#5eead4")
    calm_slate = ("#64748b", "#94a3b8")
    good_green = ("#22c55e", "#86efac")
    warn_amber = ("#f59e0b", "#fcd34d")
    alert_rose = ("#f43f5e", "#fda4af")
    alert_orange = ("#f97316", "#fdba74")
    alert_purple = ("#a855f7", "#d8b4fe")
    alert_cyan = ("#06b6d4", "#67e8f9")
    alert_yellow = ("#eab308", "#fde047")
    alert_red = ("#ef4444", "#fca5a5")
    calm_purple = ("#7c3aed", "#c4b5fd")

    if card_id == "high_churn":
        return alert_rose if ctx.eviction_count > 0 else good_green
    if card_id == "police_calls":
        return alert_rose if ctx.crime_count > 0 else calm_blue
    if card_id == "area_safety":
        return warn_amber if ctx.crime_count > 0 else calm_teal
    if card_id == "tenant_warnings":
        return calm_purple
    if card_id == "demolitions":
        return alert_orange if (ctx.permit_count > 0 or ctx.construction_311_count > 0) else calm_slate
    if card_id == "noise_schedule":
        return alert_yellow if ctx.noise_count > 0 else calm_slate
    if card_id == "flight_path":
        return alert_cyan if ctx.has_flight_path else calm_slate
    if card_id == "reports_311":
        if ctx.reports_count >= _HIGH_311_REPORTS_THRESHOLD:
            return alert_purple
        return calm_purple if ctx.reports_count > 0 else calm_slate
    if card_id == "oven_effect":
        return alert_red
    spec = next((c for c in CARD_SPECS if c["id"] == card_id), None)
    if spec:
        return spec["border_color"], spec["text_color"]
    return calm_slate


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

    # Dense 311 neighborhoods should not read as "strong signals" when crime is quiet.
    if reports_count >= _HIGH_311_REPORTS_THRESHOLD:
        penalty = min(30, int(6 * math.log1p(reports_count / 40)))
        safety_score = max(0, safety_score - penalty)

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
    if reports_count >= _HIGH_311_REPORTS_THRESHOLD:
        suffix_parts.append(
            f"High 311 volume ({reports_count} complaints nearby) — see the 311 card and map pins; "
            "the wellness score weights crime and evictions more than every complaint type."
        )

    scan_mi = city_data.get_scan_radius_miles()
    risk_description = (
        f"Analysis based on {crime_count} crime reports, {reports_count} 311 calls, "
        f"{permit_count} active permits, and {eviction_count} eviction filings "
        f"within ~{scan_mi:g} miles."
        + (" " + " ".join(suffix_parts) if suffix_parts else "")
    )

    return {
        "danger_score": safety_score,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "risk_description": risk_description,
    }


def cards_from_specs_and_bullets(
    bullets_by_id: dict[str, list[str]],
    chrome: CardChromeContext | None = None,
) -> list[dict[str, Any]]:
    """Merge fixed chrome with three bullets per card (order follows CARD_SPECS)."""
    ctx = chrome or CardChromeContext()
    out: list[dict[str, Any]] = []
    for spec in CARD_SPECS:
        cid = spec["id"]
        raw = bullets_by_id.get(cid)
        if not isinstance(raw, list):
            raw = []
        b = [str(x).strip() if x is not None else "" for x in raw[:3]]
        while len(b) < 3:
            b.append("")
        border_color, text_color = resolve_card_colors(cid, ctx)
        out.append({**spec, "border_color": border_color, "text_color": text_color, "bullets": b})
    return out
