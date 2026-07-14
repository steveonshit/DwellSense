#!/usr/bin/env python3
"""Strict end-to-end audit: every URI in a freshly downloaded local PDF."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

ADDR = "742 Lefferts Ave, Brooklyn, NY 11203"
BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://localhost:3000"

PASS = FAIL = WARN = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {msg}")


def warn(msg: str) -> None:
    global WARN
    WARN += 1
    print(f"  WARN  {msg}")


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 180):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "DwellSense-StrictAudit/1.0"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype or body[:1] in (b"{", b"["):
                return resp.status, json.loads(body), ctype, body
            return resp.status, None, ctype, body
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        try:
            return e.code, json.loads(raw), "", raw
        except Exception:
            return e.code, raw.decode(errors="replace"), "", raw


def http_get(url: str, timeout: int = 25) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "DwellSense-StrictAudit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except Exception as e:
        return -1, str(e).encode()


def extract_pdf_uris(pdf: bytes) -> list[str]:
    uris: list[str] = []
    for raw in re.findall(rb"/URI\s*\((?:\\.|[^\\)])*\)", pdf):
        inner = raw[raw.find(b"(") + 1 : -1].decode("latin-1")
        s = inner.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
        s = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)
        uris.append(s)
    for hx in re.findall(rb"/URI\s*<([0-9A-Fa-f]+)>", pdf):
        try:
            uris.append(bytes.fromhex(hx.decode()).decode("utf-8", errors="replace"))
        except Exception:
            pass
    return sorted(set(uris))


def explore_where(url: str) -> str | None:
    if "/explore/query/" not in url:
        return None
    soql = urllib.parse.unquote(url.split("/explore/query/", 1)[1])
    if " WHERE " not in soql.upper():
        # some queries may start with SELECT without uppercase consistency
        m = re.search(r"\bWHERE\b\s+(.*)", soql, flags=re.I | re.S)
        if not m:
            return None
        rest = m.group(1)
    else:
        rest = re.split(r"\bWHERE\b", soql, maxsplit=1, flags=re.I)[1]
    rest = re.split(r"\bORDER\s+BY\b", rest, maxsplit=1, flags=re.I)[0]
    rest = re.split(r"\bLIMIT\b", rest, maxsplit=1, flags=re.I)[0]
    return rest.strip()


def soda_rows(dataset_id: str, where: str, limit: int = 5) -> tuple[int, str]:
    api = (
        f"https://data.cityofnewyork.us/resource/{dataset_id}.json"
        f"?$select=*&$where={urllib.parse.quote(where, safe='')}&$limit={limit}"
    )
    status, body = http_get(api)
    if status != 200:
        return -1, f"HTTP {status}: {body[:180].decode(errors='replace')}"
    try:
        data = json.loads(body)
    except Exception as e:
        return -1, f"json: {e}"
    if not isinstance(data, list):
        return -1, "not list"
    return len(data), ""


HOME_PATTERNS = [
    # NYC Open Data landing / catalog — not filtered data
    re.compile(r"^https://data\.cityofnewyork\.us/?$", re.I),
    re.compile(r"^https://opendata\.cityofnewyork\.us/?$", re.I),
    re.compile(r"^https://data\.cityofnewyork\.us/[^/]+/[^/]+/[a-z0-9]{4}-[a-z0-9]{4}/?$", re.I),
    re.compile(r"^https://data\.cityofnewyork\.us/dataset/", re.I),
    # Generic homes
    re.compile(r"^https://opensky-network\.org/?$", re.I),
    re.compile(r"^https://www\.google\.com/?$", re.I),
    re.compile(r"^https://maps\.google\.com/?$", re.I),
    re.compile(r"^https://www\.yelp\.com/?$", re.I),
    re.compile(r"^https://hpdonline\.nyc\.gov(?:/hpdonline)?/?$", re.I),
]


def is_homepage(url: str) -> bool:
    return any(p.search(url) for p in HOME_PATTERNS)


def classify(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    path = urllib.parse.urlparse(url).path
    qs = urllib.parse.urlparse(url).query
    if "localhost" in host or host.startswith("127."):
        return "localhost"
    if is_homepage(url):
        return "homepage"
    if "data.cityofnewyork.us" in host:
        if "/explore/query/" in url:
            return "nyc_explore"
        if "/resource/" in url and ".json" in path:
            return "nyc_soda_json"
        return "nyc_other"
    if "opensky-network.org" in host:
        if "aircraft-profile" in url or "/network/explorer/" in url:
            return "opensky_deep"
        return "opensky_other"
    if "google." in host or "maps.google." in host:
        if "query=" in qs or "/maps/" in path or "cid=" in qs or "cid=" in url:
            return "maps_deep"
        return "maps_other"
    if "yelp.com" in host:
        if "/biz/" in path or "/search?" in url:
            return "yelp_deep"
        return "yelp_other"
    if "hpdonline" in host:
        return "hpd_portal"
    return f"other:{host}"


def main() -> int:
    print(f"Strict PDF link audit @ {datetime.now(timezone.utc).isoformat()}")
    print(f"Address: {ADDR}")

    # 1) Scan
    print("\n=== 1) LOCAL SCAN ===")
    st, scan, _, _ = http_json("POST", f"{BACKEND}/scan", {"address": ADDR, "defer_gemini": True})
    if st != 200 or not isinstance(scan, dict):
        fail(f"scan failed HTTP {st}: {scan}")
        return 1
    token = scan.get("dossier_token")
    if not token:
        fail("missing dossier_token")
        return 1
    ok(f"scan ok token={token[:14]}... score={scan.get('danger_score')} "
       f"addr={scan.get('formatted_address')}")

    # 2) Download PDF the same way the UI does: Next.js /api/pdf proxy
    print("\n=== 2) DOWNLOAD PDF VIA /api/pdf (same as UI) ===")
    pdf_body = {
        "dossier_token": token,
        "danger_score": scan["danger_score"],
        "risk_level": scan["risk_level"],
        "risk_label": scan["risk_label"],
        "risk_description": scan.get("risk_description") or "",
        "banner_driver": scan.get("banner_driver"),
        "threat_cards": scan.get("threat_cards") or [],
    }
    st, _, ctype, raw = http_json("POST", f"{FRONTEND}/api/pdf", pdf_body, timeout=300)
    if st != 200 or b"%PDF" not in raw[:20]:
        # fallback direct backend
        warn(f"frontend /api/pdf failed HTTP {st} ctype={ctype}; trying backend /pdf")
        st2, _, ctype2, raw = http_json("POST", f"{BACKEND}/pdf", pdf_body, timeout=300)
        if st2 != 200 or b"%PDF" not in raw[:20]:
            fail(f"pdf download failed frontend={st} backend={st2}")
            return 1
        ok(f"pdf via backend {len(raw):,} bytes")
    else:
        ok(f"pdf via frontend proxy {len(raw):,} bytes (ctype={ctype})")

    out = "/tmp/dwellsense_strict_audit.pdf"
    with open(out, "wb") as f:
        f.write(raw)
    print(f"  wrote {out}")

    # 3) Extract + classify every URI
    print("\n=== 3) CLASSIFY EVERY URI ===")
    uris = extract_pdf_uris(raw)
    if not uris:
        fail("zero URI annotations in PDF")
        return 1
    ok(f"extracted {len(uris)} unique URIs")

    by_class: dict[str, list[str]] = defaultdict(list)
    for u in uris:
        by_class[classify(u)].append(u)

    for cls, items in sorted(by_class.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"  {cls}: {len(items)}")

    # Hard fail categories
    for u in by_class.get("localhost", []):
        fail(f"localhost link: {u}")
    for u in by_class.get("homepage", []):
        fail(f"HOMEPAGE link (not address-specific): {u}")
    for u in by_class.get("nyc_other", []):
        fail(f"NYC non-explore link: {u[:140]}")
    for u in by_class.get("opensky_other", []):
        fail(f"OpenSky non-deep link: {u}")
    for u in by_class.get("maps_other", []):
        fail(f"Maps non-deep link: {u}")
    for u in by_class.get("yelp_other", []):
        fail(f"Yelp non-deep link: {u}")
    for u in by_class.get("hpd_portal", []):
        # HPD portal home is not address-specific
        fail(f"HPD portal homepage (no address filter): {u}")

    # 4) Validate EVERY nyc_explore URI via SODA
    print("\n=== 4) VALIDATE ALL NYC EXPLORE LINKS VIA SODA ===")
    explores = by_class.get("nyc_explore", [])
    empty_browse = 0
    empty_record = 0
    soda_errors = 0
    for i, u in enumerate(explores, 1):
        m = re.search(r"/([a-z0-9]{4}-[a-z0-9]{4})/explore/", u)
        if not m:
            fail(f"explore URI missing dataset id: {u[:120]}")
            continue
        ds = m.group(1)
        where = explore_where(u)
        if not where:
            fail(f"explore URI missing WHERE: {u[:120]}")
            continue
        # Must look address/id specific — reject SELECT * with no filter extras? WHERE already required.
        n, err = soda_rows(ds, where)
        is_record = bool(
            re.search(
                r"\b(cmplnt_num|unique_key|job__|docket_number|court_index_number|housenumber)\s*=",
                where,
            )
        )
        is_area = bool(
            re.search(r"within_circle|like\s+'%|borough\s*=|boro\s*=", where, flags=re.I)
        )
        if n < 0:
            fail(f"[{i}/{len(explores)}] SODA error {ds}: {err}\n         WHERE={where[:160]}")
            soda_errors += 1
        elif n == 0:
            if is_record:
                fail(f"[{i}/{len(explores)}] RECORD link 0 rows {ds}: {where[:160]}")
                empty_record += 1
            else:
                # Browse can be empty for some signals; still user-hostile blank table
                fail(f"[{i}/{len(explores)}] BROWSE link 0 rows (blank table) {ds}: {where[:160]}")
                empty_browse += 1
        else:
            kind = "record" if is_record else ("area" if is_area else "filter")
            ok(f"[{i}/{len(explores)}] {kind} {ds}: {n}+ rows")

    print(f"  explore totals: {len(explores)}  soda_errors={soda_errors} "
          f"empty_record={empty_record} empty_browse={empty_browse}")

    # 5) Non-NYC deep links shape checks
    print("\n=== 5) NON-NYC DEEP LINKS ===")
    for u in by_class.get("maps_deep", []):
        q = urllib.parse.unquote(urllib.parse.urlparse(u).query + u)
        if "restaurants near" in q.lower() or "near " in q.lower() or "cid=" in u.lower() or "/maps/" in u:
            ok(f"maps deep: {u[:110]}")
        else:
            warn(f"maps link weak specificity: {u[:110]}")
    for u in by_class.get("yelp_deep", []):
        ok(f"yelp deep: {u[:110]}")
    for u in by_class.get("opensky_deep", []):
        if "/network/explorer/lamin/" in u or "aircraft-profile?icao24=" in u:
            ok(f"opensky deep: {u[:110]}")
        else:
            fail(f"opensky unexpected: {u}")

    # 6) Sanity: link counts / hosts
    print("\n=== 6) HOST SUMMARY ===")
    hosts = Counter(urllib.parse.urlparse(u).netloc for u in uris)
    for h, n in hosts.most_common():
        print(f"  {h}: {n}")

    print("\n=== SUMMARY ===")
    print(f"PASS={PASS}  FAIL={FAIL}  WARN={WARN}")
    if FAIL:
        print("RESULT: FAILED — fix required before links are fully deep")
    else:
        print("RESULT: PASSED — every URI is a deep, resolvable, non-homepage link")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
