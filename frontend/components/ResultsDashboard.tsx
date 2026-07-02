"use client";

import { useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { ScanResult } from "@/lib/types";
import { buildProximityCards } from "@/lib/proximityCards";
import DangerBanner from "./DangerBanner";
import LogisticsCarousel from "./LogisticsCarousel";
import ThreatCarousel, { scrollToThreatCard } from "./ThreatCarousel";
import SideAds, { ScanSummaryProps } from "./SideAds";

// Mapbox must only render on the client side (no SSR)
const MapComponent = dynamic(() => import("./MapComponent"), { ssr: false });

interface Props {
  result: ScanResult;
  onReset: () => void;
  bulletsRefreshing?: boolean;
}

export default function ResultsDashboard({ result, onReset, bulletsRefreshing = false }: Props) {
  const [activeRoute, setActiveRoute] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);

  const proximityCards = useMemo(
    () => buildProximityCards(result.logistics, result.dining),
    [result.logistics, result.dining],
  );

  const sideSummary = useMemo((): ScanSummaryProps => {
    const showFlight = Boolean(result.flight_exposure?.show_flight_feature);
    const paths = showFlight
      ? result.map_data.flight_paths?.length
        ? result.map_data.flight_paths
        : result.map_data.flight_path
          ? [result.map_data.flight_path]
          : []
      : [];
    return {
      score: result.danger_score,
      riskLabel: result.risk_label,
      address: result.formatted_address,
      swarmShown: result.map_data.swarm.length,
      swarmTotal: result.map_data.swarm_location_total ?? null,
      scanRadiusMi: result.map_data.scan_radius_miles ?? 2,
      flightPathCount: paths.length,
      showFlightFeature: showFlight,
      flightElevation: result.flight_exposure?.elevation_level ?? null,
      threatCardCount: result.threat_cards.length,
    };
  }, [result]);

  const handleScrollToCard = useCallback((cardId: string) => {
    scrollToThreatCard(cardId);
  }, []);

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
      <SideAds summary={sideSummary} />
      <div className="w-full space-y-3 pb-5 overflow-hidden relative z-20">

        <DangerBanner result={result} onScrollToCard={handleScrollToCard} />

        <LogisticsCarousel
          cards={proximityCards}
          onHoverCard={handleHoverCard}
        />

        <MapComponent
          key={`${result.coordinates.lat},${result.coordinates.lng}`}
          mapData={result.map_data}
          logistics={proximityCards}
          activeRoute={activeRoute}
          flightExposure={result.flight_exposure}
        />

        <div className="pt-5">
          <ThreatCarousel cards={result.threat_cards} bulletsRefreshing={bulletsRefreshing} />
        </div>

        {/* Action buttons */}
        <div className="pt-5">
          <div className="flex flex-col sm:flex-row gap-4 fade-in" style={{ animationDelay: "0.4s" }}>
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

      </div>
    </>
  );
}
