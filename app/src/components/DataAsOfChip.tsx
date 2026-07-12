"use client";

// The "Data as of …" freshness chip that sits in the header on every page. The
// snapshot date is per-city (each city's feed publishes on its own cadence), so
// this reads the selected city's tiny data-meta.json (emitted next to the search
// index) and re-fetches when the city changes. Server render + first paint show
// nothing; the chip appears once the date loads (no hydration mismatch, matching
// the CityContext default-then-effect pattern).

import { useEffect, useState } from "react";
import { CalendarDays } from "lucide-react";
import { dataUrl } from "@/lib/city";
import { useCity } from "@/components/CityContext";
import { formatInspectionDate } from "@/lib/utils";

interface DataMeta {
  as_of_date?: string | null;
}

// Long-form month for the screen-reader label ("12 June 2026") — the visible
// chip keeps the compact "12 Jun 2026" the rest of the app uses.
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS_LONG[m - 1]} ${y}`;
}

export function DataAsOfChip() {
  const { city } = useCity();
  const [asOf, setAsOf] = useState<string | null>(null);

  // Clear the previous city's date the instant the city changes, before the
  // effect refetches — the render-phase reset React recommends over calling
  // setState inside an effect (same idiom as InspectorWorklist's city reset).
  const [prevCity, setPrevCity] = useState(city);
  if (city !== prevCity) {
    setPrevCity(city);
    setAsOf(null);
  }

  useEffect(() => {
    let live = true;
    fetch(dataUrl(city, "data-meta.json"))
      .then((r) => (r.ok ? (r.json() as Promise<DataMeta>) : null))
      .then((m) => {
        if (live && m?.as_of_date) setAsOf(m.as_of_date);
      })
      .catch(() => {
        /* freshness chip is non-critical — stay silent if the meta 404s */
      });
    return () => {
      live = false;
    };
  }, [city]);

  if (!asOf) return null;

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-2xs text-muted whitespace-nowrap"
      aria-label={`Data current as of ${longDate(asOf)}`}
    >
      <CalendarDays className="size-3.5 shrink-0" aria-hidden />
      <span aria-hidden>
        Data as of{" "}
        <span className="text-ink font-medium">{formatInspectionDate(asOf)}</span>
      </span>
    </span>
  );
}
