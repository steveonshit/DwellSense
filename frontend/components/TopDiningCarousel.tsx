"use client";

import { useEffect, useRef } from "react";
import { RestaurantBarCard } from "@/lib/types";

interface Props {
  cards: RestaurantBarCard[];
}

function sourceLabel(source: RestaurantBarCard["source"]): string {
  return source === "yelp" ? "Yelp" : "Google Places";
}

export default function TopDiningCarousel({ cards }: Props) {
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
    const onUp = () => {
      isDown = false;
      el.style.cursor = "grab";
    };
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
    <div className="fade-in w-full" style={{ animationDelay: "0.15s" }}>
      <div className="flex justify-between items-center mb-1 px-2">
        <h3 className="text-white font-black uppercase tracking-widest text-sm md:text-base flex items-center gap-2">
          🍸 Top Restaurants &amp; Bars Within 2 Miles
        </h3>
        <span className="text-[10px] font-black tracking-widest uppercase text-slate-400 bg-slate-900/80 px-3 py-1.5 rounded-full border border-slate-700">
          Ranked by rating + review volume
        </span>
      </div>

      {!cards.length ? (
        <div className="bg-[#1e293b] border border-slate-700/50 p-4 rounded-2xl text-slate-400 text-sm font-bold">
          Restaurant/bar rankings unavailable from the configured place APIs.
        </div>
      ) : (
        <div ref={sliderRef} className="horizontal-scroll-container">
          {cards.map((card, i) => (
            <a
              key={`${card.source}-${card.name}-${i}`}
              href={card.url || "#"}
              target={card.url ? "_blank" : undefined}
              rel={card.url ? "noreferrer" : undefined}
              className="logistics-card bg-[#1e293b] border border-slate-700/50 p-2.5 rounded-2xl shadow-lg hover-card hover:bg-slate-700 group transition-colors"
              style={{ borderColor: "transparent" }}
            >
              <div className="flex items-center gap-2 overflow-hidden flex-1 pr-1">
                <div className="w-10 h-10 md:w-11 md:h-11 bg-[#0f172a] rounded-xl border border-amber-400/40 flex items-center justify-center text-xl shrink-0 shadow-inner">
                  {i + 1}
                </div>
                <div className="flex flex-col justify-center min-w-0">
                  <div className="text-amber-300 text-[8px] md:text-[9px] font-black uppercase tracking-widest leading-none mb-1">
                    {card.category}
                  </div>
                  <div className="text-white font-black text-[13px] xl:text-[14px] leading-tight mb-1 whitespace-normal">
                    {card.name}
                  </div>
                  <div className="text-[8px] font-bold uppercase tracking-widest leading-none text-slate-400 truncate">
                    {sourceLabel(card.source)}
                    {card.price_level ? ` · ${card.price_level}` : ""}
                  </div>
                </div>
              </div>

              <div className="text-right flex flex-col justify-center items-end pl-2 ml-1 border-l border-slate-700/50 shrink-0 h-full">
                <div className="text-white text-base lg:text-lg font-black leading-none tracking-tight mb-1">
                  {card.rating != null ? card.rating.toFixed(1) : "N/A"}
                </div>
                <div className="text-amber-300 text-[8px] md:text-[9px] font-bold uppercase tracking-widest leading-none">
                  {card.review_count != null ? `${card.review_count} reviews` : "No reviews"}
                </div>
                <div className="text-slate-400 text-[8px] md:text-[9px] font-bold uppercase tracking-widest leading-none mt-1 capitalize">
                  {card.distance_value} {card.distance_unit}
                </div>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
