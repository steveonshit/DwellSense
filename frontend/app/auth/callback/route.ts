import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * OAuth / magic-link callback (PKCE).
 * Uses @supabase/ssr cookies so the code_verifier set at sign-in is available here.
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const nextRaw = searchParams.get("next") ?? "/";
  const next = nextRaw.startsWith("/") ? nextRaw : "/";

  if (code) {
    try {
      const supabase = await createClient();
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error) {
        return NextResponse.redirect(`${origin}${next}`);
      }
      const msg = encodeURIComponent(error.message);
      return NextResponse.redirect(`${origin}/sign-in?error=${msg}`);
    } catch (err) {
      const msg = encodeURIComponent(
        err instanceof Error ? err.message : "Auth callback failed",
      );
      return NextResponse.redirect(`${origin}/sign-in?error=${msg}`);
    }
  }

  const desc =
    searchParams.get("error_description") ||
    searchParams.get("error") ||
    "Sign-in was cancelled or incomplete.";
  return NextResponse.redirect(
    `${origin}/sign-in?error=${encodeURIComponent(desc)}`,
  );
}
