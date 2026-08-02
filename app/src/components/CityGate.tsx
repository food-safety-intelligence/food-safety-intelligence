"use client";

// Render one subtree for Chicago (the default `children`) and a city-specific
// alternative for the other cities. Lets a server-rendered page keep its Chicago
// content while swapping in a per-city alternative at runtime (DR 0016),
// without duplicating the page. A city with no override falls back to `children`.

import type { ReactNode } from "react";
import { useCity } from "@/components/CityContext";

export function CityGate({
  children,
  nyc,
  la,
}: {
  children: ReactNode;
  nyc?: ReactNode;
  la?: ReactNode;
}) {
  const { city } = useCity();
  if (city === "nyc") return <>{nyc ?? children}</>;
  if (city === "la") return <>{la ?? children}</>;
  return <>{children}</>;
}
