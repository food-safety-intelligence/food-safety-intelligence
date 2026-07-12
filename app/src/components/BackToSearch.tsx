"use client";

// "Back to search" link that returns to the *current* city's search page.
// City lives in the client CityContext (URL `?city=` → localStorage → default),
// so this must be a client component: it reads the active city and points the
// link at that city's home. Chicago is the default, so it needs no query param;
// NYC / LA carry `?city=` so a refresh or shared link lands on the right city.
// Server pages (sources, feedback, caregivers, how-it-works) render it too —
// they can't read the city themselves.

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCity } from "@/components/CityContext";
import { type City, DEFAULT_CITY } from "@/lib/city";

// The search page for a city. Chicago is the default home (no query param);
// the other cities carry `?city=` so a refresh or shared back-link lands on the
// right city rather than falling back to Chicago.
export function backToSearchHref(city: City): string {
  return city === DEFAULT_CITY ? "/" : `/?city=${city}`;
}

// className is passed through verbatim so each call site keeps its own look
// (small text link vs pill button) — this component only owns the city href.
export function BackToSearch({ className }: { className: string }) {
  const { city } = useCity();
  return (
    <Link href={backToSearchHref(city)} className={className}>
      <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
      Back to search
    </Link>
  );
}
