"""
Google Maps Places API (New) — finds nearest transit stops, groceries, airports.
Yelp / Google Places dining lookup — finds top nearby restaurants and bars.
Uses the new Places API (v1) directly via requests, since the legacy
googlemaps library is no longer enabled on new Google Cloud projects.
"""

import os
import math
import asyncio
import logging
import requests
from models.schemas import Coordinate, LogisticsCard, RestaurantBarCard

logger = logging.getLogger(__name__)

PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_TEXT_URL   = "https://places.googleapis.com/v1/places:searchText"
YELP_BUSINESS_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"
DINING_RADIUS_MILES = 2.0
DINING_RADIUS_METERS = int(DINING_RADIUS_MILES * 1609.344)

# NYC-area airports (static — airports don't move)
NYC_AIRPORTS = [
    {"name": "JFK International",      "lat": 40.6413, "lng": -73.7781},
    {"name": "LaGuardia Airport (LGA)","lat": 40.7769, "lng": -73.8740},
    {"name": "Newark Liberty (EWR)",   "lat": 40.6895, "lng": -74.1745},
]

# Fallback only when Places returns no mall (see _get_logistics_blocking_inner).
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


def _is_placeholder(value: str) -> bool:
    lower = (value or "").strip().lower()
    return (
        not lower
        or "your_" in lower
        or lower.startswith("<")
        or "placeholder" in lower
    )


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


async def get_top_restaurants_bars(coord: Coordinate, *, limit: int = 4) -> list[RestaurantBarCard]:
    """Return top-ranked real restaurants/bars within 2 miles; empty when unavailable."""
    return await asyncio.to_thread(_get_top_restaurants_bars_blocking, coord, limit)


def _ranking_score(rating: float | None, review_count: int | None, distance_miles: float) -> float:
    """
    Conservative ranking: rating matters, but review volume makes the rating more trustworthy.
    Distance is only a small tie-breaker because this is "best within 2 miles", not nearest.
    """
    if rating is None:
        return -1.0
    reviews = max(0, int(review_count or 0))
    confidence = min(1.0, math.log10(reviews + 1) / math.log10(500 + 1))
    return (rating * 0.78) + (confidence * 1.15) - (distance_miles * 0.08)


def _category_from_yelp(item: dict) -> str:
    categories = item.get("categories") if isinstance(item.get("categories"), list) else []
    for category in categories:
        title = category.get("title") if isinstance(category, dict) else None
        if title:
            return str(title)
    return "Restaurant / Bar"


def _price_from_google(price_level: object) -> str | None:
    if not isinstance(price_level, str):
        return None
    mapping = {
        "PRICE_LEVEL_FREE": None,
        "PRICE_LEVEL_INEXPENSIVE": "$",
        "PRICE_LEVEL_MODERATE": "$$",
        "PRICE_LEVEL_EXPENSIVE": "$$$",
        "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
    }
    return mapping.get(price_level)


def _get_top_restaurants_bars_blocking(coord: Coordinate, limit: int = 4) -> list[RestaurantBarCard]:
    yelp_key = os.getenv("YELP_API_KEY", "")
    if not _is_placeholder(yelp_key):
        yelp_cards = _get_top_restaurants_bars_yelp(coord, yelp_key, limit=limit)
        if yelp_cards:
            return yelp_cards

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if _is_placeholder(api_key):
        logger.warning("Dining lookup unavailable — no YELP_API_KEY or GOOGLE_MAPS_API_KEY.")
        return []
    return _get_top_restaurants_bars_google(coord, api_key, limit=limit)


def _get_top_restaurants_bars_yelp(coord: Coordinate, api_key: str, *, limit: int) -> list[RestaurantBarCard]:
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "latitude": coord.lat,
        "longitude": coord.lng,
        "radius": DINING_RADIUS_METERS,
        "categories": "restaurants,bars",
        "limit": 20,
        "sort_by": "rating",
    }
    try:
        resp = requests.get(YELP_BUSINESS_SEARCH_URL, headers=headers, params=params, timeout=12)
        resp.raise_for_status()
        businesses = resp.json().get("businesses") or []
    except Exception as e:
        logger.warning("Yelp dining lookup failed: %s", e)
        return []

    cards: list[RestaurantBarCard] = []
    seen: set[str] = set()
    for item in businesses:
        if not isinstance(item, dict):
            continue
        coords = item.get("coordinates") if isinstance(item.get("coordinates"), dict) else {}
        p_lat = coords.get("latitude")
        p_lng = coords.get("longitude")
        name = item.get("name")
        if not name or p_lat is None or p_lng is None:
            continue
        try:
            distance_miles = _haversine_miles(coord.lat, coord.lng, float(p_lat), float(p_lng))
        except Exception:
            continue
        if distance_miles > DINING_RADIUS_MILES:
            continue
        key = str(item.get("id") or name).lower()
        if key in seen:
            continue
        seen.add(key)
        rating = float(item["rating"]) if isinstance(item.get("rating"), (int, float)) else None
        review_count = int(item["review_count"]) if isinstance(item.get("review_count"), int) else None
        val, unit = _miles_to_display(distance_miles)
        cards.append(
            RestaurantBarCard(
                name=str(name),
                category=_category_from_yelp(item),
                rating=rating,
                review_count=review_count,
                price_level=str(item.get("price")) if item.get("price") else None,
                distance_value=val,
                distance_unit=unit,
                coordinates=Coordinate(lat=float(p_lat), lng=float(p_lng)),
                source="yelp",
                url=str(item.get("url")) if item.get("url") else None,
                ranking_score=round(_ranking_score(rating, review_count, distance_miles), 3),
            )
        )

    cards.sort(key=lambda c: (c.ranking_score or -1, c.rating or 0, c.review_count or 0), reverse=True)
    return cards[:limit]


def _get_top_restaurants_bars_google(coord: Coordinate, api_key: str, *, limit: int) -> list[RestaurantBarCard]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.displayName,places.location,places.rating,places.userRatingCount,"
            "places.primaryTypeDisplayName,places.types,places.googleMapsUri,places.priceLevel,places.businessStatus"
        ),
    }
    body = {
        "includedTypes": ["restaurant", "bar"],
        "maxResultCount": 20,
        "rankPreference": "POPULARITY",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": coord.lat, "longitude": coord.lng},
                "radius": float(DINING_RADIUS_METERS),
            }
        },
    }
    try:
        resp = requests.post(PLACES_NEARBY_URL, json=body, headers=headers, timeout=12)
        resp.raise_for_status()
        places = resp.json().get("places") or []
    except Exception as e:
        logger.warning("Google Places dining lookup failed: %s", e)
        return []

    cards: list[RestaurantBarCard] = []
    seen: set[str] = set()
    for place in places:
        if not isinstance(place, dict):
            continue
        if place.get("businessStatus") and place.get("businessStatus") != "OPERATIONAL":
            continue
        loc = place.get("location") if isinstance(place.get("location"), dict) else {}
        p_lat = loc.get("latitude")
        p_lng = loc.get("longitude")
        name = (place.get("displayName") or {}).get("text") if isinstance(place.get("displayName"), dict) else None
        if not name or p_lat is None or p_lng is None:
            continue
        try:
            distance_miles = _haversine_miles(coord.lat, coord.lng, float(p_lat), float(p_lng))
        except Exception:
            continue
        if distance_miles > DINING_RADIUS_MILES:
            continue
        key = str(name).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        rating = float(place["rating"]) if isinstance(place.get("rating"), (int, float)) else None
        review_count = int(place["userRatingCount"]) if isinstance(place.get("userRatingCount"), int) else None
        primary = place.get("primaryTypeDisplayName")
        category = (
            primary.get("text")
            if isinstance(primary, dict) and primary.get("text")
            else "Restaurant / Bar"
        )
        val, unit = _miles_to_display(distance_miles)
        cards.append(
            RestaurantBarCard(
                name=str(name),
                category=str(category),
                rating=rating,
                review_count=review_count,
                price_level=_price_from_google(place.get("priceLevel")),
                distance_value=val,
                distance_unit=unit,
                coordinates=Coordinate(lat=float(p_lat), lng=float(p_lng)),
                source="google_places",
                url=str(place.get("googleMapsUri")) if place.get("googleMapsUri") else None,
                ranking_score=round(_ranking_score(rating, review_count, distance_miles), 3),
            )
        )

    cards.sort(key=lambda c: (c.ranking_score or -1, c.rating or 0, c.review_count or 0), reverse=True)
    return cards[:limit]


def _get_logistics_blocking(coord: Coordinate) -> list[LogisticsCard]:
    """
    Returns logistics cards using Places API (New).
    Falls back to static airport/mall only if no API key.
    """
    try:
        return _get_logistics_blocking_inner(coord)
    except Exception:
        logger.exception("Logistics lookup failed — using static airport/mall cards only.")
        return _fallback_static_cards(coord)


def _get_logistics_blocking_inner(coord: Coordinate) -> list[LogisticsCard]:
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

    # --- Nearest mall / retail hub (Places — not limited to static list below) ---
    place = _nearby_search(api_key, coord, ["shopping_mall"], radius_m=15000)
    if not place:
        place = _text_search(api_key, coord, "shopping mall", radius_m=12000)
    if place:
        card = _make_card(place, coord, "mall", "Retail Center", "🛍️", "#06b6d4")
        if card:
            cards.append(card)
    else:
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
