"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { createClient } from "@/lib/supabase/client";

export default function SignInPage() {
  const router = useRouter();
  const { isConfigured } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("error");
    if (fromQuery) {
      setError(fromQuery);
      return;
    }
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const fromHash = hash.get("error_description") || hash.get("error");
    if (fromHash) {
      setError(decodeURIComponent(fromHash.replace(/\+/g, " ")));
    }
  }, []);

  const onEmailSignIn = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured. Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.");
      return;
    }
    setLoading(true);
    const { error: signError } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (signError) {
      setError(signError.message);
      return;
    }
    router.push("/");
    router.refresh();
  };

  const onGoogle = async () => {
    setError(null);
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured. Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.");
      return;
    }
    setLoading(true);
    const origin = window.location.origin;
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${origin}/auth/callback` },
    });
    if (oauthError) {
      setLoading(false);
      setError(oauthError.message);
    }
    // On success, browser redirects to Google — leave loading on.
  };

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-950 px-4 pt-[76px]">
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-xl">
        <div className="mb-6 text-center">
          <p className="text-2xl font-semibold text-white tracking-tight">
            Dwell<span className="text-rose-500">Sense</span>
          </p>
          <p className="mt-2 text-sm text-slate-400">Sign in to save reports (coming next).</p>
        </div>

        {!isConfigured && (
          <p className="mb-4 text-sm text-amber-300 bg-amber-950/50 border border-amber-700/50 rounded-lg px-3 py-2">
            Supabase Auth keys are not set yet. Add the anon key to{" "}
            <code className="text-amber-200">frontend/.env.local</code>.
          </p>
        )}

        {error && (
          <p className="mb-4 text-sm text-rose-300 bg-rose-950/40 border border-rose-700/40 rounded-lg px-3 py-2 break-words">
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={() => void onGoogle()}
          disabled={loading || !isConfigured}
          className="w-full mb-4 bg-white text-slate-900 font-semibold py-2.5 rounded-lg hover:bg-slate-100 disabled:opacity-50 transition-colors"
        >
          {loading ? "Redirecting…" : "Continue with Google"}
        </button>

        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-slate-700" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-slate-900 px-2 text-slate-500">or email</span>
          </div>
        </div>

        <form onSubmit={onEmailSignIn} className="space-y-3">
          <label className="block text-sm text-slate-300">
            Email
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-rose-500/50"
            />
          </label>
          <label className="block text-sm text-slate-300">
            Password
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-rose-500/50"
            />
          </label>
          <button
            type="submit"
            disabled={loading || !isConfigured}
            className="w-full bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white font-semibold py-2.5 rounded-lg transition-colors"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-slate-400">
          No account?{" "}
          <Link href="/sign-up" className="text-rose-400 hover:text-rose-300 font-medium">
            Sign up
          </Link>
        </p>
      </div>
    </main>
  );
}
