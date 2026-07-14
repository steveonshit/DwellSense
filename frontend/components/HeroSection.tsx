"use client";

import { useState } from "react";

interface Props {
  onScan: (address: string) => void;
  isLoading: boolean;
}

export default function HeroSection({ onScan, isLoading }: Props) {
  const [address, setAddress] = useState("742 Lefferts Ave, # 5B, Brooklyn, NY 11203");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!address.trim()) return;
    onScan(address.trim());
  };

  return (
    <div className="text-center w-full max-w-4xl mb-10 mt-8 transition-all duration-500">
      <h1 className="text-4xl md:text-6xl font-semibold mb-4 tracking-tight text-white leading-[1.1]">
        Don&apos;t sign a{" "}
        <span className="text-rose-500 underline decoration-4 underline-offset-4">blind</span> lease.
      </h1>
      <p className="text-slate-400 text-base md:text-lg font-normal mb-8 leading-relaxed">
        Landlords sell the layout. We expose the reality.
      </p>

      <form
        onSubmit={handleSubmit}
        className="w-full bg-slate-800 p-8 rounded-3xl shadow-2xl border border-slate-700 text-left relative z-20"
      >
        <label className="block text-sm font-medium text-slate-400 mb-3">
          Target property address
        </label>
        <div className="flex flex-col md:flex-row gap-4">
          <input
            type="text"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="e.g. 350 W 42nd St, New York, NY"
            className="flex-1 bg-slate-900 border border-slate-600 rounded-xl px-5 py-4 text-white text-lg font-normal focus:outline-none focus:border-rose-500 shadow-inner transition-colors"
          />
          <button
            type="submit"
            disabled={isLoading}
            className="bg-rose-600 hover:bg-rose-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-semibold text-lg py-4 px-8 rounded-xl transition-colors flex justify-center items-center gap-2"
          >
            {isLoading ? (
              <span className="animate-pulse">Scanning…</span>
            ) : (
              <span>Run forensics</span>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
