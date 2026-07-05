import { Suspense } from "react";
import { InspectorWorklist } from "@/components/InspectorWorklist";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata = {
  title: "For inspectors — Food Safety Chicago",
  description:
    "A model-ranked inspection worklist: establishments ordered by their probability of a failed inspection or critical violation in the next 180 days.",
};

export default function InspectorsPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <SiteHeader activeNav="inspectors" />
      {/* InspectorWorklist reads ?tier=&sort= via useSearchParams, which the
          static export requires to be inside a Suspense boundary. */}
      <Suspense fallback={null}>
        <InspectorWorklist />
      </Suspense>
      <SiteFooter />
    </div>
  );
}
