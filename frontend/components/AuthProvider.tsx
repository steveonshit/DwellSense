"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { AuthChangeEvent, Session } from "@supabase/supabase-js";
import type { AuthUser } from "@/lib/auth/types";
import { createClient } from "@/lib/supabase/client";

type AuthContextValue = {
  user: AuthUser | null;
  isLoaded: boolean;
  /** False when NEXT_PUBLIC_SUPABASE_* keys are missing/placeholder. */
  isConfigured: boolean;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function toAuthUser(id: string, email: string | null | undefined): AuthUser {
  return { id, email: email ?? null };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [isConfigured, setIsConfigured] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const supabase = createClient();

    if (!supabase) {
      setIsConfigured(false);
      setUser(null);
      setIsLoaded(true);
      return;
    }

    setIsConfigured(true);

    void supabase.auth.getUser().then(({ data }: { data: { user: { id: string; email?: string | null } | null } }) => {
      if (cancelled) return;
      const u = data.user;
      setUser(u ? toAuthUser(u.id, u.email) : null);
      setIsLoaded(true);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event: AuthChangeEvent, session: Session | null) => {
      const u = session?.user;
      setUser(u ? toAuthUser(u.id, u.email) : null);
      setIsLoaded(true);
    });

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  const signOut = useCallback(async () => {
    const supabase = createClient();
    if (supabase) await supabase.auth.signOut();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, isLoaded, isConfigured, signOut }),
    [user, isLoaded, isConfigured, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Thin identity hook — prefer this over calling Supabase auth directly in product UI. */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
