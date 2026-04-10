"""
Determines the flight path corridor above an address.
Uses static FAA approach corridor data for NYC airports.
Live animated plane position can be fetched from OpenSky Network.
"""

import os
import math
import httpx
from models.schemas import Coordinate, FlightPath

OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")

# NYC airport approach corridors (simplified straight-line paths)
# Each entry: the flight path that planes follow on approach/departure.
# start = where the plane comes from (far out), end = the airport.
NYC_FLIGHT_CORRIDORS = [
    {
        "airport": "JFK",
        "runway": "Runway 31L/R",
        "start": Coordinate(lat=40.8500, lng=-72.8000),  # East approach over the Atlantic
        "end": Coordinate(lat=40.6413, lng=-73.7781),
        "description": "JFK approach corridor — planes fly low over Queens from the east.",
    },
    {
        "airport": "LGA",
        "runway": "Runway 13/31",
        "start": Coordinate(lat=40.9000, lng=-73.5000),  # Northeast approach
        "end": Coordinate(lat=40.7769, lng=-73.8740),
        "description": "LaGuardia approach — low over Flushing Bay and northern Queens.",
    },
    {
        "airport": "EWR",
        "runway": "Runway 22L/R",
        "start": Coordinate(lat=40.8000, lng=-73.9000),  # Approach from Manhattan
        "end": Coordinate(lat=40.6895, lng=-74.1745),
        "description": "Newark approach — planes cross upper Manhattan and the Hudson.",
    },
]


def _distance_to_line_miles(
    point_lat: float, point_lng: float,
    line_start: Coordinate, line_end: Coordinate
) -> float:
    """Calculates perpendicular distance from a point to a flight corridor line."""
    # Convert to rough x/y (not perfect but good enough for ~50mi range)
    scale_lng = math.cos(math.radians(point_lat))

    px = (point_lng - line_start.lng) * scale_lng
    py = point_lat - line_start.lat
    dx = (line_end.lng - line_start.lng) * scale_lng
    dy = line_end.lat - line_start.lat

    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return math.sqrt(px * px + py * py) * 69.0

    t = max(0.0, min(1.0, (px * dx + py * dy) / seg_len_sq))
    cx = dx * t - px
    cy = dy * t - py
    return math.sqrt(cx * cx + cy * cy) * 69.0


def get_nearest_flight_corridor(coord: Coordinate) -> FlightPath | None:
    """
    Returns the nearest flight corridor within 3 miles of the address.
    Returns None if the address is not under a flight path.
    """
    closest = None
    min_dist = float("inf")

    for corridor in NYC_FLIGHT_CORRIDORS:
        dist = _distance_to_line_miles(
            coord.lat, coord.lng,
            corridor["start"], corridor["end"]
        )
        if dist < min_dist:
            min_dist = dist
            closest = corridor

    # Only report a flight path if actually close (within 3 miles)
    if closest and min_dist <= 3.0:
        return FlightPath(
            start=closest["start"],
            end=closest["end"],
            label=f"{closest['airport']} Approach — {closest['runway']} ({min_dist:.1f} mi from property)",
        )
    return None


async def get_live_plane_position(
    lat_min: float, lat_max: float,
    lng_min: float, lng_max: float
) -> Coordinate | None:
    """
    Fetches a live plane position from OpenSky Network within a bounding box.
    Returns None if unavailable or no planes in the area.
    """
    try:
        auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD) if OPENSKY_USERNAME else None
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://opensky-network.org/api/states/all",
                params={
                    "lamin": lat_min, "lamax": lat_max,
                    "lomin": lng_min, "lomax": lng_max,
                },
                auth=auth,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            states = data.get("states", [])
            if not states:
                return None
            # Return position of first aircraft found [lat=6, lng=5]
            plane = states[0]
            if plane[6] and plane[5]:
                return Coordinate(lat=plane[6], lng=plane[5])
    except Exception:
        pass
    return None
