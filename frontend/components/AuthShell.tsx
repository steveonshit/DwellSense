import Link from "next/link";
import type { ReactNode } from "react";

type AuthShellProps = {
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
};

/** Shared chrome for sign-in / sign-up / password pages. */
export function AuthShell({ subtitle, children, footer }: AuthShellProps) {
  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-950 px-4 pt-[76px]">
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-xl">
        <div className="mb-6 text-center">
          <Link
            href="/"
            className="text-2xl font-semibold text-white tracking-tight inline-block"
          >
            Dwell<span className="text-rose-500">Sense</span>
          </Link>
          <p className="mt-2 text-sm text-slate-400">{subtitle}</p>
        </div>
        {children}
        {footer}
      </div>
    </main>
  );
}

export function AuthAlert({
  tone,
  children,
}: {
  tone: "error" | "success" | "warn";
  children: ReactNode;
}) {
  const styles =
    tone === "error"
      ? "text-rose-300 bg-rose-950/40 border-rose-700/40"
      : tone === "success"
        ? "text-emerald-300 bg-emerald-950/40 border-emerald-700/40"
        : "text-amber-300 bg-amber-950/50 border-amber-700/50";
  return (
    <p className={`mb-4 text-sm border rounded-lg px-3 py-2 break-words ${styles}`}>
      {children}
    </p>
  );
}

export function AuthField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm text-slate-300">
      {label}
      {children}
    </label>
  );
}

export const authInputClassName =
  "mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-rose-500/50";

export const authPrimaryButtonClassName =
  "w-full bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white font-semibold py-2.5 rounded-lg transition-colors";

export const authGoogleButtonClassName =
  "w-full mb-4 bg-white text-slate-900 font-semibold py-2.5 rounded-lg hover:bg-slate-100 disabled:opacity-50 transition-colors";
