"""Mapbox Geocoding — converts a plain-text address to lat/lng."""

import os
import urllib.parse
import requests
from models.schemas import Coordinate


GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"


async def geocode(address: str) -> tuple[Coordinate, str]:
    """
    Returns (Coordinate, formatted_address).
    Raises ValueError if address is not found.
    Raises RuntimeError on API/network failure.
    """
    mapbox_token = os.getenv("MAPBOX_TOKEN", "")
    if not mapbox_token:
        raise RuntimeError("MAPBOX_TOKEN is not set in environment variables.")

    try:
        # Some environments set HTTPS_PROXY/HTTP_PROXY which can break outbound calls
        # (e.g., tunnel errors / 403). For geocoding, prefer a direct connection.
        session = requests.Session()
        session.trust_env = False

        resp = session.get(
            GEOCODE_URL.format(query=urllib.parse.quote(address, safe="")),
            params={
                "access_token": mapbox_token,
                "country": "US",
                "types": "address,place",
                "limit": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Geocoding network error: {e}") from e

    features = data.get("features", [])
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
