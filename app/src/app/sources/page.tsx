import { BackToSearch } from "@/components/BackToSearch";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { SourcesList } from "@/components/SourcesList";

export const metadata = {
  title: "Sources · Eatelligence Food Safety",
  description: "Public datasets behind every score on this site.",
};

// Server wrapper (for metadata); the list itself is client-rendered so it can show
// the selected city's sources (Chicago / NYC / LA), tracking the app's city context.
export default function SourcesPage() {
  return (
    <>
      <SiteHeader activeNav="sources" />

      <main className="max-w-[820px] mx-auto px-8 pt-10 pb-24 flex-1">
        <BackToSearch className="inline-flex items-center gap-2 text-sm text-teal hover:underline" />

        <SourcesList />
      </main>

      <SiteFooter />
    </>
  );
}
