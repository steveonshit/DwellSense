export default function SideAds() {
  return (
    <div className="hidden fixed inset-0 pointer-events-none z-30 top-[76px]">
      <div className="w-full h-full flex justify-between items-start max-w-[1640px] mx-auto pt-[40px] px-2 xl:px-4">

        <div className="w-[160px] h-[850px] bg-slate-800 border border-slate-700 rounded-2xl pointer-events-none hidden min-[1550px]:flex flex-col shadow-2xl fade-in relative overflow-hidden opacity-90">
          <div className="absolute top-0 right-0 bg-slate-900 text-slate-500 text-[8px] uppercase tracking-widest px-3 py-1 rounded-bl-lg border-b border-l border-slate-700 z-10">
            Sponsored
          </div>
          <div className="h-[220px] bg-slate-700 flex flex-col items-center justify-center p-4 relative overflow-hidden shrink-0">
            <div className="text-slate-300 font-black text-lg text-center leading-tight uppercase tracking-tight">
              Ad space
            </div>
          </div>
          <div className="flex-1 bg-slate-900 p-4 flex flex-col items-center justify-center text-center">
            <div className="text-slate-500 text-xs font-bold leading-relaxed">
              Placeholder panel. No offers or stats are shown until a real sponsor is linked.
            </div>
          </div>
        </div>

        <div
          className="w-[160px] h-[850px] bg-slate-800 border border-slate-700 rounded-2xl pointer-events-none hidden min-[1550px]:flex flex-col shadow-2xl fade-in relative overflow-hidden opacity-90"
          style={{ animationDelay: "0.2s" }}
        >
          <div className="absolute top-0 right-0 bg-slate-900 text-slate-500 text-[8px] uppercase tracking-widest px-3 py-1 rounded-bl-lg border-b border-l border-slate-700 z-10">
            Sponsored
          </div>
          <div className="h-[220px] bg-slate-700 flex flex-col items-center justify-center p-4 relative overflow-hidden shrink-0">
            <div className="text-slate-300 font-black text-lg text-center leading-tight uppercase tracking-tight">
              Ad space
            </div>
          </div>
          <div className="flex-1 bg-slate-900 p-4 flex flex-col items-center justify-center text-center">
            <div className="text-slate-500 text-xs font-bold leading-relaxed">
              Placeholder panel. No offers or stats are shown until a real sponsor is linked.
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
