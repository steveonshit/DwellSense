"use client";

export default function Navbar() {
  return (
    <nav className="w-full bg-slate-900/95 backdrop-blur-md border-b border-slate-800 py-3 px-4 md:px-8 flex items-center justify-between fixed top-0 z-50 shadow-lg h-[76px]">
      {/* Left links */}
      <div className="hidden md:flex gap-6 text-sm font-bold text-slate-400 w-1/3">
        <a href="#" className="hover:text-white transition-colors">Dashboard</a>
        <a href="#" className="hover:text-white transition-colors">Saved Reports</a>
        <a href="#" className="hover:text-white transition-colors">About Us</a>
      </div>

      {/* Centered logo */}
      <div
        className="absolute left-1/2 transform -translate-x-1/2 font-black text-4xl md:text-5xl text-white tracking-tighter cursor-pointer flex items-center gap-1 drop-shadow-md"
        onClick={() => window.location.reload()}
      >
        Dwell<span className="text-rose-500">Sense</span>
      </div>

      {/* Right — search + user */}
      <div className="flex items-center justify-end gap-5 w-full md:w-1/3 text-sm font-bold text-slate-300">
        <div className="hidden lg:block relative max-w-[200px] w-full">
          <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">🔍</span>
          <input
            type="text"
            placeholder="Quick search..."
            className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-4 py-1.5 text-xs text-white focus:outline-none focus:border-rose-500 transition-colors"
          />
        </div>

        <div className="flex items-center gap-3 pl-2 cursor-pointer group">
          <div className="hidden sm:block text-right">
            <div className="text-sm font-bold text-white group-hover:text-rose-400 transition-colors">
              Alex Morgan
            </div>
            <div className="text-[9px] text-slate-400 uppercase tracking-widest bg-slate-800 rounded px-1 inline-block border border-slate-700">
              Free Tier
            </div>
          </div>
          <div className="w-10 h-10 rounded-full bg-slate-700 border-2 border-slate-600 group-hover:border-rose-500 transition-colors overflow-hidden flex items-center justify-center text-slate-400">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
            </svg>
          </div>
        </div>
      </div>
    </nav>
  );
}
