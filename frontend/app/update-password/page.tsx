"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  AuthAlert,
  AuthField,
  AuthShell,
  authInputClassName,
  authPrimaryButtonClassName,
} from "@/components/AuthShell";
import { useAuth } from "@/components/AuthProvider";
import { createClient } from "@/lib/supabase/client";

export default function UpdatePasswordPage() {
  const { user, isLoaded, isConfigured } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isConfigured) {
      setError("Auth is not configured.");
      return;
    }
    if (!user) {
      setError("Open the password reset link from your email, then set a new password here.");
    }
  }, [isLoaded, isConfigured, user]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured.");
      return;
    }
    setLoading(true);
    const { error: updateError } = await supabase.auth.updateUser({ password });
    setLoading(false);
    if (updateError) {
      setError(updateError.message);
      return;
    }
    setMessage("Password updated. You can continue to the home page.");
  };

  return (
    <AuthShell
      subtitle="Choose a new password."
      footer={
        <p className="mt-4 text-center text-sm text-slate-400">
          <Link href="/" className="text-rose-400 hover:text-rose-300 font-medium">
            Back to home
          </Link>
        </p>
      }
    >
      {error && <AuthAlert tone="error">{error}</AuthAlert>}
      {message && <AuthAlert tone="success">{message}</AuthAlert>}

      <form onSubmit={onSubmit} className="space-y-3">
        <AuthField label="New password">
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={!user || !!message}
            className={authInputClassName}
          />
        </AuthField>
        <AuthField label="Confirm password">
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            disabled={!user || !!message}
            className={authInputClassName}
          />
        </AuthField>
        <button
          type="submit"
          disabled={loading || !user || !!message}
          className={authPrimaryButtonClassName}
        >
          {loading ? "Saving…" : "Update password"}
        </button>
      </form>
    </AuthShell>
  );
}
