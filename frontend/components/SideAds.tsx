export interface ScanSummaryProps {
  score: number;
  riskLabel: string;
  address: string;
  swarmShown: number;
  swarmTotal: number | null;
  scanRadiusMi: number;
  flightPathCount: number;
  showFlightFeature?: boolean;
  flightElevation?: string | null;
  threatCardCount?: number;
}

interface Props {
  summary?: ScanSummaryProps | null;
}

function truncateAddress(address: string, max = 42): string {
  const trimmed = address.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

export default function SideAds({ summary }: Props) {
  return (
    <div className="hidden fixed inset-0 pointer-events-none z-30 top-[76px]">
      <div className="w-full h-full flex justify-between items-start max-w-[1640px] mx-auto pt-[40px] px-2 xl:px-4">

        {summary ? (
          <div
            className="w-[160px] min-h-[420px] bg-slate-800/95 border border-slate-700 rounded-2xl pointer-events-auto hidden min-[1550px]:flex flex-col shadow-2xl fade-in relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 bg-slate-900 text-slate-500 text-[8px] uppercase tracking-widest px-3 py-1 rounded-bl-lg border-b border-l border-slate-700 z-10">
              Scan summary
            </div>
            <div className="p-4 pt-8 flex flex-col gap-3 h-full">
              <div>
                <div className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-1">
                  Wellness score
                </div>
                <div className="text-3xl font-black text-yellow-400 leading-none">
                  {summary.score}
                  <span className="text-sm text-slate-600">/100</span>
                </div>
                <div className="text-[10px] font-bold text-slate-300 mt-1 uppercase leading-snug">
                  {summary.riskLabel.replace(/^[^\s]+\s*/, "")}
                </div>
              </div>
              <div className="border-t border-slate-700/80 pt-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-1">
                  Address
                </div>
                <p className="text-[10px] font-semibold text-slate-300 leading-snug">
                  {truncateAddress(summary.address)}
                </p>
              </div>
              <div className="border-t border-slate-700/80 pt-3 space-y-2 text-[10px] font-bold text-slate-400">
                <p>
                  Map:{" "}
                  <span className="text-white">
                    {summary.swarmTotal != null && summary.swarmTotal > summary.swarmShown
                      ? `${summary.swarmShown} of ${summary.swarmTotal}`
                      : summary.swarmShown}{" "}
                    pins
                  </span>
                  <span className="text-slate-500"> ({summary.scanRadiusMi}-mi)</span>
                </p>
                <p>
                  {summary.showFlightFeature ? (
                    <>
                      Flight noise:{" "}
                      <span className="text-cyan-300 capitalize">
                        {summary.flightElevation ?? "elevated"}
                      </span>
                      {summary.flightPathCount > 0 ? (
                        <span className="text-slate-500">
                          {" "}
                          · {summary.flightPathCount} track(s) on map
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <span className="text-slate-500">
                      Flight noise: typical for NYC (not shown)
                    </span>
                  )}
                </p>
              </div>
              <p className="mt-auto text-[9px] text-slate-500 leading-snug border-t border-slate-700/80 pt-3">
                Swipe the threat carousel below — {summary.threatCardCount ?? 9} cards total.
              </p>
            </div>
          </div>
        ) : (
          <div className="w-[160px] h-[850px] bg-slate-800 border border-slate-700 rounded-2xl pointer-events-none hidden min-[1550px]:flex flex-col shadow-2xl fade-in relative overflow-hidden opacity-90">
            <div className="absolute top-0 right-0 bg-slate-900 text-slate-500 text-[8px] uppercase tracking-widest px-3 py-1 rounded-bl-lg border-b border-l border-slate-700 z-10">
              Sponsored
            </div>
            <div className="h-[220px] bg-slate-700 flex flex-col items-center justify-center p-4 relative overflow-hidden shrink-0">
              <div className="text-slate-300 font-black text-lg text-center leading-tight uppercase tracking-tight">
                Ad space
              </div>
            </div>
            <div className="flex-1 bg-slate-900 p-4 flex flex-col items-center justify-center text-center">
              <div className="text-slate-500 text-xs font-bold leading-relaxed">
                Placeholder panel. No offers or stats are shown until a real sponsor is linked.
              </div>
            </div>
          </div>
        )}

        <div
          className="w-[160px] h-[850px] bg-slate-800 border border-slate-700 rounded-2xl pointer-events-none hidden min-[1550px]:flex flex-col shadow-2xl fade-in relative overflow-hidden opacity-90"
          style={{ animationDelay: "0.2s" }}
        >
          <div className="absolute top-0 right-0 bg-slate-900 text-slate-500 text-[8px] uppercase tracking-widest px-3 py-1 rounded-bl-lg border-b border-l border-slate-700 z-10">
            Sponsored
          </div>
          <div className="h-[220px] bg-slate-700 flex flex-col items-center justify-center p-4 relative overflow-hidden shrink-0">
            <div className="text-slate-300 font-black text-lg text-center leading-tight uppercase tracking-tight">
              Ad space
            </div>
          </div>
          <div className="flex-1 bg-slate-900 p-4 flex flex-col items-center justify-center text-center">
            <div className="text-slate-500 text-xs font-bold leading-relaxed">
              Placeholder panel. No offers or stats are shown until a real sponsor is linked.
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
