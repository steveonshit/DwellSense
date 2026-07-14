/**
 * PDF generation route — proxies to the Python backend's /pdf endpoint.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/** Vercel / Node serverless max for this route (seconds). */
export const maxDuration = 300;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const backendRes = await fetch(`${BACKEND_URL}/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(290_000),
    });

    if (!backendRes.ok) {
      let detail = "PDF generation failed";
      try {
        const err = await backendRes.json();
        detail = err.detail || err.error || detail;
      } catch {
        /* ignore */
      }
      return NextResponse.json({ error: detail }, { status: backendRes.status });
    }

    const pdfBuffer = await backendRes.arrayBuffer();
    return new NextResponse(pdfBuffer, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": "attachment; filename=DwellSense-Full-Data-Report.pdf",
      },
    });
  } catch {
    return NextResponse.json({ error: "PDF service unavailable" }, { status: 503 });
  }
}
