"""Deep links to NYC Open Data and third-party sources used in PDF dossiers.

All links point at official external sources (never localhost) and open pages
pre-filtered to the scanned address, scan radius, or exact dossier record.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from models.schemas import Coordinate

_BASE = "https://data.cityofnewyork.us"

_DATASETS: dict[str, dict[str, object]] = {
    "crime": {
        "id": "5uac-w243",
        "path": "Public-Safety/NYPD-Complaint-Data-Current-Year-To-Date-/5uac-w243",
        "id_field": "cmplnt_num",
        "geo_mode": "within_circle",
        "geo_field": "lat_lon",
        "date_field": "cmplnt_fr_dt",
        "date_cast": "floating_timestamp",
        "order_field": "cmplnt_fr_dt",
        "label": "NYPD Complaint Data (NYC Open Data)",
        "select": "cmplnt_num,cmplnt_fr_dt,ofns_desc,pd_desc,boro_nm,latitude,longitude",
    },
    "311": {
        "id": "erm2-nwe9",
        "path": "Social-Services/311-Service-Requests-from-2010-to-Present/erm2-nwe9",
        "id_field": "unique_key",
        "geo_mode": "within_circle",
        "geo_field": "location",
        "address_field": "incident_address",
        "date_field": "created_date",
        "date_cast": "floating_timestamp",
        "order_field": "created_date",
        "label": "311 Service Requests (NYC Open Data)",
        "select": "unique_key,created_date,complaint_type,descriptor,borough,incident_address,latitude,longitude",
    },
    "permits": {
        "id": "ipu4-2q9a",
        "path": "Housing-Development/DOB-Permit-Issuance/ipu4-2q9a",
        "id_field": "job__",
        "geo_mode": "borough",
        "borough_field": "borough",
        "address_field": "street_name",
        "date_field": None,
        "order_field": "filing_date",
        "label": "DOB Permit Issuance (NYC Open Data)",
        "select": "job__,filing_date,permit_type,permit_status,street_name,borough,gis_latitude,gis_longitude",
    },
    "evictions": {
        "id": "6z8x-wfk4",
        "path": "City-Government/Evictions/6z8x-wfk4",
        "id_field": "docket_number",
        "alt_id_field": "court_index_number",
        "geo_mode": "borough",
        "borough_field": "borough",
        "address_field": "eviction_address",
        "date_field": "executed_date",
        "date_cast": "floating_timestamp",
        "order_field": "executed_date",
        "label": "Evictions (NYC Open Data)",
        "select": "court_index_number,docket_number,eviction_address,executed_date,borough,latitude,longitude",
    },
}

_HPD_VIOLATIONS: dict[str, str] = {
    "path": "Housing-Development/Housing-Maintenance-Code-Violations/wvxf-dwi5",
    "select": (
        "violationid,housenumber,streetname,boro,class,novdescription,"
        "novissueddate,currentstatus,violationstatus,apartment"
    ),
    "order_field": "novissueddate",
}

_CARD_DATASET_KEYS: dict[str, list[str]] = {
    "high_churn": ["evictions"],
    "police_calls": ["crime"],
    "area_safety": ["crime"],
    "demolitions": ["permits", "311"],
    "noise_schedule": ["311"],
    "reports_311": ["311"],
}

CARD_DATASET_KEYS = _CARD_DATASET_KEYS

_BOROUGH_ALIASES: dict[str, tuple[str, ...]] = {
    "MANHATTAN": ("MANHATTAN", "NEW YORK"),
    "BROOKLYN": ("BROOKLYN", "KINGS"),
    "QUEENS": ("QUEENS",),
    "BRONX": ("BRONX",),
    "STATEN ISLAND": ("STATEN ISLAND", "RICHMOND", "STATEN"),
}

_STREET_SUFFIX_RE = re.compile(
    r"\b(STREET|ST|AVENUE|AVE|ROAD|RD|BOULEVARD|BLVD|PLACE|PL|DRIVE|DR|LANE|LN|COURT|CT|WAY|TERRACE|TER)\b",
    re.IGNORECASE,
)

_HOUSE_STREET_RE = re.compile(r"^(\d+[A-Z]?)\s+(.+)$", re.IGNORECASE)
_ICAO_FROM_LABEL_RE = re.compile(r"\(([a-f0-9]{6})\b", re.IGNORECASE)

_RECORD_LIMIT = 10
_BROWSE_LIMIT = 200
_MAX_ID_CLAUSES = 50


def _soql_escape(value: str) -> str:
    return (value or "").replace("'", "''")


def _since_timestamp(days_back: int) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    return since.strftime("%Y-%m-%dT%H:%M:%S")


def _explore_url(dataset_key: str, soql: str) -> str:
    path = str(_DATASETS[dataset_key]["path"])
    return f"{_BASE}/{path}/explore/query/{quote(soql, safe='')}"


def _hpd_explore_url(soql: str) -> str:
    path = _HPD_VIOLATIONS["path"]
    return f"{_BASE}/{path}/explore/query/{quote(soql, safe='')}"


def _select_soql(
    dataset_key: str,
    *,
    where: str,
    limit: int,
    order: bool = True,
) -> str:
    meta = _DATASETS[dataset_key]
    select = str(meta["select"])
    order_field = str(meta["order_field"])
    soql = f"SELECT {select} WHERE {where}"
    if order:
        soql += f" ORDER BY {order_field} DESC"
    soql += f" LIMIT {limit}"
    return soql


def parse_address_parts(formatted_address: str) -> dict[str, str | None]:
    """House number, street token, and borough parsed from a geocoded NYC address."""
    if not formatted_address:
        return {"housenumber": None, "street_token": None, "street_line": None, "borough": None}
    first = formatted_address.split(",")[0].strip()
    match = _HOUSE_STREET_RE.match(first)
    housenumber = match.group(1).upper() if match else None
    street_line = (match.group(2) if match else first).strip()
    street_token = street_token_from_address(formatted_address)
    return {
        "housenumber": housenumber,
        "street_token": street_token,
        "street_line": street_line,
        "borough": borough_from_address(formatted_address),
    }


def street_token_from_address(formatted_address: str) -> str | None:
    """Core street name token for LIKE filters (e.g. LEFFERTS from 742 Lefferts Ave)."""
    if not formatted_address:
        return None
    first = formatted_address.split(",")[0].strip().upper()
    without_number = re.sub(r"^\d+[A-Z]?\s*", "", first).strip()
    without_suffix = _STREET_SUFFIX_RE.sub("", without_number).strip()
    parts = [p for p in without_suffix.split() if p]
    if not parts:
        return None
    # "W 42ND" / "EAST 14" — prefer the numeric street name over a compass prefix.
    if len(parts) >= 2 and parts[0] in {"N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST"}:
        if re.search(r"\d", parts[1]):
            token = parts[1]
        else:
            token = parts[1]
    else:
        token = parts[0]
    # HPD/Open Data store numbered streets as "WEST 42 STREET", not "42ND".
    token = re.sub(r"^(\d+)(ST|ND|RD|TH)$", r"\1", token)
    token = token.strip(" .")
    return token if len(token) >= 2 else None


def borough_from_address(formatted_address: str) -> str | None:
    """Best-effort NYC borough label for SODA filters."""
    upper = (formatted_address or "").upper()
    if "STATEN ISLAND" in upper or re.search(r",\s*STATEN\b", upper):
        return "STATEN ISLAND"
    if "BROOKLYN" in upper:
        return "BROOKLYN"
    if "QUEENS" in upper:
        return "QUEENS"
    if "BRONX" in upper:
        return "BRONX"
    if re.search(r"\bMANHATTAN\b", upper):
        return "MANHATTAN"
    if re.search(r",\s*NEW YORK(?:,|\s+\d)", upper):
        return "MANHATTAN"
    return None


def _borough_where(dataset_key: str, borough: str) -> str:
    meta = _DATASETS[dataset_key]
    field = str(meta.get("borough_field", "borough"))
    aliases = _BOROUGH_ALIASES.get(borough.upper(), (borough.upper(),))
    if len(aliases) == 1:
        return f"{field}='{_soql_escape(aliases[0])}'"
    inner = " OR ".join(f"{field}='{_soql_escape(alias)}'" for alias in aliases)
    return f"({inner})"


def _geo_where(
    dataset_key: str,
    coord: Coordinate,
    radius_miles: float,
    *,
    borough: str | None = None,
) -> str:
    meta = _DATASETS[dataset_key]
    mode = meta.get("geo_mode", "")
    if mode == "within_circle":
        radius_m = radius_miles * 1609.344
        field = meta["geo_field"]
        return f"within_circle({field}, {coord.lat:.6f}, {coord.lng:.6f}, {radius_m:.0f})"
    if mode == "borough" and borough:
        return _borough_where(dataset_key, borough)
    return "1=1"


def _date_where(dataset_key: str, days_back: int) -> str | None:
    meta = _DATASETS[dataset_key]
    field = meta.get("date_field")
    if not field:
        return None
    # Match city_data._since_socrata / live fetch: >= ISO timestamp, no cast.
    # The :: floating_timestamp cast is unnecessary and has blanked explore pages.
    since = _since_timestamp(days_back)
    return f"{field} >= '{since}'"


def _address_where(dataset_key: str, formatted_address: str) -> str | None:
    meta = _DATASETS[dataset_key]
    field = meta.get("address_field")
    token = street_token_from_address(formatted_address)
    if not field or not token:
        return None
    escaped = _soql_escape(token)
    if dataset_key == "permits":
        return f"upper({field}) like '%{escaped}%'"
    return f"upper({field}) like '%{escaped}%'"


def _id_clause(dataset_key: str, source_id: str) -> str | None:
    raw = (source_id or "").strip()
    if not raw:
        return None
    meta = _DATASETS[dataset_key]
    field = str(meta["id_field"])
    if dataset_key == "permits":
        raw = raw.split("_", 1)[0]
    # All NYC Open Data id fields used here are text (cmplnt_num, unique_key,
    # job__, docket_number). Unquoted numeric SoQL causes type-mismatch 400s
    # and blank explore pages for table "View" links.
    value = _soql_escape(raw)
    clause = f"{field}='{value}'"
    alt = meta.get("alt_id_field")
    if alt and "/" in raw:
        alt_val = _soql_escape(raw)
        clause = f"({clause} OR {alt}='{alt_val}')"
    return clause


def dataset_home_url(dataset_key: str) -> str:
    return f"{_BASE}/{_DATASETS[dataset_key]['path']}"


def dataset_label(dataset_key: str) -> str:
    return str(_DATASETS[dataset_key]["label"])


def _browse_where_parts(
    dataset_key: str,
    coord: Coordinate,
    *,
    radius_miles: float,
    days_back: int | None,
    formatted_address: str,
) -> list[str]:
    borough = borough_from_address(formatted_address)
    parts: list[str] = []

    addr = _address_where(dataset_key, formatted_address)
    if addr:
        parts.append(addr)

    geo = _geo_where(dataset_key, coord, radius_miles, borough=borough)
    if geo != "1=1":
        parts.append(geo)

    # Crime YTD feed often has no incidents inside a short rolling window for a
    # given block even when nearby older YTD rows exist. Date-filtering browse
    # links then opens a blank NYC Open Data table. Prefer exact dossier IDs
    # when available; for open browse, keep area/geo filters only for crime.
    if days_back is not None and dataset_key != "crime":
        date_part = _date_where(dataset_key, days_back)
        if date_part:
            parts.append(date_part)

    return parts


def record_url(dataset_key: str, source_id: str) -> str | None:
    """NYC Open Data explorer filtered to one dossier record."""
    clause = _id_clause(dataset_key, source_id)
    if not clause:
        return None
    soql = _select_soql(dataset_key, where=clause, limit=_RECORD_LIMIT)
    return _explore_url(dataset_key, soql)


def dossier_records_url(dataset_key: str, source_ids: list[str]) -> str | None:
    """NYC Open Data explorer filtered to exact dossier record IDs."""
    clauses: list[str] = []
    seen: set[str] = set()
    for raw_id in source_ids:
        sid = (raw_id or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        clause = _id_clause(dataset_key, sid)
        if clause:
            clauses.append(clause)
        if len(clauses) >= _MAX_ID_CLAUSES:
            break
    if not clauses:
        return None
    where = clauses[0] if len(clauses) == 1 else "(" + ") OR (".join(clauses) + ")"
    soql = _select_soql(
        dataset_key,
        where=where,
        limit=min(_BROWSE_LIMIT, max(len(clauses), 1)),
    )
    return _explore_url(dataset_key, soql)


def radius_browse_url(
    dataset_key: str,
    coord: Coordinate,
    *,
    radius_miles: float,
    days_back: int | None = None,
    formatted_address: str = "",
    source_ids: list[str] | None = None,
) -> str:
    """NYC Open Data explorer filtered to the scan area around the subject address."""
    if source_ids:
        exact = dossier_records_url(dataset_key, source_ids)
        if exact:
            return exact

    parts = _browse_where_parts(
        dataset_key,
        coord,
        radius_miles=radius_miles,
        days_back=days_back,
        formatted_address=formatted_address,
    )
    if not parts:
        return dataset_home_url(dataset_key)

    soql = _select_soql(
        dataset_key,
        where=" AND ".join(parts),
        limit=_BROWSE_LIMIT,
    )
    return _explore_url(dataset_key, soql)


def card_dataset_urls(
    card_id: str,
    coord: Coordinate,
    *,
    radius_miles: float,
    crime_days: int,
    reports_311_days: int,
    permit_days: int,
    eviction_days: int,
    formatted_address: str = "",
    dossier_ids: dict[str, list[str]] | None = None,
) -> list[tuple[str, str, str]]:
    windows = {
        "crime": crime_days,
        "311": reports_311_days,
        "permits": permit_days,
        "evictions": eviction_days,
    }
    ids_by_key = dossier_ids or {}
    out: list[tuple[str, str, str]] = []
    for key in _CARD_DATASET_KEYS.get(card_id, []):
        days = windows.get(key)
        ids = ids_by_key.get(key, [])
        url = radius_browse_url(
            key,
            coord,
            radius_miles=radius_miles,
            days_back=days,
            formatted_address=formatted_address,
            source_ids=ids or None,
        )
        out.append((dataset_label(key), url, key))
    return out


def opensky_track_url(icao24: str, observed_at: str = "") -> str | None:
    icao = (icao24 or "").strip().lower()
    if not icao:
        return None
    return f"https://opensky-network.org/aircraft-profile?icao24={quote(icao)}"


def opensky_area_url(coord: Coordinate, *, radius_miles: float) -> str:
    """OpenSky Network explorer centered on the scan area."""
    lat_delta = radius_miles / 69.0
    lng_delta = radius_miles / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
    lamin = coord.lat - lat_delta
    lamax = coord.lat + lat_delta
    lomin = coord.lng - lng_delta
    lomax = coord.lng + lng_delta
    return (
        "https://opensky-network.org/network/explorer/"
        f"lamin/{lamin:.6f}/lomin/{lomin:.6f}/lamax/{lamax:.6f}/lomax/{lomax:.6f}"
    )


def opensky_track_from_label(label: str) -> str | None:
    match = _ICAO_FROM_LABEL_RE.search(label or "")
    if not match:
        return None
    return opensky_track_url(match.group(1))


def hpd_violations_url(formatted_address: str = "") -> str:
    """HPD housing violations on NYC Open Data filtered to the subject address."""
    parts = parse_address_parts(formatted_address)
    clauses: list[str] = []
    if parts.get("housenumber"):
        clauses.append(f"housenumber='{_soql_escape(str(parts['housenumber']))}'")
    token = parts.get("street_token")
    if token:
        clauses.append(f"upper(streetname) like '%{_soql_escape(str(token).upper())}%'")
    borough = parts.get("borough")
    if borough:
        clauses.append(f"upper(boro)='{_soql_escape(str(borough).upper())}'")
    if not clauses:
        return "https://hpdonline.nyc.gov/hpdonline/"
    where = " AND ".join(clauses)
    soql = (
        f"SELECT {_HPD_VIOLATIONS['select']} WHERE {where} "
        f"ORDER BY {_HPD_VIOLATIONS['order_field']} DESC LIMIT {_BROWSE_LIMIT}"
    )
    return _hpd_explore_url(soql)


def dining_listing_url(card: dict, formatted_address: str = "") -> str | None:
    """Business-specific Yelp or Google Maps listing for a dining row."""
    direct = (card.get("url") or "").strip()
    if direct:
        return direct
    name = (card.get("name") or "").strip()
    if not name:
        return None
    coords = card.get("coordinates") if isinstance(card.get("coordinates"), dict) else {}
    lat = coords.get("lat")
    lng = coords.get("lng")
    source = str(card.get("source") or "")
    if source == "yelp":
        loc = formatted_address or (f"{lat},{lng}" if lat is not None and lng is not None else "")
        if not loc:
            return None
        return (
            "https://www.yelp.com/search?"
            f"find_desc={quote(name)}&find_loc={quote(loc)}"
        )
    query = f"{name} near {formatted_address}" if formatted_address else name
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def dining_area_url(formatted_address: str, coord: Coordinate) -> str:
    """Google Maps search for restaurants near the scanned address."""
    if formatted_address:
        query = f"restaurants near {formatted_address}"
    else:
        query = f"restaurants near {coord.lat:.5f},{coord.lng:.5f}"
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"
