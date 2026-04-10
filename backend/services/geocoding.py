"""Mapbox Geocoding — converts a plain-text address to lat/lng."""

import os
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
        resp = requests.get(
            GEOCODE_URL.format(query=address),
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
    lng, lat = best["geometry"]["coordinates"]
    formatted = best.get("place_name", address)

    return Coordinate(lat=lat, lng=lng), formatted
