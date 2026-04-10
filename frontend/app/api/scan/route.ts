/**
 * Next.js API Route — proxies POST /api/scan to the Python backend.
 * This keeps the BACKEND_URL secret and never exposes it to the browser.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const backendRes = await fetch(`${BACKEND_URL}/scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await backendRes.json();

    if (!backendRes.ok) {
      return NextResponse.json(
        { error: data.detail || "Scan failed. Please try again." },
        { status: backendRes.status }
      );
    }

    return NextResponse.json(data);
  } catch (err) {
    console.error("Scan proxy error:", err);
    return NextResponse.json(
      { error: "Could not reach the analysis server. Make sure the backend is running." },
      { status: 503 }
    );
  }
}
