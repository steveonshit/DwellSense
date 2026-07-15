import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * OAuth / magic-link / recovery callback (PKCE).
 *
 * Session cookies must be written onto the redirect Response itself.
 * Next.js does not reliably copy cookies().set(...) onto a separately
 * constructed NextResponse.redirect(), which shows up in production as:
 * Google succeeds → land on `/` still signed out.
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const nextRaw = searchParams.get("next") ?? "/";
  const next = nextRaw.startsWith("/") ? nextRaw : "/";

  const forwardedHost = request.headers.get("x-forwarded-host");
  const isLocal = process.env.NODE_ENV === "development";
  const redirectBase =
    !isLocal && forwardedHost ? `https://${forwardedHost}` : origin;

  if (code) {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!url || !anonKey) {
      return NextResponse.redirect(
        `${redirectBase}/sign-in?error=${encodeURIComponent(
          "Auth is not configured on this deployment.",
        )}`,
      );
    }

    const successRedirect = NextResponse.redirect(`${redirectBase}${next}`);
    const cookieStore = await cookies();

    const supabase = createServerClient(url, anonKey, {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            try {
              cookieStore.set(name, value, options);
            } catch {
              // Request-scope store can throw outside a mutable context.
            }
            successRedirect.cookies.set(name, value, options);
          });
        },
      },
    });

    const { error } = await supabase.auth.exchangeCodeForSession(code);
    // Flush deferred auth subscriber work (cookie writes) before returning.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));

    if (!error) {
      return successRedirect;
    }

    const msg = encodeURIComponent(error.message);
    return NextResponse.redirect(`${redirectBase}/sign-in?error=${msg}`);
  }

  const desc =
    searchParams.get("error_description") ||
    searchParams.get("error") ||
    "Sign-in was cancelled or incomplete.";
  return NextResponse.redirect(
    `${redirectBase}/sign-in?error=${encodeURIComponent(desc)}`,
  );
}
