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

# NYC ~2 mi calibration for banner copy (absolute 311 counts are much higher at 2 mi).
_BANNER_CALIB: dict[str, tuple[float, float]] = {
    "crime": (8, 42),
    "311": (500, 2200),
    "permits": (1, 7),
    "evictions": (0.5, 3),
}
_BANNER_WEIGHTS: dict[str, float] = {
    "crime": 0.40,
    "311": 0.26,
    "permits": 0.14,
    "evictions": 0.20,
}

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


def _311_reports_label(count: int) -> str:
    if count == 1:
        return "1 city report"
    return f"{_format_count(count)} city reports"


def _banner_severity(percentile: float) -> str:
    if percentile >= 0.85:
        return "heavy"
    if percentile >= 0.58:
        return "moderate"
    if percentile >= 0.32:
        return "some"
    return "low"


def _factor_banner_phrase(kind: str, severity: str, count: int) -> tuple[str, str]:
    """Return (reason label, count snippet) for one factor."""
    if kind == "crime":
        count_snip = f"{_format_count(count)} NYPD reports" if count >= 10 else (
            f"{count} NYPD report" if count == 1 else f"{count} NYPD reports"
        )
        labels = {
            "heavy": "High crime nearby",
            "moderate": "Crime nearby",
            "some": "Some crime nearby",
            "low": "Low crime",
        }
        return labels[severity], count_snip
    if kind == "311":
        labels = {
            "heavy": "Heavy 311 (city reports) nearby",
            "moderate": "Moderate 311 (city reports) nearby",
            "some": "Some 311 (city reports) nearby",
            "low": "Low 311 (city reports)",
        }
        return labels[severity], _311_reports_label(count)
    if kind == "permits":
        word = "permit" if count == 1 else "permits"
        count_snip = f"{count} {word}"
        labels = {
            "heavy": "Heavy construction nearby",
            "moderate": "Construction nearby",
            "some": "Some construction nearby",
            "low": "Low construction",
        }
        return labels[severity], count_snip
    if kind == "evictions":
        count_snip = "1 filing" if count == 1 else f"{count} filings"
        labels = {
            "heavy": "Heavy evictions nearby",
            "moderate": "Evictions nearby",
            "some": "Some evictions nearby",
            "low": "Low evictions",
        }
        return labels[severity], count_snip
    return "", ""


def _banner_factor_stats(
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
) -> list[tuple[float, str, str, str, float]]:
    """Weighted impact, kind, reason, count snippet, percentile — highest impact first."""
    counts = {
        "crime": crime_count,
        "311": reports_count,
        "permits": permit_count,
        "evictions": eviction_count,
    }
    rows: list[tuple[float, str, str, str, float]] = []
    for kind, count in counts.items():
        median, p90 = _BANNER_CALIB[kind]
        percentile = _percentile_from_count(count, median_count=median, p90_count=p90)
        severity = _banner_severity(percentile)
        reason, count_snip = _factor_banner_phrase(kind, severity, count)
        impact = _BANNER_WEIGHTS[kind] * percentile
        rows.append((impact, kind, reason, count_snip, percentile))
    rows.sort(key=lambda row: (-row[0], -row[4]))
    return rows


def _build_risk_description(
    wellness: int,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    *,
    capped: bool,
) -> str:
    """One short sentence tied to what actually moves the score for this address."""
    scan_mi = city_data.get_scan_radius_miles()
    mi_label = f"~{scan_mi:g} mi"

    all_clear = (
        crime_count == 0
        and reports_count == 0
        and permit_count == 0
        and eviction_count == 0
    )
    if all_clear:
        sentence = f"No crime, 311 (city reports), evictions, or permits in {mi_label}."
    else:
        stats = _banner_factor_stats(
            crime_count, reports_count, permit_count, eviction_count
        )
        counts = {
            "crime": crime_count,
            "311": reports_count,
            "permits": permit_count,
            "evictions": eviction_count,
        }
        problems = [
            row for row in stats if _banner_severity(row[4]) in ("heavy", "moderate", "some")
        ]
        # Prefer factors that materially affect the score; fall back to top weighted signal.
        notable = [row for row in problems if row[0] >= 0.12 or _banner_severity(row[4]) != "low"]
        if not notable and problems:
            notable = problems[:1]
        elif not notable:
            notable = stats[:1]

        def _display_rank(row: tuple[float, str, str, str, float]) -> float:
            impact, kind, _, _, percentile = row
            rank = impact
            count = counts[kind]
            if kind == "crime" and count >= 3:
                rank += 0.14
            elif kind == "evictions" and count >= 1:
                rank += 0.12
            elif kind == "permits" and count >= 3:
                rank += 0.08
            elif kind == "311" and _banner_severity(percentile) == "heavy":
                rank += 0.05
            return rank

        notable.sort(key=lambda row: (-_display_rank(row), -row[4]))

        lows = [
            row
            for row in stats
            if _banner_severity(row[4]) == "low"
            and (
                counts[row[1]] > 0
                or row[1] in ("crime", "311")
            )
        ]
        if wellness >= 55 and len(problems) <= 1 and (
            not problems or _banner_severity(problems[0][4]) in ("some", "low")
        ):
            if len(lows) >= 2:
                sentence = (
                    f"{lows[0][2].replace(' nearby', '')} and "
                    f"{lows[1][2].replace(' nearby', '').lower()} in {mi_label}."
                )
            elif lows:
                sentence = f"{lows[0][2]} in {mi_label}."
            else:
                sentence = f"Nothing major in {mi_label}."
        elif len(notable) == 1:
            _, _, reason, count_snip, _ = notable[0]
            sentence = f"{reason} — {count_snip} in {mi_label}."
        else:
            top = notable[:2]
            reasons = " + ".join(row[2] for row in top)
            counts = ", ".join(row[3] for row in top)
            sentence = f"{reasons} — {counts} in {mi_label}."

    if capped:
        return sentence + " Count cap may apply in dense areas."
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
