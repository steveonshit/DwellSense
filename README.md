# DwellSense — Real Estate Forensics Platform

> Don't sign a blind lease. Landlords sell the layout. We expose the reality.

---

## Project Structure

```
DwellSense/
├── frontend/        Next.js 14 + Tailwind CSS + Mapbox GL JS
└── backend/         Python FastAPI + Gemini AI + Supabase
```

---

## Prerequisites — Install These First

### 1. Node.js (for the frontend)
Download from: https://nodejs.org (choose the LTS version)
After installing, verify with: `node --version`

### 2. Python 3.12+ (already installed on your machine)
Verify with: `python3 --version`

---

## Setup Guide

### Step 1 — Get Your API Keys

You need accounts and keys for:

| Service | What it does | Where to get it |
|---|---|---|
| **Mapbox** | Map rendering + geocoding | mapbox.com → Account → Tokens |
| **Google Maps Platform** | Transit/grocery distances | console.cloud.google.com → Enable: Places API, Distance Matrix API |
| **Google Gemini** | AI threat analysis | aistudio.google.com → Get API Key |
| **Supabase** | Database | supabase.com → New Project → Settings → API |

---

### Step 2 — Set Up the Database (Supabase)

In your Supabase project, go to **SQL Editor** and run this:

```sql
-- Crime reports from NYPD
CREATE TABLE crime_reports (
  id BIGSERIAL PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  crime_type TEXT,
  description TEXT,
  occurred_at TIMESTAMPTZ,
  borough TEXT,
  source_id TEXT UNIQUE
);
CREATE INDEX crime_reports_lat_lng ON crime_reports (lat, lng);

-- 311 Service Requests
CREATE TABLE reports_311 (
  id BIGSERIAL PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  complaint_type TEXT,
  descriptor TEXT,
  created_at TIMESTAMPTZ,
  borough TEXT,
  source_id TEXT UNIQUE
);
CREATE INDEX reports_311_lat_lng ON reports_311 (lat, lng);

-- DOB Building Permits
CREATE TABLE building_permits (
  id BIGSERIAL PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  permit_type TEXT,
  permit_status TEXT,
  job_description TEXT,
  filing_date TIMESTAMPTZ,
  expiration_date TIMESTAMPTZ,
  source_id TEXT UNIQUE
);
CREATE INDEX building_permits_lat_lng ON building_permits (lat, lng);

-- Eviction Records
CREATE TABLE eviction_records (
  id BIGSERIAL PRIMARY KEY,
  lat DOUBLE PRECISION NOT NULL,
  lng DOUBLE PRECISION NOT NULL,
  case_type TEXT,
  filing_date TIMESTAMPTZ,
  source_id TEXT UNIQUE
);
CREATE INDEX eviction_records_lat_lng ON eviction_records (lat, lng);
```

---

### Step 3 — Configure Environment Variables

**Backend:**
```bash
cd backend
cp .env.example .env
# Open .env and fill in all your API keys
```

**Frontend:**
```bash
cd frontend
cp .env.local.example .env.local
# Open .env.local and fill in your Mapbox token
```

---

### Step 4 — Install Dependencies

**Backend (Python):**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Frontend (Node.js):**
```bash
cd frontend
npm install
```

---

### Step 5 — Run Your First Data Refresh

This downloads the latest NYC data into your Supabase database.
Run this once now, and it will auto-run every day at 3 AM after that.

```bash
cd backend
source venv/bin/activate
python -m jobs.daily_refresh
```

This takes 1-3 minutes. You'll see logs showing how many records were downloaded.

---

### Step 6 — Start the Application

Open **two terminals**:

**Terminal 1 — Backend:**
```bash
cd backend
source venv/bin/activate
python main.py
```
Backend will be running at: http://localhost:8000

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```
Frontend will be running at: http://localhost:3000

Open http://localhost:3000 in your browser. Type any NYC address and click **RUN FORENSICS**.

---

## How It Works

1. User enters an NYC address → frontend sends to Next.js API route
2. Next.js proxies to Python FastAPI backend (keeps API keys safe)
3. Backend geocodes the address with Mapbox
4. Backend queries Supabase for nearby crime, 311, and permit data (pre-loaded daily)
5. Backend calls Google Maps for nearest transit/grocery (live, per request)
6. Backend computes the nearest flight corridor (instant math)
7. All data gets sent to Gemini AI, which writes the danger score + 9-point analysis
8. Results sent back to frontend → displayed on the map + carousels

---

## Deploying to Production

**Frontend → Vercel (free):**
```bash
cd frontend
npx vercel
```
Set `NEXT_PUBLIC_MAPBOX_TOKEN` and `BACKEND_URL` in Vercel's environment settings.

**Backend → Railway (paid, ~$5/mo):**
Push the `backend/` folder to a GitHub repo, connect to Railway, set all env vars.

---

## Daily Data Refresh Schedule

The backend auto-runs the NYC data refresh every night at 3:00 AM.
This keeps crime/311/permit data fresh without you doing anything.
To trigger it manually: `python -m jobs.daily_refresh`
