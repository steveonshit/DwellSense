export default function SideAds() {
  return (
    <div className="hidden fixed inset-0 pointer-events-none z-30 top-[76px]">
      <div className="w-full h-full flex justify-between items-start max-w-[1640px] mx-auto pt-[40px] px-2 xl:px-4">

        {/* Left ad */}
        <div className="w-[160px] h-[850px] bg-slate-800 border border-slate-700 rounded-2xl pointer-events-auto hidden min-[1550px]:flex flex-col shadow-2xl fade-in group hover:border-blue-500 transition-colors relative overflow-hidden">
          <div className="absolute top-0 right-0 bg-slate-900 text-slate-500 text-[8px] uppercase tracking-widest px-3 py-1 rounded-bl-lg border-b border-l border-slate-700 z-10">
            Ad
          </div>
          <div className="h-[220px] bg-blue-600 flex flex-col items-center justify-center p-4 relative overflow-hidden shrink-0">
            <div className="absolute inset-0 bg-black/20" />
            <div className="text-white font-black text-2xl text-center leading-tight relative z-10 uppercase tracking-tight">
              Moving<br />Soon?
            </div>
          </div>
          <div className="flex-1 bg-slate-900 p-4 flex flex-col items-center text-center">
            <div className="text-6xl mb-4 mt-4 transform group-hover:scale-110 transition-transform drop-shadow-lg">📦</div>
            <div className="text-slate-300 text-xs mb-4 font-bold leading-relaxed">
              Escape bad leases fast. Get 20% off heavy-duty moving supplies today.
            </div>
            <div className="bg-slate-800 rounded p-2 mb-4 w-full border border-slate-700">
              <div className="text-yellow-400 text-[10px] tracking-widest">★★★★★</div>
              <div className="text-[9px] text-slate-400 mt-1 italic leading-tight">
                &ldquo;Saved me from a nightmare landlord!&rdquo;
              </div>
            </div>
            <button className="mt-auto w-full bg-blue-600 text-white text-[11px] font-black py-3 rounded-lg group-hover:bg-blue-500 transition-colors uppercase tracking-widest shadow-lg">
              Shop Now
            </button>
          </div>
        </div>

        {/* Right ad */}
        <div
          className="w-[160px] h-[850px] bg-slate-800 border border-slate-700 rounded-2xl pointer-events-auto hidden min-[1550px]:flex flex-col shadow-2xl fade-in group hover:border-emerald-500 transition-colors relative overflow-hidden"
          style={{ animationDelay: "0.2s" }}
        >
          <div className="absolute top-0 right-0 bg-slate-900 text-slate-500 text-[8px] uppercase tracking-widest px-3 py-1 rounded-bl-lg border-b border-l border-slate-700 z-10">
            Ad
          </div>
          <div className="h-[220px] bg-emerald-600 flex flex-col items-center justify-center p-4 relative overflow-hidden shrink-0">
            <div className="absolute inset-0 bg-black/20" />
            <div className="text-white font-black text-2xl text-center leading-tight relative z-10 uppercase tracking-tight">
              Bad<br />Landlord?
            </div>
          </div>
          <div className="flex-1 bg-slate-900 p-4 flex flex-col items-center text-center">
            <div className="text-6xl mb-4 mt-4 transform group-hover:scale-110 transition-transform drop-shadow-lg">⚖️</div>
            <div className="text-slate-300 text-xs mb-4 font-bold leading-relaxed">
              Legal protection for renters. Break your lease safely.
            </div>
            <div className="bg-slate-800 rounded p-2 mb-4 w-full border border-slate-700">
              <div className="text-emerald-400 text-xs font-black">98%</div>
              <div className="text-[9px] text-slate-400 uppercase tracking-widest font-bold mt-0.5">Success Rate</div>
            </div>
            <button className="mt-auto w-full bg-emerald-600 text-white text-[11px] font-black py-3 rounded-lg group-hover:bg-emerald-500 transition-colors uppercase tracking-widest shadow-lg">
              Free Consult
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
