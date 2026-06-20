/**
 * Proxies POST /scan/bullets — completes deferred Gemini threat-card bullets.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export const maxDuration = 300;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    const backendRes = await fetch(`${BACKEND_URL}/scan/bullets`, {
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
          : raw.trim().slice(0, 240) || "Could not refresh AI summaries.";
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
      return NextResponse.json(
        { error: "AI summary refresh took too long." },
        { status: 504 }
      );
    }
    return NextResponse.json(
      { error: "Could not reach the analysis server." },
      { status: 503 }
    );
  }
}
