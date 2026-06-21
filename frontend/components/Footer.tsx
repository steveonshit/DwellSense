import Link from "next/link";

export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="w-full bg-slate-950 border-t border-slate-900 py-4 mt-auto z-20">
      <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div className="flex-1">
          <div className="font-black text-base text-white tracking-tight flex items-center gap-1 mb-1">
            Dwell<span className="text-rose-500">Sense</span>
          </div>
          <p className="text-slate-500 text-[10px] leading-snug max-w-xs">
            Asymmetric data leverage for renters. Uncovering the truth Big Real Estate wants hidden.
          </p>
        </div>
        <div className="flex flex-wrap gap-8 text-[11px] font-medium text-slate-400">
          <div className="flex flex-col gap-1">
            <span className="text-white font-bold uppercase text-[9px] tracking-widest mb-0.5">Product</span>
            <Link href="/" className="hover:text-rose-400 transition-colors">Scanner</Link>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-white font-bold uppercase text-[9px] tracking-widest mb-0.5">Data</span>
            <a
              href="https://opendata.cityofnewyork.us/"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-rose-400 transition-colors"
            >
              NYC Open Data
            </a>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-white font-bold uppercase text-[9px] tracking-widest mb-0.5">Legal</span>
            <span className="text-slate-500">Privacy (soon)</span>
          </div>
        </div>
        <div className="flex flex-col items-start md:items-end gap-2 text-[10px] text-slate-600">
          <p>&copy; {year} DwellSense. Not affiliated with Zillow.</p>
        </div>
      </div>
    </footer>
  );
}
