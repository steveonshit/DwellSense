"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import {
  AuthAlert,
  AuthField,
  AuthShell,
  authInputClassName,
  authPrimaryButtonClassName,
} from "@/components/AuthShell";
import { useAuth } from "@/components/AuthProvider";
import { isValidEmail } from "@/lib/auth/email";
import { createClient } from "@/lib/supabase/client";

export default function ForgotPasswordPage() {
  const { isConfigured } = useAuth();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured.");
      return;
    }
    const trimmedEmail = email.trim();
    if (!isValidEmail(trimmedEmail)) {
      setError("Enter a valid email address.");
      return;
    }
    setLoading(true);
    const origin = window.location.origin;
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(trimmedEmail, {
      redirectTo: `${origin}/auth/callback?next=${encodeURIComponent("/update-password")}`,
    });
    setLoading(false);
    if (resetError) {
      setError(resetError.message);
      return;
    }
    // Always show the same copy (do not reveal whether the email exists).
    setMessage(
      "If an account exists for that email, we sent a password reset link. Check inbox and spam.",
    );
  };

  return (
    <AuthShell
      subtitle="Reset your password."
      footer={
        <p className="mt-4 text-center text-sm text-slate-400">
          <Link href="/sign-in" className="text-rose-400 hover:text-rose-300 font-medium">
            Back to sign in
          </Link>
        </p>
      }
    >
      {!isConfigured && (
        <AuthAlert tone="warn">Auth is not configured on this deployment.</AuthAlert>
      )}
      {error && <AuthAlert tone="error">{error}</AuthAlert>}
      {message && <AuthAlert tone="success">{message}</AuthAlert>}

      <form onSubmit={onSubmit} noValidate className="space-y-3">
        <AuthField label="Email">
          <input
            type="text"
            inputMode="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={authInputClassName}
          />
        </AuthField>
        <button
          type="submit"
          disabled={loading || !isConfigured}
          className={authPrimaryButtonClassName}
        >
          {loading ? "Sending…" : "Send reset link"}
        </button>
      </form>
    </AuthShell>
  );
}
