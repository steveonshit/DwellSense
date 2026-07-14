"use client";

import { useState, useRef, useEffect } from "react";
import HeroSection from "@/components/HeroSection";
import LoadingAd from "@/components/LoadingAd";
import ResultsDashboard from "@/components/ResultsDashboard";
import { ScanResult } from "@/lib/types";

type View = "hero" | "loading" | "results";

export default function HomeClient() {
  const [view, setView] = useState<View>("hero");
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isApiReady, setIsApiReady] = useState(false);
  const [bulletsRefreshing, setBulletsRefreshing] = useState(false);

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
      setIsApiReady(true);
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, result?.bullets_token, result?.gemini_status]);

  return (
    <>
      <main className="flex-1 w-full max-w-[1300px] mx-auto flex flex-col items-center px-1.5 sm:px-2 md:px-3 min-[1550px]:px-5 mt-4 relative z-10">
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
    </>
  );
}
