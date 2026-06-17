export interface Coordinate {
  lat: number;
  lng: number;
}

export interface LogisticsCard {
  type: string;
  name: string;
  category: string;
  emoji: string;
  distance_value: number;
  distance_unit: "feet" | "miles";
  color: string;
  coordinates: Coordinate;
}

export interface RestaurantBarCard {
  name: string;
  category: string;
  rating?: number | null;
  review_count?: number | null;
  price_level?: string | null;
  distance_value: number;
  distance_unit: "feet" | "miles";
  coordinates: Coordinate;
  source: "yelp" | "google_places";
  url?: string | null;
  ranking_score?: number | null;
}

export interface ThreatCard {
  id: string;
  emoji: string;
  title: string;
  subtitle: string;
  border_color: string;
  text_color: string;
  bullets: string[];
}

export interface Zone {
  lat: number;
  lng: number;
  radius_meters: number;
  color: string;
  label: string;
}

export interface SwarmPin {
  lat: number;
  lng: number;
  type:
    | "police"
    | "rat"
    | "permit"
    | "truck"
    | "bus"
    | "noise"
    | "fire"
    | "water"
    | "trash"
    | "graffiti"
    | "construction"
    | "report";
  label: string;
}

export interface FlightPath {
  start: Coordinate;
  end: Coordinate;
  label: string;
  /** Optional polyline points (ADS‑B tracks). */
  path?: Coordinate[] | null;
  closest_miles?: number | null;
  median_altitude_ft?: number | null;
  sample_count?: number | null;
  callsign?: string | null;
  airline?: string | null;
  flight_number?: string | null;
  last_seen_utc?: string | null;
}

export interface FlightExposure {
  night_overflights_per_hour: number;
  day_overflights_per_hour: number;
  typical_altitude_ft?: number | null;
  trend?: "stable" | "variable" | null;
  data_quality: "good" | "sparse" | "unavailable";
}

export interface MapData {
  target: Coordinate;
  zones: Zone[];
  swarm: SwarmPin[];
  flight_paths?: FlightPath[];
  /** Back-compat: some responses include a single path */
  flight_path?: FlightPath | null;
}

export interface ScanResult {
  address: string;
  formatted_address: string;
  coordinates: Coordinate;
  danger_score: number;
  risk_level: "LOW" | "MODERATE" | "HIGH" | "EXTREME";
  risk_label: string;
  risk_description: string;
  logistics: LogisticsCard[];
  dining?: RestaurantBarCard[];
  threat_cards: ThreatCard[];
  map_data: MapData;
  flight_exposure?: FlightExposure | null;
  /** From backend: whether a real GEMINI_API_KEY was loaded (check Network → /api/scan response). */
  gemini_configured?: boolean;
}
