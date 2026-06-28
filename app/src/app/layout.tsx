import type { Metadata } from "next";
import { IBM_Plex_Sans, Instrument_Serif, Manrope } from "next/font/google";
import "./globals.css";
import { FloatingChat } from "@/components/FloatingChat";

// Body — distinctive sans, full weight range.
const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

// Italic accents for moments of warmth (hero phrasing, callouts).
const instrument = Instrument_Serif({
  variable: "--font-instrument",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
});

// Tabular numbers — used for risk scores and any aligned numeric data.
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Food Safety — Chicago",
  description:
    "Predicted 180-day food-safety risk for licensed Chicago food establishments. A research preview.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${manrope.variable} ${instrument.variable} ${plexSans.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        <FloatingChat />
      </body>
    </html>
  );
}
