/**
 * PDF generation route — proxies to the Python backend's /pdf endpoint.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const backendRes = await fetch(`${BACKEND_URL}/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!backendRes.ok) {
      return NextResponse.json({ error: "PDF generation failed" }, { status: 500 });
    }

    const pdfBuffer = await backendRes.arrayBuffer();
    return new NextResponse(pdfBuffer, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": "attachment; filename=DwellSense-Report.pdf",
      },
    });
  } catch {
    return NextResponse.json({ error: "PDF service unavailable" }, { status: 503 });
  }
}
