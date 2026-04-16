/**
 * Next.js API Route — proxies POST /api/scan to the Python backend.
 * This keeps the BACKEND_URL secret and never exposes it to the browser.
 *
 * Long timeout: Gemini + Places + DB can exceed 60s; undici defaults can abort early without an explicit signal.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/** Vercel / Node serverless max for this route (seconds). */
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const backendRes = await fetch(`${BACKEND_URL}/scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(110_000),
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
    const name = err instanceof Error ? err.name : "";
    if (name === "AbortError" || name === "TimeoutError") {
      console.error("Scan proxy error: upstream timeout", err);
      return NextResponse.json(
        { error: "Scan took too long. Try again in a moment." },
        { status: 504 }
      );
    }
    console.error("Scan proxy error:", err);
    return NextResponse.json(
      { error: "Could not reach the analysis server. Make sure the backend is running." },
      { status: 503 }
    );
  }
}
