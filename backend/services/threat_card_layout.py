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

# Percentile anchors for wellness scoring (shared by score + banner reasoning).
_SCORE_CALIB: dict[str, tuple[float, float]] = {
    "crime": (8, 42),
    "311": (15, 65),
    "permits": (1, 7),
    "evictions": (0.5, 3),
}
_SCORE_WEIGHTS: dict[str, float] = {
    "crime": 0.40,
    "311": 0.26,
    "permits": 0.14,
    "evictions": 0.20,
}
_MIN_DRAG_TO_MENTION = 4.0
# Banner-only 2 mi NYC calibration (score math uses _SCORE_CALIB unchanged).
_BANNER_DRAG_CALIB: dict[str, tuple[float, float]] = {
    "area_safety": (8, 42),
    "311": (2000, 4000),
    "permits": (2, 8),
    "evictions": (0.5, 3),
    "noise": (180, 550),
}
_BANNER_WEIGHTS: dict[str, float] = {
    "area_safety": 0.40,
    "311": 0.26,
    "permits": 0.14,
    "evictions": 0.20,
    "noise": 0.11,
}
_MIN_FACTOR_PERCENTILE = 0.32
# Hide routine 311 when another factor is clearly more notable for this address.
_SUPPRESS_311_BELOW_PERCENTILE = 0.42

_FACTOR_LABELS: dict[str, tuple[str, str, str]] = {
    "area_safety": ("area safety", "crime report", "crime reports"),
    "311": ("city reports", "city report", "city reports"),
    "permits": ("construction", "permit", "permits"),
    "evictions": ("evictions", "filing", "filings"),
    "noise": ("noise", "complaint", "complaints"),
}

# v2 label bands (wellness score 0–100, higher is better).
_LABEL_BANDS: list[tuple[int, str, str]] = [
    (15, "EXTREME", "Terrible"),
    (28, "HIGH", "Bad"),
    (48, "MODERATE", "Average"),
    (62, "LOW", "Good"),
    (75, "LOW", "Very Good"),
    (83, "LOW", "Great"),
    (92, "LOW", "Excellent"),
    (100, "LOW", "Outstanding"),
]

# Order matches the UI carousel / original Gemini system prompt.
CARD_SPECS: list[dict[str, Any]] = [
    {
        "id": "high_churn",
        "emoji": "🏃‍♂️",
        "title": "TENANT CHURN",
        "subtitle": "Historical turnover data from NYC court records.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "police_calls",
        "emoji": "🚓",
        "title": "POLICE CALLS",
        "subtitle": "NYPD dispatch activity in the area.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "area_safety",
        "emoji": "🛡️",
        "title": "AREA SAFETY",
        "subtitle": "Property and violent crime density.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "tenant_warnings",
        "emoji": "🗣️",
        "title": "TENANT WARNINGS",
        "subtitle": "HPD violation data not ingested; verify on NYC HPD portal.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "demolitions",
        "emoji": "🚧",
        "title": "CONSTRUCTION & DEMOLITIONS",
        "subtitle": "DOB active permits and 311 building complaints.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "noise_schedule",
        "emoji": "🚛",
        "title": "NOISE SCHEDULE",
        "subtitle": "Commercial and municipal noise sources.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "flight_path",
        "emoji": "✈️",
        "title": "FLIGHT NOISE",
        "subtitle": "Aircraft exposure vs typical NYC blocks (ADS-B).",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "reports_311",
        "emoji": "🐀",
        "title": "311 REPORTS",
        "subtitle": "City service complaints from neighbors.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
    {
        "id": "oven_effect",
        "emoji": "☀️",
        "title": "OVEN EFFECT",
        "subtitle": "Sun exposure and AC cost risk.",
        "border_color": "#64748b",
        "text_color": "#94a3b8",
    },
]


def ordered_card_ids() -> list[str]:
    return [c["id"] for c in CARD_SPECS]


def filter_threat_cards_for_exposure(
    cards: list[dict[str, Any]],
    *,
    show_flight_feature: bool,
) -> list[dict[str, Any]]:
    """Hide the flight card when exposure is typical for NYC (not renter-actionable)."""
    if show_flight_feature:
        return cards
    return [c for c in cards if c.get("id") != "flight_path"]


@dataclass(frozen=True)
class CardChromeContext:
    crime_count: int = 0
    reports_count: int = 0
    permit_count: int = 0
    eviction_count: int = 0
    noise_count: int = 0
    construction_311_count: int = 0
    has_flight_path: bool = False
    show_flight_feature: bool = False


# Muted severity palette — matches wellness banner: emerald (clear) / amber (watch) / rose (elevated).
_SEVERITY_CHROME: dict[str, tuple[str, str]] = {
    "quiet": ("#059669", "#6ee7b7"),
    "watch": ("#d97706", "#fbbf24"),
    "elevated": ("#f43f5e", "#fda4af"),
}


def _card_severity(card_id: str, ctx: CardChromeContext) -> str:
    """Return quiet | watch | elevated for this card's primary signal."""
    if card_id == "high_churn":
        return "elevated" if ctx.eviction_count > 0 else "quiet"
    if card_id == "police_calls":
        return "elevated" if ctx.crime_count > 0 else "quiet"
    if card_id == "area_safety":
        return "watch" if ctx.crime_count > 0 else "quiet"
    if card_id == "tenant_warnings":
        return "quiet"
    if card_id == "demolitions":
        has_activity = ctx.permit_count > 0 or ctx.construction_311_count > 0
        return "watch" if has_activity else "quiet"
    if card_id == "noise_schedule":
        return "watch" if ctx.noise_count > 0 else "quiet"
    if card_id == "flight_path":
        if not ctx.show_flight_feature:
            return "quiet"
        return "elevated" if ctx.has_flight_path else "watch"
    if card_id == "reports_311":
        if ctx.reports_count >= _HIGH_311_REPORTS_THRESHOLD:
            return "elevated"
        if ctx.reports_count > 0:
            return "watch"
        return "quiet"
    if card_id == "oven_effect":
        return "quiet"
    return "quiet"


def resolve_card_colors(card_id: str, ctx: CardChromeContext) -> tuple[str, str]:
    """Border + subtitle colors from muted severity tier."""
    return _SEVERITY_CHROME[_card_severity(card_id, ctx)]


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
    drags, _ = _score_factor_drags(crime_count, reports_count, permit_count, eviction_count)
    hazard_01 = sum(drags.values()) / 100.0
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


def _volume_word(percentile: float) -> str:
    if percentile >= 0.58:
        return "A lot of"
    if percentile >= 0.32:
        return "Some"
    return "Little"


def _factor_percentile(kind: str, count: int) -> float:
    median, p90 = _BANNER_DRAG_CALIB[kind]
    return _percentile_from_count(count, median_count=median, p90_count=p90)


def _factor_banner_line(kind: str, count: int, *, percentile: float | None = None) -> str:
    """Qualitative label first, then the exact count (2 mi banner calibration)."""
    p = percentile if percentile is not None else _factor_percentile(kind, count)
    volume = _volume_word(p)
    label, singular, plural = _FACTOR_LABELS[kind]

    if kind == "area_safety":
        n = _format_count(count) if count >= 10 else str(count)
        word = singular if count == 1 else plural
        if p < 0.58:
            return f"Area safety — {n} {word}"
        return f"{volume} area safety concerns — {n} {word}"

    if kind == "311":
        word = singular if count == 1 else plural
        if p < 0.58:
            return f"City reports — {_format_count(count)} {word}"
        return f"{volume} 311 reports — {_format_count(count)} {word}"

    if kind == "noise":
        word = singular if count == 1 else plural
        n = _format_count(count) if count >= 10 else str(count)
        if p < 0.58:
            return f"Noise complaints — {n} {word}"
        return f"{volume} noise complaints — {n} {word}"

    word = singular if count == 1 else plural
    return f"{volume} {label} — {count} {word}"


def _score_factor_drags(
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
) -> tuple[dict[str, float], dict[str, float]]:
    """Points each municipal factor pulls off a perfect 100 (same math as scoring)."""
    counts = {
        "crime": crime_count,
        "311": reports_count,
        "permits": permit_count,
        "evictions": eviction_count,
    }
    percentiles: dict[str, float] = {}
    drags: dict[str, float] = {}
    for kind, count in counts.items():
        median, p90 = _SCORE_CALIB[kind]
        percentile = _percentile_from_count(count, median_count=median, p90_count=p90)
        percentiles[kind] = percentile
        drags[kind] = _SCORE_WEIGHTS[kind] * percentile * 100.0
    return drags, percentiles


def _cap_explanation(
    score_before_caps: int,
    score_after_caps: int,
    crime_count: int,
    permit_count: int,
    eviction_count: int,
    *,
    capped: bool,
) -> str | None:
    """Short note when a safety or sample cap limited the score."""
    if score_after_caps >= score_before_caps:
        return None

    notes: list[str] = []
    if crime_count >= 10 and score_after_caps <= 38:
        notes.append("high crime cap")
    elif crime_count >= 3 and score_after_caps <= 50:
        notes.append("crime cap")
    elif crime_count >= 1 and score_after_caps <= 58:
        notes.append("crime cap")

    if eviction_count >= 2 and score_after_caps <= 44:
        notes.append("eviction cap")
    elif eviction_count >= 1 and score_after_caps <= 54:
        notes.append("eviction cap")

    if permit_count >= 4 and score_after_caps <= 52:
        notes.append("construction cap")
    elif permit_count >= 2 and score_after_caps <= 62:
        notes.append("construction cap")

    if capped and score_after_caps <= 74:
        notes.append("sample count cap")

    if not notes:
        return "Capped by a safety limit."
    if len(notes) == 1:
        return f"Capped due to {notes[0]}."
    return f"Capped due to {' and '.join(notes[:2])}."


def _pick_banner_drivers(
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    noise_count: int,
    extra_311_drag: float,
) -> list[tuple[str, int, float]]:
    """
    Pick 1–2 factors that best explain this address vs typical NYC ~2 mi blocks.

    Rank by how elevated each signal is for its own category (percentile), not raw
    311 volume — so area safety, noise, construction, or evictions can lead when they stand out.
    """
    counts = {
        "area_safety": crime_count,
        "311": reports_count,
        "permits": permit_count,
        "evictions": eviction_count,
        "noise": noise_count,
    }
    candidates: list[tuple[str, int, float, float]] = []
    for kind, count in counts.items():
        if count <= 0:
            continue
        percentile = _factor_percentile(kind, count)
        if percentile < _MIN_FACTOR_PERCENTILE:
            continue
        tie_break = _BANNER_WEIGHTS[kind] * percentile
        candidates.append((kind, count, percentile, tie_break))

    if not candidates:
        return []

    non_311 = [row for row in candidates if row[0] != "311"]
    if non_311 and any(row[2] >= _SUPPRESS_311_BELOW_PERCENTILE for row in non_311):
        candidates = [
            row
            for row in candidates
            if not (
                row[0] == "311"
                and row[2] < _SUPPRESS_311_BELOW_PERCENTILE
                and extra_311_drag < _MIN_DRAG_TO_MENTION
            )
        ]

    if not candidates:
        return []

    candidates.sort(key=lambda row: (-row[2], -row[3]))
    top_kind, top_count, top_p, _ = candidates[0]
    drivers: list[tuple[str, int, float]] = [(top_kind, top_count, top_p)]

    if len(candidates) > 1:
        second_kind, second_count, second_p, _ = candidates[1]
        if second_p >= top_p - 0.14:
            drivers.append((second_kind, second_count, second_p))

    return drivers


def _build_risk_description(
    wellness: int,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    noise_count: int,
    *,
    capped: bool,
) -> tuple[str, str | None]:
    """Explain the wellness score using the same inputs and adjustments as scoring."""
    scan_mi = city_data.get_scan_radius_miles()
    mi_label = f"~{scan_mi:g} mi"
    counts = {
        "area_safety": crime_count,
        "311": reports_count,
        "permits": permit_count,
        "evictions": eviction_count,
        "noise": noise_count,
    }

    all_clear = all(counts[k] == 0 for k in counts)
    if all_clear:
        return (
            (
                f"No area safety issues, city reports, evictions, construction permits, "
                f"or noise complaints in {mi_label}."
            ),
            None,
        )

    score_after_base = _base_wellness_score(
        crime_count, reports_count, permit_count, eviction_count
    )
    score_after_311 = _apply_311_adjustment(
        score_after_base,
        crime_count=crime_count,
        reports_count=reports_count,
    )
    extra_311_drag = float(score_after_base - score_after_311)
    score_after_caps = _apply_safety_caps(
        score_after_311,
        crime_count=crime_count,
        reports_count=reports_count,
        permit_count=permit_count,
        eviction_count=eviction_count,
        capped=capped,
    )

    drivers = _pick_banner_drivers(
        crime_count,
        reports_count,
        permit_count,
        eviction_count,
        noise_count,
        extra_311_drag,
    )

    cap_note = _cap_explanation(
        score_after_311,
        score_after_caps,
        crime_count,
        permit_count,
        eviction_count,
        capped=capped,
    )

    if not drivers:
        sentence = f"Nothing major in {mi_label}."
    elif len(drivers) == 1:
        kind, count, percentile = drivers[0]
        sentence = f"{_factor_banner_line(kind, count, percentile=percentile)} in {mi_label}."
    else:
        parts = [
            _factor_banner_line(kind, count, percentile=percentile)
            for kind, count, percentile in drivers
        ]
        sentence = f"{' and '.join(parts)} in {mi_label}."

    primary_driver = drivers[0][0] if drivers else None
    if cap_note:
        return f"{sentence} {cap_note}", primary_driver
    return sentence, primary_driver


def compute_risk_from_counts(
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int = 0,
    noise_count: int = 0,
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

    risk_description, banner_driver = _build_risk_description(
        wellness,
        crime_count,
        reports_count,
        permit_count,
        eviction_count,
        noise_count,
        capped=capped,
    )

    return {
        "danger_score": wellness,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "risk_description": risk_description,
        "banner_driver": banner_driver,
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
        severity = _card_severity(cid, ctx)
        out.append({
            **spec,
            "border_color": border_color,
            "text_color": text_color,
            "severity_level": severity,
            "bullets": b,
        })
    return out
