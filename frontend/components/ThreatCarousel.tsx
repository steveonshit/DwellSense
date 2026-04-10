"use client";

import { useEffect, useRef } from "react";
import { ThreatCard } from "@/lib/types";

interface Props {
  cards: ThreatCard[];
}

export default function ThreatCarousel({ cards }: Props) {
  const sliderRef = useRef<HTMLDivElement>(null);

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
      el.scrollLeft = scrollLeft - (e.pageX - el.offsetLeft - startX) * 2;
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
    <div className="fade-in w-full" style={{ animationDelay: "0.3s" }}>
      <div className="flex justify-between items-center mb-2 px-2">
        <h3 className="text-white font-black uppercase tracking-widest text-sm md:text-base flex items-center gap-2">
          📑 9-Point Threat Analysis
        </h3>
        <div className="flex items-center gap-2 text-rose-400 bg-rose-500/10 px-3 py-1.5 rounded-full border border-rose-500/20">
          <span className="animate-pulse">←</span>
          <span className="text-[10px] font-black tracking-widest uppercase mx-1">Drag / Swipe</span>
          <span className="animate-pulse">→</span>
        </div>
      </div>

      <div ref={sliderRef} className="horizontal-scroll-container" id="stats-slider">
        {cards.map((card, i) => (
          <div
            key={card.id}
            className="stat-card bg-slate-800 p-6 md:p-8 rounded-3xl shadow-xl hover:bg-slate-700 transition-colors"
            style={{
              borderLeft: `10px solid ${card.border_color}`,
              paddingRight: i === cards.length - 1 ? "2rem" : undefined,
            }}
          >
            <h3 className="text-xl md:text-2xl font-black text-white mb-2 uppercase">
              {card.emoji} {card.title}
            </h3>
            <p className="font-bold mb-4 text-sm md:text-base" style={{ color: card.text_color }}>
              {card.subtitle}
            </p>
            <ul className="list-disc pl-5 text-slate-300 text-xs md:text-sm space-y-2">
              {card.bullets.map((b, j) => (
                <li key={j} dangerouslySetInnerHTML={{ __html: b }} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
