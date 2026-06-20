"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import HeroSection from "@/components/HeroSection";
import LoadingAd from "@/components/LoadingAd";
import ResultsDashboard from "@/components/ResultsDashboard";
import { ScanResult } from "@/lib/types";

type View = "hero" | "loading" | "results";

export default function Home() {
  const [view, setView] = useState<View>("hero");
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isApiReady, setIsApiReady] = useState(false);
  const [bulletsRefreshing, setBulletsRefreshing] = useState(false);

  // Holds the scan result while the ad is still playing
  const pendingResult = useRef<ScanResult | null>(null);

  const handleScan = async (address: string) => {
    setError(null);
    setIsApiReady(false);
    pendingResult.current = null;
    setView("loading");

    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, defer_gemini: true }),
        signal: AbortSignal.timeout(295_000),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Scan failed. Please try again.");
      }

      pendingResult.current = data as ScanResult;
      setIsApiReady(true); // Signal LoadingAd that data is ready
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      setError(msg);
      setView("hero");
    }
  };

  const handleAdComplete = () => {
    if (pendingResult.current) {
      setResult(pendingResult.current);
      setView("results");
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const handleReset = () => {
    setResult(null);
    setIsApiReady(false);
    setBulletsRefreshing(false);
    pendingResult.current = null;
    setView("hero");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  useEffect(() => {
    if (view !== "results" || !result) return;
    if (result.gemini_status !== "pending" || !result.bullets_token) return;

    const token = result.bullets_token;
    let cancelled = false;
    setBulletsRefreshing(true);

    (async () => {
      try {
        const res = await fetch("/api/scan/bullets", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bullets_token: token }),
          signal: AbortSignal.timeout(295_000),
        });
        const data = await res.json();
        if (cancelled || !res.ok) return;

        setResult((prev) =>
          prev
            ? {
                ...prev,
                threat_cards: data.threat_cards ?? prev.threat_cards,
                gemini_configured: data.gemini_configured ?? prev.gemini_configured,
                gemini_status: data.gemini_status ?? prev.gemini_status,
                gemini_latency_ms: data.gemini_latency_ms ?? prev.gemini_latency_ms,
                bullets_token: null,
              }
            : prev
        );
      } catch {
        // Keep fact-locked template bullets if the deferred Gemini call fails.
      } finally {
        if (!cancelled) setBulletsRefreshing(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  // Intentionally keyed on token/status only — avoid re-fetch when threat_cards update.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, result?.bullets_token, result?.gemini_status]);

  return (
    <div className="min-h-screen flex flex-col pt-[76px] relative">
      <Navbar />

      <main className="flex-1 w-full max-w-[1300px] mx-auto flex flex-col items-center px-4 md:px-8 mt-4 relative z-10">

        {view === "hero" && (
          <>
            {error && (
              <div className="w-full max-w-4xl mb-4 bg-rose-950 border border-rose-500/50 rounded-2xl px-6 py-4 text-rose-300 font-bold text-sm fade-in">
                ⚠️ {error}
              </div>
            )}
            <HeroSection onScan={handleScan} isLoading={false} />
          </>
        )}

        {view === "loading" && (
          <LoadingAd onComplete={handleAdComplete} isApiReady={isApiReady} />
        )}

        {view === "results" && result && (
          <ResultsDashboard
            result={result}
            onReset={handleReset}
            bulletsRefreshing={bulletsRefreshing}
          />
        )}

      </main>

      <footer className="w-full bg-slate-950 border-t border-slate-900 py-4 mt-auto z-20">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
          <div className="flex-1">
            <div className="font-black text-base text-white tracking-tight flex items-center gap-1 mb-1">
              Dwell<span className="text-rose-500">Sense</span>
            </div>
            <p className="text-slate-500 text-[10px] leading-snug max-w-xs">
              Asymmetric data leverage for renters. Uncovering the truth Big Real Estate wants hidden.
            </p>
          </div>
          <div className="flex flex-wrap gap-8 text-[11px] font-medium text-slate-400">
            <div className="flex flex-col gap-1">
              <span className="text-white font-bold uppercase text-[9px] tracking-widest mb-0.5">Product</span>
              <Link href="/" className="hover:text-rose-400 transition-colors">Scanner</Link>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-white font-bold uppercase text-[9px] tracking-widest mb-0.5">Data</span>
              <a
                href="https://opendata.cityofnewyork.us/"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-rose-400 transition-colors"
              >
                NYC Open Data
              </a>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-white font-bold uppercase text-[9px] tracking-widest mb-0.5">Legal</span>
              <span className="text-slate-500">Privacy (soon)</span>
            </div>
          </div>
          <div className="flex flex-col items-start md:items-end gap-2 text-[10px] text-slate-600">
            <p>&copy; {new Date().getFullYear()} DwellSense. Not affiliated with Zillow.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
