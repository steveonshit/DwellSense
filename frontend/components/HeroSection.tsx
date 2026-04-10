"use client";

import { useState } from "react";

interface Props {
  onScan: (address: string) => void;
  isLoading: boolean;
}

export default function HeroSection({ onScan, isLoading }: Props) {
  const [address, setAddress] = useState("Apt 4B, 350 W 42nd St, New York, NY");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!address.trim()) return;
    onScan(address.trim());
  };

  return (
    <div className="text-center w-full max-w-4xl mb-10 mt-8 transition-all duration-500">
      <h1 className="text-5xl md:text-7xl font-black mb-4 tracking-tight">
        Don&apos;t sign a{" "}
        <span className="text-rose-500 underline decoration-8 underline-offset-8">blind</span> lease.
      </h1>
      <p className="text-slate-400 text-lg md:text-xl font-bold mb-8">
        Landlords sell the layout. We expose the reality.
      </p>

      <form
        onSubmit={handleSubmit}
        className="w-full bg-slate-800 p-8 rounded-3xl shadow-2xl border border-slate-700 text-left relative z-20"
      >
        <label className="block text-sm font-bold text-slate-400 mb-3 uppercase tracking-widest">
          📍 Target Property Address
        </label>
        <div className="flex flex-col md:flex-row gap-4">
          <input
            type="text"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="e.g. 350 W 42nd St, New York, NY"
            className="flex-1 bg-slate-900 border-2 border-slate-600 rounded-xl px-5 py-4 text-white text-xl font-semibold focus:outline-none focus:border-rose-500 shadow-inner transition-colors"
          />
          <button
            type="submit"
            disabled={isLoading}
            className="bg-rose-600 hover:bg-rose-500 disabled:opacity-60 disabled:cursor-not-allowed text-white font-black text-xl py-4 px-10 rounded-xl transition-transform transform hover:scale-105 shadow-[0_0_20px_rgba(225,29,72,0.4)] flex justify-center items-center gap-2"
          >
            {isLoading ? (
              <span className="animate-pulse">SCANNING...</span>
            ) : (
              <span>RUN FORENSICS</span>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
