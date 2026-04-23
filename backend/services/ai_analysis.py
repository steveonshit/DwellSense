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
from services.threat_card_layout import (
    cards_from_specs_and_bullets,
    compute_risk_from_counts,
    ordered_card_ids,
)

logger = logging.getLogger(__name__)

# Allow override via env (Railway / local).
_GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "90"))
_GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2048"))

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

BULLETS_SYSTEM_PROMPT = """You are DwellSense, a brutally honest real estate forensics AI for renters.
You receive a data brief about one NYC address. Write ONLY the nine threat-card bullet lists.

Rules:
- Each bullet is one short sentence. Use specific numbers from the brief when possible.
- No markdown. No nested JSON inside strings.
- TONE: Direct, data-driven, slightly adversarial. Bullets should feel like insider knowledge, not generic warnings.

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
    return {
        "high_churn": [
            "Eviction records found nearby.",
            "High turnover signals problem landlords.",
            bullet_extra,
        ],
        "police_calls": [
            f"{crime_count} incidents logged in last 30 days.",
            "See blue zones on the threat map.",
            bullet_extra,
        ],
        "area_safety": [
            "Crime data pulled from NYC Open Data.",
            "See red zones on the threat map.",
            bullet_extra,
        ],
        "tenant_warnings": [
            "Check HPD building violations for this address.",
            "Past violations indicate maintenance neglect.",
            bullet_extra,
        ],
        "demolitions": [
            f"{permit_count} active permits found nearby.",
            "Heavy equipment possible during business hours.",
            bullet_extra,
        ],
        "noise_schedule": [
            "311 noise complaints logged nearby.",
            "Check for commercial loading docks on the block.",
            bullet_extra,
        ],
        "flight_path": [
            "Flight corridor analysis computed.",
            "See cyan flight path line on map.",
            bullet_extra,
        ],
        "reports_311": [
            f"{reports_count} 311 reports filed nearby.",
            "Primary complaints visible on map.",
            bullet_extra,
        ],
        "oven_effect": [
            "West-facing units trap afternoon heat.",
            "Check unit orientation before signing.",
            bullet_extra,
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
    Python builds danger score + card chrome; Gemini writes bullets only.
    Falls back to template bullets if Gemini is unavailable.
    """
    crime_count = len(crime)
    reports_count = len(reports_311)
    permit_count = len(permits)
    eviction_count = len(evictions)

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
        f"{address}:{crime_count}:{reports_count}:{permit_count}:{eviction_count}:{key_fp}".encode()
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
                "gemini_timeout_seconds": _GEMINI_TIMEOUT,
                "gemini_error_kind": None,
                "gemini_error_detail": None,
            }
        return hit

    risk = compute_risk_from_counts(crime_count, reports_count, permit_count, eviction_count)

    if not gemini_api_key:
        fb = _fallback_bullets_by_id(
            crime_count, reports_count, permit_count, eviction_count, _third_bullet_no_key()
        )
        result = {
            **risk,
            "threat_cards": cards_from_specs_and_bullets(fb),
            "gemini_configured": False,
            "gemini_status": _pre_status,
            "gemini_latency_ms": None,
            "gemini_timeout_seconds": _GEMINI_TIMEOUT,
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
        f"CRIME_30D_0.5MI: {_summarize_crime(crime)}\n"
        f"SR311_30D_0.5MI: {_summarize_311(reports_311)}\n"
        f"PERMITS_90D_0.5MI: {_summarize_permits(permits)}\n"
        f"EVICTIONS_NEARBY: count={eviction_count}\n"
        f"LOGISTICS: {_summarize_logistics(logistics)}\n"
        f"FLIGHT: {flight_text}\n"
        "\n"
        "Return the 27 bullets JSON only. Use the numbers above; don't invent new stats."
    )

    template_fb = _fallback_bullets_by_id(
        crime_count, reports_count, permit_count, eviction_count, _third_bullet_ai_failed()
    )

    async def _call_gemini_bullets() -> dict[str, list[str]]:
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, prompt),
            timeout=_GEMINI_TIMEOUT,
        )
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
        return _merge_bullets_with_fallback(template_fb, gemini_map)

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
                "gemini_timeout_seconds": _GEMINI_TIMEOUT,
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
                "gemini_timeout_seconds": _GEMINI_TIMEOUT,
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
                "gemini_timeout_seconds": _GEMINI_TIMEOUT,
                "gemini_error_kind": error_kind,
                "gemini_error_detail": error_detail or None,
            }
            _analysis_cache[cache_key] = result
            return result
