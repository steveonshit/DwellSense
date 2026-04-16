# DwellSense — Project Overview

This document describes the **DwellSense** codebase, architecture, deployment, and work completed during setup (GitHub, Railway, Vercel, debugging). It is the **canonical overview** for contributors and for tools like **Claude Code** (read this file first).

---

## What DwellSense Is

**DwellSense** is a NYC-focused “real estate forensics” web app. A user enters an address; the system:

- Geocodes the address (Mapbox)
- Pulls nearby **crime**, **311**, **permits**, and **evictions** from **Supabase** (pre-loaded via a daily job)
- Fetches **transit / grocery / retail** proximity via **Google Places API (New)**
- Computes a **flight corridor** (pure geometry)
- Builds **danger score**, **risk labels**, and **threat-card chrome** (titles, colors, emojis) in **Python**; **Google Gemini** writes only the **27 bullet strings** (three per card) from the same data brief
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
| AI | Google Gemini (`gemini-2.0-flash`) for **bullets only**; card chrome + score in Python |
| Maps / geo | Mapbox (geocoding + map), Google Places API (New), Distance Matrix (if used) |
| Hosting | **Vercel** (frontend), **Railway** (backend) |

---

## Request Flow (Production)

1. User submits an address on **Vercel** (e.g. `dwellsense.vercel.app`).
2. Browser calls **`POST /api/scan`** on the Next.js app (keeps `BACKEND_URL` server-side).
3. Next.js proxies to **`POST {BACKEND_URL}/scan`** on Railway with a **~110s** upstream timeout; the route declares **`maxDuration = 120`** seconds.
4. Backend runs geocoding, parallel DB + Places calls, flight math, then **Gemini** (bullets only — often the slowest step).
5. JSON response drives the UI (map, logistics carousel, threat cards).

**Loading ad (UX):** `frontend/components/LoadingAd.tsx` runs a **5-second** countdown. The ad only completes when **both** the timer hits zero **and** the scan request has finished (`isApiReady`). If the scan takes longer than 5s, the user waits past the ad until data arrives. If they skip the ad early, they still wait until the API returns.

**Client:** `frontend/app/page.tsx` uses `AbortSignal.timeout(115_000)` on the fetch to `/api/scan` so the UI does not hang forever.

**Health check:** `GET /health` on the backend returns `{"status":"ok","service":"DwellSense API"}`.

---

## Environment Variables

### Backend (Railway / local)

| Variable | Purpose |
|----------|---------|
| `MAPBOX_TOKEN` | Geocoding |
| `GOOGLE_MAPS_API_KEY` | Places API (New) — transit, grocery, Target, etc. **Must be a real key, not a placeholder.** |
| `GEMINI_API_KEY` | AI threat analysis |
| `GEMINI_TIMEOUT_SECONDS` | Optional. Seconds for `asyncio.wait_for` around Gemini (default **90**). See `backend/.env.example`. |
| `SUPABASE_URL` | Database URL |
| `SUPABASE_SERVICE_KEY` | Service role key (not anon) |
| `FRONTEND_URL` | CORS — set to your Vercel URL in production |
| `PORT` | Railway sets this automatically |

### Frontend (Vercel / local)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Mapbox map (public by design) |
| `BACKEND_URL` | Railway backend URL (e.g. `https://dwellsense-production.up.railway.app`) |

---

## Deployment Summary

### GitHub

- Remote: `https://github.com/steveonshit/DwellSense.git`
- `.gitignore` excludes `backend/.env`, `backend/venv/`, `frontend/.env.local`, `frontend/node_modules/`, etc.

### Railway (backend)

- **Root directory:** `backend` (required — whole-repo builds fail without this).
- **Public URL:** generated under **Networking → Generate Domain**.
- **Auto-deploy:** on push to `main` (typical GitHub integration).

### Vercel (frontend)

- Project linked to **`frontend`** as root (or deploy from `frontend/` via CLI).
- **`vercel.json`** sets **`maxDuration`: 120** seconds for `app/api/scan/route.ts` and `app/api/pdf/route.ts` so long scans (Gemini + Places) are not cut off by the default serverless limit.
- **`frontend/app/api/scan/route.ts`** also exports `maxDuration = 120` and uses `AbortSignal.timeout(110_000)` on the fetch to the backend.

---

## Supabase Schema

Tables used by the app include (see `README.md` for full SQL):

- `crime_reports`
- `reports_311`
- `building_permits`
- `eviction_records`

Populate via **`python -m jobs.daily_refresh`** (local) or the scheduled job in `main.py` (3:00 AM). Empty tables are allowed; the app degrades gracefully.

---

## Notable Code Locations

| Area | Path |
|------|------|
| Main scan pipeline | `backend/routers/scan.py` |
| Threat card layout + deterministic risk | `backend/services/threat_card_layout.py` |
| Gemini (bullets only) + merge / fallback | `backend/services/ai_analysis.py` |
| Places / logistics cards | `backend/services/places.py` |
| City data + swarm pins | `backend/services/city_data.py` |
| Swarm pin types | `backend/models/schemas.py` (`SwarmPin`) |
| Next.js scan proxy | `frontend/app/api/scan/route.ts` |
| Scan + loading ad flow | `frontend/app/page.tsx`, `frontend/components/LoadingAd.tsx` |
| Results UI | `frontend/components/ResultsDashboard.tsx` |
| Map + markers | `frontend/components/MapComponent.tsx` |
| Logistics carousel | `frontend/components/LogisticsCarousel.tsx` |

---

## Gemini / AI (Current Behavior)

**Split of responsibilities (implemented):**

| Piece | Where |
|--------|--------|
| Nine cards’ **ids, emoji, titles, subtitles, hex colors** | `threat_card_layout.py` (`CARD_SPECS`) |
| **Danger score**, **risk_level**, **risk_label**, **risk_description** (count-based formula; description includes eviction count) | `threat_card_layout.compute_risk_from_counts` |
| **27 bullets** (three per card) | Gemini `gemini-2.0-flash` returns JSON `{ "bullets": { "high_churn": ["","",""], ... } }` only |
| Merge + validation | `ai_analysis.py` merges Gemini bullets into the fixed chrome; **per-card** fallback to template bullets if fewer than two non-empty strings |

**Gemini call details:**

- **Model:** `gemini-2.0-flash` with system instruction `BULLETS_SYSTEM_PROMPT`; **`response_mime_type: application/json`**.
- **Timeout:** `GEMINI_TIMEOUT_SECONDS` (default 90) wrapping `asyncio.to_thread(model.generate_content, ...)`.
- **Parsing:** Response text is read safely (including when `.text` is empty); JSON tolerates markdown fences; one retry on non-timeout failures.
- **Fallback bullets:** If the key is missing → template bullets with a third line mentioning **`GEMINI_API_KEY`**. If the key exists but Gemini errors or times out → template third line says **AI summary unavailable**; counts/map still valid.
- **Cache:** In-memory cache keyed by address hash + crime / 311 / permit / **eviction** counts (`ai_analysis.py`).

---

## Roadmap / Product Ideas

**Implemented:**

- **Smaller Gemini ask:** Scoring and threat-card chrome live in Python; Gemini returns only **`bullets`** JSON — reduces latency vs the old full-card JSON.

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

### Backend behavior (production debugging)

- **Only airport + mall in logistics:** `GOOGLE_MAPS_API_KEY` on Railway was still a **placeholder** (`YOUR_GOOGLE_MAPS_API_KEY_HERE`). Places calls failed silently; code fell back to static airport/mall only. **Fix:** set the real Google Maps API key in Railway Variables.
- **Google Cloud API key restrictions:** If restricted, ensure **Places API (New)** (and related Maps APIs) are allowed for that key.
- **Gemini / generic bullets:** Check Railway logs for timeout, empty/blocked responses, JSON parse errors, or quota — not only “too little time.”

### Frontend map UX

- **Pins jumping to top-left on hover:** CSS `transform: scale()` without `transform-origin` on custom Mapbox marker elements. **Fix:** `transform-origin: center center` on swarm and logistics marker elements in `MapComponent.tsx`.

---

## Local Development

**Backend**

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in keys
python main.py
```

**Frontend**

```bash
cd frontend
cp .env.local.example .env.local   # set NEXT_PUBLIC_MAPBOX_TOKEN, BACKEND_URL
npm install
npm run dev
```

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

*Last updated: Python vs Gemini split (`threat_card_layout.py` + bullets-only Gemini), cache key includes evictions, roadmap reflects implemented “smaller ask”; remaining: two-phase load + optional model swap.*
