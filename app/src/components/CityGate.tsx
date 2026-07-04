"use client";

// Render one subtree for Chicago (the default `children`) and another for NYC.
// Lets a server-rendered page keep its Chicago content while swapping in a
// city-specific alternative at runtime (DR 0014), without duplicating the page.

import type { ReactNode } from "react";
import { useCity } from "@/components/CityContext";

export function CityGate({ children, nyc }: { children: ReactNode; nyc: ReactNode }) {
  const { city } = useCity();
  return <>{city === "nyc" ? nyc : children}</>;
}
