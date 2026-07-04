"use client";

// Client-side city selection (DR 0014). Source of truth precedence:
//   URL `?city=` → localStorage → DEFAULT_CITY.
// The choice is mirrored back to both the URL (shareable links) and
// localStorage (sticky across visits). `needsPick` is true on a first visit
// with no stored/URL choice, so the entry popup can prompt once.

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { type City, DEFAULT_CITY, isCity } from "@/lib/city";

const STORAGE_KEY = "fsi.city";

interface CityContextValue {
  city: City;
  setCity: (c: City) => void;
  needsPick: boolean;
  dismissPick: () => void;
}

const CityContext = createContext<CityContextValue | null>(null);

function readInitial(): { city: City; needsPick: boolean } {
  if (typeof window === "undefined") return { city: DEFAULT_CITY, needsPick: false };
  const url = new URLSearchParams(window.location.search).get("city");
  if (isCity(url)) return { city: url, needsPick: false };
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (isCity(stored)) return { city: stored, needsPick: false };
  return { city: DEFAULT_CITY, needsPick: true };
}

export function CityProvider({ children }: { children: React.ReactNode }) {
  // Server render + first client paint use DEFAULT_CITY so markup matches
  // (no hydration mismatch); a mount effect then applies the real choice.
  const [city, setCityState] = useState<City>(DEFAULT_CITY);
  const [needsPick, setNeedsPick] = useState(false);

  // Hydration read: URL/localStorage are browser-only, so the real choice can
  // only be applied after mount (a lazy initializer would diverge from the
  // server's DEFAULT_CITY paint and cause a hydration mismatch). This one-shot
  // post-mount setState is the intended use, not a cascading-render smell.
  useEffect(() => {
    const { city: c, needsPick: np } = readInitial();
    /* eslint-disable react-hooks/set-state-in-effect */
    setCityState(c);
    setNeedsPick(np);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const setCity = useCallback((c: City) => {
    setCityState(c);
    setNeedsPick(false);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, c);
      const url = new URL(window.location.href);
      url.searchParams.set("city", c);
      window.history.replaceState(null, "", url.toString());
    }
  }, []);

  const dismissPick = useCallback(() => setNeedsPick(false), []);

  return (
    <CityContext.Provider value={{ city, setCity, needsPick, dismissPick }}>
      {children}
    </CityContext.Provider>
  );
}

export function useCity(): CityContextValue {
  const ctx = useContext(CityContext);
  if (!ctx) throw new Error("useCity must be used within <CityProvider>");
  return ctx;
}
