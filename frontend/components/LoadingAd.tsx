"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  onComplete: () => void;
  isApiReady: boolean;
}

const AD_DURATION = 5; // seconds

export default function LoadingAd({ onComplete, isApiReady }: Props) {
  const [secondsLeft, setSecondsLeft] = useState(AD_DURATION);
  const [showSkip, setShowSkip] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasCompleted = useRef(false);

  const complete = () => {
    if (hasCompleted.current) return;
    hasCompleted.current = true;
    if (intervalRef.current) clearInterval(intervalRef.current);
    onComplete();
  };

  useEffect(() => {
    // Show skip button after 2 seconds
    const skipTimer = setTimeout(() => setShowSkip(true), 2000);

    intervalRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          // Ad timer expired — complete only if API is also ready
          if (isApiReady) complete();
          return 0;
        }
        return s - 1;
      });
    }, 1000);

    return () => {
      clearTimeout(skipTimer);
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When API finishes AND timer has already expired → complete
  useEffect(() => {
    if (isApiReady && secondsLeft === 0) {
      complete();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isApiReady, secondsLeft]);

  const handleSkip = () => {
    setSkipped(true);
    if (isApiReady) {
      complete();
    }
    // If API is not ready yet, we just hide the timer — complete() will be called
    // as soon as isApiReady becomes true (handled by the useEffect above)
  };

  // If user skipped but API just became ready
  useEffect(() => {
    if (skipped && isApiReady) complete();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skipped, isApiReady]);

  const progressPct = ((AD_DURATION - secondsLeft) / AD_DURATION) * 100;

  return (
    <div className="w-full max-w-4xl bg-slate-900 border border-slate-700 rounded-3xl overflow-hidden shadow-2xl mt-4 relative fade-in">
      {/* Top bar */}
      <div className="bg-black/80 px-4 py-3 border-b border-slate-800 flex justify-between items-center">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full bg-rose-500 animate-pulse" />
          <span className="text-slate-300 text-xs font-bold uppercase tracking-widest hidden sm:inline-block">
            Analyzing Data &amp; Mapping...
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-slate-400 text-[10px] font-bold uppercase tracking-wider border border-slate-600 px-2 py-0.5 rounded hidden sm:inline-block">
            Advertisement
          </span>

          {!showSkip && (
            <span className="text-white text-xs font-bold bg-slate-800 px-3 py-1.5 rounded border border-slate-700 inline-block">
              Report in{" "}
              <span className="text-rose-400 w-3 inline-block text-center">
                {secondsLeft}
              </span>
              s
            </span>
          )}

          {showSkip && (
            <button
              onClick={handleSkip}
              className="text-white text-xs font-bold bg-slate-700 hover:bg-rose-600 px-3 py-1.5 rounded transition-colors cursor-pointer border border-slate-500 shadow-lg flex items-center gap-1"
            >
              {skipped && !isApiReady ? (
                <span className="animate-pulse">Loading data...</span>
              ) : (
                <>Skip Ad ⏭</>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Ad content */}
      <div className="w-full h-[350px] bg-gradient-to-br from-indigo-900 to-slate-900 flex flex-col md:flex-row items-center justify-center p-8 pt-4 relative">
        <div className="md:w-1/2 flex justify-center items-center z-10">
          <div className="w-32 h-32 bg-indigo-500/20 rounded-full border-4 border-indigo-500/30 flex items-center justify-center shadow-[0_0_30px_rgba(99,102,241,0.3)] text-5xl">
            🛡️
          </div>
        </div>
        <div className="md:w-1/2 text-center md:text-left z-10 mt-6 md:mt-0">
          <div className="text-indigo-400 font-black tracking-widest text-[10px] uppercase mb-1">
            Sponsored Partner
          </div>
          <h2 className="text-3xl font-black text-white mb-3">SafeLease Insurance</h2>
          <p className="text-slate-300 text-sm mb-5">
            Protect your belongings from terrible neighbors and sudden leaks. Plans start at just{" "}
            <strong className="text-white">$5/mo</strong>.
          </p>
          <button
            onClick={handleSkip}
            className="bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2 px-6 rounded-lg transition-colors shadow-lg shadow-indigo-900/50"
          >
            Get a Free Quote ↗
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1 bg-slate-800">
        <div
          className="h-full bg-rose-500 shadow-[0_0_10px_rgba(225,29,72,0.8)] transition-all"
          style={{ width: `${progressPct}%`, transition: "width 1s linear" }}
        />
      </div>
    </div>
  );
}
