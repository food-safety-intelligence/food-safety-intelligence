"use client";

// Entry popup (first visit) + a compact header toggle for switching city.
// Both drive the same CityContext, so the whole app re-fetches the selected
// city's data (DR 0016).

import { startTransition, useCallback } from "react";
import { MapPin } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { CITIES, CITY_CONFIG, type City } from "@/lib/city";
import { useCity } from "@/components/CityContext";
import { Wordmark } from "@/components/Wordmark";

// Switch the active city, but reroute to the new city's map when the user is on
// an establishment detail page. That page is keyed to a city-specific `?id=`
// with no equivalent in another city, so switching in place would 404
// ("Establishment not found"). Every other page is city-aware but not id-bound,
// so it switches in place. trailingSlash is on (next.config), so usePathname()
// returns "/restaurant/"; match both forms so the guard holds either way.
// Shared by the header toggle AND the entry modal so both honour the guard.
function useCitySwitch(): (c: City) => void {
  const { city, setCity } = useCity();
  const router = useRouter();
  const pathname = usePathname();
  const onDetailPage = pathname === "/restaurant" || pathname === "/restaurant/";

  return useCallback(
    (c: City) => {
      // Only reroute on a real change — re-picking the current city should stay
      // put, not bounce the user off the detail page to the map.
      if (onDetailPage && c !== city) {
        // Batch the city change and the navigation into one transition so React
        // commits the destination (the map) directly, skipping an intermediate
        // re-render of the detail page — which would otherwise remount the detail
        // loader (keyed on city+id) and fire a doomed fetch for the new city's
        // nonexistent bundle before we navigate away.
        startTransition(() => {
          setCity(c);
          router.push(`/?city=${c}`);
        });
        return;
      }
      setCity(c);
    },
    [onDetailPage, city, setCity, router],
  );
}

export function CityEntryModal() {
  const { needsPick } = useCity();
  const switchCity = useCitySwitch();

  // Intentionally NOT dismissable: the picker is a mandatory gate. There is no
  // close button, Esc handler, or backdrop dismiss — the only way past it is to
  // choose a city. The home logo re-opens it (requestPick) precisely so a
  // returning visitor can re-choose; "closing" means picking a city.
  if (!needsPick) return null;
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center px-4 bg-cover bg-center"
      style={{
        backgroundImage: `url(${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/images/popup-produce.jpg)`,
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="city-pick-title"
    >
      {/* Dark scrim over the produce photo so the card stays readable (photo by
          Unsplash, self-hosted). */}
      <div className="absolute inset-0 bg-ink/65" aria-hidden />
      <div className="relative z-10 w-full max-w-md rounded-2xl bg-card border border-line soft-shadow p-6">
        {/* Brand lockup on the entry screen, mirroring the header logo's text. */}
        <div className="mb-4">
          <div className="text-lg font-semibold tracking-tight">
            <Wordmark />
          </div>
          <div className="text-2xs text-muted tracking-wide">Food Safety</div>
        </div>
        <h2 id="city-pick-title" className="text-2xl font-light tracking-tight">
          Choose a city
        </h2>
        <p className="text-sm text-muted mt-2 leading-[1.6]">
          This tool covers {CITIES.length} cities. Pick one to start. You can
          switch any time from the header.
        </p>
        <div className="mt-5 grid gap-3">
          {CITIES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => switchCity(c)}
              className="flex items-center gap-3 rounded-xl border border-line px-4 py-3 text-left hover:border-sage hover:bg-sage/5 transition-colors min-h-[44px]"
            >
              <MapPin className="size-5 text-sage shrink-0" aria-hidden />
              <span>
                <span className="block font-medium">{CITY_CONFIG[c].label}</span>
                <span className="block text-xs text-muted capitalize">
                  {CITY_CONFIG[c].nounPlural}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function CityToggle() {
  const { city } = useCity();
  const switchCity = useCitySwitch();

  return (
    <div
      className="flex items-center rounded-lg border border-line overflow-hidden text-2xs"
      role="group"
      aria-label="Select city"
    >
      {CITIES.map((c: City) => {
        const active = c === city;
        return (
          <button
            key={c}
            type="button"
            aria-pressed={active}
            onClick={() => switchCity(c)}
            className={
              "px-2.5 py-1.5 min-h-[44px] sm:min-h-0 transition-colors " +
              (active ? "bg-sage text-white" : "bg-transparent text-muted hover:text-ink")
            }
          >
            {CITY_CONFIG[c].label}
          </button>
        );
      })}
    </div>
  );
}
