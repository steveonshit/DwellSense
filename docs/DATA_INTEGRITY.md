# Data integrity (non-negotiable)

**ALWAYS USE REAL DATA. NEVER FAKE OR MAKE UP ANY DATA.**

This file exists so Graphify and Cursor always have a dedicated, searchable node for ZerMap’s data-truth law. Full product context: `project.md` → **Data integrity**.

## Law

Every user-visible number, pin, score input, listing, and map marker must trace to a **real source**:

- NYC Open Data / Supabase municipal tables
- Google Places
- Yelp Fusion
- Mapbox geocoding
- ADS-B ingest (`adsb_samples`)
- other real APIs configured for the product

## Rules

| Rule | Requirement |
|------|-------------|
| **No invented records** | Do not place pins, counts, or incidents that are not in the fetched datasets. |
| **No synthetic fallbacks on the map** | Do not draw heuristic flight corridors, random jitter, or demo swarms when live data is missing — show **nothing** or label **unavailable**. |
| **Truncation must be honest** | If the map shows a subset of real locations for readability, the UI must say so (e.g. “Showing 100 of 1,896 real locations”). Scoring and risk copy still use the **full** in-radius counts. |
| **Unavailable means unavailable** | If an API or table has no data, return empty / `unavailable` — never approximate without clear labeling. |
| **PDF / external links** | Every dossier hyperlink must open a **real external source page already filtered** to the address, scan area, or exact record — never a site homepage and never a localhost proxy. |

## Allowed (display-only, not new facts)

- Great-circle smoothing of **existing** ADS-B vertices for map rendering
- Merged label when multiple real records share one NYC geocode

## Explicit demo mode (not a silent fallback)

- `FLIGHT_MODE=static` may show hand-authored corridor segments as an **explicit demo mode**.
- `FLIGHT_MODE=auto` and `live_adsb` must **not** fall back to those corridors when ADS-B is missing — return **no paths**.

## Agent checklist (scan / map / score / dining / flights / PDF)

1. Is this value from a real fetch or table row?
2. If missing, do we return empty / `unavailable` instead of inventing?
3. If the UI shows fewer pins than exist, is the caption honest?
4. Do PDF links open filtered official pages (not homepages / localhost)?

If any answer is no, fix before shipping.
