"""
Google Gemini AI — writes threat-card bullets only. Card chrome (emoji, colors,
titles) and danger score come from Python (services.threat_card_layout).
"""

import os
import re
import json
import time
import asyncio
import hashlib
import logging
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from models.schemas import Coordinate, FlightPath, LogisticsCard
from services import city_data
from services.threat_card_layout import (
    cards_from_specs_and_bullets,
    compute_risk_from_counts,
    ordered_card_ids,
)

logger = logging.getLogger(__name__)

# Bump this when bullet formatting / merge rules change so in-memory caches don't
# serve stale card text across deploys.
_ANALYSIS_CACHE_VERSION = "2026-06-18-fact-lock-all-cards"

# Allow override via env (Railway / local).
# Default raised so Gemini can finish during end-to-end debugging.
# Set GEMINI_TIMEOUT_SECONDS=0 (or negative) to disable the asyncio wait_for guard.
_GEMINI_TIMEOUT_RAW = os.getenv("GEMINI_TIMEOUT_SECONDS", "300").strip()
if not _GEMINI_TIMEOUT_RAW:
    _GEMINI_TIMEOUT = 300.0
else:
    _GEMINI_TIMEOUT = float(_GEMINI_TIMEOUT_RAW)
_GEMINI_TIMEOUT_REPORT: float | None = None if _GEMINI_TIMEOUT <= 0 else _GEMINI_TIMEOUT
_GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096"))

_PLACEHOLDER_GEMINI_KEYS = frozenset(
    {
        "",
        "your_gemini_api_key_here",
        "your_google_ai_api_key_here",
    }
)


def _effective_gemini_key(raw: str | None = None) -> str:
    """Strip key / BOM; treat empty and common .env.example placeholders as unset."""
    s = (raw if raw is not None else (os.getenv("GEMINI_API_KEY") or "")).strip().lstrip("\ufeff")
    if not s:
        return ""
    lower = s.lower()
    if lower in _PLACEHOLDER_GEMINI_KEYS or "your_gemini_api_key" in lower:
        return ""
    if s.startswith("<") and s.endswith(">"):
        return ""
    return s


def _sanitize_error_detail(text: str, max_len: int = 240) -> str:
    """
    Return a short, user-safe error snippet for JSON responses.
    Never echo API keys (defense-in-depth; keys shouldn't appear in exceptions anyway).
    """
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return ""
    # Redact common secret-ish patterns if they ever leak through upstream errors.
    s = re.sub(r"(?i)(api[_-]?key|token)\s*[:=]\s*\S+", r"\1=<redacted>", s)
    return s[:max_len]


def _classify_gemini_error(e: Exception) -> tuple[str, str]:
    """
    Map exceptions to (kind, detail) where kind is a coarse category for clients.
    detail is sanitized and safe to return in JSON.
    """
    detail = _sanitize_error_detail(str(e))

    # google.api_core.GoogleAPICallError has structured fields
    if isinstance(e, google_exceptions.GoogleAPICallError):
        code = getattr(e, "grpc_status_code", None) or getattr(e, "code", None)
        reason = getattr(e, "reason", None) or ""
        msg = f"{reason} {detail}".strip().lower()

        if isinstance(e, google_exceptions.NotFound) or "not found" in msg or "was not found" in msg or "404" in msg:
            return "not_found", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.PermissionDenied) or "permission denied" in msg or "403" in msg:
            return "auth", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.ResourceExhausted) or "resource exhausted" in msg or "429" in msg:
            return "quota", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.InvalidArgument) or "invalid argument" in msg or "400" in msg:
            return "bad_request", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.Unauthenticated) or "unauthenticated" in msg or "401" in msg:
            return "auth", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.ServiceUnavailable) or "503" in msg or "unavailable" in msg:
            return "unavailable", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.DeadlineExceeded) or "deadline exceeded" in msg:
            return "deadline", _sanitize_error_detail(f"{reason} {detail}".strip())

        if code is not None:
            return "api_error", _sanitize_error_detail(f"{type(e).__name__} code={code} {detail}".strip())

        return "api_error", _sanitize_error_detail(f"{type(e).__name__} {detail}".strip())

    # Non-Google errors / wrapped errors
    msg = detail.lower()
    if isinstance(e, json.JSONDecodeError) or "jsondecodeerror" in type(e).__name__.lower():
        return "json_parse", _sanitize_error_detail(str(e))
    if "could not parse json" in msg or "could not parse" in msg:
        if "truncat" in msg or "unterminated" in msg or "unexpected end" in msg:
            return "truncated_output", detail
        return "json_parse", detail
    if "empty gemini response" in msg or "blocked" in msg or "no candidates" in msg:
        return "empty", detail
    if "deadline exceeded" in msg:
        return "deadline", detail
    if "ssl" in msg or "certificate" in msg:
        return "tls", detail
    if "timed out" in msg or "timeout" in msg:
        # Should normally be asyncio.TimeoutError, but keep a fallback for library wording
        return "timeout", detail
    if "not found" in msg or "was not found" in msg or "404" in msg:
        return "not_found", detail
    if "permission denied" in msg or "403" in msg or "invalid api key" in msg or "api key not valid" in msg:
        return "auth", detail
    if "429" in msg or "resource exhausted" in msg or "quota" in msg or "rate limit" in msg:
        return "quota", detail
    if "401" in msg or "unauthenticated" in msg:
        return "auth", detail
    if "400" in msg or "invalid argument" in msg:
        return "bad_request", detail
    if "503" in msg or "service unavailable" in msg:
        return "unavailable", detail

    return "unknown", detail

# Simple in-memory cache: address hash → analysis result
_analysis_cache: dict[str, dict] = {}

BULLETS_SYSTEM_PROMPT = """You are DwellSense, a renter-focused real estate forensics assistant.
You receive a data brief about one NYC address. Write ONLY the nine threat-card bullet lists.

Rules:
- Write in plain English a renter can understand.
- Each bullet must be short (max ~80 characters). One sentence.
- Use the exact numbers in the brief when possible. Never invent stats.
- high_churn = eviction filings only. Never mention construction permits there.
- demolitions = DOB active permits plus 311 construction complaints (separate counts in brief).
- noise_schedule = 311 noise complaints only (SR311_NOISE_30D), not all 311.
- tenant_warnings = we do not have HPD violation data; do not claim violations at this address.
- oven_effect = general orientation guidance only; not from NYC Open Data.
- flight_path = only when FLIGHT line says a path exists inside the scan radius.
- If the brief indicates there are zero recent items for a card, the 3rd bullet must be:
  "No recent reports!"
- No markdown. No HTML. No nested JSON inside strings.

Return ONLY valid JSON (no markdown fences, no extra text) in this exact shape:
{
  "bullets": {
    "high_churn": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
    "police_calls": ["...", "...", "..."],
    "area_safety": ["...", "...", "..."],
    "tenant_warnings": ["...", "...", "..."],
    "demolitions": ["...", "...", "..."],
    "noise_schedule": ["...", "...", "..."],
    "flight_path": ["...", "...", "..."],
    "reports_311": ["...", "...", "..."],
    "oven_effect": ["...", "...", "..."]
  }
}

You must include all nine keys exactly as shown. Each value must be an array of exactly three strings.
"""


def _summarize_crime(data: list[dict]) -> str:
    if not data:
        return "count=0"
    types: dict[str, int] = {}
    for row in data:
        t = row.get("crime_type", "Unknown")
        types[t] = types.get(t, 0) + 1
    top = sorted(types.items(), key=lambda x: x[1], reverse=True)[:3]
    top_text = "; ".join([f"{t}:{c}" for t, c in top]) if top else ""
    return f"count={len(data)}; top={top_text}"


def _summarize_311(data: list[dict]) -> str:
    if not data:
        return "count=0"
    types: dict[str, int] = {}
    for row in data:
        t = row.get("complaint_type", "Unknown")
        types[t] = types.get(t, 0) + 1
    top = sorted(types.items(), key=lambda x: x[1], reverse=True)[:3]
    top_text = "; ".join([f"{t}:{c}" for t, c in top]) if top else ""
    return f"count={len(data)}; top={top_text}"


def _summarize_permits(data: list[dict]) -> str:
    if not data:
        return "active_count=0"
    active = [r for r in data if r.get("permit_status", "").lower() in ("issued", "active", "renewed")]
    types: dict[str, int] = {}
    for row in active:
        t = row.get("permit_type", "Unknown")
        types[t] = types.get(t, 0) + 1
    top = sorted(types.items(), key=lambda x: x[1], reverse=True)[:3]
    top_text = "; ".join([f"{t}:{c}" for t, c in top]) if top else ""
    return f"active_count={len(active)}; top={top_text}"


def _count_active_permits(data: list[dict]) -> int:
    if not data:
        return 0
    return sum(1 for r in data if (r.get("permit_status", "") or "").lower() in ("issued", "active", "renewed"))


def _311_blob(row: dict) -> str:
    ctype = str(row.get("complaint_type") or "")
    desc = str(row.get("descriptor") or "")
    return f"{ctype} {desc}".lower()


def _count_311_noise(data: list[dict]) -> int:
    if not data:
        return 0
    keys = ("noise", "loud", "music", "party")
    return sum(1 for row in data if any(k in _311_blob(row) for k in keys))


def _count_311_construction(data: list[dict]) -> int:
    """311 building / construction complaints (distinct from DOB permits)."""
    if not data:
        return 0
    keys = ("construction", "building", "scaffold", "demolition", "crane")
    return sum(1 for row in data if any(k in _311_blob(row) for k in keys))


def _summarize_logistics(logistics: list[LogisticsCard]) -> str:
    if not logistics:
        return "none"
    # Keep it short: only the first few cards (already sorted by importance in places.py)
    parts = []
    for card in logistics[:4]:
        parts.append(f"{card.category}:{card.distance_value}{card.distance_unit}")
    return "; ".join(parts)


def _extract_text_from_response(response) -> str:
    """
    google-generativeai sometimes raises on .text when content is blocked or empty.
    Fall back to walking candidates/parts.
    """
    try:
        t = (response.text or "").strip()
        if t:
            return t
    except (ValueError, AttributeError) as e:
        logger.warning("Gemini response.text unavailable: %s", e)

    try:
        cand = response.candidates[0]
        parts = cand.content.parts
        chunks = []
        for p in parts:
            if hasattr(p, "text") and p.text:
                chunks.append(p.text)
        return "\n".join(chunks).strip()
    except (IndexError, AttributeError, KeyError) as e:
        logger.warning("Could not read Gemini candidates: %s", e)
    return ""


def _parse_ai_json(raw: str) -> dict:
    """Parse JSON from model output; tolerate markdown fences and leading junk."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s else s
        s = s.strip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from Gemini output (first 200 chars): {s[:200]!r}")


def _third_bullet_no_key() -> str:
    return "Add GEMINI_API_KEY to your backend environment for AI-written threat cards."


def _third_bullet_ai_failed() -> str:
    return "AI summary unavailable this scan; counts and map data above are still accurate."


def _no_recent_reports_text() -> str:
    return "No recent reports!"


def _apply_no_recent_reports_bottom_line(
    bullets_by_id: dict[str, list[str]],
    *,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    noise_count: int,
    construction_311_count: int,
    flight_path: FlightPath | None,
) -> dict[str, list[str]]:
    """
    The UI treats the 3rd bullet as the "bottom line".
    If there is no recent data for a card, make that bottom line easy to read.
    """
    out = {k: v[:] for k, v in bullets_by_id.items()}

    def _set(cid: str, has_data: bool) -> None:
        if has_data:
            return
        row = out.get(cid) or ["", "", ""]
        row = _normalize_three(row)
        row[2] = _no_recent_reports_text()
        out[cid] = row

    _set("police_calls", crime_count > 0)
    _set("area_safety", crime_count > 0)
    _set("reports_311", reports_count > 0)
    _set("noise_schedule", noise_count > 0)
    _set("demolitions", permit_count > 0 or construction_311_count > 0)
    _set("high_churn", eviction_count > 0)
    _set("flight_path", flight_path is not None)

    return out

def _normalize_three(row: list[str] | None) -> list[str]:
    if not row:
        return ["", "", ""]
    b = [str(x).strip() if x is not None else "" for x in row[:3]]
    while len(b) < 3:
        b.append("")
    return b


def _fallback_bullets_by_id(
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    bullet_extra: str,
) -> dict[str, list[str]]:
    """Template bullets when Gemini is off or a card fails validation."""
    crime_bottom = _no_recent_reports_text() if crime_count == 0 else bullet_extra
    reports_bottom = _no_recent_reports_text() if reports_count == 0 else bullet_extra
    permits_bottom = _no_recent_reports_text() if permit_count == 0 else bullet_extra
    evictions_bottom = _no_recent_reports_text() if eviction_count == 0 else bullet_extra
    return {
        "high_churn": [
            f"{eviction_count} eviction filing(s) in scan radius." if eviction_count else "No eviction filings in scan radius.",
            "Turnover risk is based on housing-court records only.",
            evictions_bottom,
        ],
        "police_calls": [
            f"{crime_count} NYPD complaint(s) in the last 30 days.",
            "See crime pins on the threat map.",
            crime_bottom,
        ],
        "area_safety": [
            f"{crime_count} crime report(s) within the scan radius." if crime_count else "No NYPD crime reports in the scan radius.",
            "Safety view uses the same NYPD Open Data feed as the map.",
            crime_bottom,
        ],
        "tenant_warnings": [
            "HPD housing-violation records are not loaded in this scan.",
            "Check NYC HPD online for this building's violation history.",
            bullet_extra,
        ],
        "demolitions": [
            f"{permit_count} active DOB permit(s) in scan radius.",
            "Map may also show 311 building/construction complaints separately.",
            permits_bottom,
        ],
        "noise_schedule": [
            "311 noise complaints in the scan radius.",
            "Commercial loading and traffic can add off-hours noise.",
            reports_bottom,
        ],
        "flight_path": [
            "Flight path analysis uses ADS-B when available.",
            "Only paths within the scan radius are drawn on the map.",
            bullet_extra,
        ],
        "reports_311": [
            f"{reports_count} 311 reports filed nearby.",
            "Primary complaints visible on map.",
            reports_bottom,
        ],
        "oven_effect": [
            "Unit orientation affects afternoon heat and AC costs.",
            "Ask which way windows face before signing a lease.",
            "General rental tip — not sourced from NYC Open Data.",
        ],
    }


def _merge_bullets_with_fallback(
    template: dict[str, list[str]],
    gemini: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Prefer Gemini strings; fall back per card if a row is empty or too thin."""
    out: dict[str, list[str]] = {}
    for cid in ordered_card_ids():
        g = _normalize_three(gemini.get(cid) if isinstance(gemini.get(cid), list) else None)
        nonempty = sum(1 for x in g if x.strip())
        if nonempty >= 2:
            out[cid] = g
        else:
            out[cid] = template[cid][:]
    return out


def _enforce_fact_locked_bullets(
    bullets_by_id: dict[str, list[str]],
    *,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    noise_count: int,
    construction_311_count: int,
    flight_path: FlightPath | None,
    scan_radius_miles: float,
) -> dict[str, list[str]]:
    """
    Reliability guardrail: every card must match municipal / flight data we actually load.
    Gemini prose is overwritten when it could contradict counts or cite unavailable datasets.
    """
    out = {k: _normalize_three(v) for k, v in (bullets_by_id or {}).items()}
    r = scan_radius_miles
    no_data = _no_recent_reports_text()

    # 1. TENANT CHURN — evictions only (never permits / construction).
    if eviction_count <= 0:
        out["high_churn"] = [
            f"No eviction filings found within ~{r:g} miles.",
            "Lower turnover risk on housing-court records in this radius.",
            no_data,
        ]
    else:
        out["high_churn"] = [
            f"{eviction_count} eviction filing(s) within ~{r:g} miles.",
            "Higher turnover can signal landlord or tenancy instability.",
            out.get("high_churn", ["", "", ""])[2] or "",
        ]

    # 2. POLICE CALLS — NYPD crime complaints.
    if crime_count <= 0:
        out["police_calls"] = [
            f"No NYPD complaints in the last 30 days within ~{r:g} miles.",
            "Police-call volume looks low on NYC Open Data for this radius.",
            no_data,
        ]
    else:
        out["police_calls"] = [
            f"{crime_count} NYPD complaint(s) in the last 30 days (~{r:g} mi).",
            "See matching pins on the threat map.",
            out.get("police_calls", ["", "", ""])[2] or "",
        ]

    # 3. AREA SAFETY — same crime feed, safety framing.
    if crime_count <= 0:
        out["area_safety"] = [
            f"No NYPD crime reports within ~{r:g} miles in the last 30 days.",
            "Area looks quieter on official crime data for this scan.",
            no_data,
        ]
    else:
        out["area_safety"] = [
            f"{crime_count} crime report(s) within ~{r:g} miles.",
            "Review crime pins and zone halos on the map.",
            out.get("area_safety", ["", "", ""])[2] or "",
        ]

    # 4. TENANT WARNINGS — HPD violations are not ingested yet.
    out["tenant_warnings"] = [
        "HPD housing-violation data is not included in this scan yet.",
        "Look up this building on the NYC HPD portal before signing.",
        "We do not claim violations without a real HPD feed.",
    ]

    # 5. DEMOLITIONS — DOB active permits + 311 construction complaints.
    parts: list[str] = []
    if permit_count > 0:
        parts.append(f"{permit_count} active DOB permit(s)")
    if construction_311_count > 0:
        parts.append(f"{construction_311_count} 311 building/construction report(s)")
    if parts:
        summary = " and ".join(parts) + f" within ~{r:g} miles."
        out["demolitions"] = [
            summary,
            "Construction pins on the map may be DOB permits or 311 complaints.",
            out.get("demolitions", ["", "", ""])[2] or "",
        ]
    else:
        out["demolitions"] = [
            f"No active DOB permits or 311 construction complaints within ~{r:g} miles.",
            "Nearby construction risk looks lower on city records right now.",
            no_data,
        ]

    # 6. NOISE SCHEDULE — noise-specific 311 only (not all 311).
    if noise_count <= 0:
        out["noise_schedule"] = [
            f"No 311 noise complaints within ~{r:g} miles in the last 30 days.",
            "Off-hours noise may still come from traffic or businesses.",
            no_data,
        ]
    else:
        out["noise_schedule"] = [
            f"{noise_count} 311 noise complaint(s) within ~{r:g} miles.",
            "Check map noise pins and commercial blocks nearby.",
            out.get("noise_schedule", ["", "", ""])[2] or "",
        ]

    # 7. FLIGHT PATH — only paths inside scan radius are returned to the client.
    if flight_path is None:
        out["flight_path"] = [
            f"No aircraft tracks within ~{r:g} miles of this address.",
            "Flight lines appear only when ADS-B passed the scan radius.",
            no_data,
        ]
    else:
        label = (flight_path.label or "Recent flight track").strip()
        if len(label) > 72:
            label = label[:69] + "..."
        closest = flight_path.closest_miles
        closest_txt = f" (closest {closest:.1f} mi)" if closest is not None else ""
        out["flight_path"] = [
            f"Flight activity within ~{r:g} mi{closest_txt}: {label}",
            "Cyan lines on the map are real ADS-B or corridor hints in radius.",
            out.get("flight_path", ["", "", ""])[2] or "",
        ]

    # 8. 311 REPORTS — all 311 in radius.
    if reports_count <= 0:
        out["reports_311"] = [
            f"No 311 service requests within ~{r:g} miles in the last 30 days.",
            "Neighbor complaint volume looks low on NYC Open Data.",
            no_data,
        ]
    else:
        out["reports_311"] = [
            f"{reports_count} 311 report(s) within ~{r:g} miles.",
            "Hover swarm pins on the map for complaint types.",
            out.get("reports_311", ["", "", ""])[2] or "",
        ]

    # 9. OVEN EFFECT — general guidance only (no municipal sun-exposure feed).
    out["oven_effect"] = [
        "Afternoon heat depends on which way the unit faces.",
        "West- and south-facing windows can raise summer AC costs.",
        "General rental tip — not sourced from NYC Open Data.",
    ]

    return out


def _finalize_threat_bullets(
    bullets_by_id: dict[str, list[str]],
    *,
    crime_count: int,
    reports_count: int,
    permit_count: int,
    eviction_count: int,
    noise_count: int,
    construction_311_count: int,
    flight_path: FlightPath | None,
    scan_radius_miles: float,
) -> dict[str, list[str]]:
    stepped = _apply_no_recent_reports_bottom_line(
        bullets_by_id,
        crime_count=crime_count,
        reports_count=reports_count,
        permit_count=permit_count,
        eviction_count=eviction_count,
        noise_count=noise_count,
        construction_311_count=construction_311_count,
        flight_path=flight_path,
    )
    return _enforce_fact_locked_bullets(
        stepped,
        crime_count=crime_count,
        reports_count=reports_count,
        permit_count=permit_count,
        eviction_count=eviction_count,
        noise_count=noise_count,
        construction_311_count=construction_311_count,
        flight_path=flight_path,
        scan_radius_miles=scan_radius_miles,
    )


async def analyze(
    address: str,
    coord: Coordinate,
    crime: list[dict],
    reports_311: list[dict],
    permits: list[dict],
    evictions: list[dict],
    logistics: list[LogisticsCard],
    flight_path: FlightPath | None,
    *,
    crime_capped: bool = False,
    reports_capped: bool = False,
    permits_capped: bool = False,
    evictions_capped: bool = False,
) -> dict:
    """
    Python builds danger score + card chrome; Gemini writes bullets only.
    Falls back to template bullets if Gemini is unavailable.
    """
    crime_count = len(crime)
    reports_count = len(reports_311)
    permit_count = _count_active_permits(permits)
    eviction_count = len(evictions)
    noise_count = _count_311_noise(reports_311)
    construction_311_count = _count_311_construction(reports_311)
    scan_radius_miles = city_data.get_scan_radius_miles()

    raw_gemini_env = (os.getenv("GEMINI_API_KEY") or "").strip()
    gemini_api_key = _effective_gemini_key(raw_gemini_env)

    # Determine pre-call status for no-key / placeholder cases
    if not gemini_api_key:
        if raw_gemini_env:
            _pre_status = "placeholder"
            logger.warning(
                "GEMINI_API_KEY is set but looks like a placeholder or template; Gemini is disabled. "
                "Use a real key from Google AI Studio on the backend (Railway), not the frontend."
            )
        else:
            _pre_status = "no_key"
    else:
        _pre_status = None  # will be set after the Gemini call

    key_fp = hashlib.md5(gemini_api_key.encode()).hexdigest()[:12] if gemini_api_key else "none"
    cache_key = hashlib.md5(
        f"{_ANALYSIS_CACHE_VERSION}:{address}:{crime_count}:{reports_count}:{permit_count}:{eviction_count}:"
        f"n{noise_count}c{construction_311_count}:"
        f"c{int(crime_capped)}r{int(reports_capped)}p{int(permits_capped)}e{int(evictions_capped)}:{key_fp}".encode()
    ).hexdigest()
    if cache_key in _analysis_cache:
        hit = _analysis_cache[cache_key]
        if "gemini_configured" not in hit:
            hit = {**hit, "gemini_configured": bool(gemini_api_key)}
        if "gemini_status" not in hit or "gemini_error_detail" not in hit:
            hit = {
                **hit,
                "gemini_status": None,
                "gemini_latency_ms": None,
                "gemini_timeout_seconds": _GEMINI_TIMEOUT_REPORT,
                "gemini_error_kind": None,
                "gemini_error_detail": None,
            }
        return hit

    risk = compute_risk_from_counts(
        crime_count,
        reports_count,
        permit_count,
        eviction_count,
        crime_capped=crime_capped,
        reports_capped=reports_capped,
        permits_capped=permits_capped,
        evictions_capped=evictions_capped,
    )

    if not gemini_api_key:
        fb = _fallback_bullets_by_id(
            crime_count, reports_count, permit_count, eviction_count, _third_bullet_no_key()
        )
        fb = _finalize_threat_bullets(
            fb,
            crime_count=crime_count,
            reports_count=reports_count,
            permit_count=permit_count,
            eviction_count=eviction_count,
            noise_count=noise_count,
            construction_311_count=construction_311_count,
            flight_path=flight_path,
            scan_radius_miles=scan_radius_miles,
        )
        result = {
            **risk,
            "threat_cards": cards_from_specs_and_bullets(fb),
            "gemini_configured": False,
            "gemini_status": _pre_status,
            "gemini_latency_ms": None,
            "gemini_timeout_seconds": _GEMINI_TIMEOUT_REPORT,
            "gemini_error_kind": None,
            "gemini_error_detail": None,
        }
        _analysis_cache[cache_key] = result
        return result

    gemini_model_name = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(
        model_name=gemini_model_name,
        system_instruction=BULLETS_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=0.35,
            max_output_tokens=_GEMINI_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        ),
    )

    flight_text = (
        f"Flight path: {flight_path.label}"
        if flight_path
        else "No major flight corridor detected near this address."
    )

    prompt = (
        "ADDRESS: " + address + "\n"
        f"COORD: {coord.lat:.5f},{coord.lng:.5f}\n"
        f"CRIME_30D_1MI: {_summarize_crime(crime)}\n"
        f"SR311_30D_1MI: {_summarize_311(reports_311)}\n"
        f"SR311_NOISE_30D: count={noise_count}\n"
        f"SR311_CONSTRUCTION_30D: count={construction_311_count}\n"
        f"PERMITS_90D_1MI: {_summarize_permits(permits)}\n"
        f"EVICTIONS_NEARBY: count={eviction_count}\n"
        f"LOGISTICS: {_summarize_logistics(logistics)}\n"
        f"FLIGHT: {flight_text}\n"
        "\n"
        "Return the 27 bullets JSON only. Use the numbers above; don't invent new stats."
    )

    template_fb = _fallback_bullets_by_id(
        crime_count, reports_count, permit_count, eviction_count, _third_bullet_ai_failed()
    )
    template_fb = _finalize_threat_bullets(
        template_fb,
        crime_count=crime_count,
        reports_count=reports_count,
        permit_count=permit_count,
        eviction_count=eviction_count,
        noise_count=noise_count,
        construction_311_count=construction_311_count,
        flight_path=flight_path,
        scan_radius_miles=scan_radius_miles,
    )

    async def _call_gemini_bullets() -> dict[str, list[str]]:
        if _GEMINI_TIMEOUT > 0:
            response = await asyncio.wait_for(
                asyncio.to_thread(model.generate_content, prompt),
                timeout=_GEMINI_TIMEOUT,
            )
        else:
            response = await asyncio.to_thread(model.generate_content, prompt)
        raw = _extract_text_from_response(response)
        if not raw:
            fb = getattr(response, "prompt_feedback", None)
            logger.error("Gemini returned empty text. prompt_feedback=%s", fb)
            raise ValueError("Empty Gemini response (blocked or no candidates)")
        data = _parse_ai_json(raw)
        inner = data.get("bullets") if isinstance(data, dict) else None
        if not isinstance(inner, dict):
            raise ValueError("Missing or invalid 'bullets' object in Gemini JSON")
        # Coerce to str lists; missing keys handled in merge
        gemini_map: dict[str, list[str]] = {}
        for cid in ordered_card_ids():
            row = inner.get(cid)
            gemini_map[cid] = row if isinstance(row, list) else []
        merged = _merge_bullets_with_fallback(template_fb, gemini_map)
        return _finalize_threat_bullets(
            merged,
            crime_count=crime_count,
            reports_count=reports_count,
            permit_count=permit_count,
            eviction_count=eviction_count,
            noise_count=noise_count,
            construction_311_count=construction_311_count,
            flight_path=flight_path,
            scan_radius_miles=scan_radius_miles,
        )

    for attempt in range(2):
        t0 = time.monotonic()
        try:
            bullets_by_id = await _call_gemini_bullets()
            latency_ms = int((time.monotonic() - t0) * 1000)
            result = {
                **risk,
                "threat_cards": cards_from_specs_and_bullets(bullets_by_id),
                "gemini_configured": True,
                "gemini_status": "ok",
                "gemini_latency_ms": latency_ms,
                "gemini_timeout_seconds": _GEMINI_TIMEOUT_REPORT,
                "gemini_error_kind": None,
                "gemini_error_detail": None,
            }
            _analysis_cache[cache_key] = result
            return result
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "Gemini timed out after %.1fs (measured %.0fms) — using fallback bullets. "
                "Increase GEMINI_TIMEOUT_SECONDS if needed.",
                _GEMINI_TIMEOUT,
                latency_ms,
            )
            result = {
                **risk,
                "threat_cards": cards_from_specs_and_bullets(template_fb),
                "gemini_configured": True,
                "gemini_status": "timeout",
                "gemini_latency_ms": latency_ms,
                "gemini_timeout_seconds": _GEMINI_TIMEOUT_REPORT,
                "gemini_error_kind": None,
                "gemini_error_detail": None,
            }
            _analysis_cache[cache_key] = result
            return result
        except Exception as e:
            if attempt == 0:
                logger.warning("Gemini attempt 1 failed (%s), retrying once…", e)
                await asyncio.sleep(1.5)
                continue
            latency_ms = int((time.monotonic() - t0) * 1000)
            error_kind, error_detail = _classify_gemini_error(e)
            logger.exception(
                "Gemini failed after retry (kind=%s, %.0fms) — using fallback bullets",
                error_kind,
                latency_ms,
            )
            result = {
                **risk,
                "threat_cards": cards_from_specs_and_bullets(template_fb),
                "gemini_configured": True,
                "gemini_status": "error",
                "gemini_latency_ms": latency_ms,
                "gemini_timeout_seconds": _GEMINI_TIMEOUT_REPORT,
                "gemini_error_kind": error_kind,
                "gemini_error_detail": error_detail or None,
            }
            _analysis_cache[cache_key] = result
            return result
