"use client";

import { CITY_CONFIG } from "@/lib/city";
import { useCity } from "@/components/CityContext";

export function SiteFooter() {
  const { city } = useCity();
  const cfg = CITY_CONFIG[city];
  return (
    <footer className="border-t border-line bg-cream/70 mt-auto">
      <div className="max-w-[1240px] mx-auto px-8 py-8 grid grid-cols-12 gap-6 items-start text-sm text-muted">
        <div className="col-span-12 md:col-span-5">
          <div className="text-ink font-medium">
            A research preview · UC Berkeley MIDS Capstone
          </div>
          <p className="mt-2 leading-relaxed max-w-[40ch]">{cfg.footerBlurb}</p>
        </div>
        <div className="col-span-6 md:col-span-3">
          <div className="text-2xs tracking-widest uppercase text-muted mb-2">
            Sources
          </div>
          <ul className="space-y-1">
            {cfg.sources.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
        <div className="col-span-6 md:col-span-4">
          <div className="text-2xs tracking-widest uppercase text-muted mb-2">
            Team
          </div>
          <p>
            Jun Xu · Arun Agarwal · Bella Davies · Deepak Srivastava · Aurelia
            Yang
          </p>
        </div>
      </div>
    </footer>
  );
}
