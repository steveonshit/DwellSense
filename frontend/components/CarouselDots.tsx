interface Props {
  count: number;
  activeIndex: number;
  onSelect: (index: number) => void;
  getAriaLabel?: (index: number) => string;
}

export default function CarouselDots({
  count,
  activeIndex,
  onSelect,
  getAriaLabel,
}: Props) {
  if (count <= 1) return null;

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      {Array.from({ length: count }, (_, i) => (
        <button
          key={i}
          type="button"
          aria-label={getAriaLabel?.(i) ?? `Go to item ${i + 1} of ${count}`}
          onClick={() => onSelect(i)}
          className={[
            "h-2 rounded-full transition-all",
            i === activeIndex ? "w-5 bg-rose-500" : "w-2 bg-slate-600 hover:bg-slate-500",
          ].join(" ")}
        />
      ))}
    </div>
  );
}
