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

export function flightElevationBadge(exposure: FlightExposure): string {
  return exposure.elevation_level === "high"
    ? "Well above NYC average"
    : "Above NYC average";
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
