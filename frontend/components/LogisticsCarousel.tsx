"use client";

import { useEffect, useRef } from "react";
import { LogisticsCard } from "@/lib/types";

interface Props {
  cards: LogisticsCard[];
  onHoverCard: (type: string | null) => void;
}

export default function LogisticsCarousel({ cards, onHoverCard }: Props) {
  const sliderRef = useRef<HTMLDivElement>(null);

  // Drag-to-scroll
  useEffect(() => {
    const el = sliderRef.current;
    if (!el) return;
    let isDown = false;
    let startX = 0;
    let scrollLeft = 0;

    const onDown = (e: MouseEvent) => {
      isDown = true;
      el.style.cursor = "grabbing";
      startX = e.pageX - el.offsetLeft;
      scrollLeft = el.scrollLeft;
    };
    const onUp = () => { isDown = false; el.style.cursor = "grab"; };
    const onMove = (e: MouseEvent) => {
      if (!isDown) return;
      e.preventDefault();
      const x = e.pageX - el.offsetLeft;
      el.scrollLeft = scrollLeft - (x - startX) * 2;
    };

    el.addEventListener("mousedown", onDown);
    el.addEventListener("mouseleave", onUp);
    el.addEventListener("mouseup", onUp);
    el.addEventListener("mousemove", onMove);
    return () => {
      el.removeEventListener("mousedown", onDown);
      el.removeEventListener("mouseleave", onUp);
      el.removeEventListener("mouseup", onUp);
      el.removeEventListener("mousemove", onMove);
    };
  }, []);

  return (
    <div className="fade-in w-full" style={{ animationDelay: "0.1s" }}>
      <div className="flex justify-between items-center mb-1 px-2">
        <h3 className="text-white font-black uppercase tracking-widest text-sm md:text-base flex items-center gap-2">
          📍 Transit &amp; Grocery Proximity
        </h3>
        <div className="flex items-center gap-2 text-rose-400 bg-rose-500/10 px-3 py-1.5 rounded-full border border-rose-500/20">
          <span className="animate-pulse">←</span>
          <span className="text-[10px] font-black tracking-widest uppercase mx-1">Drag / Swipe</span>
          <span className="animate-pulse">→</span>
        </div>
      </div>

      <div ref={sliderRef} className="horizontal-scroll-container">
        {cards.map((card, i) => (
          <div
            key={card.type + i}
            className="logistics-card bg-[#1e293b] border border-slate-700/50 p-2 md:p-2.5 rounded-2xl shadow-lg hover-card hover:bg-slate-700 group transition-colors"
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
                <div className="text-white font-black text-[13px] xl:text-[14px] leading-tight mb-1 whitespace-normal">
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

            <div className="text-right flex flex-col justify-center items-end pl-2 ml-1 border-l border-slate-700/50 shrink-0 h-full">
              <div className="text-white text-base lg:text-lg font-black leading-none tracking-tight mb-1">
                {card.distance_value}
              </div>
              <div className="text-slate-400 text-[8px] md:text-[9px] font-bold uppercase tracking-widest leading-none capitalize">
                {card.distance_unit}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
