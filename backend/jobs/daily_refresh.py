"""
Daily NYC Open Data Refresh Job
─────────────────────────────────
Uses requests for ALL HTTP calls (Socrata + Supabase REST API).
This avoids the httpx DNS bug on macOS entirely.

Run manually:
  python -m jobs.daily_refresh
"""

import os
import time
import requests
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("daily_refresh")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SOCRATA_BASE = "https://data.cityofnewyork.us/resource"

DATASETS = {
    "crime":   "5uac-w243",
    "reports": "erm2-nwe9",
    "permits": "ipu4-2q9a",
}

BATCH_SIZE = 50_000
DAYS_BACK = 30
PERMIT_DAYS_BACK = 90


# ── Supabase REST helpers (pure requests, no httpx) ───────────────────────────

def _supa_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _supa_upsert(table: str, records: list[dict]):
    """Upsert records into a Supabase table. Retries up to 4 times on network errors."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    for i in range(0, len(records), 1000):
        batch = records[i:i+1000]
        for attempt in range(4):
            try:
                resp = requests.post(url, json=batch, headers=_supa_headers(), timeout=30)
                if not resp.ok:
                    logger.warning(f"Upsert warning on {table}: {resp.status_code} — {resp.text[:200]}")
                break
            except Exception as e:
                if attempt < 3:
                    wait = 2 ** attempt
                    logger.warning(f"Upsert attempt {attempt+1} failed, retrying in {wait}s... ({e})")
                    time.sleep(wait)
                else:
                    logger.error(f"Upsert failed after 4 attempts on {table}: {e}")
                    raise


def _supa_delete_old(table: str, column: str, cutoff: str):
    """Delete records older than cutoff. Non-fatal — skipped if connection fails."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}?{column}=lt.{cutoff}"
        resp = requests.delete(url, headers=_supa_headers(), timeout=30)
        if not resp.ok:
            logger.warning(f"Delete warning on {table}: {resp.status_code}")
    except Exception as e:
        logger.warning(f"Delete skipped for {table} (non-fatal): {e}")


# ── Socrata fetcher ───────────────────────────────────────────────────────────

def _fetch_socrata(dataset_id: str, where: str) -> list[dict]:
    url = f"{SOCRATA_BASE}/{dataset_id}.json"
    resp = requests.get(url, params={
        "$where": where,
        "$limit": BATCH_SIZE,
        "$order": ":id",
    }, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ── Refresh functions ─────────────────────────────────────────────────────────

def refresh_crime() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%S")
    logger.info("Fetching NYPD crime data...")
    rows = _fetch_socrata(DATASETS["crime"], f"cmplnt_fr_dt >= '{cutoff}'")

    records = []
    for row in rows:
        try:
            lat = float(row.get("latitude") or 0)
            lng = float(row.get("longitude") or 0)
            if not lat or not lng:
                continue
            records.append({
                "lat": lat, "lng": lng,
                "crime_type": row.get("ofns_desc", "Unknown"),
                "description": row.get("pd_desc", ""),
                "occurred_at": row.get("cmplnt_fr_dt"),
                "borough": row.get("boro_nm", ""),
                "source_id": row.get("cmplnt_num", ""),
            })
        except (ValueError, TypeError):
            continue

    _supa_upsert("crime_reports", records)
    old_cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).isoformat()
    _supa_delete_old("crime_reports", "occurred_at", old_cutoff)
    logger.info(f"Crime refresh complete: {len(records)} records.")
    return len(records)


def refresh_311() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%S")
    logger.info("Fetching 311 reports...")
    rows = _fetch_socrata(DATASETS["reports"], f"created_date >= '{cutoff}'")

    records = []
    for row in rows:
        try:
            lat = float(row.get("latitude") or 0)
            lng = float(row.get("longitude") or 0)
            if not lat or not lng:
                continue
            records.append({
                "lat": lat, "lng": lng,
                "complaint_type": row.get("complaint_type", "Unknown"),
                "descriptor": row.get("descriptor", ""),
                "created_at": row.get("created_date"),
                "borough": row.get("borough", ""),
                "source_id": row.get("unique_key", ""),
            })
        except (ValueError, TypeError):
            continue

    _supa_upsert("reports_311", records)
    old_cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).isoformat()
    _supa_delete_old("reports_311", "created_at", old_cutoff)
    logger.info(f"311 refresh complete: {len(records)} records.")
    return len(records)


def refresh_permits() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PERMIT_DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%S")
    logger.info("Fetching DOB permits...")
    rows = _fetch_socrata(DATASETS["permits"], f"filing_date >= '{cutoff}'")

    records = []
    for row in rows:
        try:
            lat = float(row.get("latitude") or 0)
            lng = float(row.get("longitude") or 0)
            if not lat or not lng:
                continue
            records.append({
                "lat": lat, "lng": lng,
                "permit_type": row.get("permit_type", "Unknown"),
                "permit_status": row.get("permit_status", ""),
                "job_description": row.get("job_description1", ""),
                "filing_date": row.get("filing_date"),
                "expiration_date": row.get("expiration_date"),
                "source_id": row.get("job__", "") + "_" + row.get("permit_type", ""),
            })
        except (ValueError, TypeError):
            continue

    _supa_upsert("building_permits", records)
    old_cutoff = (datetime.now(timezone.utc) - timedelta(days=PERMIT_DAYS_BACK)).isoformat()
    _supa_delete_old("building_permits", "filing_date", old_cutoff)
    logger.info(f"Permits refresh complete: {len(records)} records.")
    return len(records)


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("Supabase credentials not set. Check your .env file.")
        return

    logger.info("Starting daily NYC data refresh...")
    results = {}

    try:
        results["crime"] = refresh_crime()
    except Exception as e:
        logger.error(f"Crime refresh failed: {e}")
        results["crime"] = 0

    logger.info("Pausing 5 seconds before next dataset...")
    time.sleep(5)

    try:
        results["311"] = refresh_311()
    except Exception as e:
        logger.error(f"311 refresh failed: {e}")
        results["311"] = 0

    logger.info("Pausing 5 seconds before next dataset...")
    time.sleep(5)

    try:
        results["permits"] = refresh_permits()
    except Exception as e:
        logger.error(f"Permits refresh failed: {e}")
        results["permits"] = 0

    logger.info(
        f"All done — Crime: {results['crime']}, 311: {results['311']}, Permits: {results['permits']}"
    )


if __name__ == "__main__":
    run_all()
