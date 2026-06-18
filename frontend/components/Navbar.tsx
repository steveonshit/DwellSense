"use client";

export default function Navbar() {
  return (
    <nav className="w-full bg-slate-900/95 backdrop-blur-md border-b border-slate-800 py-3 px-4 md:px-8 flex items-center justify-between fixed top-0 z-50 shadow-lg h-[76px]">
      <div className="hidden md:flex gap-6 text-sm font-bold text-slate-600 w-1/3">
        <span title="Not available yet">Dashboard</span>
        <span title="Not available yet">Saved Reports</span>
        <span title="Not available yet">About</span>
      </div>

      <div
        className="absolute left-1/2 transform -translate-x-1/2 font-black text-4xl md:text-5xl text-white tracking-tighter cursor-pointer flex items-center gap-1 drop-shadow-md"
        onClick={() => window.location.reload()}
      >
        Dwell<span className="text-rose-500">Sense</span>
      </div>

      <div className="flex items-center justify-end w-full md:w-1/3">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 bg-slate-800 border border-slate-700 rounded-full px-3 py-1">
          Public beta
        </span>
      </div>
    </nav>
  );
}
