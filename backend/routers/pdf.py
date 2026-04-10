"""
POST /pdf — generates and returns a PDF dossier for a completed scan result.
Uses fpdf2 (pure Python, no system dependencies required).
"""

from fastapi import APIRouter
from fastapi.responses import Response
from fpdf import FPDF
from datetime import datetime

router = APIRouter()

RISK_COLORS = {
    "EXTREME": (244, 63, 94),
    "HIGH":    (249, 115, 22),
    "MODERATE":(234, 179, 8),
    "LOW":     (16, 185, 129),
}


@router.post("/pdf")
async def generate_pdf(data: dict):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    risk_level = data.get("risk_level", "MODERATE")
    r, g, b = RISK_COLORS.get(risk_level, (148, 163, 184))

    # ── Header ────────────────────────────────────────────────────────────────
    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 40, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_xy(10, 8)
    pdf.cell(0, 12, "DwellSense", ln=False)
    pdf.set_text_color(r, g, b)
    pdf.cell(0, 12, " Forensic Report", ln=True)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(148, 163, 184)
    pdf.set_x(10)
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", ln=True)

    # ── Address ───────────────────────────────────────────────────────────────
    pdf.set_xy(10, 46)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 6, "TARGET PROPERTY", ln=True)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(255, 255, 255)
    pdf.set_x(10)
    pdf.multi_cell(190, 8, data.get("formatted_address", data.get("address", "Unknown")))

    # ── Danger Score ──────────────────────────────────────────────────────────
    pdf.set_xy(10, pdf.get_y() + 4)
    pdf.set_fill_color(30, 41, 59)
    pdf.rect(10, pdf.get_y(), 190, 28, "F")
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(148, 163, 184)
    pdf.set_xy(16, pdf.get_y() + 4)
    pdf.cell(0, 6, "DANGER SCORE", ln=True)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(r, g, b)
    pdf.set_x(16)
    pdf.cell(40, 12, str(data.get("danger_score", "?")))
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 12, f"/ 100 — {data.get('risk_label', risk_level)}", ln=True)

    # ── Summary ───────────────────────────────────────────────────────────────
    pdf.set_xy(10, pdf.get_y() + 8)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(r, g, b)
    pdf.cell(0, 6, "EXECUTIVE SUMMARY", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(200, 210, 220)
    pdf.set_x(10)
    pdf.multi_cell(190, 6, data.get("risk_description", ""))

    # ── 9-Point Threat Analysis ───────────────────────────────────────────────
    pdf.set_xy(10, pdf.get_y() + 8)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, "9-POINT THREAT ANALYSIS", ln=True)

    for card in data.get("threat_cards", []):
        if pdf.get_y() > 260:
            pdf.add_page()

        hex_color = card.get("border_color", "#94a3b8").lstrip("#")
        cr = int(hex_color[0:2], 16)
        cg = int(hex_color[2:4], 16)
        cb = int(hex_color[4:6], 16)

        y = pdf.get_y() + 4
        pdf.set_fill_color(30, 41, 59)
        pdf.rect(10, y, 190, 4, "F")
        pdf.set_fill_color(cr, cg, cb)
        pdf.rect(10, y, 4, 4, "F")  # left border accent

        pdf.set_xy(18, y + 0.5)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(cr, cg, cb)
        pdf.cell(0, 4, f"{card.get('emoji', '')}  {card.get('title', '')}", ln=True)

        pdf.set_xy(18, pdf.get_y())
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(200, 210, 220)
        pdf.cell(0, 5, card.get("subtitle", ""), ln=True)

        for bullet in card.get("bullets", []):
            pdf.set_xy(22, pdf.get_y())
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(180, 195, 210)
            pdf.multi_cell(178, 5, f"• {bullet}")

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, "DwellSense — dwellsense.com  |  Not affiliated with Zillow.  |  © 2026 DwellSense", align="C")

    pdf_bytes = pdf.output()
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=DwellSense-Report.pdf"},
    )
