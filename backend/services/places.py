"""
Google Maps Places API (New) — finds nearest transit stops, groceries, airports.
Uses the new Places API (v1) directly via requests, since the legacy
googlemaps library is no longer enabled on new Google Cloud projects.
"""

import os
import math
import asyncio
import logging
import requests
from models.schemas import Coordinate, LogisticsCard

logger = logging.getLogger(__name__)

PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_TEXT_URL   = "https://places.googleapis.com/v1/places:searchText"

# NYC-area airports (static — airports don't move)
NYC_AIRPORTS = [
    {"name": "JFK International",      "lat": 40.6413, "lng": -73.7781},
    {"name": "LaGuardia Airport (LGA)","lat": 40.7769, "lng": -73.8740},
    {"name": "Newark Liberty (EWR)",   "lat": 40.6895, "lng": -74.1745},
]

# NYC major malls (static)
NYC_MALLS = [
    {"name": "Westfield World Trade Center", "lat": 40.7127, "lng": -74.0134},
    {"name": "Brookfield Place",             "lat": 40.7133, "lng": -74.0155},
    {"name": "Manhattan Mall",               "lat": 40.7484, "lng": -73.9890},
    {"name": "Kings Plaza Shopping Center",  "lat": 40.5878, "lng": -73.9319},
    {"name": "Queens Center Mall",           "lat": 40.7343, "lng": -73.8695},
    {"name": "Staten Island Mall",           "lat": 40.5826, "lng": -74.1670},
]


def _haversine_miles(lat1, lng1, lat2, lng2) -> float:
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _miles_to_display(miles: float) -> tuple[float, str]:
    feet = miles * 5280
    if feet < 2640:
        return round(feet), "feet"
    return round(miles, 1), "miles"


def _nearest_static(coord: Coordinate, options: list[dict]) -> dict:
    return min(options, key=lambda p: _haversine_miles(coord.lat, coord.lng, p["lat"], p["lng"]))


def _nearby_search(api_key: str, coord: Coordinate, place_types: list[str], radius_m: int = 800) -> dict | None:
    """Calls Places API (New) Nearby Search. Returns first result or None."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.location",
    }
    body = {
        "includedTypes": place_types,
        "maxResultCount": 1,
        "rankPreference": "DISTANCE",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": coord.lat, "longitude": coord.lng},
                "radius": float(radius_m),
            }
        },
    }
    try:
        resp = requests.post(PLACES_NEARBY_URL, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        places = resp.json().get("places", [])
        return places[0] if places else None
    except Exception as e:
        logger.warning(f"Nearby search failed for {place_types}: {e}")
        return None


def _text_search(api_key: str, coord: Coordinate, query: str, radius_m: int = 3000) -> dict | None:
    """Calls Places API (New) Text Search. Returns first result or None."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.location",
    }
    body = {
        "textQuery": query,
        "maxResultCount": 1,
        "rankPreference": "DISTANCE",
        "locationBias": {
            "circle": {
                "center": {"latitude": coord.lat, "longitude": coord.lng},
                "radius": float(radius_m),
            }
        },
    }
    try:
        resp = requests.post(PLACES_TEXT_URL, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        places = resp.json().get("places", [])
        return places[0] if places else None
    except Exception as e:
        logger.warning(f"Text search failed for '{query}': {e}")
        return None


def _make_card(place: dict, coord: Coordinate, type_key: str, category: str, emoji: str, color: str) -> LogisticsCard | None:
    if not place:
        return None
    loc = place.get("location", {})
    p_lat = loc.get("latitude")
    p_lng = loc.get("longitude")
    name = place.get("displayName", {}).get("text", category)
    if not p_lat or not p_lng:
        return None
    dist = _haversine_miles(coord.lat, coord.lng, p_lat, p_lng)
    val, unit = _miles_to_display(dist)
    return LogisticsCard(
        type=type_key, name=name, category=category,
        emoji=emoji, distance_value=val, distance_unit=unit,
        color=color,
        coordinates=Coordinate(lat=p_lat, lng=p_lng),
    )


def _get_logistics_sync(coord: Coordinate) -> list[LogisticsCard]:
    """Synchronous version — called via asyncio.to_thread."""
    return _get_logistics_blocking(coord)


async def get_logistics(coord: Coordinate) -> list[LogisticsCard]:
    """Async entry point — runs blocking HTTP calls in a thread pool."""
    return await asyncio.to_thread(_get_logistics_blocking, coord)


def _get_logistics_blocking(coord: Coordinate) -> list[LogisticsCard]:
    """
    Returns logistics cards using Places API (New).
    Falls back to static airport/mall only if no API key.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_MAPS_API_KEY not set — returning static cards only.")
        return _fallback_static_cards(coord)

    cards: list[LogisticsCard] = []

    # --- Subway Station ---
    place = _nearby_search(api_key, coord, ["subway_station"], radius_m=1200)
    card = _make_card(place, coord, "subway", "Subway", "🚇", "#10b981")
    if card:
        cards.append(card)

    # --- Commuter Train ---
    place = _nearby_search(api_key, coord, ["train_station", "light_rail_station"], radius_m=3000)
    card = _make_card(place, coord, "train", "Train Line", "🚆", "#c4b5fd")
    if card:
        cards.append(card)

    # --- City Bus Stop ---
    place = _nearby_search(api_key, coord, ["bus_station", "transit_station"], radius_m=800)
    card = _make_card(place, coord, "bus", "City Bus", "🚌", "#bef264")
    if card:
        cards.append(card)

    # --- Grocery Store ---
    place = _nearby_search(api_key, coord, ["supermarket", "grocery_store"], radius_m=1500)
    card = _make_card(place, coord, "grocery", "Grocery", "🛒", "#3b82f6")
    if card:
        cards.append(card)

    # --- Target ---
    place = _text_search(api_key, coord, "Target store", radius_m=4000)
    card = _make_card(place, coord, "targetstore", "Grocery", "🎯", "#ef4444")
    if card:
        cards.append(card)

    # --- Trader Joe's ---
    place = _text_search(api_key, coord, "Trader Joe's grocery", radius_m=4000)
    card = _make_card(place, coord, "traderjoes", "Grocery", "🥑", "#f97316")
    if card:
        cards.append(card)

    # --- Nearest Airport (static math) ---
    airport = _nearest_static(coord, NYC_AIRPORTS)
    dist = _haversine_miles(coord.lat, coord.lng, airport["lat"], airport["lng"])
    val, unit = _miles_to_display(dist)
    cards.append(LogisticsCard(
        type="airport", name=airport["name"], category="Airport",
        emoji="✈️", distance_value=val, distance_unit=unit, color="#fbbf24",
        coordinates=Coordinate(lat=airport["lat"], lng=airport["lng"]),
    ))

    # --- Nearest Mall (static math) ---
    mall = _nearest_static(coord, NYC_MALLS)
    dist = _haversine_miles(coord.lat, coord.lng, mall["lat"], mall["lng"])
    val, unit = _miles_to_display(dist)
    cards.append(LogisticsCard(
        type="mall", name=mall["name"], category="Retail Center",
        emoji="🛍️", distance_value=val, distance_unit=unit, color="#06b6d4",
        coordinates=Coordinate(lat=mall["lat"], lng=mall["lng"]),
    ))

    logger.info(f"Logistics: returned {len(cards)} cards.")
    return cards


def _fallback_static_cards(coord: Coordinate) -> list[LogisticsCard]:
    cards = []
    airport = _nearest_static(coord, NYC_AIRPORTS)
    dist = _haversine_miles(coord.lat, coord.lng, airport["lat"], airport["lng"])
    val, unit = _miles_to_display(dist)
    cards.append(LogisticsCard(
        type="airport", name=airport["name"], category="Airport",
        emoji="✈️", distance_value=val, distance_unit=unit, color="#fbbf24",
        coordinates=Coordinate(lat=airport["lat"], lng=airport["lng"]),
    ))
    mall = _nearest_static(coord, NYC_MALLS)
    dist = _haversine_miles(coord.lat, coord.lng, mall["lat"], mall["lng"])
    val, unit = _miles_to_display(dist)
    cards.append(LogisticsCard(
        type="mall", name=mall["name"], category="Retail Center",
        emoji="🛍️", distance_value=val, distance_unit=unit, color="#06b6d4",
        coordinates=Coordinate(lat=mall["lat"], lng=mall["lng"]),
    ))
    return cards
