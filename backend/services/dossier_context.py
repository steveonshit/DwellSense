"""In-memory dossier store — raw scan rows for PDF generation (local + single-instance)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

_DOSSIER_TTL_SEC = 30 * 60

_pending_dossiers: dict[str, tuple[float, DossierContext]] = {}


@dataclass
class DossierContext:
    formatted_address: str
    coord_lat: float
    coord_lng: float
    scan_radius_miles: float
    scanned_at: str

    crime: list[dict]
    reports_311: list[dict]
    permits: list[dict]
    evictions: list[dict]

    crime_capped: bool
    reports_capped: bool
    permits_capped: bool
    evictions_capped: bool

    logistics: list[dict]
    dining_candidates: list[dict]

    flight_paths: list[dict]
    adsb_samples: list[dict]
    flight_exposure: dict | None

    map_swarm_shown: int
    map_swarm_total: int | None
    map_zones_count: int

    dossier_token: str = field(default="")


def _purge_expired() -> None:
    now = time.monotonic()
    for key, (expires, _) in list(_pending_dossiers.items()):
        if expires < now:
            del _pending_dossiers[key]


def store_dossier(ctx: DossierContext) -> str:
    _purge_expired()
    token = secrets.token_urlsafe(24)
    ctx.dossier_token = token
    _pending_dossiers[token] = (time.monotonic() + _DOSSIER_TTL_SEC, ctx)
    return token


def get_dossier(token: str) -> DossierContext | None:
    _purge_expired()
    key = (token or "").strip()
    if not key:
        return None
    entry = _pending_dossiers.get(key)
    if not entry:
        return None
    expires, ctx = entry
    if expires < time.monotonic():
        del _pending_dossiers[key]
        return None
    return ctx
