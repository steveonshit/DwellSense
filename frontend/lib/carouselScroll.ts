import { RefObject, useCallback, useEffect, useState } from "react";

export function useCarouselScroll(
  sliderRef: RefObject<HTMLDivElement | null>,
  cardSelector: string,
) {
  const [activeIndex, setActiveIndex] = useState(0);

  const updateActiveIndex = useCallback(() => {
    const el = sliderRef.current;
    if (!el) return;
    const cardEls = el.querySelectorAll<HTMLElement>(cardSelector);
    if (!cardEls.length) return;

    const containerLeft = el.getBoundingClientRect().left;
    let best = 0;
    let bestDist = Infinity;
    cardEls.forEach((card, i) => {
      const dist = Math.abs(card.getBoundingClientRect().left - containerLeft);
      if (dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    });
    setActiveIndex(best);
  }, [sliderRef, cardSelector]);

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
      el.scrollLeft = scrollLeft - (e.pageX - el.offsetLeft - startX) * 2;
    };

    el.addEventListener("mousedown", onDown);
    el.addEventListener("mouseleave", onUp);
    el.addEventListener("mouseup", onUp);
    el.addEventListener("mousemove", onMove);
    el.addEventListener("scroll", updateActiveIndex, { passive: true });
    updateActiveIndex();

    return () => {
      el.removeEventListener("mousedown", onDown);
      el.removeEventListener("mouseleave", onUp);
      el.removeEventListener("mouseup", onUp);
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("scroll", updateActiveIndex);
    };
  }, [sliderRef, updateActiveIndex]);

  const scrollToIndex = useCallback(
    (index: number) => {
      const el = sliderRef.current;
      if (!el) return;
      const card = el.querySelectorAll<HTMLElement>(cardSelector)[index];
      card?.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" });
    },
    [sliderRef, cardSelector],
  );

  return { activeIndex, scrollToIndex };
}
