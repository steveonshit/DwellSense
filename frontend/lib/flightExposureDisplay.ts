import type { FlightExposure, FlightPath } from "./types";

/** Plain-language frequency bucket for planes per hour. */
export function flightFrequencyLabel(ratePerHour: number): string {
  if (ratePerHour < 0.2) return "Rare";
  if (ratePerHour < 0.7) return "Occasional";
  if (ratePerHour < 2) return "Fairly common";
  return "Frequent";
}

/** One-sentence takeaway for renters. */
export function flightNoiseSummary(exposure: FlightExposure): string {
  const nightP = exposure.night_percentile ?? 0;
  const dayP = exposure.day_percentile ?? 0;

  if (nightP >= 0.78 || (nightP >= 0.6 && exposure.night_overflights_per_hour >= 0.8)) {
    return "Planes fly over often at night — more than in most NYC neighborhoods.";
  }
  if (nightP >= 0.6) {
    return "More overnight flight noise than in most NYC neighborhoods.";
  }
  if (dayP >= 0.68) {
    return "Busier daytime air traffic than in most of NYC.";
  }
  if (exposure.elevation_level === "high") {
    return "This block sees noticeably more planes than typical NYC areas.";
  }
  return "Flight noise here is higher than usual for NYC.";
}

export type FlightComparisonTier = "below" | "average" | "above";

/** NYC-relative tier from combined (or peak) flight exposure percentile. */
export function flightComparisonTier(exposure: FlightExposure): FlightComparisonTier {
  const p =
    exposure.combined_percentile ??
    Math.max(exposure.night_percentile ?? 0, exposure.day_percentile ?? 0);
  if (p >= 0.54) return "above";
  if (p >= 0.42) return "average";
  return "below";
}

export function flightElevationBadge(exposure: FlightExposure): string {
  const tier = flightComparisonTier(exposure);
  if (tier === "above") {
    return exposure.elevation_level === "high"
      ? "Well above NYC average"
      : "Above NYC average";
  }
  if (tier === "average") return "Around NYC average";
  return "Below NYC average";
}

export function flightElevationBadgeClasses(exposure: FlightExposure): string {
  const tier = flightComparisonTier(exposure);
  if (tier === "above") {
    return exposure.elevation_level === "high"
      ? "bg-rose-950/50 border-rose-600 text-rose-200"
      : "bg-amber-950/50 border-amber-500 text-amber-200";
  }
  if (tier === "average") {
    return "bg-slate-800/80 border-slate-500 text-slate-300";
  }
  return "bg-emerald-950/40 border-emerald-600 text-emerald-200";
}

/** Short note about altitude when flights are low enough to hear. */
export function flightAltitudeNote(exposure: FlightExposure): string | null {
  const alt = exposure.typical_altitude_ft;
  if (alt == null || alt > 3200) return null;
  return `Many planes pass around ${alt.toLocaleString()} ft — low enough to hear from the street.`;
}

/** Human-readable recent track line (no ADS-B jargon). */
export function formatFlightPathPlain(path: FlightPath): string {
  const parts: string[] = [];
  if (path.closest_miles != null) {
    parts.push(`about ${path.closest_miles.toFixed(1)} mi from this address`);
  }
  const alt = path.median_altitude_ft;
  if (alt != null) {
    parts.push(`around ${alt.toLocaleString()} ft`);
  }
  if (!parts.length) return "A recent plane route is drawn on the map in cyan.";
  return `Recent plane route ${parts.join(", ")}.`;
}

export function formatObservationWindow(exposure: FlightExposure): string {
  const days = exposure.observation_days ?? 7;
  const mi = exposure.radius_miles ?? 2;
  const miLabel = Number.isInteger(mi) ? `${mi}` : mi.toFixed(1);
  return `Based on ${days} days of flight tracking within ~${miLabel} mi.`;
}
