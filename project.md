# DwellSense — Project Overview

This document describes the **DwellSense** codebase, architecture, deployment, and work completed during setup (GitHub, Railway, Vercel, debugging). It is the **canonical overview** for contributors and for tools like **Claude Code** (read this file first).

---

## What DwellSense Is

**DwellSense** is a NYC-focused “real estate forensics” web app. A user enters an address; the system:

- Geocodes the address (Mapbox)
- Pulls nearby **crime**, **311**, **permits**, and **evictions** from **Supabase** (pre-loaded via a daily job)
- Fetches **transit / grocery / retail** proximity via **Google Places API (New)**
- Computes **flight overlays** (static corridors or live ADS‑B tracks) and a **prototype flight exposure summary** (`flight_exposure`) when ingestion data exists
- Builds a **Wellness Score** (0–100, where **100 is best**), **risk labels**, and **threat-card chrome** (titles, colors, emojis) in **Python**; **Google Gemini** writes only the **27 bullet strings** (three per card) from the same data brief
- Renders results on a **Mapbox** map and carousels

Tagline: *Don’t sign a blind lease.*

---

## Repository Layout

```
DwellSense/
├── backend/              # Python FastAPI API (includes services/threat_card_layout.py)
├── frontend/             # Next.js 15 + Tailwind + Mapbox GL
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
| Maps / geo | Mapbox (geocoding + map), Google Places API (New), Distance Matrix (if used) |
| Hosting | **Vercel** (frontend), **Railway** (backend) |

---

## Request Flow (Production)

1. User submits an address on **Vercel** (e.g. `dwellsense.vercel.app`).
2. Browser calls **`POST /api/scan`** on the Next.js app (keeps `BACKEND_URL` server-side).
3. Next.js proxies to **`POST {BACKEND_URL}/scan`** on Railway with a **~290s** upstream timeout; the route declares **`maxDuration = 300`** seconds.
4. Backend runs geocoding, parallel DB + Places calls, flight math, then **Gemini** (bullets only — often the slowest step).
5. JSON response drives the UI (map, logistics carousel, threat cards).

**Scan response extras (current local build):**

- `map_data.flight_paths` / `map_data.flight_path` — flight overlays (static corridors or live tracks)
- `flight_exposure` — prototype “exposure summary” (may be `unavailable` if Supabase ingestion isn’t running)

**Loading ad (UX):** `frontend/components/LoadingAd.tsx` runs a **5-second** countdown. The ad only completes when **both** the timer hits zero **and** the scan request has finished (`isApiReady`). If the scan takes longer than 5s, the user waits past the ad until data arrives. If they skip the ad early, they still wait until the API returns.

**Client:** `frontend/app/page.tsx` uses `AbortSignal.timeout(295_000)` on the fetch to `/api/scan` so the UI does not hang forever.

**Health check:** `GET /health` on the backend returns `{"status":"ok","service":"DwellSense API"}`.

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

Geocoding uses Mapbox via `backend/services/geocoding.py`.

**Local/proxy pitfall:** if the machine has `HTTP_PROXY` / `HTTPS_PROXY` set, `requests` may try to tunnel through a proxy and fail with `403` / tunnel errors when calling Mapbox.

**Fix implemented:** geocoding uses a `requests.Session()` with `trust_env = False` so Mapbox calls prefer a **direct connection**, and the address is **URL-encoded** safely.

---

## What “Nearby” Means (Data Windows + Radius)

This app intentionally uses **recent** municipal signals and a **true ~0.5 mile radius**.

### Time windows (intended behavior)

- **Crime**: last **30 days**
- **311**: last **30 days**
- **Permits**: last **90 days**
- **Evictions**: last **180 days**

These windows are applied in **both** the Supabase query path and the NYC Open Data live fallback path.

### Radius (important)

Supabase queries are done as a fast **bounding-box prefilter** (lat/lng rectangle). After results are returned, rows are filtered by **Haversine distance** to keep only points within a true **0.5 mile** circle.

### 311 noise filtering (NYC reality)

NYC 311 is extremely noisy. DwellSense excludes **parking / vehicle / traffic enforcement** style 311 complaints from:

- scoring
- map pins / zones
- Gemini’s 311 summary brief

Rationale: illegal parking volume is not a meaningful renter safety / lease-quality signal.

---

## Environment Variables

### Backend (Railway / local)

| Variable | Purpose |
|----------|---------|
| `MAPBOX_TOKEN` | Geocoding |
| `GOOGLE_MAPS_API_KEY` | Places API (New) — transit, grocery, Target, etc. **Must be a real key, not a placeholder.** |
| `GEMINI_API_KEY` | AI threat analysis |
| `GEMINI_MODEL` | Optional. Gemini model name used for bullets. Defaults to **`gemini-2.5-flash`**. |
| `GEMINI_MAX_OUTPUT_TOKENS` | Optional. Output token budget for Gemini JSON. Defaults to **4096**. Too-low values can truncate JSON and cause parse failures. |
| `GEMINI_TIMEOUT_SECONDS` | Optional. Seconds for `asyncio.wait_for` around Gemini (default **300**). Set **`0`** to disable the asyncio timeout guard (still subject to upstream/Vercel/Railway limits). See `backend/.env.example`. |
| `SUPABASE_URL` | Database URL |
| `SUPABASE_SERVICE_KEY` | Service role key (not anon) |
| `FRONTEND_URL` | CORS — set to your Vercel URL in production |
| `PORT` | Railway sets this automatically |
| `OPENSKY_USERNAME` | Optional. OpenSky username (higher rate limits for ADS‑B). |
| `OPENSKY_PASSWORD` | Optional. OpenSky password. |
| `FLIGHT_MODE` | Optional. `static` (default) or `adsb` for live ADS‑B tracks. |
| `ADSB_INGEST_ENABLED` | Optional. `true` to run OpenSky → `adsb_samples` on a timer inside the API process (requires SQL table). Default off. |
| `ADSB_INGEST_INTERVAL_SECONDS` | Optional. Ingest cadence when enabled (default **3600** = 1 hour, minimum **60**). |

### Frontend (Vercel / local)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Mapbox map (public by design) |
| `BACKEND_URL` | Railway backend URL (e.g. `https://dwellsense-production.up.railway.app`) |

**Local dev gotcha:** for local testing, set `BACKEND_URL=http://127.0.0.1:8000`. If `BACKEND_URL` points at Railway, your local frontend will keep using production and you won’t see local backend changes.

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

### Vercel (frontend)

- Project linked to **`frontend`** as root (or deploy from `frontend/` via CLI).
- **`vercel.json`** sets **`maxDuration`: 300** seconds for `app/api/scan/route.ts` and `app/api/pdf/route.ts` so long scans (Gemini + Places) are not cut off by the default serverless limit.
- **`frontend/app/api/scan/route.ts`** exports `maxDuration = 300` and uses `AbortSignal.timeout(290_000)` on the fetch to the backend.

---

## Supabase Schema

Tables used by the app include (see `README.md` for full SQL):

- `crime_reports`
- `reports_311`
- `building_permits`
- `eviction_records`

Populate municipal tables via **`python -m jobs.daily_refresh`** (local) or the scheduled job in `main.py` (3:00 AM). Empty tables are allowed; the app degrades gracefully.

### Flight exposure (prototype table)

For the “flight exposure score” prototype, we also added:

- `adsb_samples` (DDL in **`supabase/migrations/`**; mirror copy in **`backend/sql/adsb_samples.sql`** for manual paste)

This table stores ADS‑B position samples so we can compute **night vs day overflight rates**, **typical altitude**, and a **data quality** badge over time.

**Important:** `adsb_samples` is **not** populated by `daily_refresh.py`. Rows are written by **`backend/jobs/adsb_ingest.py`** — either run **`python -m jobs.adsb_ingest`** manually, or enable **`ADSB_INGEST_ENABLED=true`** in production so **`main.py`** schedules the same ingest on the API service.

---

## Notable Code Locations

| Area | Path |
|------|------|
| Main app + schedulers | `backend/main.py` |
| Supabase migrations (CI) | `supabase/migrations/`, `.github/workflows/supabase-migrations.yml` |
| Main scan pipeline | `backend/routers/scan.py` |
| Threat card layout + deterministic risk | `backend/services/threat_card_layout.py` |
| Gemini (bullets only) + merge / fallback | `backend/services/ai_analysis.py` |
| Places / logistics cards | `backend/services/places.py` |
| City data + swarm pins | `backend/services/city_data.py` |
| Flights / overhead aircraft | `backend/services/flights.py` |
| ADS‑B ingestion loop | `backend/jobs/adsb_ingest.py` |
| Flight exposure scoring | `backend/services/flight_exposure.py` |
| Swarm pin types | `backend/models/schemas.py` (`SwarmPin`) |
| Next.js scan proxy | `frontend/app/api/scan/route.ts` |
| Scan + loading ad flow | `frontend/app/page.tsx`, `frontend/components/LoadingAd.tsx` |
| Results UI | `frontend/components/ResultsDashboard.tsx` |
| Shared TS types | `frontend/lib/types.ts` |
| Map + markers | `frontend/components/MapComponent.tsx` |
| Logistics carousel | `frontend/components/LogisticsCarousel.tsx` |

---

## Gemini / AI (Current Behavior)

**Split of responsibilities (implemented):**

| Piece | Where |
|--------|--------|
| Nine cards’ **ids, emoji, titles, subtitles, hex colors** | `threat_card_layout.py` (`CARD_SPECS`) |
| **Wellness Score** (`danger_score` field), **risk_level**, **risk_label**, **risk_description** | `threat_card_layout.compute_risk_from_counts` |
| **27 bullets** (three per card) | Gemini returns JSON `{ "bullets": { "high_churn": ["","",""], ... } }` only (model configurable) |
| Merge + validation | `ai_analysis.py` merges Gemini bullets into the fixed chrome; **per-card** fallback to template bullets if fewer than two non-empty strings |

**Gemini call details:**

- **Model:** `GEMINI_MODEL` env var (default `gemini-2.5-flash`) with system instruction `BULLETS_SYSTEM_PROMPT`; **`response_mime_type: application/json`**.
- **Max output tokens:** `GEMINI_MAX_OUTPUT_TOKENS` (default **4096**) — the bullets JSON is larger than it looks; too-small values truncate JSON and cause parse failures.
- **Timeout:** `GEMINI_TIMEOUT_SECONDS` (default **300**) wrapping `asyncio.to_thread(model.generate_content, ...)` when `> 0`. Set **`0`** to disable the `asyncio.wait_for` guard (still subject to upstream HTTP limits).
- **Parsing:** Response text is read safely (including when `.text` is empty); JSON tolerates markdown fences; one retry on non-timeout failures.
- **Fallback bullets:** If the key is missing → template bullets with a third line mentioning **`GEMINI_API_KEY`**. If the key exists but Gemini errors or times out → template third line says **AI summary unavailable**; counts/map still valid.
- **Cache:** In-memory cache keyed by address hash + crime / 311 / permit / **eviction** counts (`ai_analysis.py`).
- **Debug fields:** API responses include `gemini_configured` plus `gemini_status`, `gemini_latency_ms`, `gemini_timeout_seconds`, and (on failures) `gemini_error_kind` + `gemini_error_detail` so you can distinguish **missing key vs timeout vs API errors** without reading Railway logs. Check **Browser DevTools → Network → `/api/scan` → Response**.

---

## Scoring (Wellness Score)

### Field naming

The API field is still named `danger_score` for backwards compatibility, but it now represents a **Wellness Score**:

- **0 = worst**
- **100 = best**

The UI banner and PDF label it as “Wellness Score”.

### Risk label wording (UX)

Risk labels are short adjectives and **do not include** “block” / “neighborhood” wording (e.g. **`STRONG SIGNALS`**, **`BELOW-AVERAGE`**).

### Current formula (Option C)

The score is computed in `backend/services/threat_card_layout.py` using a **percentile-style curve** over log-scaled counts:

- Convert each metric’s count → smooth percentile-like value (0..1) using a logistic curve over `log1p(count)`
- Take a weighted average → **raw hazard**
- Invert: `wellness = 100 - raw_hazard`

### Caps + honesty

Some queries are intentionally capped (e.g. dense Manhattan can hit limits). When caps are hit, the system:

- adds a note to `risk_description` indicating counts may be capped
- avoids claiming a perfect “100” (caps the wellness score’s upper bound in truncated cases)

---

## Roadmap / Product Ideas

**Implemented:**

- **Smaller Gemini ask:** Scoring and threat-card chrome live in Python; Gemini returns only **`bullets`** JSON — reduces latency vs the old full-card JSON.

---

## Working Style (Production Standard)

- **Reliability first**: treat this as a production system; avoid shortcuts and “demo” behavior.
- **No fake outputs**: if a data source is unavailable, surface **unavailable** (with graceful degradation) rather than inventing approximations without clear labeling.
- **When giving operational instructions** (dashboards, env vars, deploy steps): provide them **clearly**, **grouped together**, and in **bullet-point format** with exact variable names/values.

**Not yet implemented** (discussed direction):

- **Two-phase load:** Return map + logistics + merged threat cards from `/scan` **without waiting for Gemini** (or return immediately after Python merge with template bullets), then **`POST /analyze`** or similar to refresh bullets when Gemini finishes — so users read the top of the page while AI runs.
- **Alternative models:** If latency remains an issue, evaluate faster inference hosts (e.g. Groq) or other APIs — quality vs speed tradeoff.

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

### Vercel

- **Next.js 14.2.5 blocked:** Security policy; upgraded to **Next.js 15** and regenerated `package-lock.json`.
- **Deployment blocked / GitHub identity:** Private email or committer mismatch; resolved via **CLI deploy** (`npx vercel --prod`) and/or linking accounts.
- **Path `frontend/frontend` error:** Vercel project had **Root Directory = `frontend`** while CLI ran from inside `frontend/` — doubled path. Fix: deploy from repo root with correct settings, or **new project** from `frontend/` without conflicting root.
- **`BACKEND_URL` / `NEXT_PUBLIC_MAPBOX_TOKEN`:** Must be set in **Vercel → Project → Environment Variables** for Production (and Preview as needed).
- **Redeploy vs new code:** Clicking **Redeploy** only rebuilds whatever source Vercel is currently connected to; it does **not** upload local changes from your laptop. If your Vercel project is using **CLI deploys** (`npx vercel --prod`), you must run the CLI again to ship changes. If you want push-to-deploy, connect the Git repo and ensure **Root Directory = `frontend`**.

### Backend behavior (production debugging)

- **Only airport + mall in logistics:** `GOOGLE_MAPS_API_KEY` on Railway was still a **placeholder** (`YOUR_GOOGLE_MAPS_API_KEY_HERE`). Places calls failed silently; code fell back to static airport/mall only. **Fix:** set the real Google Maps API key in Railway Variables.
- **Google Cloud API key restrictions:** If restricted, ensure **Places API (New)** (and related Maps APIs) are allowed for that key.
- **Gemini / generic bullets:** Check Railway logs for timeout, empty/blocked responses, JSON parse errors, or quota — not only “too little time.”

### Frontend map UX

- **Pins jumping to top-left on hover:** Mapbox Marker sets `style.transform` on the marker element for positioning. If hover handlers also set `transform: scale(...)` on that same element, it overwrites Mapbox’s positioning transform and the pin snaps to a corner. **Fix:** use an **outer wrapper** element for Mapbox positioning and apply hover scaling to an **inner** element in `frontend/components/MapComponent.tsx`. (Also avoid putting the map inside an animated `transform` subtree; prefer opacity-only for global “fade-in”.)
- **Mapbox `line-dasharray` errors:** Mapbox GL does not accept `undefined` for paint properties. When switching between dashed static corridors and solid ADS‑B tracks, clear dash styling explicitly (omit the property or set it to `null`) in `frontend/components/MapComponent.tsx`.
- **`/scan` 500 after adding flight exposure:** if Supabase DNS/network is flaky, exposure must not take down scans. **Fix:** `flight_exposure.compute_exposure` is fail-open and returns `data_quality="unavailable"` when storage is unreachable.

---

## Flights / Overhead Aircraft (Current Behavior)

### Modes + data source (important)

Flight overlays support two modes:

- **`FLIGHT_MODE=static` (default)**: simplified, hand-authored NYC corridor segments (JFK/LGA/EWR). Backend returns up to **3** nearby paths in `map_data.flight_paths` (nearest first).
- **`FLIGHT_MODE=adsb` (local dev / testing)**: uses **OpenSky ADS‑B** to render **real aircraft track polylines** (recent samples) near the address. Intended for local testing and UX iteration before productionizing a paid feed / ingestion pipeline.

**OpenSky auth:** OpenSky can be used **without** credentials for basic prototyping, but `OPENSKY_USERNAME` / `OPENSKY_PASSWORD` improve rate limits and reliability.

### Static mode (what it is / what it isn’t)

`static` mode is **not** “FAA official tracks.” It is a small set of simplified corridor segments used as a **directional hint** when ADS‑B is disabled.

Distance-to-corridor uses the **minimum great-circle distance** from the property to each corridor segment (cross-track distance with endpoint fallbacks), implemented in `backend/services/flights.py`.

### API shape

`map_data` includes:

- `flight_paths`: list (up to 3) — preferred
- `flight_path`: single path (backwards compatibility)

`FlightPath` may include an optional `path` polyline (list of lat/lng points). When present, the frontend renders that polyline directly (solid line).

Additional best-effort fields on `FlightPath` (ADS‑B mode):

- `median_altitude_ft`
- `closest_miles`
- `callsign`, `airline`, `flight_number` (when parsable)
- `last_seen_utc` (used to display “seen Xm ago”)

### How ADS‑B tracks are built (truth-first)

In `adsb` mode, the backend:

- Calls OpenSky `states/all` in a bounding box around the property
- Chooses nearby in-air aircraft
- Fetches `tracks/all` for each aircraft
- Returns the **track polyline** (not an inferred corridor)
- Labels tracks in a human-friendly way when possible (e.g. airline + flight number), with optional NYC airport hint (`→ LGA`, `→ EWR`, etc.)

**Note:** ADS‑B is sampled data. Lines can look segmented if the provider misses samples; DwellSense trims to the contiguous “nearby pass” around closest approach to avoid drawing irrelevant far-away segments.

**Altitude caveats:** OpenSky altitude fields can be missing or noisy. The UI uses a **median altitude** over available samples and ignores obviously invalid near-zero altitudes when computing medians.

**Human labels (partial mapping):** OpenSky callsigns often look like `DAL1234` (ICAO airline designator + digits). `backend/services/flights.py` maps a **small curated set** of common NYC carriers (and some regionals) to friendly names; unknown carriers fall back to the raw callsign string.

### Frontend rendering

`frontend/components/MapComponent.tsx`:

- Draws up to 3 flight polylines (solid for ADS‑B tracks; dashed for static corridors)
- Shows caption when displaying live tracks: **“Live flight tracks (recent).”**
- Animates a small ✈️ icon **per flight path** along each polyline/segment

**Map lifecycle fixes (important):** the map is created once; flight overlays must update when scan results change. The component queues updates until Mapbox style is loaded and recenters when the property moves.

#### Flight Activity UI (current)

Under the map, the UI shows a **Flight Activity** block:

- Summary chips (when available): **Night `/hr`**, **Day `/hr`**, **Typical altitude**, **Data quality**
- Track chips (horizontal scroll): label + `~altitude ft` + `closest mi` + “seen Xm ago”

Users do **not** need to understand “ADS‑B”; we avoid showing that term in the UI.

### Flight exposure score (prototype)

The backend now returns an optional `flight_exposure` field on the scan response:

- `night_overflights_per_hour`
- `day_overflights_per_hour`
- `typical_altitude_ft`
- `data_quality` (`good` | `sparse` | `unavailable`)

Important: this prototype uses Supabase storage; if Supabase is unreachable or ingestion isn’t running, exposure returns **`data_quality="unavailable"`** and the UI shows **“Exposure: unavailable”**.

**Fail-open behavior:** `/scan` must not crash if Supabase is down; exposure computation is wrapped so scans still succeed.

**Known limitation (honesty):** the current night/day split in `flight_exposure.py` is still a **prototype** (UTC-hour heuristic). Before production, this should be switched to **America/New_York** local time windows and tuned to match renter expectations (e.g. “late night”).

---

## Local Development

**Backend**

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in keys
FLIGHT_MODE=adsb uvicorn main:app --reload --host 127.0.0.1 --port 8000   # optional: ADS‑B tracks
python main.py
```

### ADS‑B exposure prototype (local)

1. **Preferred:** configure GitHub Action secrets (see **README** / **`.github/workflows/supabase-migrations.yml`**) and run **Deploy Supabase migrations** or push to `main`.
2. **Manual:** run `backend/sql/adsb_samples.sql` in the Supabase SQL editor (same DDL as `supabase/migrations/`).
2. **Production ingest:** set **`ADSB_INGEST_ENABLED=true`** on Railway (same service as the API). Optionally tune **`ADSB_INGEST_INTERVAL_SECONDS`** (default **3600** = 1 hour in code; set on Railway to override).

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

## Where We Left Off (Before Deploying to “Real Site”)

We have implemented and tested locally (Next.js dev + FastAPI):

- NYC-only scans (backend guardrail) + NYC-locked map viewport
- Flight overlays:
  - multi-path support (`flight_paths`)
  - ADS‑B live tracks mode (`FLIGHT_MODE=adsb`)
  - human-friendly flight labels (airline/flight number when parsable)
  - per-path plane animations
  - “Flight Activity” UI module
- Flight exposure prototype (`flight_exposure`) backed by Supabase `adsb_samples` + ingest loop

**Not deployed yet:** production must still:

- have latest **`main`** deployed on Railway/Vercel
- ensure Railway/Vercel env vars are set (`FLIGHT_MODE`, `ADSB_INGEST_*`, etc.)
- configure GitHub Action secrets and let **Deploy Supabase migrations** apply `supabase/migrations/`, **or** paste `backend/sql/adsb_samples.sql` once in the Supabase SQL editor (if using exposure)
- decide whether production should use `FLIGHT_MODE=static` or a paid ADS‑B provider + ingestion pipeline

**Next decisions before prod:**

- **Commercial ADS‑B provider vs OpenSky** (coverage, SLA, licensing)
- **Whether prod should default to `FLIGHT_MODE=static`** until ingestion is stable
- **Ingestion:** set **`ADSB_INGEST_ENABLED=true`** on Railway (timer inside API) or run a separate worker / `python -m jobs.adsb_ingest`
- **Replace UTC night/day heuristic** with NYC-local windows + clearer copy (“late night”, “weekday vs weekend”)

---

## Recent changelog (high-signal)

- **Risk banner copy:** removed “block/neighborhood” wording from deterministic risk labels (`backend/services/threat_card_layout.py`).
- **Geocoding:** Mapbox requests ignore system proxy env vars; addresses are URL-encoded (`backend/services/geocoding.py`).
- **Flights:** evolved from static corridors → multi-corridor → OpenSky live tracks with polylines + UI polish (`backend/services/flights.py`, `frontend/components/MapComponent.tsx`).
- **Flight UX:** multiple ✈️ animations (one per path), “seen Xm ago” relative timestamps from `last_seen_utc`, and copy that avoids dumping raw ADS‑B jargon on renters.
- **Mapbox paint correctness:** avoid `undefined` dash arrays when toggling dashed vs solid lines.
- **Exposure prototype:** `adsb_samples` + ingest + `flight_exposure` on scan; optional **`ADSB_INGEST_ENABLED`** timer in `main.py` (`backend/sql/adsb_samples.sql`, `backend/jobs/adsb_ingest.py`, `backend/services/flight_exposure.py`, `backend/routers/scan.py`, `backend/models/schemas.py`, `frontend/lib/types.ts`).

---

*Last updated: optional ADS-B sample ingest via `ADSB_INGEST_ENABLED` in `main.py`; docs for Supabase SQL + Railway env.*
