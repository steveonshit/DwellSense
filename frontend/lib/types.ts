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
}

export interface MapData {
  target: Coordinate;
  zones: Zone[];
  swarm: SwarmPin[];
  flight_path: FlightPath | null;
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
  threat_cards: ThreatCard[];
  map_data: MapData;
  /** From backend: whether a real GEMINI_API_KEY was loaded (check Network → /api/scan response). */
  gemini_configured?: boolean;
}
