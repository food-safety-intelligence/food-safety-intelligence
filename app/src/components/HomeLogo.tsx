"use client";

// The top-left home logo. Client component because clicking it re-opens the
// "choose a city" entry popup (via CityContext) in addition to routing home,
// so a returning visitor can land back on the beginning prompt.

import Link from "next/link";
import { MapPin } from "lucide-react";
import { useCity } from "@/components/CityContext";
import { Wordmark } from "@/components/Wordmark";

export function HomeLogo() {
  const { requestPick } = useCity();
  return (
    <Link
      href="/"
      onClick={() => requestPick()}
      className="flex items-center gap-3 group"
    >
      <span className="inline-flex items-center justify-center w-9 h-9 rounded-full bg-sage/15">
        <MapPin className="w-[18px] h-[18px] text-sage" strokeWidth={2} />
      </span>
      <div className="leading-tight">
        <div className="text-lg font-semibold tracking-tight group-hover:text-teal transition-colors">
          <Wordmark />
        </div>
        <div className="text-2xs text-muted tracking-wide">Food Safety</div>
      </div>
    </Link>
  );
}
