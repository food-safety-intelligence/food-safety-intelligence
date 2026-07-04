"use client";

// Below-the-fold "why this exists" blurb + index stats, made city-aware.
// The server renders Chicago's totals into `initialTotals` for the first paint;
// on the client we swap copy + counts for the selected city (fetching the
// city's search-index for its totals when it isn't the default).

import { useEffect, useState } from "react";
import { CITY_CONFIG, dataUrl, DEFAULT_CITY } from "@/lib/city";
import { useCity } from "@/components/CityContext";

interface Totals {
  establishments: number;
  high: number;
}

export function CityIntro({ initialTotals }: { initialTotals: Totals }) {
  const { city } = useCity();
  const [totals, setTotals] = useState<Totals>(initialTotals);

  useEffect(() => {
    let alive = true;
    if (city === DEFAULT_CITY) {
      setTotals(initialTotals);
      return;
    }
    fetch(dataUrl(city, "search-index.json"))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: { total: number; tier_counts: { High: number } }) => {
        if (alive) setTotals({ establishments: d.total, high: d.tier_counts.High });
      })
      .catch(() => {
        /* keep whatever we have */
      });
    return () => {
      alive = false;
    };
  }, [city, initialTotals]);

  const pct =
    totals.establishments > 0
      ? ((totals.high / totals.establishments) * 100).toFixed(1)
      : "0.0";

  return (
    <div className="grid grid-cols-12 gap-6 items-end">
      <div className="col-span-12 lg:col-span-7">
        <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">
          A risk signal, not a verdict
        </p>
        <h2 className="text-4xl font-light tracking-tight leading-[1.1]">Why this exists</h2>
        <p className="text-lg text-muted leading-[1.6] mt-4 max-w-[58ch]">
          {CITY_CONFIG[city].sourceBlurb}
        </p>
      </div>
      <div className="col-span-12 lg:col-span-5 grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-card p-5 soft-shadow border border-line">
          <div className="text-2xs tracking-widest uppercase text-muted">In the index</div>
          <div className="num text-3xl font-medium mt-1 leading-none">
            {totals.establishments.toLocaleString()}
          </div>
          <div className="text-xs text-muted mt-1">{CITY_CONFIG[city].nounPlural}</div>
        </div>
        <div className="rounded-2xl bg-card p-5 soft-shadow border border-line">
          <div className="text-2xs tracking-widest uppercase text-muted">High tier today</div>
          <div className="num text-3xl font-medium mt-1 leading-none text-terra">
            {totals.high.toLocaleString()}
          </div>
          <div className="text-xs text-muted mt-1">{pct}% of the index</div>
        </div>
      </div>
    </div>
  );
}
