import type { ThreatCard } from "./types";

export type ThreatSeverity = "quiet" | "watch" | "elevated";

const SEVERITY_LABEL: Record<ThreatSeverity, string> = {
  quiet: "All clear",
  watch: "Worth watching",
  elevated: "Elevated",
};

const SEVERITY_STYLE: Record<
  ThreatSeverity,
  { card: string; badge: string; borderWidth: number }
> = {
  quiet: {
    card: "bg-emerald-950/20 hover:bg-emerald-950/30 ring-1 ring-emerald-500/20",
    badge: "bg-emerald-950/70 text-emerald-200 border-emerald-500/35",
    borderWidth: 4,
  },
  watch: {
    card: "bg-amber-950/25 hover:bg-amber-950/35 ring-1 ring-amber-500/20",
    badge: "bg-amber-950/70 text-amber-200 border-amber-500/40",
    borderWidth: 4,
  },
  elevated: {
    card: "bg-rose-950/30 hover:bg-rose-950/40 ring-1 ring-rose-500/25",
    badge: "bg-rose-950/70 text-rose-200 border-rose-500/45",
    borderWidth: 5,
  },
};

export function threatSeverity(card: ThreatCard): ThreatSeverity {
  const level = card.severity_level;
  if (level === "watch" || level === "elevated") return level;
  return "quiet";
}

export function threatSeverityLabel(card: ThreatCard): string {
  return SEVERITY_LABEL[threatSeverity(card)];
}

export function threatSeverityStyle(card: ThreatCard) {
  return SEVERITY_STYLE[threatSeverity(card)];
}
