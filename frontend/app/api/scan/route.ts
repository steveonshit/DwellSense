/**
 * Next.js API Route — proxies POST /api/scan to the Python backend.
 * This keeps the BACKEND_URL secret and never exposes it to the browser.
 *
 * Long timeout: Gemini + Places + DB can exceed 60s; undici defaults can abort early without an explicit signal.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/** Vercel / Node serverless max for this route (seconds). */
export const maxDuration = 300;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const backendRes = await fetch(`${BACKEND_URL}/scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(290_000),
    });

    const raw = await backendRes.text();
    let data: unknown = null;
    try {
      data = raw ? JSON.parse(raw) : null;
    } catch {
      data = null;
    }

    if (!backendRes.ok) {
      const detail =
        typeof data === "object" &&
        data !== null &&
        "detail" in data &&
        (data as { detail: unknown }).detail != null
          ? String((data as { detail: unknown }).detail)
          : raw.trim().slice(0, 240) || "Scan failed. Please try again.";
      return NextResponse.json({ error: detail }, { status: backendRes.status });
    }

    if (data === null) {
      return NextResponse.json(
        { error: "Analysis server returned invalid JSON." },
        { status: 502 }
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
