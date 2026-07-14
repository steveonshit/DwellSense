"""Institutional-grade PDF dossier — earnings-report layout with source deep links."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from fpdf import FPDF

from models.schemas import Coordinate
from services.city_data import (
    CRIME_DAYS_BACK,
    EVICTION_DAYS_BACK,
    PERMIT_DAYS_BACK,
    REPORTS_311_DAYS_BACK,
)
from services.dossier_context import DossierContext
from services import source_links

PDF_311_MAX = 200
PDF_CARD_RECORDS_MAX = 50

RISK_COLORS = {
    "EXTREME": (180, 40, 40),
    "HIGH": (180, 90, 20),
    "MODERATE": (140, 110, 20),
    "LOW": (30, 100, 60),
}

WELLNESS_BANDS = [
    ("91-100", "Outstanding"),
    ("81-90", "Excellent"),
    ("69-80", "Great"),
    ("56-68", "Very Good"),
    ("43-55", "Good"),
    ("29-42", "Average"),
    ("16-28", "Bad"),
    ("0-15", "Terrible"),
]

_CARD_DATASET_KEY: dict[str, str] = {
    "high_churn": "evictions",
    "police_calls": "crime",
    "area_safety": "crime",
    "demolitions": "permits",
    "noise_schedule": "311",
    "reports_311": "311",
}

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "\uFE0F"
    "]+",
    flags=re.UNICODE,
)

_ASCII_REPLACEMENTS = str.maketrans({
    "\u2014": "-",
    "\u2013": "-",
    "\u2022": "*",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a9": "(c)",
    "\u00ae": "(R)",
})

# Institutional palette (navy / warm gray / gold accent)
_NAVY = (0, 45, 114)
_GOLD = (168, 139, 70)
_INK = (33, 33, 33)
_BODY = (68, 68, 68)
_MUTED = (120, 120, 120)
_RULE = (190, 190, 190)
_RULE_LIGHT = (220, 220, 220)
_WHITE = (255, 255, 255)
_LINK = (0, 45, 114)
_WATERMARK = (230, 230, 230)

_LINK_DISPLAY = {
    "Source": "View source record",
    "Browse all": "Browse records near this address",
    "Dataset": "View filtered records near this address",
    "Listing": "Open business listing",
    "HPD": "HPD violations for this address",
}

# Layout — generous margins like formal filings
_MARGIN_L = 20
_MARGIN_R = 20
_MARGIN_T = 22
_MARGIN_B = 18
_CONTENT_W = 210 - _MARGIN_L - _MARGIN_R
_PAGE_BOTTOM = 297 - _MARGIN_B - 8


def pdf_text(value: object, *, default: str = "", max_len: int = 0) -> str:
    if value is None:
        return default
    text = str(value)
    text = _EMOJI_RE.sub("", text)
    text = text.translate(_ASCII_REPLACEMENTS)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("latin-1", errors="ignore").decode("latin-1")
    text = text.strip() or default
    if max_len > 0 and len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    raw = (hex_color or "#787878").strip().lstrip("#")
    if len(raw) >= 6 and all(c in "0123456789abcdefABCDEF" for c in raw[:6]):
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return 120, 120, 120


def _311_blob(row: dict) -> str:
    ctype = str(row.get("complaint_type") or "")
    desc = str(row.get("descriptor") or "")
    return f"{ctype} {desc}".lower()


def _filter_311_noise(rows: list[dict]) -> list[dict]:
    keys = ("noise", "loud", "music", "party")
    return [r for r in rows if any(k in _311_blob(r) for k in keys)]


def _filter_311_construction(rows: list[dict]) -> list[dict]:
    keys = ("construction", "building", "scaffold", "demolition", "crane")
    return [r for r in rows if any(k in _311_blob(r) for k in keys)]


def _freq_label(rate: float) -> str:
    if rate < 0.2:
        return "Rare"
    if rate < 0.7:
        return "Occasional"
    if rate < 2:
        return "Fairly common"
    return "Frequent"


def _coord(ctx: DossierContext) -> Coordinate:
    return Coordinate(lat=ctx.coord_lat, lng=ctx.coord_lng)


# ── Typography helpers ────────────────────────────────────────────────────────

def _font_sans(pdf: FPDF, style: str = "", size: int = 9) -> None:
    pdf.set_font("Helvetica", style, size)


def _font_serif(pdf: FPDF, style: str = "", size: int = 10) -> None:
    pdf.set_font("Times", style, size)


def _count_lines(pdf: FPDF, width: float, text: str, *, line_h: float = 4) -> int:
    if not text:
        return 0
    lines = pdf.multi_cell(width, line_h, pdf_text(text), split_only=True)
    return max(1, len(lines))


def _text_height(
    pdf: FPDF, width: float, text: str, *, line_h: float = 4,
    family: str = "sans", style: str = "", size: int = 9,
) -> float:
    if family == "serif":
        _font_serif(pdf, style, size)
    else:
        _font_sans(pdf, style, size)
    return _count_lines(pdf, width, text, line_h=line_h) * line_h


def _hrule(pdf: FPDF, *, y: float | None = None, color: tuple[int, int, int] = _RULE) -> None:
    y = pdf.get_y() if y is None else y
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.2)
    pdf.line(_MARGIN_L, y, _MARGIN_L + _CONTENT_W, y)
    pdf.set_line_width(0.2)


def _ensure_space(pdf: FPDF, needed: float) -> None:
    if pdf.get_y() + needed > _PAGE_BOTTOM:
        pdf.add_page()


# ── PDF document class ────────────────────────────────────────────────────────

class DossierPDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self._running_section = ""
        self._property_label = ""

    def header(self) -> None:
        if self.page_no() <= 1:
            return
        self.set_y(10)
        _font_sans(self, "B", 7)
        self.set_text_color(*_NAVY)
        self.set_x(_MARGIN_L)
        self.cell(50, 4, "DWELLSENSE", ln=False)
        _font_sans(self, "", 7)
        self.set_text_color(*_MUTED)
        self.cell(80, 4, "Full Data Report", ln=False, align="C")
        if self._running_section:
            self.cell(0, 4, pdf_text(self._running_section, max_len=50), ln=True, align="R")
        else:
            self.ln(4)
        _hrule(self, y=16, color=_RULE_LIGHT)
        self.set_y(_MARGIN_T)

    def footer(self) -> None:
        self.set_y(-14)
        _hrule(self, color=_RULE_LIGHT)
        self.set_y(-11)
        _font_sans(self, "", 6.5)
        self.set_text_color(*_MUTED)
        self.set_x(_MARGIN_L)
        self.cell(90, 3, pdf_text(self._property_label, max_len=60), ln=False)
        self.cell(0, 3, f"Page {self.page_no()}/{{nb}}", align="R")

    def set_section(self, name: str) -> None:
        self._running_section = name


# ── Cover page ────────────────────────────────────────────────────────────────

def _render_cover(pdf: DossierPDF, address: str) -> None:
    pdf._property_label = pdf_text(address, max_len=80)
    # Gold accent rule at top
    pdf.set_fill_color(*_GOLD)
    pdf.rect(0, 0, 210, 1.2, "F")
    # Navy band
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, 1.2, 210, 52, "F")
    pdf.set_text_color(*_WHITE)
    _font_sans(pdf, "B", 9)
    pdf.set_xy(_MARGIN_L, 14)
    pdf.cell(0, 4, "DWELLSENSE", ln=True)
    _font_sans(pdf, "B", 26)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 12, "Full Data Report", ln=True)
    _font_sans(pdf, "", 10)
    pdf.set_text_color(200, 210, 225)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 5, "Neighborhood Intelligence & Municipal Data Dossier", ln=True)
    pdf.set_y(68)

    # Property block
    _font_sans(pdf, "B", 8)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 4, "SUBJECT PROPERTY", ln=True)
    pdf.ln(2)
    _font_serif(pdf, "B", 14)
    pdf.set_text_color(*_INK)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 6.5, pdf_text(address))
    pdf.ln(6)

    _hrule(pdf)
    pdf.ln(6)
    generated = datetime.now().strftime("%B %d, %Y")
    _font_sans(pdf, "", 8)
    pdf.set_text_color(*_BODY)
    for label, value in [
        ("Report Date", generated),
        ("Report Type", "Full raw-data disclosure"),
        ("Data Sources", "NYC Open Data, Yelp/Google Places, ADS-B ingest"),
    ]:
        pdf.set_x(_MARGIN_L)
        _font_sans(pdf, "B", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(32, 4.5, label, ln=False)
        _font_serif(pdf, "", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 4.5, pdf_text(value), ln=True)

    # Bottom disclaimer
    disc = (
        "This report aggregates publicly available municipal and third-party data for informational purposes only. "
        "It does not constitute legal, financial, or real-estate advice. Verify all figures at source before making decisions."
    )
    disc_h = _text_height(pdf, _CONTENT_W, disc, line_h=4, family="serif", size=8)
    pdf.set_y(260 - disc_h)
    _hrule(pdf)
    pdf.ln(4)
    _font_serif(pdf, "I", 8)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 4, disc)


# ── Section layout (earnings-report style) ────────────────────────────────────

def _section_opener(pdf: DossierPDF, number: int, title: str, *, subtitle: str = "") -> None:
    pdf.set_section(title)
    pdf.ln(4)
    _ensure_space(pdf, 28)
    y0 = pdf.get_y()
    # Watermark numeral
    _font_sans(pdf, "B", 42)
    pdf.set_text_color(*_WATERMARK)
    pdf.set_xy(_MARGIN_L + _CONTENT_W - 38, y0 - 2)
    pdf.cell(38, 16, f"{number:02d}", align="R")
    # Title
    pdf.set_xy(_MARGIN_L, y0)
    _font_sans(pdf, "B", 16)
    pdf.set_text_color(*_NAVY)
    pdf.cell(0, 8, pdf_text(title), ln=True)
    if subtitle:
        pdf.set_x(_MARGIN_L)
        _font_serif(pdf, "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(_CONTENT_W - 40, 4.5, pdf_text(subtitle))
    pdf.ln(2)
    _hrule(pdf, color=_GOLD)
    pdf.set_draw_color(*_RULE)
    pdf.ln(8)


def _subsection(pdf: DossierPDF, number: str, title: str) -> None:
    pdf.ln(5)
    _ensure_space(pdf, 12)
    _font_sans(pdf, "B", 10)
    pdf.set_text_color(*_NAVY)
    pdf.set_x(_MARGIN_L)
    if number and number != "-":
        heading = pdf_text(f"{number}  {title}")
    else:
        heading = pdf_text(title)
    pdf.cell(0, 5, heading, ln=True)
    _hrule(pdf, color=_RULE_LIGHT)
    pdf.ln(4)


def _body_paragraph(pdf: FPDF, text: str) -> None:
    body = pdf_text(text)
    if not body:
        return
    line_h = 5
    h = _text_height(pdf, _CONTENT_W, body, line_h=line_h, family="serif", size=10)
    _ensure_space(pdf, h + 4)
    _font_serif(pdf, "", 10)
    pdf.set_text_color(*_INK)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, line_h, body)
    pdf.ln(4)


def _footnote(pdf: FPDF, text: str) -> None:
    _font_sans(pdf, "", 7)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 3.5, pdf_text(text))
    pdf.ln(2)


def _source_ref(pdf: FPDF, label: str, url: str, *, display: str = "") -> None:
    if not url:
        return
    disp = pdf_text(display or _LINK_DISPLAY.get(label, "View source"))
    text_w = _CONTENT_W - 24
    h = _text_height(pdf, text_w, disp, line_h=3.8, style="U", size=7.5)
    _ensure_space(pdf, h + 2)
    y0 = pdf.get_y()
    _font_sans(pdf, "B", 7)
    pdf.set_text_color(*_MUTED)
    pdf.set_xy(_MARGIN_L, y0)
    pdf.cell(22, 3.8, label.upper(), ln=False)
    _font_sans(pdf, "U", 7.5)
    pdf.set_text_color(*_LINK)
    pdf.set_xy(_MARGIN_L + 24, y0)
    pdf.multi_cell(text_w, 3.8, disp, link=url)
    pdf.set_y(y0 + h + 3)


def _kpi_row(pdf: FPDF, items: list[tuple[str, str]], *, accent: tuple[int, int, int] = _NAVY) -> None:
    """Earnings-style KPI strip: large value, small-caps label, vertical dividers."""
    n = len(items)
    if not n:
        return
    col_w = _CONTENT_W / n
    _ensure_space(pdf, 28)
    y0 = pdf.get_y()
    # Top rule
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.6)
    pdf.line(_MARGIN_L, y0, _MARGIN_L + _CONTENT_W, y0)
    pdf.set_line_width(0.2)
    row_h = 22
    for i, (label, value) in enumerate(items):
        x = _MARGIN_L + i * col_w
        if i > 0:
            pdf.set_draw_color(*_RULE_LIGHT)
            pdf.line(x, y0 + 3, x, y0 + row_h - 3)
        pdf.set_xy(x + 4, y0 + 5)
        _font_sans(pdf, "B", 18)
        pdf.set_text_color(*_INK)
        pdf.cell(col_w - 8, 8, pdf_text(str(value), max_len=14), ln=True)
        pdf.set_x(x + 4)
        _font_sans(pdf, "B", 6.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_w - 8, 3.5, pdf_text(label.upper()), ln=True)
    # Bottom rule
    pdf.set_draw_color(*_RULE)
    pdf.line(_MARGIN_L, y0 + row_h, _MARGIN_L + _CONTENT_W, y0 + row_h)
    pdf.set_y(y0 + row_h + 6)


def _facts_table(pdf: FPDF, rows: list[tuple[str, str]]) -> None:
    """Two-column facts table — label | value, filing style."""
    line_h = 4.5
    row_heights = []
    label_w = 42
    val_w = _CONTENT_W - label_w
    for _, val in rows:
        row_heights.append(max(6, _text_height(pdf, val_w, val, line_h=line_h, family="serif", size=9) + 2))
    total_h = sum(row_heights)
    _ensure_space(pdf, total_h + 4)
    y = pdf.get_y()
    for (label, val), rh in zip(rows, row_heights):
        pdf.set_draw_color(*_RULE_LIGHT)
        pdf.line(_MARGIN_L, y + rh, _MARGIN_L + _CONTENT_W, y + rh)
        pdf.set_xy(_MARGIN_L, y + 2)
        _font_sans(pdf, "B", 7.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(label_w, line_h, pdf_text(label.upper()), ln=False)
        _font_serif(pdf, "", 9)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(val_w, line_h, pdf_text(val))
        y += rh
    pdf.set_y(y + 4)


def _numbered_analysis(pdf: FPDF, title: str, points: list[str]) -> None:
    """Analysis block — serif numbered points, no tinted box."""
    pdf.ln(2)
    _font_sans(pdf, "B", 8)
    pdf.set_text_color(*_NAVY)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 4, pdf_text(title.upper()), ln=True)
    pdf.ln(2)
    for i, point in enumerate(points, start=1):
        pt = pdf_text(point)
        text_w = _CONTENT_W - 10
        h = _text_height(pdf, text_w, pt, line_h=4.8, family="serif", size=9.5)
        _ensure_space(pdf, h + 2)
        y0 = pdf.get_y()
        _font_sans(pdf, "B", 8)
        pdf.set_text_color(*_MUTED)
        pdf.set_xy(_MARGIN_L, y0)
        pdf.cell(8, 4.8, f"{i}.", ln=False)
        _font_serif(pdf, "", 9.5)
        pdf.set_text_color(*_INK)
        pdf.set_xy(_MARGIN_L + 10, y0)
        pdf.multi_cell(text_w, 4.8, pt)
        pdf.ln(2)
    pdf.ln(2)


# ── Institutional data tables ─────────────────────────────────────────────────

def _scaled_col_widths(columns: list[tuple[str, str, float]], *, link_w: float = 0) -> list[float]:
    raw = [w * _CONTENT_W for _, _, w in columns]
    data_w = _CONTENT_W - link_w
    total = sum(raw) or 1.0
    return [w * data_w / total for w in raw]


def _table_row_height(
    pdf: FPDF, col_widths: list[float], values: list[str],
    *, size: int = 8, line_h: float = 3.8, min_h: float = 6.5,
) -> float:
    _font_sans(pdf, "", size)
    max_lines = 1
    for val, w in zip(values, col_widths):
        n = _count_lines(pdf, max(w - 3, 8), val, line_h=line_h)
        max_lines = max(max_lines, n)
    return max(min_h, 3 + max_lines * line_h)


def _institutional_table(
    pdf: FPDF,
    columns: list[tuple[str, str, float]],
    rows: list[dict],
    *,
    link_key: str = "",
) -> None:
    link_w = 16.0 if link_key else 0.0
    col_widths = _scaled_col_widths(columns, link_w=link_w)
    header_h = 8

    _ensure_space(pdf, header_h + 6)
    y0 = pdf.get_y()
    pdf.set_fill_color(*_NAVY)
    pdf.rect(_MARGIN_L, y0, _CONTENT_W, header_h, "F")
    x = _MARGIN_L + 3
    _font_sans(pdf, "B", 7)
    pdf.set_text_color(*_WHITE)
    for (label, _, _), w in zip(columns, col_widths):
        pdf.set_xy(x, y0 + 2.5)
        pdf.cell(w - 3, 4, pdf_text(label.upper()), ln=False)
        x += w
    if link_w:
        pdf.set_xy(x, y0 + 2.5)
        pdf.cell(link_w - 3, 4, "SOURCE", ln=False)
    pdf.set_y(y0 + header_h)

    for i, row in enumerate(rows):
        values = [pdf_text(row.get(key, "")) for _, key, _ in columns]
        rh = _table_row_height(pdf, col_widths, values)
        _ensure_space(pdf, rh + 1)
        y0 = pdf.get_y()
        x = _MARGIN_L + 3
        _font_sans(pdf, "", 8)
        pdf.set_text_color(*_BODY)
        for val, w in zip(values, col_widths):
            pdf.set_xy(x, y0 + 2)
            pdf.multi_cell(max(w - 3, 8), 3.8, val)
            x += w
        if link_key:
            url = str(row.get(link_key, "") or "")
            pdf.set_xy(x, y0 + (rh - 4) / 2)
            if url:
                _font_sans(pdf, "U", 7)
                pdf.set_text_color(*_LINK)
                pdf.cell(link_w - 3, 4, "View", link=url, ln=False)
            else:
                pdf.set_text_color(*_MUTED)
                pdf.cell(link_w - 3, 4, "-", ln=False)
        pdf.set_draw_color(*_RULE_LIGHT)
        pdf.line(_MARGIN_L, y0 + rh, _MARGIN_L + _CONTENT_W, y0 + rh)
        pdf.set_y(y0 + rh)
    pdf.ln(4)


def _record_dataset_key(row: dict, default_key: str) -> str:
    if row.get("permit_status") == "311 complaint":
        return "311"
    return default_key


# ── Data accessors ────────────────────────────────────────────────────────────

def _card_data(card_id: str, ctx: DossierContext):
    crime_cols = [
        ("Date", "occurred_at", 0.14),
        ("Type", "crime_type", 0.20),
        ("Description", "description", 0.36),
        ("Location", "lat", 0.18),
    ]
    r311_cols = [
        ("Date", "created_at", 0.13),
        ("Complaint", "complaint_type", 0.20),
        ("Descriptor", "descriptor", 0.39),
        ("Location", "lat", 0.16),
    ]
    permit_cols = [
        ("Filed", "filing_date", 0.13),
        ("Type", "permit_type", 0.17),
        ("Status", "permit_status", 0.13),
        ("Details", "job_description", 0.41),
    ]
    eviction_cols = [
        ("Filed", "filing_date", 0.18),
        ("Case", "case_type", 0.28),
        ("Location", "lat", 0.38),
    ]

    def _with_lng(rows: list[dict], lat_key: str = "lat") -> list[dict]:
        out = []
        for r in rows:
            copy = dict(r)
            lat, lng = copy.get(lat_key), copy.get("lng")
            if lat is not None and lng is not None:
                copy[lat_key] = f"{lat}, {lng}"
            out.append(copy)
        return out

    dk = _CARD_DATASET_KEY.get(card_id, "")
    if card_id == "high_churn":
        return "Eviction Filings", _with_lng(ctx.evictions), eviction_cols, len(ctx.evictions), PDF_CARD_RECORDS_MAX, dk
    if card_id == "police_calls":
        return "NYPD Dispatch", _with_lng(ctx.crime), crime_cols, len(ctx.crime), PDF_CARD_RECORDS_MAX, dk
    if card_id == "area_safety":
        return "Crime Reports", _with_lng(ctx.crime), crime_cols, len(ctx.crime), PDF_CARD_RECORDS_MAX, dk
    if card_id == "demolitions":
        construction = _filter_311_construction(ctx.reports_311)
        combined = list(ctx.permits) + [
            {**r, "filing_date": r.get("created_at"), "permit_type": r.get("complaint_type"),
             "permit_status": "311 complaint", "job_description": r.get("descriptor")}
            for r in construction
        ]
        return "Permits & Construction", combined, permit_cols, len(combined), PDF_CARD_RECORDS_MAX, dk
    if card_id == "noise_schedule":
        noise = _filter_311_noise(ctx.reports_311)
        return "Noise Complaints", _with_lng(noise), r311_cols, len(noise), PDF_CARD_RECORDS_MAX, dk
    if card_id == "reports_311":
        return "311 Complaints", _with_lng(ctx.reports_311), r311_cols, len(ctx.reports_311), PDF_311_MAX, dk
    return "", [], [], 0, 0, ""


def _collect_source_ids(rows: list[dict]) -> list[str]:
    return [
        str(r.get("source_id") or "").strip()
        for r in rows
        if str(r.get("source_id") or "").strip()
    ]


def _dossier_ids_for_card(card_id: str, ctx: DossierContext) -> dict[str, list[str]]:
    if card_id == "high_churn":
        return {"evictions": _collect_source_ids(ctx.evictions)}
    if card_id in ("police_calls", "area_safety"):
        return {"crime": _collect_source_ids(ctx.crime)}
    if card_id in ("noise_schedule", "reports_311"):
        return {"311": _collect_source_ids(ctx.reports_311)}
    if card_id == "demolitions":
        construction = _filter_311_construction(ctx.reports_311)
        return {
            "permits": _collect_source_ids(ctx.permits),
            "311": _collect_source_ids(construction),
        }
    return {}


def _browse_url_for_card(card_id: str, ctx: DossierContext) -> str:
    urls = source_links.card_dataset_urls(
        card_id,
        _coord(ctx),
        radius_miles=ctx.scan_radius_miles,
        crime_days=CRIME_DAYS_BACK,
        reports_311_days=REPORTS_311_DAYS_BACK,
        permit_days=PERMIT_DAYS_BACK,
        eviction_days=EVICTION_DAYS_BACK,
        formatted_address=ctx.formatted_address,
        dossier_ids=_dossier_ids_for_card(card_id, ctx),
    )
    return urls[0][1] if urls else ""


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_overview(pdf: DossierPDF, ctx: DossierContext, client: dict) -> None:
    pdf.add_page()
    _section_opener(pdf, 1, "Executive Overview",
                    subtitle="Property identification, wellness assessment, and summary findings")

    _subsection(pdf, "1.1", "Subject Property")
    _font_serif(pdf, "B", 12)
    pdf.set_text_color(*_INK)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 5.5, pdf_text(ctx.formatted_address))
    pdf.ln(3)
    _facts_table(pdf, [
        ("Coordinates", f"{ctx.coord_lat:.5f}, {ctx.coord_lng:.5f}"),
        ("Scan Radius", f"{ctx.scan_radius_miles:g} miles"),
        ("Scan Timestamp", ctx.scanned_at[:19].replace("T", " ") + " UTC"),
        ("Crime / 311 Window", f"{CRIME_DAYS_BACK} days"),
        ("Permits Window", f"{PERMIT_DAYS_BACK} days"),
        ("Evictions Window", f"{EVICTION_DAYS_BACK} days"),
    ])

    risk_level = pdf_text(client.get("risk_level", "MODERATE"), default="MODERATE")
    r, g, b = RISK_COLORS.get(risk_level, (120, 120, 120))
    score = client.get("danger_score", "?")
    label = pdf_text(client.get("risk_label", ""))

    _subsection(pdf, "1.2", "Wellness Assessment")
    _kpi_row(pdf, [
        ("Wellness Score", f"{score}"),
        ("Rating", label),
        ("Risk Level", risk_level.title()),
    ], accent=(r, g, b))
    _footnote(pdf, "Scale: 0 (worst) to 100 (best).  " + "  |  ".join(f"{b}: {n}" for b, n in WELLNESS_BANDS))

    _subsection(pdf, "1.3", "Summary of Findings")
    _body_paragraph(pdf, str(client.get("risk_description", "") or "No summary available."))
    if client.get("banner_driver"):
        pdf.ln(2)
        _font_sans(pdf, "B", 7.5)
        pdf.set_text_color(*_MUTED)
        pdf.set_x(_MARGIN_L)
        pdf.cell(0, 4, "PRIMARY DRIVER", ln=True)
        _body_paragraph(pdf, str(client.get("banner_driver")))


def _render_threat_card(pdf: DossierPDF, card: dict, ctx: DossierContext, sec: str, idx: int) -> None:
    card_id = str(card.get("id", ""))
    title = pdf_text(card.get("title", ""))
    sev = pdf_text(card.get("severity_level", "quiet")).upper()
    subtitle = pdf_text(card.get("subtitle", ""))

    pdf.ln(4 if idx > 1 else 0)
    _subsection(pdf, sec, title)
    _font_sans(pdf, "B", 7.5)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.cell(18, 4, "SEVERITY", ln=False)
    _font_sans(pdf, "B", 8)
    cr, cg, cb = _parse_hex_color(str(card.get("border_color", "")))
    pdf.set_text_color(cr, cg, cb)
    pdf.cell(30, 4, sev, ln=True)
    if subtitle:
        _body_paragraph(pdf, subtitle)

    coord = _coord(ctx)
    dossier_ids = _dossier_ids_for_card(card_id, ctx)
    for label, url, ds_key in source_links.card_dataset_urls(
        card_id,
        coord,
        radius_miles=ctx.scan_radius_miles,
        crime_days=CRIME_DAYS_BACK,
        reports_311_days=REPORTS_311_DAYS_BACK,
        permit_days=PERMIT_DAYS_BACK,
        eviction_days=EVICTION_DAYS_BACK,
        formatted_address=ctx.formatted_address,
        dossier_ids=dossier_ids,
    ):
        short = label.replace(" (NYC Open Data)", "")
        has_ids = bool(dossier_ids.get(ds_key))
        display = (
            f"{short} — records from this report"
            if has_ids
            else f"{short} — filtered near this address"
        )
        _source_ref(pdf, "Source", url, display=display)

    if card_id == "tenant_warnings":
        _source_ref(pdf, "HPD", source_links.hpd_violations_url(ctx.formatted_address),
                    display="HPD violations for this address (NYC Open Data)")

    bullets = card.get("bullets") or []
    if bullets:
        _numbered_analysis(pdf, "Analysis", [pdf_text(b) for b in bullets])

    if card_id == "tenant_warnings":
        _footnote(pdf, "HPD violation data not ingested. Verify at the linked NYC Open Data records before signing.")
        return
    if card_id == "oven_effect":
        _footnote(pdf, "Orientation guidance only. Not sourced from NYC Open Data.")
        return
    if card_id == "flight_path":
        _render_flight(pdf, ctx, inline=True)
        return

    ds_title, rows, columns, total, max_rows, dataset_key = _card_data(card_id, ctx)
    if not ds_title:
        return

    cap = " (fetch capped in dense areas)" if card_id == "reports_311" and ctx.reports_capped else ""
    browse_url = _browse_url_for_card(card_id, ctx)

    pdf.ln(2)
    _font_sans(pdf, "B", 8)
    pdf.set_text_color(*_NAVY)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 4, pdf_text(f"SUPPORTING DATA — {ds_title.upper()}  ({total:,} records{cap})"), ln=True)
    pdf.ln(2)
    if browse_url:
        has_rows = total > 0
        _source_ref(
            pdf,
            "Dataset",
            browse_url,
            display=(
                "View report records on NYC Open Data"
                if has_rows
                else "View area-filtered records on NYC Open Data"
            ),
        )

    table_rows = []
    for row in rows[:max_rows]:
        r = dict(row)
        dk = _record_dataset_key(row, dataset_key)
        r["_url"] = source_links.record_url(dk, str(r.get("source_id") or "")) or browse_url
        table_rows.append(r)

    if not table_rows:
        _footnote(pdf, "No matching records in scan radius.")
    else:
        _institutional_table(pdf, columns, table_rows, link_key="_url")
        if len(rows) > max_rows:
            _footnote(pdf, f"Showing {len(table_rows):,} of {total:,} records. Counts reflect full in-radius data.")


def _render_dining(pdf: DossierPDF, candidates: list[dict], *, formatted_address: str, coord: Coordinate) -> None:
    pdf.add_page()
    _section_opener(pdf, 3, "Dining & Nightlife",
                    subtitle="Top-rated restaurants and bars within 2 miles (Yelp / Google Places)")
    if not candidates:
        _footnote(pdf, "Restaurant rankings unavailable from configured APIs.")
        return

    _source_ref(
        pdf,
        "Browse all",
        source_links.dining_area_url(formatted_address, coord),
        display="View nearby restaurants on Google Maps",
    )

    cols = [
        ("#", "_rank", 0.05),
        ("Establishment", "name", 0.26),
        ("Category", "category", 0.14),
        ("Rating", "_rating", 0.08),
        ("Reviews", "_reviews", 0.09),
        ("Distance", "_distance", 0.10),
        ("Provider", "source", 0.10),
    ]
    table_rows = []
    for i, card in enumerate(candidates, start=1):
        rating = card.get("rating")
        reviews = card.get("review_count")
        table_rows.append({
            "_rank": str(i),
            "name": pdf_text(card.get("name", "Unknown")),
            "category": pdf_text(card.get("category", "")),
            "source": pdf_text(card.get("source", "")),
            "_rating": f"{rating}" if rating is not None else "-",
            "_reviews": f"{reviews:,}" if reviews else "-",
            "_distance": f"{card.get('distance_value', '?')} {card.get('distance_unit', 'mi')}",
            "_url": source_links.dining_listing_url(card, formatted_address) or "",
        })
    _institutional_table(pdf, cols, table_rows, link_key="_url")


def _render_flight(pdf: DossierPDF, ctx: DossierContext, *, inline: bool = False) -> None:
    exposure = ctx.flight_exposure or {}
    if not exposure.get("show_flight_feature"):
        if inline:
            _footnote(pdf, "Insufficient ADS-B data for this block.")
        return

    if not inline:
        pdf.add_page()
        _section_opener(pdf, 4, "Flight Noise & Exposure",
                        subtitle="ADS-B-derived aircraft exposure vs. NYC block baselines")

    obs_days = exposure.get("observation_days", 7)
    radius = exposure.get("radius_miles") or ctx.scan_radius_miles
    night = float(exposure.get("night_overflights_per_hour") or 0)
    day = float(exposure.get("day_overflights_per_hour") or 0)

    _subsection(pdf, "4.1" if not inline else "-", "Exposure Metrics" if not inline else "Flight Exposure Metrics")
    stats: list[tuple[str, str]] = [
        ("Overnight Flights/Hr", f"{night:.2f}"),
        ("Daytime Flights/Hr", f"{day:.2f}"),
        ("Observation Window", f"{obs_days} days"),
    ]
    for key, label in [("night_percentile", "Night Percentile"), ("day_percentile", "Day Percentile")]:
        v = exposure.get(key)
        if v is not None:
            stats.append((label, f"{v:.0%}"))
    _kpi_row(pdf, stats)

    notes = []
    if exposure.get("headline"):
        notes.append(str(exposure.get("headline")))
    if exposure.get("detail"):
        notes.append(str(exposure.get("detail")))
    alt = exposure.get("typical_altitude_ft")
    if alt is not None:
        notes.append(f"Typical median altitude: {alt:,} ft")
    notes.append(
        f"Radius {radius:g} mi  |  Elevation {exposure.get('elevation_level', 'n/a')}  |  "
        f"Quality {exposure.get('data_quality', 'n/a')}  |  Samples {exposure.get('sample_count', 0)}"
    )
    if notes:
        _numbered_analysis(pdf, "Exposure Notes", notes)
    _source_ref(
        pdf,
        "Source",
        source_links.opensky_area_url(_coord(ctx), radius_miles=float(radius or ctx.scan_radius_miles)),
        display="View aircraft traffic near this address on OpenSky Network",
    )

    paths = ctx.flight_paths or []
    if paths:
        _subsection(pdf, "4.2" if not inline else "-", f"Aircraft Tracks ({len(paths)})")
        path_cols = [
            ("#", "_n", 0.06), ("Route", "label", 0.22), ("Callsign", "callsign", 0.16),
            ("Closest", "closest", 0.14), ("Altitude", "altitude", 0.14), ("Vertices", "vertices", 0.12),
        ]
        path_rows = [{
            "_n": str(i), "label": pdf_text(p.get("label", "")),
            "callsign": pdf_text(p.get("callsign") or "n/a"),
            "closest": f"{p.get('closest_miles', 'n/a')} mi",
            "altitude": f"{p.get('median_altitude_ft', 'n/a')} ft",
            "vertices": str(len(p.get("path") or [])),
            "_url": source_links.opensky_track_from_label(str(p.get("label", "")))
            or source_links.opensky_area_url(_coord(ctx), radius_miles=float(radius or ctx.scan_radius_miles)),
        } for i, p in enumerate(paths, start=1)]
        _institutional_table(pdf, path_cols, path_rows, link_key="_url")

    adsb = ctx.adsb_samples or []
    if adsb:
        cap = 50 if inline else 80
        _subsection(pdf, "4.3" if not inline else "-", f"ADS-B Observations ({min(len(adsb), cap):,} of {len(adsb):,})")
        adsb_cols = [
            ("#", "_n", 0.05), ("Observed (UTC)", "observed_at", 0.22),
            ("ICAO24", "icao24", 0.12), ("Position", "position", 0.22),
            ("Baro Alt", "baro", 0.11), ("Geo Alt", "geo", 0.11),
        ]
        adsb_rows = [{
            "_n": str(i),
            "observed_at": pdf_text(r.get("observed_at", "")),
            "icao24": pdf_text(r.get("icao24", "")),
            "position": f"{r.get('lat', '')}, {r.get('lng', '')}",
            "baro": f"{r.get('baro_alt_m', 'n/a')} m",
            "geo": f"{r.get('geo_alt_m', 'n/a')} m",
            "_url": source_links.opensky_track_url(str(r.get("icao24") or ""), "")
            or source_links.opensky_area_url(_coord(ctx), radius_miles=float(radius or ctx.scan_radius_miles)),
        } for i, r in enumerate(adsb[:cap], start=1)]
        _institutional_table(pdf, adsb_cols, adsb_rows, link_key="_url")
        if len(adsb) > cap:
            _footnote(pdf, f"{len(adsb) - cap:,} additional ADS-B observations on file for this scan.")


def build_dossier_pdf(ctx: DossierContext, client: dict) -> bytes:
    pdf = DossierPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=_MARGIN_B)
    pdf.set_margins(_MARGIN_L, _MARGIN_T, _MARGIN_R)
    pdf.add_page()

    _render_cover(pdf, ctx.formatted_address)
    _render_overview(pdf, ctx, client)

    cards = client.get("threat_cards") or []
    pdf.add_page()
    _section_opener(pdf, 2, "Threat Analysis",
                    subtitle=f"{len(cards)} risk dimensions with AI interpretation and municipal source records")

    for i, card in enumerate(cards, start=1):
        _render_threat_card(pdf, card, ctx, f"2.{i}", i)

    _render_dining(pdf, ctx.dining_candidates or [], formatted_address=ctx.formatted_address, coord=_coord(ctx))

    if ctx.flight_exposure and ctx.flight_exposure.get("show_flight_feature"):
        if not any(str(c.get("id")) == "flight_path" for c in cards):
            _render_flight(pdf, ctx, inline=False)

    return bytes(pdf.output())
