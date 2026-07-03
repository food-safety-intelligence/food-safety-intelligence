import { Suspense } from "react";
import { RestaurantDetail } from "@/components/RestaurantDetail";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

// Single statically-exported detail page for ALL establishments. The license id
// comes from the `?id=` query param, read client-side in RestaurantDetail, which
// fetches that establishment's bundle from same-origin static JSON. This keeps
// the build O(1) in establishment count (the old `[id]` route pre-rendered a page
// each, capped at the top-500 by risk — so the Low / A–Z tabs and most map pins
// 404'd). `useSearchParams` requires a Suspense boundary under static export.
export default function RestaurantPage() {
  return (
    <>
      <SiteHeader activeNav="search" />
      <Suspense>
        <RestaurantDetail />
      </Suspense>
      <SiteFooter />
    </>
  );
}
