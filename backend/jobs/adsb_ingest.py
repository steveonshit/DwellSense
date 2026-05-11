"""
ADS-B ingestion (prototype).

Pulls OpenSky states within a bounding box and writes samples to Supabase.
This enables "flight exposure" scoring over time (night vs day, altitude bands).
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import httpx

from services.city_data import _get_client  # reuse existing Supabase client config


OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")


def _bbox_for_nyc() -> tuple[float, float, float, float]:
    """
    NYC-ish bounding box for continuous sampling.
    Tuned for the DwellSense use-case (NYC only).
    """
    lat_min, lat_max = 40.35, 41.10
    lng_min, lng_max = -74.55, -73.50
    return lat_min, lat_max, lng_min, lng_max


async def ingest_once(*, source: str = "opensky") -> int:
    lat_min, lat_max, lng_min, lng_max = _bbox_for_nyc()
    auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD) if OPENSKY_USERNAME else None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://opensky-network.org/api/states/all",
            params={"lamin": lat_min, "lamax": lat_max, "lomin": lng_min, "lomax": lng_max},
            auth=auth,
        )
        resp.raise_for_status()
        data = resp.json()

    states = data.get("states") or []
    if not isinstance(states, list) or not states:
        return 0

    observed_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for s in states:
        # OpenSky state vector format:
        # [0]=icao24, [5]=lon, [6]=lat, [7]=baro_alt, [8]=on_ground, [9]=velocity, [10]=true_track, [13]=geo_alt (often)
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
                "icao24": str(icao24),
                "lat": float(lat),
                "lng": float(lng),
                "baro_alt_m": float(s[7]) if isinstance(s[7], (int, float)) else None,
                "geo_alt_m": float(s[13]) if len(s) > 13 and isinstance(s[13], (int, float)) else None,
                "on_ground": bool(s[8]) if isinstance(s[8], bool) else None,
                "velocity_mps": float(s[9]) if isinstance(s[9], (int, float)) else None,
                "true_track_deg": float(s[10]) if isinstance(s[10], (int, float)) else None,
                "source": source,
            }
        )

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

