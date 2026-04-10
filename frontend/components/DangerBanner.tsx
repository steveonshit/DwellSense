import { ScanResult } from "@/lib/types";

const RISK_COLORS: Record<string, { bg: string; border: string; text: string; score: string }> = {
  EXTREME: {
    bg: "from-rose-950 to-slate-900",
    border: "border-rose-500/50",
    text: "text-rose-300",
    score: "text-rose-500",
  },
  HIGH: {
    bg: "from-orange-950 to-slate-900",
    border: "border-orange-500/50",
    text: "text-orange-300",
    score: "text-orange-500",
  },
  MODERATE: {
    bg: "from-yellow-950 to-slate-900",
    border: "border-yellow-500/50",
    text: "text-yellow-300",
    score: "text-yellow-500",
  },
  LOW: {
    bg: "from-emerald-950 to-slate-900",
    border: "border-emerald-500/50",
    text: "text-emerald-300",
    score: "text-emerald-500",
  },
};

interface Props {
  result: ScanResult;
}

export default function DangerBanner({ result }: Props) {
  const colors = RISK_COLORS[result.risk_level] ?? RISK_COLORS.MODERATE;

  return (
    <div
      className={`bg-gradient-to-r ${colors.bg} border ${colors.border} p-4 md:px-6 md:py-4 rounded-2xl flex flex-col md:flex-row justify-between items-center shadow-xl fade-in mt-2`}
    >
      <div>
        <h2 className="text-xl md:text-3xl font-black text-white flex items-center gap-3 uppercase tracking-tight">
          {result.risk_label}
        </h2>
        <p className={`${colors.text} text-sm mt-1 font-bold`}>{result.risk_description}</p>
      </div>

      <div className="text-center mt-4 md:mt-0 bg-black/40 px-4 py-2 rounded-xl border border-white/10 backdrop-blur-sm shrink-0 flex items-center gap-3">
        <div className="text-left hidden sm:block">
          <div className={`text-[10px] ${colors.text} uppercase tracking-widest font-bold leading-tight`}>
            Danger<br />Score
          </div>
        </div>
        <div className={`text-4xl md:text-5xl font-black ${colors.score} drop-shadow-[0_0_15px_rgba(225,29,72,0.5)]`}>
          {result.danger_score}
          <span className="text-xl text-slate-700">/100</span>
        </div>
      </div>
    </div>
  );
}
