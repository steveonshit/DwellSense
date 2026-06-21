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

# High 311 volume should temper the wellness label even when crime is quiet.
_HIGH_311_REPORTS_THRESHOLD = 200
_ELEVATED_311_REPORTS_THRESHOLD = 80

# v2 label bands (wellness score 0–100, higher is better).
_LABEL_BANDS: list[tuple[int, str, str]] = [
    (15, "EXTREME", "Terrible"),
    (28, "HIGH", "Bad"),
    (42, "MODERATE", "Average"),
    (55, "LOW", "Good"),
    (68, "LOW", "Very Good"),
    (80, "LOW", "Great"),
    (90, "LOW", "Excellent"),
    (100, "LOW", "Outstanding"),
]

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


def _percentile_from_count(
    x: int,
    *,
    median_count: float,
    p90_count: float,
) -> float:
    x = max(0, int(x))
    lx = math.log1p(x)
    l50 = math.log1p(max(0.0, float(median_count)))
    l90 = math.log1p(max(1e-6, float(p90_count)))
    denom = max(1e-6, (l90 - l50))
    k = 2.2 / denom
    z = (lx - l50) * k
    return 1.0 / (1.0 + math.exp(-z))


def _base_wellness_score(
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
) -> int:
    """Single hazard → wellness model (NYC-calibrated percentiles, inverted)."""
    crime_p = _percentile_from_count(crime_count, median_count=8, p90_count=42)
    reports_p = _percentile_from_count(reports_count, median_count=15, p90_count=65)
    permits_p = _percentile_from_count(permit_count, median_count=1, p90_count=7)
    evict_p = _percentile_from_count(eviction_count, median_count=0.5, p90_count=3)

    hazard_01 = (
        (0.40 * crime_p)
        + (0.26 * reports_p)
        + (0.14 * permits_p)
        + (0.20 * evict_p)
    )
    wellness = int(round(max(0.0, min(100.0, 100.0 - hazard_01 * 100.0))))
    # NYC realism: dense city baseline, not suburb scoring.
    return max(0, wellness - 5)


def _apply_311_adjustment(
    wellness: int,
    *,
    crime_count: int,
    reports_count: int,
) -> int:
    """One 311 path — extra penalty when complaint volume is high but crime is quiet."""
    if reports_count >= _HIGH_311_REPORTS_THRESHOLD and crime_count < 8:
        excess = reports_count - _HIGH_311_REPORTS_THRESHOLD
        penalty = min(24, int(4.5 * math.log1p(excess / 45)))
        return max(0, wellness - penalty)
    if reports_count >= _ELEVATED_311_REPORTS_THRESHOLD and crime_count < 5:
        excess = reports_count - _ELEVATED_311_REPORTS_THRESHOLD
        penalty = min(12, int(2.5 * math.log1p(excess / 90)))
        return max(0, wellness - penalty)
    return wellness


def _apply_safety_caps(
    wellness: int,
    *,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    capped: bool,
) -> int:
    """Soft ceilings for serious signals — avoids stacking with duplicate penalties."""
    score = wellness
    if crime_count >= 10:
        score = min(score, 38)
    elif crime_count >= 3:
        score = min(score, 50)
    elif crime_count >= 1:
        score = min(score, 58)

    if eviction_count >= 2:
        score = min(score, 44)
    elif eviction_count >= 1:
        score = min(score, 54)

    if permit_count >= 4:
        score = min(score, 52)
    elif permit_count >= 2:
        score = min(score, 62)

    if capped:
        score = min(score, 74)

    return max(0, score)


def _label_for_score(
    score: int,
    *,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
) -> tuple[str, str]:
    """Map score to label; gate Excellent/Outstanding on multiple clean signals."""
    risk_level = "MODERATE"
    risk_label = "Average"
    for ceiling, level, label in _LABEL_BANDS:
        if score <= ceiling:
            risk_level, risk_label = level, label
            break

    # Empty radius is often sparse data, not proof of excellence.
    all_clear = (
        crime_count == 0
        and reports_count == 0
        and permit_count == 0
        and eviction_count == 0
    )
    if all_clear and risk_label in ("Excellent", "Outstanding", "Great"):
        risk_level, risk_label = "LOW", "Very Good"

    # Top tiers require more than one clean signal.
    if risk_label in ("Excellent", "Outstanding"):
        if crime_count > 0 or eviction_count > 0 or reports_count >= 120 or permit_count >= 3:
            risk_level, risk_label = "LOW", "Great"
        elif reports_count >= 40 or permit_count >= 1:
            risk_level, risk_label = "LOW", "Excellent" if score >= 86 else "Great"

    return risk_level, risk_label


def _format_count(n: int) -> str:
    return f"{int(n):,}"


def _driver_phrase(
    kind: str,
    count: int,
) -> tuple[float, str] | None:
    """Return (priority, plain phrase) for a signal worth mentioning."""
    if kind == "crime":
        if count >= 10:
            return (100, f"{_format_count(count)} NYPD crime reports")
        if count >= 3:
            return (80, f"{_format_count(count)} crime reports")
        if count >= 1:
            word = "report" if count == 1 else "reports"
            return (60, f"{count} crime {word}")
    elif kind == "evictions":
        if count >= 2:
            return (85, f"{count} eviction filings")
        if count >= 1:
            return (65, "1 eviction filing")
    elif kind == "311":
        if count >= _HIGH_311_REPORTS_THRESHOLD:
            return (75, f"{_format_count(count)} neighbor 311 complaints")
        if count >= _ELEVATED_311_REPORTS_THRESHOLD:
            return (55, f"{_format_count(count)} 311 complaints from neighbors")
        if count >= 40:
            return (35, f"{_format_count(count)} 311 complaints")
    elif kind == "permits":
        if count >= 4:
            return (50, f"{count} active construction permits")
        if count >= 2:
            return (30, f"{count} construction permits")
        if count >= 1:
            return (20, "1 active construction permit")
    return None


def _join_phrases(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _build_risk_description(
    wellness: int,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    *,
    capped: bool,
) -> str:
    """One or two plain sentences on what's driving the score."""
    scan_mi = city_data.get_scan_radius_miles()
    mi_label = f"~{scan_mi:g} mile{'s' if abs(scan_mi - 1) > 0.01 else ''}"

    drivers: list[tuple[float, str]] = []
    for kind, count in (
        ("crime", crime_count),
        ("evictions", eviction_count),
        ("311", reports_count),
        ("permits", permit_count),
    ):
        phrase = _driver_phrase(kind, count)
        if phrase:
            drivers.append(phrase)

    all_clear = (
        crime_count == 0
        and reports_count == 0
        and permit_count == 0
        and eviction_count == 0
    )

    if all_clear:
        if wellness >= 70:
            sentence = (
                f"We didn't find crime, evictions, permits, or 311 complaints within {mi_label}. "
                "Quiet on paper — but sparse data doesn't prove much."
            )
        else:
            sentence = (
                f"Nothing major in our records within {mi_label}. "
                "That isn't the same as a clean bill of health."
            )
    elif not drivers:
        sentence = f"Not much turned up within {mi_label} — mostly normal NYC background noise."
    else:
        drivers.sort(key=lambda item: -item[0])
        joined = _join_phrases([label for _, label in drivers[:2]])
        sentence = f"{joined} within {mi_label}."

    if capped:
        return sentence + " Dense areas may hit our count cap."
    return sentence


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
    v2 wellness scoring: one percentile model + one 311 adjustment + soft caps + gated labels.
    `danger_score` is 0–100 where **100 is best**.
    """
    capped = crime_capped or reports_capped or permits_capped or evictions_capped

    wellness = _base_wellness_score(crime_count, reports_count, permit_count, eviction_count)
    wellness = _apply_311_adjustment(
        wellness, crime_count=crime_count, reports_count=reports_count
    )
    wellness = _apply_safety_caps(
        wellness,
        crime_count=crime_count,
        reports_count=reports_count,
        permit_count=permit_count,
        eviction_count=eviction_count,
        capped=capped,
    )
    risk_level, risk_label = _label_for_score(
        wellness,
        crime_count=crime_count,
        reports_count=reports_count,
        permit_count=permit_count,
        eviction_count=eviction_count,
    )

    risk_description = _build_risk_description(
        wellness,
        crime_count,
        reports_count,
        permit_count,
        eviction_count,
        capped=capped,
    )

    return {
        "danger_score": wellness,
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
