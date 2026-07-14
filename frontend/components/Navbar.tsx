"use client";

import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";

export default function Navbar() {
  const { user, isLoaded, signOut } = useAuth();

  return (
    <nav className="w-full bg-slate-900/95 backdrop-blur-md border-b border-slate-800 py-3 px-4 md:px-8 flex items-center justify-between fixed top-0 z-50 shadow-lg h-[76px]">
      <div className="hidden md:flex gap-6 text-sm font-medium text-slate-500 w-1/3">
        <span title="Not available yet">Dashboard</span>
        <span title="Not available yet">Saved Reports</span>
        <span title="Not available yet">About</span>
      </div>

      <Link
        href="/"
        className="absolute left-1/2 transform -translate-x-1/2 font-semibold text-3xl md:text-4xl text-white tracking-tight flex items-center gap-0.5 drop-shadow-md leading-none"
      >
        Dwell<span className="text-rose-500">Sense</span>
      </Link>

      <div className="flex items-center justify-end gap-2 sm:gap-3 w-full md:w-1/3">
        <span className="hidden sm:inline text-[11px] font-medium text-slate-400 bg-slate-800 border border-slate-700 rounded-full px-3 py-1">
          Public beta
        </span>

        {!isLoaded && <span className="w-9 h-9 rounded-full bg-slate-800 animate-pulse" aria-hidden />}

        {isLoaded && !user && (
          <>
            <Link
              href="/sign-in"
              className="text-sm font-medium text-slate-300 hover:text-white transition-colors whitespace-nowrap"
            >
              Sign in
            </Link>
            <Link
              href="/sign-up"
              className="text-sm font-semibold text-white bg-rose-600 hover:bg-rose-500 border border-rose-500 rounded-lg px-3 py-1.5 transition-colors whitespace-nowrap"
            >
              Sign up
            </Link>
          </>
        )}

        {isLoaded && user && (
          <div className="flex items-center gap-2 sm:gap-3">
            <span
              className="hidden sm:inline max-w-[140px] truncate text-xs text-slate-400"
              title={user.email ?? user.id}
            >
              {user.email ?? "Signed in"}
            </span>
            <button
              type="button"
              onClick={() => void signOut()}
              className="text-sm font-medium text-slate-300 hover:text-white border border-slate-600 hover:border-slate-500 rounded-lg px-3 py-1.5 transition-colors whitespace-nowrap"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
