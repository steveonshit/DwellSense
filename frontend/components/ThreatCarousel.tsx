"use client";

import { useRef } from "react";
import { ThreatCard } from "@/lib/types";
import { useCarouselScroll } from "@/lib/carouselScroll";
import { threatSeverityLabel, threatSeverityStyle } from "@/lib/threatCardSeverity";
import CarouselDots from "./CarouselDots";

interface Props {
  cards: ThreatCard[];
  bulletsRefreshing?: boolean;
}

export function scrollToThreatCard(cardId: string) {
  const el = document.getElementById(`threat-card-${cardId}`);
  el?.scrollIntoView({ behavior: "smooth", inline: "center", block: "center" });
}

export default function ThreatCarousel({ cards, bulletsRefreshing = false }: Props) {
  const sliderRef = useRef<HTMLDivElement>(null);
  const { activeIndex, scrollToIndex } = useCarouselScroll(sliderRef, ".stat-card");

  return (
    <div className="fade-in w-full" style={{ animationDelay: "0.3s" }}>
      <div className="flex justify-between items-center mb-2 px-0 gap-3">
        <h3 className="text-white font-black uppercase tracking-widest text-sm md:text-base flex items-center gap-2 shrink-0">
          📑 {cards.length}-Point Threat Analysis
        </h3>
        <div className="flex items-center gap-3 min-w-0">
          {bulletsRefreshing ? (
            <span className="text-[10px] font-black tracking-widest uppercase text-amber-300 whitespace-nowrap">
              Refining AI summaries…
            </span>
          ) : (
            <CarouselDots
              count={cards.length}
              activeIndex={activeIndex}
              onSelect={scrollToIndex}
              getAriaLabel={(i) => `Go to ${cards[i]?.title ?? "card"} (${i + 1} of ${cards.length})`}
            />
          )}
        </div>
      </div>

      <div ref={sliderRef} className="horizontal-scroll-container hide-scrollbar" id="stats-slider">
        {cards.map((card, i) => {
          const severity = threatSeverityStyle(card);
          return (
            <div
              key={card.id}
              id={`threat-card-${card.id}`}
              className={`stat-card p-6 md:p-8 rounded-3xl shadow-xl transition-colors ${severity.card}`}
              style={{
                borderLeft: `${severity.borderWidth}px solid ${card.border_color}`,
                paddingRight: i === cards.length - 1 ? "2rem" : undefined,
              }}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <h3 className="text-xl md:text-2xl font-black text-white uppercase min-w-0">
                  {card.emoji} {card.title}
                </h3>
                <span
                  className={`shrink-0 text-[10px] md:text-xs font-black uppercase tracking-wider px-2 py-1 rounded-full border ${severity.badge}`}
                >
                  {threatSeverityLabel(card)}
                </span>
              </div>
              <p className="font-bold mb-4 text-sm md:text-base" style={{ color: card.text_color }}>
                {card.subtitle}
              </p>
              <ul className="list-disc pl-5 text-slate-300 text-xs md:text-sm space-y-2">
                {card.bullets.map((b, j) => (
                  <li key={j} dangerouslySetInnerHTML={{ __html: b }} />
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
