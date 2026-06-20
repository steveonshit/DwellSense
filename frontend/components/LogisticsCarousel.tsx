"use client";

import { useRef } from "react";
import { LogisticsCard } from "@/lib/types";
import { isDiningCard } from "@/lib/proximityCards";
import { useCarouselScroll } from "@/lib/carouselScroll";
import CarouselDots from "./CarouselDots";

interface Props {
  cards: LogisticsCard[];
  onHoverCard: (type: string | null) => void;
}

export default function LogisticsCarousel({ cards, onHoverCard }: Props) {
  const sliderRef = useRef<HTMLDivElement>(null);
  const { activeIndex, scrollToIndex } = useCarouselScroll(sliderRef, ".logistics-card");

  return (
    <div className="fade-in w-full" style={{ animationDelay: "0.1s" }}>
      <div className="flex justify-between items-center mb-1 px-2 gap-3">
        <h3 className="text-white font-black uppercase tracking-widest text-sm md:text-base flex items-center gap-2 shrink-0">
          📍 Transit, Grocery &amp; Dining Proximity
        </h3>
        <div className="flex items-center min-w-0">
          <CarouselDots
            count={cards.length}
            activeIndex={activeIndex}
            onSelect={scrollToIndex}
            getAriaLabel={(i) => `Go to ${cards[i]?.name ?? "card"} (${i + 1} of ${cards.length})`}
          />
        </div>
      </div>

      <div ref={sliderRef} className="horizontal-scroll-container hide-scrollbar">
        {cards.map((card, i) => (
          <div
            key={card.type + i}
            className="logistics-card bg-[#1e293b] border border-slate-700/50 p-2.5 md:p-3 rounded-2xl shadow-lg hover-card hover:bg-slate-700 group transition-colors"
            style={{ borderColor: "transparent" }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor = card.color;
              onHoverCard(card.type);
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor = "transparent";
              onHoverCard(null);
            }}
          >
            <div className="flex items-center gap-2 overflow-hidden flex-1 pr-1">
              <div
                className="w-10 h-10 md:w-11 md:h-11 bg-[#0f172a] rounded-xl border border-slate-700/60 flex items-center justify-center text-xl shrink-0 shadow-inner transition-colors"
                style={{ "--hover-border": card.color } as React.CSSProperties}
              >
                {card.emoji}
              </div>
              <div className="flex flex-col justify-center min-w-0">
                <div className="text-slate-400 text-[8px] md:text-[9px] font-black uppercase tracking-widest leading-none mb-1">
                  {card.category}
                </div>
                <div
                  className="text-white font-black text-[13px] xl:text-[14px] leading-snug mb-1 line-clamp-2"
                  title={card.name}
                >
                  {card.name}
                </div>
                <div
                  className="text-[8px] font-bold uppercase tracking-widest leading-none transition-colors truncate"
                  style={{ color: card.color }}
                >
                  Route Map ↗
                </div>
              </div>
            </div>

            <div className="text-right flex flex-col justify-center items-end pl-2 ml-1 border-l border-slate-700/50 shrink-0 min-w-[4.75rem] h-full">
              {isDiningCard(card.type) && card.rating != null ? (
                <>
                  <div className="text-white text-base lg:text-lg font-black leading-none tracking-tight mb-1 whitespace-nowrap">
                    {card.rating.toFixed(1)}
                  </div>
                  <div className="text-amber-300 text-[8px] md:text-[9px] font-bold uppercase tracking-widest leading-none mb-1 whitespace-nowrap">
                    {card.review_count != null ? `${card.review_count} reviews` : "Rated"}
                  </div>
                  <div className="text-slate-400 text-[8px] md:text-[9px] font-bold uppercase tracking-widest leading-none capitalize whitespace-nowrap">
                    {card.distance_value} {card.distance_unit}
                  </div>
                </>
              ) : (
                <>
                  <div className="text-white text-base lg:text-lg font-black leading-none tracking-tight mb-1 whitespace-nowrap">
                    {card.distance_value}
                  </div>
                  <div className="text-slate-400 text-[8px] md:text-[9px] font-bold uppercase tracking-widest leading-none capitalize whitespace-nowrap">
                    {card.distance_unit}
                  </div>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
