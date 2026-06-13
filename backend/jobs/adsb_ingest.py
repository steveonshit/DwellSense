"""
ADS-B ingestion.

Pulls real observed aircraft positions within a NYC bounding box and writes samples
to Supabase. OpenSky is preferred; adsb.lol is used as a real-data fallback when
OpenSky is unavailable from the runtime environment.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx

from services.city_data import _get_client  # reuse existing Supabase client config

logger = logging.getLogger(__name__)


def _opensky_auth() -> tuple[str, str] | None:
    """Basic auth only when username is set; read env at call time (not import time)."""
    u = (os.getenv("OPENSKY_USERNAME") or "").strip()
    p = (os.getenv("OPENSKY_PASSWORD") or "").strip()
    return (u, p) if u else None


def _bbox_for_nyc() -> tuple[float, float, float, float]:
    """
    NYC-ish bounding box for continuous sampling.
    Tuned for the DwellSense use-case (NYC only).
    """
    lat_min, lat_max = 40.35, 41.10
    lng_min, lng_max = -74.55, -73.50
    return lat_min, lat_max, lng_min, lng_max


def _to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _feet_to_meters(value: object) -> float | None:
    feet = _to_float(value)
    return feet * 0.3048 if feet is not None else None


def _knots_to_mps(value: object) -> float | None:
    knots = _to_float(value)
    return knots * 0.514444 if knots is not None else None


async def _fetch_opensky_rows(
    client: httpx.AsyncClient,
    *,
    lat_min: float,
    lat_max: float,
    lng_min: float,
    lng_max: float,
    observed_at: str,
) -> list[dict]:
    auth = _opensky_auth()
    resp = await client.get(
        "https://opensky-network.org/api/states/all",
        params={"lamin": lat_min, "lamax": lat_max, "lomin": lng_min, "lomax": lng_max},
        auth=auth,
    )
    resp.raise_for_status()
    data = resp.json()
    states = data.get("states") or []
    if not isinstance(states, list) or not states:
        return []

    rows: list[dict] = []
    for s in states:
        # OpenSky state vector format:
        # [0]=icao24, [5]=lon, [6]=lat, [7]=baro_alt, [8]=on_ground,
        # [9]=velocity, [10]=true_track, [13]=geo_alt (often)
        if not isinstance(s, list) or len(s) < 11:
            continue
        icao24 = s[0]
        lng = s[5]
        lat = s[6]
        if not icao24 or lat is None or lng is None:
            continue
        rows.append(
            {
                "observed_at": observed_at,
                "icao24": str(icao24).lower(),
                "lat": float(lat),
                "lng": float(lng),
                "baro_alt_m": _to_float(s[7]),
                "geo_alt_m": _to_float(s[13]) if len(s) > 13 else None,
                "on_ground": bool(s[8]) if isinstance(s[8], bool) else None,
                "velocity_mps": _to_float(s[9]),
                "true_track_deg": _to_float(s[10]),
                "source": "opensky",
            }
        )
    return rows


async def _fetch_adsb_lol_rows(
    client: httpx.AsyncClient,
    *,
    lat_min: float,
    lat_max: float,
    lng_min: float,
    lng_max: float,
    observed_at: str,
) -> list[dict]:
    center_lat = (lat_min + lat_max) / 2.0
    center_lng = (lng_min + lng_max) / 2.0
    try:
        radius_nm = max(10.0, min(250.0, float(os.getenv("ADSB_LOL_RADIUS_NM", "65"))))
    except ValueError:
        radius_nm = 65.0
    try:
        max_seen_seconds = max(10.0, min(600.0, float(os.getenv("ADSB_LOL_MAX_SEEN_SECONDS", "120"))))
    except ValueError:
        max_seen_seconds = 120.0

    resp = await client.get(
        f"https://api.adsb.lol/v2/point/{center_lat:.5f}/{center_lng:.5f}/{radius_nm:.1f}",
        headers={"User-Agent": "DwellSense/1.0 (real ADS-B fallback)"},
    )
    resp.raise_for_status()
    data = resp.json()
    aircraft = data.get("ac") or []
    if not isinstance(aircraft, list):
        return []

    rows: list[dict] = []
    for ac in aircraft:
        if not isinstance(ac, dict):
            continue
        icao24 = str(ac.get("hex") or "").strip().lower()
        lat = _to_float(ac.get("lat"))
        lng = _to_float(ac.get("lon"))
        if not icao24 or lat is None or lng is None:
            continue
        if lat < lat_min or lat > lat_max or lng < lng_min or lng > lng_max:
            continue
        seen_pos = _to_float(ac.get("seen_pos"))
        seen = _to_float(ac.get("seen"))
        freshness = seen_pos if seen_pos is not None else seen
        if freshness is not None and freshness > max_seen_seconds:
            continue

        alt_baro = ac.get("alt_baro")
        on_ground = alt_baro == "ground"
        rows.append(
            {
                "observed_at": observed_at,
                "icao24": icao24,
                "lat": lat,
                "lng": lng,
                # adsb.lol readsb-compatible altitude fields are feet; store meters.
                "baro_alt_m": None if on_ground else _feet_to_meters(alt_baro),
                "geo_alt_m": _feet_to_meters(ac.get("alt_geom")),
                "on_ground": on_ground,
                "velocity_mps": _knots_to_mps(ac.get("gs")),
                "true_track_deg": _to_float(ac.get("track")),
                "source": "adsb_lol",
            }
        )
    return rows


async def ingest_once(*, source: str | None = None) -> int:
    lat_min, lat_max, lng_min, lng_max = _bbox_for_nyc()
    observed_at = datetime.now(timezone.utc).isoformat()
    try:
        timeout_sec = max(10.0, min(60.0, float(os.getenv("ADSB_OPENSKY_TIMEOUT_SECONDS", "25"))))
    except ValueError:
        timeout_sec = 25.0

    provider_order = [p.strip().lower() for p in (source or os.getenv("ADSB_INGEST_SOURCES", "opensky,adsb_lol")).split(",")]
    provider_order = [p for p in provider_order if p in {"opensky", "adsb_lol"}]
    if not provider_order:
        provider_order = ["opensky", "adsb_lol"]

    rows: list[dict] = []
    # Railway often sets HTTP(S)_PROXY; OpenSky direct TLS can fail if those are honored.
    async with httpx.AsyncClient(timeout=timeout_sec, trust_env=False) as client:
        for provider in provider_order:
            try:
                if provider == "opensky":
                    rows = await _fetch_opensky_rows(
                        client,
                        lat_min=lat_min,
                        lat_max=lat_max,
                        lng_min=lng_min,
                        lng_max=lng_max,
                        observed_at=observed_at,
                    )
                else:
                    rows = await _fetch_adsb_lol_rows(
                        client,
                        lat_min=lat_min,
                        lat_max=lat_max,
                        lng_min=lng_min,
                        lng_max=lng_max,
                        observed_at=observed_at,
                    )
                if rows:
                    logger.info("ADS-B ingest: fetched %s %s rows", len(rows), provider)
                    break
            except Exception as exc:
                logger.warning("ADS-B ingest provider %s failed: %s", provider, exc)

    if not rows:
        return 0

    supabase = _get_client()
    # Insert in chunks to avoid large payload issues.
    inserted = 0
    chunk = 500
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
        res = supabase.table("adsb_samples").insert(batch).execute()
        # supabase-py returns data list on success
        inserted += len(getattr(res, "data", []) or batch)
    return inserted


async def run_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            n = await ingest_once()
            print(f"[adsb_ingest] inserted ~{n} samples @ {time.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[adsb_ingest] error: {e}")
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    interval = int(os.getenv("ADSB_INGEST_INTERVAL_SECONDS", "60"))
    asyncio.run(run_loop(interval_seconds=interval))

