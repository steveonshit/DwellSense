import { ScanResult } from "@/lib/types";

export type BannerDriverKind = "area_safety" | "311" | "permits" | "evictions" | "noise";

const BANNER_DRIVER_MAP: Record<
  BannerDriverKind,
  { cardId: string; label: string }
> = {
  area_safety: { cardId: "area_safety", label: "See area safety breakdown" },
  noise: { cardId: "noise_schedule", label: "See noise breakdown" },
  "311": { cardId: "reports_311", label: "See 311 breakdown" },
  permits: { cardId: "demolitions", label: "See construction breakdown" },
  evictions: { cardId: "high_churn", label: "See tenant churn breakdown" },
};

function isBannerDriverKind(value: string): value is BannerDriverKind {
  return value in BANNER_DRIVER_MAP;
}

/** Infer driver from banner copy when older scans lack `banner_driver`. */
function inferBannerDriver(description: string): BannerDriverKind | null {
  const d = description.toLowerCase();
  if (d.includes("noise complaint")) return "noise";
  if (d.includes("area safety")) return "area_safety";
  if (d.includes("eviction") || d.includes("tenant churn")) return "evictions";
  if (d.includes("construction") || d.includes("permit") || d.includes("demolition")) {
    return "permits";
  }
  if (d.includes("311")) return "311";
  return null;
}

export function resolveBannerBreakdown(
  result: ScanResult,
): { cardId: string; label: string } | null {
  const raw = result.banner_driver ?? inferBannerDriver(result.risk_description);
  if (!raw || !isBannerDriverKind(raw)) return null;

  const mapping = BANNER_DRIVER_MAP[raw];
  const cardExists = result.threat_cards.some((c) => c.id === mapping.cardId);
  if (!cardExists) return null;

  return mapping;
}
