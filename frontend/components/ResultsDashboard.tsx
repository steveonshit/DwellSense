"use client";

import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import { ScanResult } from "@/lib/types";
import DangerBanner from "./DangerBanner";
import LogisticsCarousel from "./LogisticsCarousel";
import ThreatCarousel from "./ThreatCarousel";
import SideAds from "./SideAds";

// Mapbox must only render on the client side (no SSR)
const MapComponent = dynamic(() => import("./MapComponent"), { ssr: false });

interface Props {
  result: ScanResult;
  onReset: () => void;
}

export default function ResultsDashboard({ result, onReset }: Props) {
  const [activeRoute, setActiveRoute] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);

  const handleHoverCard = useCallback((type: string | null) => {
    setActiveRoute(type);
  }, []);

  const handleDownloadPdf = async () => {
    setPdfLoading(true);
    try {
      const res = await fetch("/api/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(result),
      });
      if (!res.ok) throw new Error("PDF generation failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `DwellSense-Report-${result.formatted_address.replace(/[^a-z0-9]/gi, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("PDF download failed. Please try again.");
    } finally {
      setPdfLoading(false);
    }
  };

  return (
    <>
      <SideAds />
      <div className="w-full space-y-5 pb-12 overflow-hidden relative z-20">

        <DangerBanner result={result} />

        <LogisticsCarousel
          cards={result.logistics}
          onHoverCard={handleHoverCard}
        />

        <MapComponent
          mapData={result.map_data}
          logistics={result.logistics}
          activeRoute={activeRoute}
        />

        <ThreatCarousel cards={result.threat_cards} />

        {/* Action buttons */}
        <div className="flex flex-col sm:flex-row gap-4 mt-4 fade-in" style={{ animationDelay: "0.4s" }}>
          <button
            onClick={handleDownloadPdf}
            disabled={pdfLoading}
            className="flex-1 bg-slate-100 text-slate-900 hover:bg-white disabled:opacity-60 font-black text-lg py-5 rounded-xl transition-colors shadow-lg border-2 border-black uppercase tracking-widest flex items-center justify-center gap-2"
          >
            {pdfLoading ? "⏳ Generating..." : "⬇️ Download PDF Dossier"}
          </button>
          <button
            onClick={onReset}
            className="flex-1 bg-slate-800 hover:bg-slate-700 border-2 border-slate-600 text-white font-black text-lg py-5 rounded-xl transition-colors shadow-lg uppercase tracking-widest flex items-center justify-center gap-2"
          >
            🔄 Scan New Address
          </button>
        </div>

      </div>
    </>
  );
}
