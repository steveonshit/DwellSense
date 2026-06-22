# DwellSense — Project Overview

This document describes the **DwellSense** codebase, architecture, deployment, and work completed during setup (GitHub, Railway, Vercel, debugging). It is the **canonical overview** for contributors and for tools like **Claude Code** (read this file first).

---

## What DwellSense Is

**DwellSense** is a NYC-focused “real estate forensics” web app. A user enters an address; the system:

- Geocodes the address (Mapbox)
- Pulls nearby **crime**, **311**, **permits**, and **evictions** from **Supabase** (pre-loaded via a daily job)
- Fetches **transit / grocery / retail** proximity via **Google Places API (New)**
- Ranks the **top 4 restaurants & bars within 2 miles** via **Yelp Fusion API** (preferred) or **Google Places API (New)** fallback — real ratings + review counts, no invented rankings
- Computes **flight overlays** (`FLIGHT_MODE`: **`auto`** prefers stable Supabase `adsb_samples` polylines from completed time buckets, else no paths; **`static`** corridors only; **`live_adsb`** optional OpenSky per scan) and a **prototype flight exposure summary** (`flight_exposure`) when ingestion data exists
- Builds a **Wellness Score** (0–100, where **100 is best**), **risk labels**, and **threat-card chrome** (titles, colors, emojis) in **Python**; **Google Gemini** writes only the **27 bullet strings** (three per card) from the same data brief
- Renders results on a **Mapbox** map and carousels

Tagline: *Don’t sign a blind lease.*

---

## Data integrity (non-negotiable)

**ALWAYS USE REAL DATA. NEVER FAKE OR MAKE UP ANY DATA.**

Every user-visible number, pin, score input, listing, and map marker must trace to a **real source** (NYC Open Data / Supabase municipal tables, Google Places, Yelp, Mapbox geocoding, ADS-B ingest, etc.).

| Rule | Requirement |
|------|-------------|
| **No invented records** | Do not place pins, counts, or incidents that are not in the fetched datasets. |
| **No synthetic fallbacks on the map** | Do not draw heuristic flight corridors, random jitter, or demo swarms when live data is missing — show **nothing** or label **unavailable**. |
| **Truncation must be honest** | If the map shows a subset of real locations for readability, the UI must say so (e.g. “Showing 100 of 1,896 real locations”). Scoring and risk copy still use the **full** in-radius counts. |
| **Unavailable means unavailable** | If an API or table has no data, return empty / `unavailable` — never approximate without clear labeling. |

**Allowed (display-only, not new facts):** great-circle smoothing of **existing** ADS-B vertices for map rendering; merged label when multiple real records share one NYC geocode.

---

## Repository Layout

```
DwellSense/
├── backend/              # Python FastAPI API (includes services/threat_card_layout.py)
├── frontend/             # Next.js 15 + Tailwind + Mapbox GL
│   └── lib/flightPathDisplay.ts  # Display-only flight line shaping (great-circle arcs + smoothing)
├── Dwellsense Final.html # Standalone HTML demo (Leaflet) — not the production app
├── README.md             # Setup: Supabase SQL, env vars, local run
└── project.md            # This file — architecture, deploy, history, roadmap
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 15, React 18, Tailwind CSS, Mapbox GL JS |
| Backend | Python 3.12, FastAPI, Uvicorn, APScheduler |
| Database | Supabase (Postgres) |
| AI | Google Gemini (`gemini-2.5-flash` by default) for **bullets only**; card chrome + score in Python |
| Maps / geo | Mapbox (geocoding + map), Google Places API (New), **Yelp Fusion API** (optional dining), Distance Matrix (if used) |
| Hosting | **Vercel** (frontend), **Railway** (backend) |

### Tech stack in plain English

- **Next.js + React** is the website layer. It renders the landing page, address form, loading ad, score banner, logistics carousel (transit, grocery, **and top dining** in one bar), threat cards, map, pins, and flight visuals.
- **Vercel** hosts the frontend and runs the small **Next.js API route** at `frontend/app/api/scan/route.ts`. That route is intentionally a server-side proxy so the browser does not need to know backend secrets or private URLs.
- **Python + FastAPI** is the backend analysis engine. The main scan endpoint is `POST /scan` in `backend/routers/scan.py`.
- **Railway** hosts the FastAPI backend. Railway owns the runtime for backend environment variables such as `MAPBOX_TOKEN`, `GOOGLE_MAPS_API_KEY`, `GEMINI_API_KEY`, `SUPABASE_URL`, and `SUPABASE_SERVICE_KEY`.
- **Supabase Postgres** is the data store for preloaded municipal and ADS-B data. The app reads recent crime, 311, permits, evictions, and optional flight samples from Supabase.
- **Mapbox** has two roles:
  - server-side geocoding in the backend (`MAPBOX_TOKEN`) turns an address into lat/lng;
  - client-side map rendering in the frontend (`NEXT_PUBLIC_MAPBOX_TOKEN`) displays the interactive Mapbox map.
- **Google Places API (New)** fills the logistics cards: nearby transit, grocery, retail/mall, airport-related proximity, and similar renter-relevant places. It also backs **restaurant/bar rankings** when `YELP_API_KEY` is not set.
- **Yelp Fusion API** (optional `YELP_API_KEY`) is the preferred source for **top restaurants & bars within 2 miles** — Yelp is the most realistic public ranking signal for dining (star rating + review volume).
- **Google Gemini** is not the scoring engine. Gemini writes only the user-facing bullet summaries for the threat cards. The Wellness Score, risk level, labels, card IDs, card colors, titles, and fallback logic are deterministic Python.
- **Two-phase scan (production):** the frontend sends `defer_gemini: true` so `/scan` returns map, score, and fact-locked template bullets quickly; a follow-up **`POST /scan/bullets`** completes Gemini bullet text when ready.
- **APScheduler** runs background jobs inside the backend process: the daily municipal data refresh and, optionally, periodic ADS-B ingestion when `ADSB_INGEST_ENABLED=true`.

### One-minute presentation script (tech stack)

Use this when explaining the system in a 3–5 minute presentation:

> DwellSense is a full-stack web app. The user-facing site is built with Next.js, React, Tailwind, and Mapbox GL, and it is hosted on Vercel. When someone enters an address, the browser calls a Next.js API route, which securely forwards the request to our Python FastAPI backend running on Railway. The backend does the real analysis: it geocodes the address with Mapbox, pulls nearby NYC data from Supabase, calls Google Places for nearby transit and grocery access, ranks the top restaurants and bars within 2 miles (Yelp when configured, else Google Places), computes the Wellness Score in Python, and returns map + score + template bullets quickly. Gemini then refines threat-card bullet text in a follow-up call while the user already reads results. The frontend turns both responses into the score, cards, carousels, map pins, and flight-path visuals.

### Short memorization version

- **Frontend:** Next.js + React on Vercel.
- **Backend:** Python FastAPI on Railway.
- **Data:** Supabase for NYC records and ADS-B samples.
- **Map/geocoding:** Mapbox.
- **Nearby places:** Google Places (+ optional Yelp for dining rankings).
- **AI:** Gemini for text bullets only (deferred in production).
- **Scoring:** deterministic Python, not AI guessing.
- **Scan UX:** two-phase — fast `/scan`, then `/scan/bullets` for Gemini.

---

## Request Flow (Production)

### High-level flow

1. User submits an address on **Vercel** (e.g. `dwellsense.vercel.app`).
2. Browser calls **`POST /api/scan`** on the Next.js app with **`{ address, defer_gemini: true }`** (keeps `BACKEND_URL` server-side).
3. Next.js proxies to **`POST {BACKEND_URL}/scan`** on Railway with a **~290s** upstream timeout; the route declares **`maxDuration = 300`** seconds.
4. Backend runs geocoding, parallel DB + Places calls, flight math, deterministic scoring, and **returns immediately** with template bullets when `defer_gemini=true` (Gemini deferred).
5. JSON response drives the UI (map, logistics/dining proximity bar, threat cards with template bullets).
6. Browser calls **`POST /api/scan/bullets`** with the returned **`bullets_token`**; backend completes Gemini and returns refreshed **`threat_cards`**.

### Detailed address → result lifecycle

1. **User types an address**
   - File: `frontend/components/HeroSection.tsx`
   - Example input: `Apt 4B, 350 W 42nd St, New York, NY`
   - The landing page sends the trimmed address to the client-side scan handler in `frontend/components/HomeClient.tsx` (wrapped by server `frontend/app/page.tsx`).

2. **Browser calls the Next.js API route**
   - File: `frontend/components/HomeClient.tsx`
   - Request: `POST /api/scan`
   - Body: `{ "address": "...", "defer_gemini": true }`
   - Timeout: `AbortSignal.timeout(295_000)` so the browser does not hang forever.

3. **Next.js acts as a secure proxy**
   - File: `frontend/app/api/scan/route.ts`
   - Reads `BACKEND_URL` from server-side environment variables.
   - Forwards the request to `POST {BACKEND_URL}/scan`.
   - Uses `AbortSignal.timeout(290_000)` and `maxDuration = 300` so long scans can finish.
   - If the backend returns an error, it tries to return clean JSON like `{ "error": "..." }` to the browser.

4. **FastAPI receives the scan**
   - File: `backend/routers/scan.py`
   - Model: `ScanRequest` (`address`, optional **`defer_gemini`**, default `false`)
   - Rejects empty addresses early.

5. **Backend geocodes the address**
   - File: `backend/services/geocoding.py`
   - Service: Mapbox Geocoding API.
   - Output: normalized formatted address + `Coordinate(lat, lng)`.
   - Reliability behavior: `httpx.AsyncClient`, `trust_env=False`, separate connect/read timeouts, and retries on transient network failures.

6. **Backend enforces NYC-only scope**
   - File: `backend/routers/scan.py`
   - Checks the coordinate against `NYC_BOUNDS`.
   - If outside bounds, returns `400` with **“Out of reach — NYC addresses only.”**

7. **Backend fetches data in parallel**
   - File: `backend/routers/scan.py`
   - Runs these concurrently with `asyncio.gather(...)`:
     - `city_data.get_nearby_crime(coord)`
     - `city_data.get_nearby_311(coord)`
     - `city_data.get_nearby_permits(coord)`
     - `city_data.get_nearby_evictions(coord)`
     - `places.get_logistics(coord)`
     - `places.get_top_restaurants_bars(coord, limit=4)` — Yelp first if configured, else Google Places

8. **Supabase municipal rows are filtered to a true radius**
   - File: `backend/services/city_data.py`
   - Supabase queries use a fast lat/lng bounding-box prefilter.
   - Returned rows are filtered with Haversine distance to keep only records inside the intended **2 mile** radius.

9. **Noisy 311 categories are filtered**
   - File: `backend/services/city_data.py`
   - Parking / vehicle / traffic-enforcement style 311 noise is excluded from scoring, pins, zones, and Gemini summaries.
   - Reason: high illegal-parking volume is not a reliable renter safety or lease-quality signal.

10. **Backend builds map data**
    - File: `backend/routers/scan.py`
    - `city_data.build_zones(...)` creates map heat zones.
    - `city_data.build_swarm(...)` creates individual emoji-style map pins from **real geocodes** (deterministic shuffle when capped; coordinates never modified).
    - Map permit pins and permit zones use **active** DOB statuses only (`ISSUED`, `ACTIVE`, `RENEWED`); scoring still uses active permit counts separately.
    - 311 sewer / water map labels use the NYC `descriptor` field when available, but visible names stay short: **Sewer Odor**, **Sewer Backup**, **Drain Blockage**, **Water Quality Issue**, **Water Leak**, or **Water Pressure**.
    - `flights.get_flight_paths(...)` creates flight overlays.
    - Result is packed into `MapData`.

11. **Backend computes flight paths**
    - File: `backend/services/flights.py`
    - `FLIGHT_MODE=auto`: use stored Supabase `adsb_samples` polylines from a stable completed time bucket when available; otherwise return **no flight paths** (no synthetic corridors).
    - `FLIGHT_MODE=static`: return only simplified corridor segments (explicit demo mode).
    - `FLIGHT_MODE=live_adsb`: optionally call OpenSky during the scan, with strict budgets; returns real tracks only.

12. **Backend computes optional flight exposure**
    - File: `backend/services/flight_exposure.py`
    - Uses the same `adsb_samples` table to estimate night overflights per hour, day overflights per hour, typical altitude, and data quality.
    - Fail-open rule: if Supabase or ingestion data is unavailable, return `data_quality="unavailable"` instead of crashing `/scan`.

13. **Backend calculates Wellness Score and risk labels (v2)**
    - File: `backend/services/threat_card_layout.py`
    - Score is deterministic Python (**v2**: one percentile model + one 311 adjustment + soft caps + gated plain-language labels).
    - The API field is still named `danger_score`, but the meaning is **Wellness Score**: `100` = best, `0` = worst.
    - Labels: **Terrible → Bad → Average → Good → Very Good → Great → Excellent → Outstanding** (not legacy jargon like “Mixed Signals”).

14. **Backend prepares threat-card chrome**
    - File: `backend/services/threat_card_layout.py`
    - Python controls card IDs, emoji, titles, subtitles, **data-driven border colors**, risk levels, and fallback structure.
    - **`CardChromeContext`** drives border/subtitle colors from actual counts (e.g. green churn when evictions = 0; purple 311 when volume ≥ 200).
    - This keeps the product UI stable even if Gemini is slow or unavailable.

15. **Gemini writes bullet text only (sync or deferred)**
    - File: `backend/services/ai_analysis.py`
    - When **`defer_gemini=false`** (default): Gemini runs inside `/scan` as before.
    - When **`defer_gemini=true`**: `/scan` stores a **`PendingBulletsContext`** in memory (TTL **300s**) and returns **`bullets_token`** + **`gemini_status: "pending"`** with **template bullets** already merged via fact-lock.
    - Client calls **`POST /scan/bullets`** with `{ "bullets_token": "..." }` → **`BulletsResponse`** with refreshed **`threat_cards`** and final **`gemini_status`**.
    - Gemini receives the same data brief and returns JSON shaped like `{ "bullets": { "card_id": ["...", "...", "..."] } }`.
    - **`_finalize_threat_bullets`** / **`_enforce_fact_locked_bullets`** overwrite bullets so every card matches municipal/flight counts (no cross-card contamination).
    - Third bullets use **card-specific** copy when a dataset is empty (not a generic “No recent reports!”).
    - Gemini does not decide the score, risk level, card order, card colors, or map data.
    - If Gemini is missing, slow, blocked, or returns bad JSON, Python merges in fallback bullets and the scan still returns.

16. **Backend returns one structured JSON response**
    - Model: `ScanResponse` in `backend/models/schemas.py`
    - Includes `formatted_address`, `coordinates`, Wellness Score, risk labels, logistics, **`dining`** (top 4 restaurants/bars), threat cards, map data, flight exposure, Gemini debug fields, and (when deferred) **`bullets_token`**.

17. **Frontend waits for scan + loading ad**
    - Files: `frontend/components/HomeClient.tsx`, `frontend/components/LoadingAd.tsx`
    - The loading ad completes only when both conditions are true: the 5-second timer finished and the scan response is ready.

18. **Frontend completes deferred Gemini bullets (when applicable)**
    - File: `frontend/components/HomeClient.tsx`
    - After results render, if **`gemini_status === "pending"`** and **`bullets_token`** is set, the client **`POST`s `/api/scan/bullets`** in the background.
    - **`ThreatCarousel`** shows **“Refining AI summaries…”** while the deferred call runs; on success, **`threat_cards`** update in place. On failure, template bullets remain.

19. **Frontend renders the result**
    - File: `frontend/components/ResultsDashboard.tsx`
    - Components: `DangerBanner` (optional **See 311 breakdown →** chip), `LogisticsCarousel` (transit/grocery + top dining, **dot nav**), `MapComponent`, `ThreatCarousel` (**dot nav**), `SideAds` (**Scan summary** panel on wide screens).
    - The frontend does not recompute the score. It displays the backend response.

20. **Mapbox renders the interactive map**
    - File: `frontend/components/MapComponent.tsx`
    - Displays the NYC-locked viewport, target marker, zones, swarm pins, logistics markers, flight routes, and flight activity chips.
    - **Flight Activity** is always shown; when **`flight_paths` is empty**, explicit copy explains no ADS-B tracks in stored samples (not a map error).
    - Map caption uses **`map_data.scan_radius_miles`** dynamically (e.g. “Showing 100 of N real NYC locations (2-mi)”).
    - Frontend **`filterFlightPathsWithinRadius`** is a safety net aligned with backend scan radius.
    - The map is client-side and uses `NEXT_PUBLIC_MAPBOX_TOKEN`.

21. **PDF dossier (optional download)**
    - Files: `frontend/app/api/pdf/route.ts` → `backend/routers/pdf.py`
    - Proxies the full `ScanResult` JSON; **`_pdf_text()`** normalizes Unicode/emojis for Helvetica (Latin-1 safe).

22. **Flight lines are display-shaped on the client**
    - File: `frontend/lib/flightPathDisplay.ts`
    - This is visual-only shaping. It does not change backend truth data.
    - The display pipeline can densify long segments with great-circle interpolation, round corners, apply centripetal Catmull–Rom sampling, and keep plane animation on the same visible route coordinates.

23. **Site footer (server-rendered)**
    - File: `frontend/components/Footer.tsx` (Server Component)
    - Wrapped by `frontend/app/page.tsx` alongside `HomeClient.tsx` so the copyright year is computed on each request (not baked into the client bundle).

**Scan response extras:**

- `dining` — top **4** ranked restaurants/bars within **2 miles** (`RestaurantBarCard[]`; empty when APIs unavailable)
- `map_data.flight_paths` / `map_data.flight_path` — flight overlays (see **Flights** section: `auto` vs `static` vs `live_adsb`)
- `flight_exposure` — prototype “exposure summary” (may be `unavailable` if Supabase ingestion isn’t running)

**Loading ad (UX):** `frontend/components/LoadingAd.tsx` runs a **5-second** countdown. The ad only completes when **both** the timer hits zero **and** the scan request has finished (`isApiReady`). If the scan takes longer than 5s, the user waits past the ad until data arrives. If they skip the ad early, they still wait until the API returns.

**Deferred Gemini (UX):** Production sends **`defer_gemini: true`**, so users see map + score + template bullets first; **`/api/scan/bullets`** refreshes AI copy afterward. The threat carousel shows **“Refining AI summaries…”** during the second call.

**Client:** `frontend/components/HomeClient.tsx` uses `AbortSignal.timeout(295_000)` on the fetch to `/api/scan` so the UI does not hang forever.

**Health check:** `GET /health` on the backend returns `{"status":"ok","service":"DwellSense API"}`.

**API errors:** `backend/main.py` registers handlers so many unhandled failures return **JSON** (e.g. `{"detail": ...}`) instead of plain-text stack traces — easier for the Next.js proxy and browser clients to parse.

---

## NYC-only Scope (Product Guardrails)

DwellSense is intentionally **NYC-only** right now.

- **Backend enforcement:** `POST /scan` rejects any address that geocodes outside NYC bounds with `400` and message **“Out of reach — NYC addresses only.”**
- **Frontend enforcement:** The Mapbox map is locked to NYC with `maxBounds` + min/max zoom so users **cannot pan/zoom outside the city**.

**Implementation notes (exact values — keep in sync with code):**

Backend `NYC_BOUNDS` in `backend/routers/scan.py` (reject scan if outside this box):

| Key | Value | Note |
|-----|-------|------|
| `lat_min` | `40.4774` | SW corner (approx) |
| `lat_max` | `40.9176` | NE corner (approx) |
| `lng_min` | `-74.2591` | |
| `lng_max` | `-73.7004` | |

Frontend map lock in `frontend/components/MapComponent.tsx` — `maxBounds` as Mapbox **SW → NE** `[lng, lat]` pairs (same rectangle as backend):

- SW: `[-74.2591, 40.4774]`
- NE: `[-73.7004, 40.9176]`
- `minZoom`: `10.5`
- `maxZoom`: `17.5`

If you tighten or widen NYC coverage, update **both** `NYC_BOUNDS` and `NYC_MAX_BOUNDS` so the API and map stay aligned.

---

## Geocoding (Mapbox) — reliability note

Geocoding uses Mapbox **Geocoding API** (`mapbox.places`) via `backend/services/geocoding.py`.

**Implementation (current):**

- **`httpx.AsyncClient`** with **`trust_env=False`** so `HTTP_PROXY` / `HTTPS_PROXY` (common on PaaS and dev laptops) do not hijack outbound TLS to `api.mapbox.com`.
- **Retries:** up to **`MAPBOX_GEOCODE_RETRIES`** attempts (default **4**) with short backoff on **`ConnectTimeout`**, **`ReadTimeout`**, **`ConnectError`**, **`ReadError`**, and on HTTP **429 / 502 / 503 / 504**.
- **Timeouts:** separate connect vs read — **`MAPBOX_GEOCODE_CONNECT_TIMEOUT`** (default **20**s), **`MAPBOX_GEOCODE_READ_TIMEOUT`** (default **35**s), each clamped to sane bounds in code.
- **URL encoding:** the free-text address is passed as a path segment with `urllib.parse.quote(..., safe="")`.
- **Errors:** persistent failure after retries surfaces as **`RuntimeError`** with copy that points to token, egress to `api.mapbox.com:443`, and “try again” (distinct from **`ValueError`** when Mapbox returns 200 but no matching feature).

**Operational note (Railway):** intermittent **`ConnectTimeoutError`** to Mapbox is usually **transient network** or **cold path** from the region; retries often clear it. To prove egress from the **same container** as production, use **`railway ssh`** into the backend service and run `curl` or a one-line `urllib.request` to `https://api.mapbox.com/` (see **Railway CLI** under Deployment). **`railway run`** executes on your **laptop** with Railway env injected — it does **not** test Railway’s outbound network.

---

## What “Nearby” Means (Data Windows + Radius)

This app intentionally uses **recent** municipal signals and a **true 2 mile radius** (configurable via `SCAN_RADIUS_MILES`, default **2**).

### Time windows (intended behavior)

- **Crime**: last **30 days**
- **311**: last **30 days**
- **Permits**: last **90 days**
- **Evictions**: last **180 days**

These windows are applied in **both** the Supabase query path and the NYC Open Data live fallback path.

### Radius (important)

Supabase queries are done as a fast **bounding-box prefilter** (lat/lng rectangle). After results are returned, rows are filtered by **Haversine distance** to keep only points within a true **2 mile** circle.

### 311 noise filtering (NYC reality)

NYC 311 is extremely noisy. DwellSense excludes **parking / vehicle / traffic enforcement** style 311 complaints from:

- scoring
- map pins / zones
- Gemini’s 311 summary brief

Rationale: illegal parking volume is not a meaningful renter safety / lease-quality signal.

### 311 sewer / water label specificity

Water-related 311 complaints are still categorized as the `water` pin type for map styling, but the visible label is more specific when the NYC record includes a useful `descriptor`. Labels should stay **2-3 words max**.

Current label rules in `backend/services/city_data.py`:

- **Sewer Odor** when the complaint or descriptor mentions sewer plus odor / smell / stench.
- **Sewer Backup** when it mentions sewer plus backup / back-up / overflow.
- **Drain Blockage** when it mentions sewer, drain, catch basin, clog, or blockage.
- **Water Quality Issue** when it mentions contamination, dirty / brown / discolored water, or water quality.
- **Water Leak** when it mentions leak or flooding.
- **Water Pressure** when it mentions no water, pressure, or hydrant.
- **Water Issue** / **Sewer Issue** as honest fallbacks when the record is water/sewer-related but does not say the exact problem clearly.

This is a labeling improvement only. It does not invent hazards: labels are derived from `complaint_type` + `descriptor` in the NYC 311 row. The descriptor is used to classify the issue, but it is not appended to the visible map label.

---

## Dining / Restaurants & Bars (Current Behavior)

DwellSense shows the **top 4 ranked restaurants and bars within 2 miles** of the scanned address. Rankings come from real third-party APIs — **no invented scores or fake listings**.

### Why Yelp + Google Places

| Source | When used | Why |
|--------|-----------|-----|
| **Yelp Fusion API** | Preferred when `YELP_API_KEY` is set | Best public signal for dining: star rating, review volume, categories, price tier, Yelp page URL |
| **Google Places API (New)** | Fallback when Yelp is unset, placeholder, or returns nothing | Reuses existing `GOOGLE_MAPS_API_KEY`; `restaurant` + `bar` nearby search with `POPULARITY` ranking |

### API integration

**Yelp** (`backend/services/places.py`):

- Endpoint: `GET https://api.yelp.com/v3/businesses/search`
- Auth: `Authorization: Bearer {YELP_API_KEY}`
- Params: `latitude`, `longitude`, `radius` (3219 m = 2 mi), `categories=restaurants,bars`, `limit=20`, `sort_by=rating`
- Docs: [Yelp Fusion — Business Search](https://www.yelp.com/developers/documentation/v3/business_search)

**Google Places (New)** fallback:

- Endpoint: `POST https://places.googleapis.com/v1/places:searchNearby`
- Types: `restaurant`, `bar`
- Radius: **3219 m** (2 miles)
- Field mask includes `rating`, `userRatingCount`, `primaryTypeDisplayName`, `googleMapsUri`, `priceLevel`, `businessStatus`
- Skips non-`OPERATIONAL` businesses

### Ranking (conservative, not “nearest”)

After fetching up to 20 candidates, the backend:

1. Filters to a true **2-mile** Haversine circle (API radius alone is not trusted blindly).
2. Computes `ranking_score` in `_ranking_score()`:
   - **Rating** is primary (`× 0.78`).
   - **Review volume** adds confidence via `log10(reviews + 1)` capped at ~500 reviews (`× 1.15`).
   - **Distance** is only a small tie-breaker (`− distance_miles × 0.08`) because the product promise is “best within 2 miles,” not “closest.”
3. Sorts by `ranking_score`, then `rating`, then `review_count`; returns top **4**.

### API shape (`dining[]`)

Each `RestaurantBarCard` (`backend/models/schemas.py`):

| Field | Meaning |
|-------|---------|
| `name` | Business name |
| `category` | Yelp category title or Google `primaryTypeDisplayName` |
| `rating` | Star rating (may be `null`) |
| `review_count` | Review count (may be `null`) |
| `price_level` | `$`–`$$$$` when available |
| `distance_value` / `distance_unit` | Haversine distance from property (`feet` if &lt; 0.5 mi, else `miles`) |
| `coordinates` | `{ lat, lng }` for the venue |
| `source` | `"yelp"` or `"google_places"` |
| `url` | Yelp business URL or Google Maps URI |
| `ranking_score` | Internal sort key (exposed for debugging/transparency) |

### UI

- Merged into the proximity bar via `frontend/lib/proximityCards.ts` and `LogisticsCarousel.tsx` (top 4 dining cards appended to transit/grocery cards in one carousel).
- Venue names use **two-line clamp** + **`title` tooltip** on hover for long names.
- Shows rank (#1–#4), name, category, rating, review count, distance, source label, and external link.
- Empty state: **“Restaurant/bar rankings unavailable from the configured place APIs.”** (no placeholder venues)

### Local / production setup

1. **Minimum (works today):** set a real `GOOGLE_MAPS_API_KEY` — dining uses Google Places fallback.
2. **Recommended for dining quality:** create a Yelp app at [yelp.com/developers](https://www.yelp.com/developers), then set `YELP_API_KEY` in `backend/.env` (local) or Railway Variables (production).
3. Dining runs in parallel with logistics inside `asyncio.gather` in `backend/routers/scan.py` — it does not block municipal or flight work.

**Commit:** `83cd8c6` — *Add top 4 ranked restaurants/bars within 2 miles*

**Production status (verified):** pushed to `main`; auto-deployed to Railway + Vercel. `POST /scan` returns `dining` with up to **4** items (Google Places fallback when `YELP_API_KEY` is unset). Dining cards appear **inside** the logistics proximity carousel (hard-refresh + new scan).

**Quick production check:**

```bash
curl -s -X POST 'https://dwellsense.vercel.app/api/scan' \
  -H 'Content-Type: application/json' \
  --data '{"address":"350 W 42nd St, New York, NY"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('dining') or []), (d.get('dining') or [{}])[0].get('name'))"
```

Expected: `4` and a real venue name (not an error).

---

## Environment Variables

### Backend (Railway / local)

| Variable | Purpose |
|----------|---------|
| `MAPBOX_TOKEN` | **Server-side** Mapbox token for **geocoding** (`/scan` address → lat/lng). Distinct from `NEXT_PUBLIC_MAPBOX_TOKEN` on the frontend. |
| `MAPBOX_GEOCODE_RETRIES` | Optional. Integer **1–8**, default **4**. Retries Mapbox on timeouts / connection errors / retryable HTTP codes. |
| `MAPBOX_GEOCODE_CONNECT_TIMEOUT` | Optional. Seconds (clamped in code), default **20**. TLS/TCP connect budget to `api.mapbox.com`. |
| `MAPBOX_GEOCODE_READ_TIMEOUT` | Optional. Seconds (clamped in code), default **35**. Read budget after connect. |
| `GOOGLE_MAPS_API_KEY` | Places API (New) — transit, grocery, Target, **shopping_mall** (nearest mall), **restaurant/bar fallback rankings**, etc. **Must be a real key, not a placeholder.** |
| `YELP_API_KEY` | Optional. **Yelp Fusion API** — preferred source for top restaurants & bars within 2 miles (`/v3/businesses/search`). If unset or placeholder, dining falls back to Google Places. |
| `GEMINI_API_KEY` | AI threat analysis |
| `GEMINI_MODEL` | Optional. Gemini model name used for bullets. Defaults to **`gemini-2.5-flash`**. |
| `GEMINI_MAX_OUTPUT_TOKENS` | Optional. Output token budget for Gemini JSON. Defaults to **4096**. Too-low values can truncate JSON and cause parse failures. |
| `GEMINI_TIMEOUT_SECONDS` | Optional. Seconds for `asyncio.wait_for` around Gemini (default **300**). Set **`0`** to disable the asyncio timeout guard (still subject to upstream/Vercel/Railway limits). See `backend/.env.example`. |
| `SUPABASE_URL` | Database URL |
| `SUPABASE_SERVICE_KEY` | Service role key (not anon) |
| `FRONTEND_URL` | CORS — set to **`https://dwellsense.vercel.app`** in production (not `localhost`) |
| `SCAN_RADIUS_MILES` | Optional. **0.25–10**, default **2**. True Haversine radius for municipal fetches, map caption, flight-path clip, and exposure default. |
| `MAP_SWARM_MAX_PINS` | Optional. **20–200**, default **100**. Max map pins rendered; **`swarm_location_total`** still reports full unique geocodes in radius. |
| `PORT` | Railway sets this automatically |
| `OPENSKY_USERNAME` | Optional. OpenSky username (higher rate limits for ADS‑B). |
| `OPENSKY_PASSWORD` | Optional. OpenSky password. |
| `FLIGHT_MODE` | **`auto`** (default): Supabase `adsb_samples` polylines when ingest has data in the stable completed query window; else **no paths**. **No OpenSky during `/scan` on the happy path.** **`static`:** corridors only (explicit demo dashed segments). **`live_adsb`:** capped OpenSky `states` + sequential `tracks` per scan (optional; can be slow); real tracks only. Legacy alias **`adsb`** is normalized to **`auto`**. See `backend/services/flights.py`. |
| `ADSB_PATH_DAYS` | Optional. **1–14**, default **7**. How far back stored samples are queried for polylines. |
| `ADSB_PATH_STABILITY_BUCKET_MINUTES` | Optional. **5–1440**, default **60**. Freezes stored path selection to completed time buckets so repeated scans of the same address do not rotate live aircraft every few seconds. |
| `ADSB_PATH_STABILITY_LAG_MINUTES` | Optional. **0–1440**, default **0** in code; production currently uses **15**. Adds lag before the completed bucket cutoff so scans use fully-ingested data. |
| `FLIGHT_PATH_MAX_RADIUS_MILES` | **Deprecated / ignored.** Flight paths clip to **`SCAN_RADIUS_MILES`**. Remove from Railway if still set. |
| `ADSB_PATH_BBOX_MILES` | Optional. **5–40**, default **~8** (max radius + 2). Bounding box half-extent around the property for the Supabase filter. |
| `ADSB_PATH_MIN_POINTS` | Optional. **5–20**, default **5**. Minimum raw samples per ICAO to include a track; output paths also preserve at least this many real vertices after cleanup. |
| `ADSB_PATH_MAX_POINTS` | Optional. **8–80**, default **40**. Even decimation cap per aircraft before cleanup. |
| `ADSB_PATH_ROW_LIMIT` | Optional. **2000–25000**, default **15000**. Max rows returned from `adsb_samples` for one scan’s query. |
| `ADSB_PATH_MAX_GAP_MINUTES` | Optional. **20–720**, default **120**. Splits a stored ADS-B series when consecutive samples are too far apart in time, preventing separate flights with the same ICAO from being stitched into one line. |
| `ADSB_PATH_BLIND_JUMP_MILES` | Optional. **0–200**, default **0**. When timestamps are missing, split a stored path if consecutive points jump farther than this many miles. `0` disables this missing-timestamp split. |
| `ADSB_PATH_KEEP_NEAR_MILES` | Optional. **1–25**, default **5** (capped by **`SCAN_RADIUS_MILES`**). Keeps one contiguous pass near the scan address instead of drawing a long unrelated track segment. |
| `ADSB_PATH_KEEP_PAD_POINTS` | Optional. **0–30**, default **6**. Adds context points before/after the near-property pass so tracks do not look abruptly clipped. |
| `ADSB_PATH_SPIKE_MIN_TURN_DEG` | Optional. **90–175**, default **148**. Sharp-turn threshold for dropping tiny local zig-zag spikes from noisy ADS-B samples. |
| `ADSB_PATH_SPIKE_MAX_LEG_MI` | Optional. **0–1**, default **0.22**. Only drop sharp turns when both nearby legs are short enough to look like local jitter. `0` disables spike removal. |
| `ADSB_PATH_DEDUPE_MIN_SEP_MI` | Optional. **0–0.5**, default **0.045**. Drop consecutive vertices closer than this (miles). |
| `ADSB_PATH_MAX_IMPLIED_MPH` | Optional. **200–900**, default **620**. Drop vertices that imply impossible speed vs timestamps. |
| `ADSB_PATH_DP_EPSILON_MILES` | Optional. **0–3**, default **0.52**. Douglas–Peucker simplification tolerance (miles); reduces zigzag. **`0`** disables DP. |
| `ADSB_PATH_SMOOTH_PASSES` | Optional. **0–4**, default **2**. Light 3-tap moving average on interior vertices after DP. **`0`** disables. |
| `OPENSKY_MAX_TRACK_FETCHES` | Optional. **1–5**, default **3**. `live_adsb`: how many closest ICAOs get `tracks/all` fetches. |
| `OPENSKY_TRACK_TIMEOUT_SECONDS` | Optional. **3–12**, default **5**. Per-track fetch budget. |
| `OPENSKY_SCAN_BUDGET_SECONDS` | Optional. **8–45**, default **18**. Total `asyncio.wait_for` budget around live OpenSky path building for one scan. |
| `ADSB_INGEST_ENABLED` | Optional. `true` to run provider snapshot ingest → `adsb_samples` on a timer inside the API process (requires SQL table). Default off. |
| `ADSB_INGEST_INTERVAL_SECONDS` | Optional. Ingest cadence when enabled (default **3600** = 1 hour, minimum **10**). Production currently uses **10** seconds to collect denser recent tracks. |
| `ADSB_INGEST_SOURCES` | Optional. Comma-separated provider order for ingest. Production currently uses **`adsb_lol,opensky`** because Railway was timing out to OpenSky live endpoints. |
| `ADSB_OPENSKY_TIMEOUT_SECONDS` | Optional. HTTP timeout for the **ingest** OpenSky call only (see `backend/.env.example`). |
| `ADSB_LOL_RADIUS_NM` | Optional. Radius in nautical miles for the adsb.lol live snapshot fallback. Production currently uses **65**. |
| `ADSB_LOL_MAX_SEEN_SECONDS` | Optional. Freshness filter for adsb.lol positions. Production currently uses **120** seconds. |

**Exposure tuning** (same `adsb_samples` table; see `backend/services/flight_exposure.py` and `backend/.env.example`):

| Variable | Purpose |
|----------|---------|
| `EXPOSURE_DAYS` | Optional. **1–30**, default **7** in `compute_exposure`. Lookback for exposure stats. |
| `EXPOSURE_RADIUS_MILES` | Optional. **0.25–10**, default **`SCAN_RADIUS_MILES`** (2 mi). Count samples within this radius of the property. |

### Frontend (Vercel / local)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Mapbox map (public by design) |
| `BACKEND_URL` | Railway backend URL (e.g. `https://dwellsense-production.up.railway.app`) |
| `NEXT_PUBLIC_FLIGHT_PATH_GREAT_CIRCLE` | Optional. Default **`1`**. Display-only: densifies line segments along great-circle arcs so long 2-point routes do not render as screen-straight chords. |
| `NEXT_PUBLIC_FLIGHT_PATH_GC_MIN_STEPS` | Optional. Default **8**. Minimum great-circle interpolation points per route leg. |
| `NEXT_PUBLIC_FLIGHT_PATH_GC_MAX_STEPS` | Optional. Default **24**. Maximum great-circle interpolation points per route leg. |
| `NEXT_PUBLIC_FLIGHT_PATH_GC_MAX_VERTICES` | Optional. Default **380**. Vertex cap before final display smoothing. |
| `NEXT_PUBLIC_FLIGHT_PATH_CHAIKIN_PASSES` | Optional. Default **2**. Display-only corner rounding passes before spline sampling. |
| `NEXT_PUBLIC_FLIGHT_PATH_SPLINE_SEGMENTS` | Optional. **0** = polyline-only after great-circle densification. Default **14** = display-only centripetal Catmull–Rom subdivisions per span in `frontend/lib/flightPathDisplay.ts` (does not change API geometry). |
| `NEXT_PUBLIC_FLIGHT_PATH_SPLINE_ALPHA` | Optional. Default **0.5**. Catmull–Rom alpha; `0.5` is centripetal and avoids many overshoot artifacts, `1` is chordal and hugs the source path more tightly. |

**Local dev gotcha:** for local testing, set `BACKEND_URL=http://127.0.0.1:8000`. If `BACKEND_URL` points at Railway, your local frontend will keep using production and you won’t see local backend changes.

### Local vs production (workflow)

Before implementing or verifying a feature, confirm **where** it should land:

| Target | Frontend | Backend | When to use |
|--------|----------|---------|-------------|
| **Local** | `http://localhost:3000` | `http://127.0.0.1:8000` | Dev, debugging, unreleased code |
| **Live site** | `https://dwellsense.vercel.app` | `https://dwellsense-production.up.railway.app` | What real users see |

**Rules of thumb:**

1. **Local code ≠ live site** until you `git push origin main` and Railway/Vercel finish deploying.
2. Local frontend with `BACKEND_URL` pointing at Railway still hits **production backend** — UI can be local while data is production.
3. After deploy, hard-refresh the live site and run a **new scan**; cached scan results and old JS bundles won’t show new fields like `dining`.
4. Verify production with `POST /api/scan` on Vercel (proxy) or `POST /scan` on Railway — check that new JSON fields exist before assuming the UI is wrong.

---

## Deployment Summary

### GitHub

- Remote: `https://github.com/steveonshit/DwellSense.git`
- `.gitignore` excludes `backend/.env`, `backend/venv/`, `frontend/.env.local`, `frontend/node_modules/`, etc.
- **Supabase migrations:** workflow **`.github/workflows/supabase-migrations.yml`** runs on pushes to `main` when `supabase/migrations/**` changes. Configure Action secrets **`SUPABASE_ACCESS_TOKEN`**, **`SUPABASE_PROJECT_REF`**, **`SUPABASE_DB_PASSWORD`** (see `README.md`). No database credentials belong in chat or committed files.

### Railway (backend)

- **Root directory:** `backend` (required — whole-repo builds fail without this).
- **Public URL:** generated under **Networking → Generate Domain**.
- **Auto-deploy:** on push to `main` (typical GitHub integration).

**Railway CLI (optional debugging):** install the [Railway CLI](https://docs.railway.com/guides/cli), `railway login`, `railway link` in the repo, then **`railway ssh`** into the **backend** service to run commands **inside the deployed container** (same egress as `/scan`). Use **`railway logs`** to tail logs. **`railway run`** runs a command **on your laptop** with Railway env vars — useful for local scripts, **not** for proving Railway→Mapbox connectivity.

### Vercel (frontend)

- Project linked to **`frontend`** as root (or deploy from `frontend/` via CLI).
- **`vercel.json`** sets **`maxDuration`: 300** seconds for `app/api/scan/route.ts`, **`app/api/scan/bullets/route.ts`**, and `app/api/pdf/route.ts` so long scans (Gemini + Places) are not cut off by the default serverless limit.
- **`frontend/app/api/scan/route.ts`** and **`frontend/app/api/scan/bullets/route.ts`** export `maxDuration = 300` and use `AbortSignal.timeout(290_000)` on fetches to the backend.
- **Vercel CLI:** `npx vercel ls` / `vercel deploy` require a valid token (`vercel login`). An expired local token does **not** mean production is down — use the live URL or Railway/Vercel dashboards to confirm deploy status.

---

## Supabase Schema

Tables used by the app include (see `README.md` for full SQL):

- `crime_reports`
- `reports_311`
- `building_permits`
- `eviction_records`

Populate municipal tables via **`python -m jobs.daily_refresh`** (local) or the scheduled job in `main.py` (3:00 AM). Empty tables are allowed; the app degrades gracefully.

### ADS-B samples / flight-path warehouse seed

For flight overlays and the “flight exposure score” prototype, we also added:

- `adsb_samples` (DDL in **`supabase/migrations/`**; mirror copy in **`backend/sql/adsb_samples.sql`** for manual paste)

This table stores raw ADS‑B position samples — individual aircraft observations, not prebuilt path rows. Over time, repeated samples for the same aircraft become the source for stable recent tracks near a searched address. This is now the seed of the long-term NYC flight-path warehouse, but it is not yet a mature warehouse with retention policies, route/corridor aggregates, or quality-score tables.

**Important:** `adsb_samples` is **not** populated by `daily_refresh.py`. Rows are written by **`backend/jobs/adsb_ingest.py`** — either run **`python -m jobs.adsb_ingest`** manually, or enable **`ADSB_INGEST_ENABLED=true`** in production so **`main.py`** schedules the same ingest on the API service. The ingest job stores real observed positions from provider snapshots (currently adsb.lol first in production, OpenSky fallback), never generated flight paths.

---

## Notable Code Locations

| Area | Path |
|------|------|
| Main app + schedulers | `backend/main.py` |
| Supabase migrations (CI) | `supabase/migrations/`, `.github/workflows/supabase-migrations.yml` |
| Main scan pipeline | `backend/routers/scan.py` |
| Threat card layout + deterministic risk | `backend/services/threat_card_layout.py` |
| Gemini (bullets only) + merge / fallback | `backend/services/ai_analysis.py` |
| Places / logistics + dining rankings | `backend/services/places.py` |
| City data + swarm pins + 311 label formatting | `backend/services/city_data.py` |
| Flights / overhead aircraft | `backend/services/flights.py` |
| ADS‑B ingestion loop | `backend/jobs/adsb_ingest.py` |
| Flight exposure scoring | `backend/services/flight_exposure.py` |
| Swarm pin types | `backend/models/schemas.py` (`SwarmPin`) |
| Dining card schema | `backend/models/schemas.py` (`RestaurantBarCard`) |
| Deferred bullets models | `backend/models/schemas.py` (`BulletsRequest`, `BulletsResponse`, `PendingBulletsContext`) |
| Next.js scan proxy | `frontend/app/api/scan/route.ts` |
| Next.js deferred bullets proxy | `frontend/app/api/scan/bullets/route.ts` |
| Home page shell (server) | `frontend/app/page.tsx` |
| Scan + loading ad + deferred bullets (client) | `frontend/components/HomeClient.tsx` |
| Site footer (server, dynamic copyright year) | `frontend/components/Footer.tsx` |
| Results UI | `frontend/components/ResultsDashboard.tsx` |
| Carousel dot nav (shared) | `frontend/components/CarouselDots.tsx`, `frontend/lib/carouselScroll.ts` |
| Wellness banner + 311 breakdown chip | `frontend/components/DangerBanner.tsx` |
| Side scan summary (≥1550px) | `frontend/components/SideAds.tsx` |
| Shared TS types | `frontend/lib/types.ts` |
| Map + markers | `frontend/components/MapComponent.tsx` |
| Flight line display shaping (great-circle arcs + smoothing, map-only) | `frontend/lib/flightPathDisplay.ts` |
| Logistics carousel | `frontend/components/LogisticsCarousel.tsx` |
| Threat carousel | `frontend/components/ThreatCarousel.tsx` |
| Top dining (merged into logistics bar) | `frontend/lib/proximityCards.ts`, `frontend/components/LogisticsCarousel.tsx` |

---

## Gemini / AI (Current Behavior)

**Split of responsibilities (implemented):**

| Piece | Where |
|--------|--------|
| Nine cards’ **ids, emoji, titles, subtitles** | `threat_card_layout.py` (`CARD_SPECS`) |
| **Border + subtitle colors** (data-driven) | `threat_card_layout.resolve_card_colors` + `CardChromeContext` |
| **Wellness Score** (`danger_score` field), **risk_level**, **risk_label**, **risk_description** | `threat_card_layout.compute_risk_from_counts` |
| **27 bullets** (three per card) | Gemini returns JSON `{ "bullets": { "high_churn": ["","",""], ... } }` only (model configurable) |
| **Fact-lock** (bullets must match counts) | `ai_analysis._enforce_fact_locked_bullets` after Gemini merge |
| Merge + validation | `ai_analysis.py` merges Gemini bullets into the fixed chrome; **per-card** fallback to template bullets if fewer than two non-empty strings |

**Card chrome highlights (current):**

| Card id | Title (chrome) | Notes |
|---------|----------------|-------|
| `high_churn` | TENANT CHURN | Evictions only; green border when zero filings |
| `tenant_warnings` | TENANT WARNINGS | Subtitle: HPD data **not ingested** — bullets never claim violations |
| `demolitions` | CONSTRUCTION & DEMOLITIONS | DOB active permits + 311 construction counts |
| `flight_path` | FLIGHT PATH | Subtitle: ADS-B tracks within scan radius (not heuristic corridors in `auto`) |
| `reports_311` | 311 REPORTS | Stronger border when volume ≥ **200** |

**Gemini call details:**

- **Model:** `GEMINI_MODEL` env var (default `gemini-2.5-flash`) with system instruction `BULLETS_SYSTEM_PROMPT`; **`response_mime_type: application/json`**.
- **Max output tokens:** `GEMINI_MAX_OUTPUT_TOKENS` (default **4096**) — the bullets JSON is larger than it looks; too-small values truncate JSON and cause parse failures.
- **Timeout:** `GEMINI_TIMEOUT_SECONDS` (default **300**) wrapping `asyncio.to_thread(model.generate_content, ...)` when `> 0`. Set **`0`** to disable the `asyncio.wait_for` guard (still subject to upstream HTTP limits).
- **Parsing:** Response text is read safely (including when `.text` is empty); JSON tolerates markdown fences; one retry on non-timeout failures.
- **Fallback bullets:** If the key is missing → template bullets with a third line mentioning **`GEMINI_API_KEY`**. If the key exists but Gemini errors or times out → template third line says **AI summary unavailable**; counts/map still valid.
- **Cache:** In-memory cache keyed by address hash + crime / 311 / permit / **eviction** counts (`ai_analysis.py`). Version string **`2026-06-20-wellness-v2`** busts stale score/bullet caches when scoring changes.
- **Deferred bullets store:** In-memory **`_pending_bullets`** map (TTL **300s**) keyed by cache token when **`defer_gemini=true`**.
- **Debug fields:** API responses include `gemini_configured` plus `gemini_status`, `gemini_latency_ms`, `gemini_timeout_seconds`, and (on failures) `gemini_error_kind` + `gemini_error_detail` so you can distinguish **missing key vs timeout vs API errors** without reading Railway logs. Check **Browser DevTools → Network → `/api/scan` → Response**.

---

## Scoring (Wellness Score)

### Field naming

The API field is still named `danger_score` for backwards compatibility, but it now represents a **Wellness Score**:

- **0 = worst**
- **100 = best**

The UI banner and PDF label it as “Wellness Score”.

### Risk label wording (UX)

Risk labels are **plain renter-facing words** (no legacy jargon):

| Score band (approx.) | Label |
|----------------------|--------|
| 0–15 | Terrible |
| 16–28 | Bad |
| 29–42 | Average |
| 43–55 | Good |
| 56–68 | Very Good |
| 69–80 | Great |
| 81–90 | Excellent |
| 91–100 | Outstanding |

**Gates:** an all-zero municipal radius is capped at **Very Good** (sparse data, not proof of excellence). **Excellent** / **Outstanding** require multiple clean signals — not just a high numeric score.

Banner emojis: **Excellent** ✨, **Outstanding** 🌟; other bands use risk-level emoji (🚨 / ⚠️ / 🟡 / ✅).

### Current formula (Wellness v2)

Implemented in `backend/services/threat_card_layout.py`:

1. **`_base_wellness_score`** — weighted percentile hazard from crime, 311, permits, evictions (log-scaled), inverted to 0–100, minus a small NYC baseline (−5).
2. **`_apply_311_adjustment`** — one extra penalty when 311 volume is high (≥200, or ≥80 when crime is quiet) but crime is low.
3. **`_apply_safety_caps`** — soft ceilings for crime, evictions, permits, and truncated fetches (no stacked duplicate penalties).
4. **`_label_for_score`** — maps score to plain label + gates top tiers.

Example calibration: **~5k 311, 0 crime** → about **37 Average** (not legacy **MIXED SIGNALS ~47** or over-strict **Bad ~22**).

### Caps + honesty

Some queries are intentionally capped (e.g. dense Manhattan can hit limits). When caps are hit, the system:

- adds a note to `risk_description` indicating counts may be capped
- applies a soft wellness ceiling via **`_apply_safety_caps`** when **`capped=true`**

### High 311 volume adjustment

When **`reports_count ≥ 200`** and **`crime_count < 8`**, the v2 311 adjustment pulls the score down so dense 311 neighborhoods do not read as top tiers when NYPD crime is quiet. The banner adds an explicit caveat and (in the UI) a **See 311 breakdown →** chip that scrolls to the **311 REPORTS** threat card when volume is high.

---

## Roadmap / Product Ideas

**Implemented:**

- **Smaller Gemini ask:** Scoring and threat-card chrome live in Python; Gemini returns only **`bullets`** JSON — reduces latency vs the old full-card JSON.
- **Two-phase scan (production):** `defer_gemini` on `/scan` + **`POST /scan/bullets`** + frontend background refresh — users see map/score/template bullets before Gemini finishes.
- **Wellness score v2:** plain-language labels (Terrible → Outstanding), gated top tiers, calibrated 311 adjustment (`threat_card_layout.py`).
- **Top dining within 2 miles:** Yelp-first (optional key) + Google Places fallback; merged into `LogisticsCarousel` via `proximityCards.ts`.
- **Fact-locked threat cards:** All nine cards’ bullets enforced against real municipal/flight counts (`ai_analysis.py`).
- **PDF dossier:** Unicode-safe generation via `_pdf_text()` in `backend/routers/pdf.py`.
- **Public beta UI:** Navbar shows **Public beta**; side panels show **Scan summary** on wide screens (≥1550px) during results, else honest **Sponsored / Ad space** placeholders.
- **Results UX polish:** carousel dot nav (proximity + threat), hidden carousel scrollbars, 311 breakdown chip, flight empty-state copy, logistics distance nowrap.
- **Server-rendered footer:** `Footer.tsx` for dynamic copyright year.
- **ESLint:** `frontend/.eslintrc.json` extends `next/core-web-vitals`.
- **Flight exposure NYC night window:** `America/New_York` 10 PM–7 AM in `flight_exposure.py`.

---

## Working Style (Production Standard)

- **Reliability first**: treat this as a production system; avoid shortcuts and misleading data.
- **ALWAYS USE REAL DATA. NEVER FAKE OR MAKE UP ANY DATA.** (See **Data integrity** above.)
- **No fake outputs**: if a data source is unavailable, surface **unavailable** (with graceful degradation) rather than inventing approximations without clear labeling. **Exception:** map **display-only** flight line shaping is allowed when labeled as visual smoothing — API coordinates remain the backend truth unless you change server code.
- **Local vs live site**: confirm whether work targets **localhost** or **production** before implementing or verifying; push to `main` and wait for Railway/Vercel deploy before expecting changes on the public URL.
- **When giving operational instructions** (dashboards, env vars, deploy steps): provide them **clearly**, **grouped together**, and in **bullet-point format** with exact variable names/values.

**Not yet implemented** (discussed direction):

- **HPD violations ingestion:** populate tenant-warning signals from NYC HPD data (today the card is honest that HPD is not ingested).
- **Alternative models:** If latency remains an issue even with deferred bullets, evaluate faster inference hosts (e.g. Groq) or other APIs — quality vs speed tradeoff.

---

## Issues Encountered & Fixes (Setup Session)

Below is a concise log of problems faced while connecting GitHub, Railway, Vercel, and debugging production behavior.

### Git & CLI

- **Long git command failed:** Special characters (e.g. em dash in commit message) broke shell parsing. Use plain ASCII hyphens in one-liners.
- **Nothing to commit:** `git commit` returned non-zero when the tree was clean; the `&&` chain stopped before `git push`. Run `git push -u origin main` separately if needed.
- **`remote origin already exists`:** Skip `git remote add`; use `git push` only.

### Railway

- **Build failed (Railpack):** Root directory was not set to `backend`. Fix: **Settings → Source → Root Directory** = `backend`.
- **No public URL:** **Networking → Generate Domain**.
- **Internal error on `/scan`:** `SwarmPin` only allowed a few `type` values; `_classify_311` returned types like `water`, `noise`, `fire`. **Fix:** Expanded `SwarmPin.type` literals in `schemas.py` and aligned permit pins to `permit`.
- **Mapbox geocode `ConnectTimeout` from Railway:** backend could not open TLS to `api.mapbox.com` within the old **10s** single-attempt budget. **Fix:** `geocoding.py` now uses **`httpx`** with **`trust_env=False`**, **longer connect/read timeouts**, and **retries** with backoff; tune via **`MAPBOX_GEOCODE_*`** env vars. If failures persist, verify egress from the container (**`railway ssh`** + `curl`), not only `railway run` on a laptop.

### Vercel

- **Next.js 14.2.5 blocked:** Security policy; upgraded to **Next.js 15** and regenerated `package-lock.json`.
- **Deployment blocked / GitHub identity:** Private email or committer mismatch; resolved via **CLI deploy** (`npx vercel --prod`) and/or linking accounts.
- **Path `frontend/frontend` error:** Vercel project had **Root Directory = `frontend`** while CLI ran from inside `frontend/` — doubled path. Fix: deploy from repo root with correct settings, or **new project** from `frontend/` without conflicting root.
- **`BACKEND_URL` / `NEXT_PUBLIC_MAPBOX_TOKEN`:** Must be set in **Vercel → Project → Environment Variables** for Production (and Preview as needed).
- **Redeploy vs new code:** Clicking **Redeploy** only rebuilds whatever source Vercel is currently connected to; it does **not** upload local changes from your laptop. If your Vercel project is using **CLI deploys** (`npx vercel --prod`), you must run the CLI again to ship changes. If you want push-to-deploy, connect the Git repo and ensure **Root Directory = `frontend`**.

### Backend behavior (production debugging)

- **Only airport + mall in logistics:** `GOOGLE_MAPS_API_KEY` on Railway was still a **placeholder** (`YOUR_GOOGLE_MAPS_API_KEY_HERE`). Places calls failed silently; code fell back to static airport/mall only. **Fix:** set the real Google Maps API key in Railway Variables.
- **“Closest mall” wrong vs Google Maps:** an early version used a tiny hardcoded `NYC_MALLS` list for the mall card. **Fix:** `backend/services/places.py` now prefers **Places API (New)** nearby **`shopping_mall`**, with a text search fallback; static NYC malls are only used if Places returns nothing.
- **Google Cloud API key restrictions:** If restricted, ensure **Places API (New)** (and related Maps APIs) are allowed for that key.
- **Gemini / generic bullets:** Check Railway logs for timeout, empty/blocked responses, JSON parse errors, or quota — not only “too little time.”

### Frontend map UX

- **Pins jumping to top-left on hover:** Mapbox Marker sets `style.transform` on the marker element for positioning. If hover handlers also set `transform: scale(...)` on that same element, it overwrites Mapbox’s positioning transform and the pin snaps to a corner. **Fix:** use an **outer wrapper** element for Mapbox positioning and apply hover scaling to an **inner** element in `frontend/components/MapComponent.tsx`. (Also avoid putting the map inside an animated `transform` subtree; prefer opacity-only for global “fade-in”.)
- **Mapbox `line-dasharray` errors:** Mapbox GL does not accept `undefined` for paint properties. When switching between dashed static corridors and solid ADS‑B tracks, clear dash styling explicitly (omit the property or set it to `null`) in `frontend/components/MapComponent.tsx`.
- **`/scan` 500 after adding flight exposure:** if Supabase DNS/network is flaky, exposure must not take down scans. **Fix:** `flight_exposure.compute_exposure` is fail-open and returns `data_quality="unavailable"` when storage is unreachable.

---

## Flights / Overhead Aircraft (Current Behavior)

### Modes + data sources (`FLIGHT_MODE`)

| Mode | Behavior |
|------|----------|
| **`auto`** (**default**) | **1)** If Supabase `adsb_samples` has rows in the configured stable completed time/bbox window, build up to **3** per-aircraft **polylines** from stored samples (**no OpenSky call during `/scan`**). **2)** If that query yields nothing useful, return **no flight paths** (no synthetic corridors). Legacy env value **`adsb`** is accepted and treated as **`auto`**. |
| **`static`** | Only hand-authored **NYC corridor segments** (JFK/LGA/EWR-style hints). Each `FlightPath` is **`start` + `end`** only (no `path`). **Explicit demo mode:** dashed straight segments. |
| **`live_adsb`** | **Per scan:** OpenSky **`states/all`** in a bbox, pick closest in-air traffic, then **sequential** **`tracks/all`** fetches with per-track timeouts and an overall **`OPENSKY_SCAN_BUDGET_SECONDS`** guard. Returns real polylines when available; otherwise **no paths**. |

**OpenSky auth:** credentials optional for prototyping; **`OPENSKY_USERNAME`** / **`OPENSKY_PASSWORD`** improve rate limits for both ingest and `live_adsb`.

### Static corridors (what they are / what they aren’t)

`static` mode only ( **`FLIGHT_MODE=static`** ) uses hand-authored NYC corridor segments — **not** FAA official tracks. **`auto`** and **`live_adsb`** do **not** fall back to these when ADS-B data is missing; they return **no paths** instead (data-integrity rule).

Nearest-corridor ranking (for `static` mode) uses **minimum great-circle distance** from the property to each segment in `backend/services/flights.py` (`get_nearby_flight_corridors` / `NYC_FLIGHT_CORRIDORS`).

### Stored-sample polylines (`auto` when ingest has data)

`get_stored_sample_flight_paths` in `backend/services/flights.py`:

1. **Query** `adsb_samples` with a lat/lng bbox and a stable completed time window (`ADSB_PATH_STABILITY_BUCKET_MINUTES` + `ADSB_PATH_STABILITY_LAG_MINUTES`), then **group by `icao24`**.
2. **Sort each aircraft’s points chronologically** by `observed_at` (so the polyline direction matches time).
3. **Split discontinuities before drawing:** break a stored ICAO series on long time gaps (`ADSB_PATH_MAX_GAP_MINUTES`), impossible implied speed vs timestamps (`ADSB_PATH_MAX_IMPLIED_MPH`), and optionally large missing-timestamp jumps (`ADSB_PATH_BLIND_JUMP_MILES`).
4. **Eligibility:** respect **`ADSB_PATH_MIN_POINTS`**. Do **not** fabricate a second point for a one-sample aircraft; if there are not enough real samples, the track is not shown.
5. **Near-property pass selection:** keep one contiguous slice around the closest approach to the scanned address (`ADSB_PATH_KEEP_NEAR_MILES` + `ADSB_PATH_KEEP_PAD_POINTS`) instead of drawing a long unrelated aircraft path.
6. **Full-resolution cleanup before capping:** dedupe close vertices, drop small sharp local reversals (`ADSB_PATH_SPIKE_*`), filter impossible-speed hops, simplify with Douglas–Peucker, then smooth.
7. **Preserve minimum real vertices:** if cleanup simplifies a valid track below `ADSB_PATH_MIN_POINTS`, restore real source vertices (capped if needed) instead of returning a misleading short line (minimum **5** by default).
8. **Vertex cap last:** if a track is still too dense after simplification, widen DP tolerance up to a limit and only then fall back to even decimation. This avoids aliasing sparse ADS-B into zig-zag chords.
9. **Ranking:** prefer the segment whose closest approach to the property is inside the distance gate; for each ICAO, keep the best nearby segment. Ties are stable (`closest distance`, raw point count, then ICAO) so repeated scans in the same bucket do not rotate paths randomly.

Labels use human text like **“Recent ADS-B track”** with ICAO, optional median altitude, and closest miles.

### Live OpenSky tracks (`live_adsb`)

`get_adsb_tracks_near_property`:

- **`states/all`** in a bounding box → closest candidates within **`near_miles`**
- **`tracks/all`** per ICAO **one after another** (not a fan-out storm of parallel requests)
- Slice each track to the contiguous **“nearby pass”** window around closest approach (`keep_miles` / padding — see `flights.py`)
- Populate **`path`**, **`callsign` / `airline` / `flight_number`** when parsable, **`last_seen_utc`** for “seen Xm ago”

**Note:** ADS‑B is sampled; **`live_adsb`** can look smoother than stored-snapshot **`auto`** polylines because OpenSky’s track API returns denser time series when it succeeds. Production defaults to **`auto`** because stored samples are more stable and do not depend on a per-scan OpenSky call.

### API shape (`map_data`)

- **`flight_paths`:** list (up to **3**) — preferred for the UI.
- **`flight_path`:** first path — backwards compatibility.

`FlightPath`:

- **`path`:** optional ordered **`Coordinate[]`**. If **`len(path) >= 2`**, the UI treats it as a **real polyline** (solid line, per-vertex plane animation). If absent, the UI draws **`start` → `end`** only (dashed when the layer detects “corridor-only” geometry).

Best-effort metadata (when present): `median_altitude_ft`, `closest_miles`, `sample_count`, `callsign`, `airline`, `flight_number`, `last_seen_utc`.

### Frontend rendering

`frontend/components/MapComponent.tsx`:

- Builds GeoJSON LineStrings via **`flightPathToLineLngLat`** from **`frontend/lib/flightPathDisplay.ts`**.
- **Display-only shaping:** the frontend may densify route legs with **great-circle interpolation**, round corners with **Chaikin-style smoothing**, then sample with **centripetal Catmull–Rom**. This does **not** change the API payload — it only changes how the line is displayed on the map.
- **2-point routes now curve visually:** even if the backend sends only `start` + `end`, `flightPathDisplay.ts` can add great-circle display vertices so Mapbox does not render the route as a single screen-straight chord.
- **Visual truth rule:** the backend coordinates remain the source of truth. Frontend smoothing is presentation-only and should be described as display-smoothed, not as raw ADS-B precision.
- **Dash vs solid:** if any path has **`path.length >= 2`**, paint uses a **solid** line; otherwise **dashed** (`line-dasharray`); Mapbox does not get `undefined` dash props when toggling.
- **Glow + rounded joins:** `MapComponent.tsx` renders a soft cyan glow layer under the visible flight line and uses rounded line caps/joins so routes read as smooth paths.
- **Caption:** when showing real polylines, copy clarifies that lines use **great-circle arcs + display smoothing** rather than raw chords.
- **Plane markers:** one ✈️ per path, animated along the **same** coordinates the user sees (including spline).

**Map lifecycle:** the map is created once; flight sources update when `mapData.flight_paths` / `flight_path` change after a new scan.

#### Flight Activity UI (current)

Under the map, the **Flight Activity** block includes:

- Summary chips (when exposure is available): **Night `/hr`**, **Day `/hr`**, **Typical altitude**, **Data quality**
- Track chips (horizontal scroll): label + `~altitude ft` + `closest mi` + “seen Xm ago” when `last_seen_utc` exists (`live_adsb`)

Users do **not** need to understand “ADS‑B” in product copy; backend logs and docs may still say ADS‑B for engineers.

### Flight exposure score (prototype)

The backend now returns an optional `flight_exposure` field on the scan response:

- `night_overflights_per_hour`
- `day_overflights_per_hour`
- `typical_altitude_ft`
- `data_quality` (`good` | `sparse` | `unavailable`)

Important: this prototype uses Supabase storage; if Supabase is unreachable or ingestion isn’t running, exposure returns **`data_quality="unavailable"`** and the UI shows **“Exposure: unavailable”**.

**Night/day window:** `flight_exposure.py` uses **`America/New_York`** local time — **10 PM–7 AM** counts as night (renter-facing).

**Fail-open behavior:** `/scan` must not crash if Supabase is down; exposure computation is wrapped so scans still succeed.

---

## Local Development

**Backend**

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in keys (optional YELP_API_KEY for better dining rankings)
# Optional flight modes for local experiments:
#   FLIGHT_MODE=auto        (default) — Supabase samples if present, else no paths
#   FLIGHT_MODE=static      — dashed corridor demo look
#   FLIGHT_MODE=live_adsb   — OpenSky per scan (slow; needs network)
uvicorn main:app --reload --host 127.0.0.1 --port 8000
# or run with APScheduler + optional ingest enabled in .env:
python main.py
```

### ADS‑B exposure prototype (local)

1. **Preferred:** configure GitHub Action secrets (see **README** / **`.github/workflows/supabase-migrations.yml`**) and run **Deploy Supabase migrations** or push to `main`.
2. **Manual DDL:** run `backend/sql/adsb_samples.sql` in the Supabase SQL editor (same DDL as `supabase/migrations/`).
3. **Production ingest:** set **`ADSB_INGEST_ENABLED=true`** on Railway (same service as the API). Optionally tune **`ADSB_INGEST_INTERVAL_SECONDS`** (default **3600** = 1 hour in code; minimum **10**). Production currently uses **10 seconds** and `ADSB_INGEST_SOURCES=adsb_lol,opensky`. The ingest job uses **`httpx` with `trust_env=False`** so container proxy env does not break outbound HTTPS (see `backend/jobs/adsb_ingest.py`).

**Local manual loop (still supported):**

```bash
cd backend && source venv/bin/activate
python -m jobs.adsb_ingest
```

Let it run for ~5–15 minutes before expecting stable exposure stats.

**Frontend**

```bash
cd frontend
cp .env.local.example .env.local   # set NEXT_PUBLIC_MAPBOX_TOKEN, BACKEND_URL
npm install
npm run dev
```

Tip: if you’re testing local backend changes, confirm `BACKEND_URL=http://127.0.0.1:8000` in `frontend/.env.local`.

**Data refresh (optional)**

```bash
cd backend && source venv/bin/activate
python -m jobs.daily_refresh
```

---

## Production URLs (examples — confirm in your dashboards)

- Frontend: `https://dwellsense.vercel.app` (or your Vercel alias)
- Backend: `https://dwellsense-production.up.railway.app` (or your Railway domain)

---

## Standalone HTML Demo

`Dwellsense Final.html` is a **single-file** prototype (Tailwind CDN + Leaflet). It is **not** wired to this backend by default; the production app is the **Next.js + FastAPI** stack above.

---

## Production status & follow-ups

**Shipped in codebase and on production (verify on your Railway + Vercel dashboards):**

- NYC-only scans (`/scan` guardrail) + NYC-locked map viewport
- **`FLIGHT_MODE=auto` (default):** Supabase **`adsb_samples`** polylines when ingest has filled the window; else **no paths** — **no OpenSky** on the default scan path when samples exist
- **`FLIGHT_MODE=static`:** explicit marketing-style **dashed corridor** segments only
- **`FLIGHT_MODE=live_adsb`:** optional **OpenSky** `tracks` polylines per scan (budgeted); real tracks only
- **ADS-B ingest:** production stores real NYC aircraft position snapshots into Supabase every **10 seconds** (`ADSB_INGEST_INTERVAL_SECONDS=10`, `ADSB_INGEST_SOURCES=adsb_lol,opensky`)
- **Stable flight paths:** production path selection uses completed **60-minute** buckets with **15-minute** lag, so repeated scans of the same address do not rotate through whatever aircraft is closest at that second
- Backend **polyline cleanup** (discontinuity splitting, near-property pass selection, dedupe, spike filtering, implied-speed filter, Douglas–Peucker, light smooth) + frontend **display-only great-circle / Chaikin / centripetal Catmull–Rom shaping** (`frontend/lib/flightPathDisplay.ts`)
- **Geocoding hardening:** `httpx`, **`trust_env=False`**, retries, longer timeouts (`MAPBOX_GEOCODE_*`)
- **Flight Activity** UI (paths + exposure chips), **fail-open** `flight_exposure`, **Places-backed mall** card with static fallback
- **Top dining within 2 miles (live):** `/scan` returns `dining[]` — top 4 ranked restaurants/bars merged into the logistics/proximity bar.
- **Nearby municipal radius:** true Haversine radius is **2 miles** (`SCAN_RADIUS_MILES`, default **2**), with widened bbox prefilter + higher fetch caps to reduce premature truncation in dense areas
- **311 sewer / water labels:** map zone and swarm pin labels now use NYC 311 descriptors to classify the issue while keeping visible names short, e.g. **Sewer Odor**, **Sewer Backup**, **Drain Blockage**, **Water Quality Issue**, **Water Leak**, or **Water Pressure**
- **Fact-locked threat cards:** all nine cards’ bullets match municipal/flight counts; card-specific bottom lines; data-driven border colors
- **Wellness score v2 + two-phase scan:** plain labels, deferred Gemini (`f918277`); faster perceived load
- **Results UX polish:** carousel dots, 311 breakdown chip, flight empty-state, side scan summary, logistics distance fix
- **Server-rendered footer:** dynamic copyright year (`c85136a`)
- **PDF dossier:** Unicode-safe (`backend/routers/pdf.py`); download via **Download PDF Dossier** on results page
- **No synthetic flight fallback in `auto`:** empty flight paths when no ADS-B samples (not static corridors)
- **Production CORS:** `FRONTEND_URL=https://dwellsense.vercel.app` on Railway
- **Public beta chrome:** navbar badge; scan summary / honest side-ad placeholders; server-rendered footer; footer links to NYC Open Data

**Production verification (June 2026, post-`f918277` / `c85136a`):** hard-refresh `https://dwellsense.vercel.app`, run a new scan (e.g. Crown Heights). Expect plain wellness labels (**Average**, not legacy jargon), **`gemini_status: "pending"`** + **`bullets_token`** on the first `/api/scan` response, then **`gemini_status: "ok"`** from `/api/scan/bullets`; carousel dot nav; optional **See 311 breakdown →** chip when 311 volume is high; footer **© 2026**.

**Ongoing / decisions:**

- Keep **`MAPBOX_TOKEN`** and **`GOOGLE_MAPS_API_KEY`** valid on Railway; **`BACKEND_URL`** + **`NEXT_PUBLIC_MAPBOX_TOKEN`** on Vercel
- **Optional:** set **`YELP_API_KEY`** on Railway for Yelp-sourced dining rankings (otherwise Google Places fallback)
- **Ingestion:** `ADSB_INGEST_ENABLED` vs external cron running `python -m jobs.adsb_ingest`
- **Flight-path warehouse:** promote `adsb_samples` from operational raw samples into a long-term warehouse: retention policy, source metadata, quality scoring, route/corridor aggregates, stable display tables, and observability
- **Deferred bullets durability:** `_pending_bullets` is in-memory on a single Railway instance — multi-instance or restart loses tokens (client keeps template bullets; acceptable for now)
- **Optional:** commercial ADS‑B feed vs OpenSky-only if you need SLA-grade tracks at scale

---

## Recent changelog (high-signal)

### June 2026 — wellness v2, two-phase scan, UX polish (`f918277`, `c85136a`)

- **Two-phase scan:** `ScanRequest.defer_gemini`, `POST /scan/bullets`, `BulletsRequest` / `BulletsResponse`; frontend `HomeClient.tsx` + `/api/scan/bullets`; template bullets first, Gemini refresh in background.
- **Wellness score v2 (`threat_card_layout.py`):** plain labels (Terrible → Outstanding), single percentile model + 311 adjustment + soft caps + gated top tiers; cache version **`2026-06-20-wellness-v2`**.
- **Flight exposure:** night/day uses **`America/New_York`** (10 PM–7 AM).
- **Results UX:** `DangerBanner` 311 breakdown chip; `CarouselDots` + `carouselScroll.ts` on proximity/threat carousels; `MapComponent` flight empty-state; `SideAds` scan summary panel (≥1550px); logistics card min-width 320px + distance nowrap.
- **Footer:** `Footer.tsx` server component + `HomeClient.tsx` split for reliable dynamic copyright year.

### June 2026 — audit + UX polish (`fc4abc8` … `b9f28e2`)

- **PDF (`pdf.py`):** `_pdf_text()` strips emojis / normalizes Unicode so Helvetica PDF generation does not 500 on real scan payloads.
- **Flights (`flights.py`):** **`auto`** and **`live_adsb`** return **no paths** when ADS-B is absent — no static corridor fallback ( **`static`** mode unchanged for explicit demo ).
- **Threat cards (`ai_analysis.py` + `threat_card_layout.py`):** fact-lock all nine cards; card-specific third bullets; **`CardChromeContext`** border colors; **CONSTRUCTION & DEMOLITIONS** rename; honest **Tenant Warnings** subtitle (HPD not ingested).
- **Wellness score:** high-311 penalty when crime is low (≥200 complaints); banner caveat; example ~3k 311 → **MIXED SIGNALS ~47**.
- **Map (`city_data.py` + `MapComponent.tsx`):** active permit pins/zones only; dynamic **`scan_radius_miles`** caption; natural pin shuffle (not grid).
- **Flight exposure:** default radius follows **`SCAN_RADIUS_MILES`**.
- **Frontend polish:** ESLint config; logistics name tooltips; footer dynamic year + NYC Open Data link; public beta navbar; placeholder side ads.
- **Docs:** `project.md` and `README.md` synced to 2-mile radius and current flight/dining behavior.

### Earlier (still true)

- **Risk banner copy:** removed “block/neighborhood” wording from deterministic risk labels (`threat_card_layout.py`).
- **Geocoding (`geocoding.py`):** switched from **`requests`** to **`httpx.AsyncClient`**; **`trust_env=False`**; configurable **`MAPBOX_GEOCODE_RETRIES`**, connect/read timeouts; retries on timeouts, connection errors, and HTTP **429 / 502 / 503 / 504**; clearer **`RuntimeError`** when Mapbox is unreachable after retries.
- **Flights (`flights.py`):** **`FLIGHT_MODE`** model is **`auto` | `static` | `live_adsb`** with **`adsb` → `auto`** alias; **`auto`** reads **`adsb_samples`** first; stored-path cleanup includes discontinuity splitting (`ADSB_PATH_MAX_GAP_MINUTES`, `ADSB_PATH_BLIND_JUMP_MILES`), near-pass slicing (`ADSB_PATH_KEEP_*`), dedupe, spike removal (`ADSB_PATH_SPIKE_*`), implied-speed filtering, Douglas–Peucker, smoothing, and final vertex capping; OpenSky **`live_adsb`** remains budgeted/sequential.
- **Map flight lines (`MapComponent.tsx` + `flightPathDisplay.ts`):** client-side display shaping now includes great-circle leg densification (`NEXT_PUBLIC_FLIGHT_PATH_GREAT_CIRCLE`, `NEXT_PUBLIC_FLIGHT_PATH_GC_*`), Chaikin corner rounding, and centripetal Catmull–Rom (`NEXT_PUBLIC_FLIGHT_PATH_SPLINE_*`); plane animation follows the **same** coordinates as the visible line; caption notes display smoothing; dash/solid rules unchanged in spirit.
- **Places (`places.py`):** nearest **mall** from **Places `shopping_mall`** / text fallback; hardcoded NYC malls only if Places is empty.
- **Dining (`places.py` + `proximityCards.ts`):** top 4 restaurants/bars within **2 miles**; Yelp Fusion when `YELP_API_KEY` is set, else Google Places `restaurant` + `bar` nearby search; ranking uses real `rating` + `review_count` with a small distance tie-breaker; empty array when APIs unavailable (no fake data).
- **City data (`city_data.py`):** nearby municipal rows use a true **2 mile** Haversine filter after bbox prefilter; fetch caps were raised for the larger area; sewer / water 311 labels now use `descriptor` details for classification while keeping visible names to 2-3 words, including **Water Quality Issue** instead of ambiguous **Water Quality**.
- **Flights (`flights.py`):** production path selection now uses completed stability buckets (`ADSB_PATH_STABILITY_BUCKET_MINUTES`, `ADSB_PATH_STABILITY_LAG_MINUTES`) and preserves at least the configured number of real ADS-B vertices, preventing paths from changing every search or collapsing to misleading 2-point lines.
- **Ingest (`adsb_ingest.py`):** ingest stores real observed position snapshots from ordered providers (`ADSB_INGEST_SOURCES`); production currently uses **adsb.lol first, OpenSky fallback**, every **10 seconds**.
- Exposure fail-open; `SwarmPin` type expansion; Mapbox `line-dasharray` paint fix; Gemini bullets-only split; `adsb_samples` schema + `flight_exposure` on scan.

---

*Last updated: **June 2026** — wellness v2 scoring, two-phase deferred Gemini scan, results UX polish (carousel dots, 311 chip, scan summary, flight empty-state), server-rendered footer, and production verification notes.*
