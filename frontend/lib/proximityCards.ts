import { LogisticsCard, RestaurantBarCard } from "./types";

const DINING_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"] as const;
const DINING_COLOR = "#fbbf24";

export function isDiningCard(type: string): boolean {
  return type.startsWith("dining-");
}

/** Merge transit/grocery logistics with top 4 dining cards for one proximity bar + map routes. */
export function buildProximityCards(
  logistics: LogisticsCard[],
  dining?: RestaurantBarCard[] | null,
): LogisticsCard[] {
  const diningCards = (dining ?? []).slice(0, 4).map((card, index) => ({
    type: `dining-${index}`,
    name: card.name,
    category: card.category || "Restaurant / Bar",
    emoji: DINING_EMOJIS[index] ?? "🍽️",
    distance_value: card.distance_value,
    distance_unit: card.distance_unit,
    color: DINING_COLOR,
    coordinates: card.coordinates,
    rating: card.rating ?? null,
    review_count: card.review_count ?? null,
    url: card.url ?? null,
  }));
  return [...logistics, ...diningCards];
}
