"""Mapbox Geocoding — converts a plain-text address to lat/lng."""

import asyncio
import logging
import os
import urllib.parse

import httpx

from models.schemas import Coordinate

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"


def _geocode_attempts() -> int:
    try:
        return max(1, min(8, int(os.getenv("MAPBOX_GEOCODE_RETRIES", "4"))))
    except ValueError:
        return 4


def _geocode_timeouts() -> httpx.Timeout:
    """Separate connect vs read timeouts (Railway / cold links often need a generous connect window)."""
    try:
        connect = float(os.getenv("MAPBOX_GEOCODE_CONNECT_TIMEOUT", "20"))
    except ValueError:
        connect = 20.0
    try:
        read = float(os.getenv("MAPBOX_GEOCODE_READ_TIMEOUT", "35"))
    except ValueError:
        read = 35.0
    connect = max(5.0, min(60.0, connect))
    read = max(5.0, min(90.0, read))
    return httpx.Timeout(connect=connect, read=read, write=read, pool=10.0)


async def geocode(address: str) -> tuple[Coordinate, str]:
    """
    Returns (Coordinate, formatted_address).
    Raises ValueError if address is not found.
    Raises RuntimeError on API/network failure.
    """
    mapbox_token = os.getenv("MAPBOX_TOKEN", "")
    if not mapbox_token:
        raise RuntimeError("MAPBOX_TOKEN is not set in environment variables.")

    url = GEOCODE_URL.format(query=urllib.parse.quote(address, safe=""))
    params = {
        "access_token": mapbox_token,
        "country": "US",
        "types": "address,place",
        "limit": 1,
    }
    timeout = _geocode_timeouts()
    attempts = _geocode_attempts()
    data: dict | None = None

    # trust_env=False: ignore HTTP(S)_PROXY in PaaS/build envs that break direct Mapbox TLS.
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                break
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in (429, 502, 503, 504) and attempt < attempts:
                    wait_s = min(3.0, 0.35 * attempt)
                    logger.warning(
                        "Mapbox geocode HTTP %s (attempt %s/%s), retrying in %.1fs",
                        code,
                        attempt,
                        attempts,
                        wait_s,
                    )
                    await asyncio.sleep(wait_s)
                    continue
                raise RuntimeError(f"Geocoding API error: HTTP {code}") from e
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, httpx.ReadError) as e:
                if attempt >= attempts:
                    raise RuntimeError(
                        "Geocoding could not reach Mapbox after several attempts (connection or timeout). "
                        "Confirm MAPBOX_TOKEN, that this host can open HTTPS to api.mapbox.com:443, "
                        "and try again in a moment."
                    ) from e
                wait_s = min(2.5, 0.4 * attempt)
                logger.warning(
                    "Mapbox geocode transport error (attempt %s/%s): %s — retrying in %.1fs",
                    attempt,
                    attempts,
                    e,
                    wait_s,
                )
                await asyncio.sleep(wait_s)

    if not isinstance(data, dict):
        raise RuntimeError("Geocoding returned an unexpected response.")
    features = data.get("features")
    if not isinstance(features, list):
        raise RuntimeError("Geocoding returned an unexpected features payload.")
    if not features:
        raise ValueError(f"Address not found: '{address}'. Try adding a city or zip code.")

    best = features[0]
    try:
        geom = best.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            raise ValueError("missing coordinates")
        lng, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError, KeyError, IndexError) as e:
        raise ValueError(
            f"Address not found: '{address}'. Try adding a city or zip code."
        ) from e
    formatted = best.get("place_name", address)

    return Coordinate(lat=lat, lng=lng), formatted
