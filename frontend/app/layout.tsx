import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DwellSense | Real Estate Forensics",
  description: "Don't sign a blind lease. AI-powered threat analysis for any NYC address.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
