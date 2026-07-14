"""
POST /pdf — generates and returns a full raw-data PDF dossier for a completed scan.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from models.schemas import PdfDossierRequest
from services import dossier_context
from services.pdf_dossier import build_dossier_pdf

router = APIRouter()


@router.post("/pdf")
async def generate_pdf(request: PdfDossierRequest):
    token = request.dossier_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="dossier_token is required.")

    ctx = dossier_context.get_dossier(token)
    if not ctx:
        raise HTTPException(
            status_code=404,
            detail="Dossier token expired or invalid. Re-run the scan to download a fresh report.",
        )

    client = {
        "danger_score": request.danger_score,
        "risk_level": request.risk_level,
        "risk_label": request.risk_label,
        "risk_description": request.risk_description,
        "banner_driver": request.banner_driver,
        "threat_cards": [c.model_dump() for c in request.threat_cards],
    }

    try:
        pdf_bytes = build_dossier_pdf(ctx, client)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=DwellSense-Full-Data-Report.pdf"},
    )
