import Link from "next/link";
import { CityToggle } from "@/components/CityPicker";
import { DataAsOfChip } from "@/components/DataAsOfChip";
import { HomeLogo } from "@/components/HomeLogo";

/**
 * Top-of-page header. Server component — no client interactivity needed.
 *
 * `activeNav` lets each page hint which item to highlight. Hard-coded
 * navigation is fine for this iteration; we'll lift to a config when more
 * routes land.
 */
// "feedback" is a valid active target (so the feedback page can pass it) but is
// intentionally NOT in NAV below — feedback is a secondary action reached from
// the footer / in-page links, not a top-nav destination, so no pill highlights.
export type NavItem =
  | "search"
  | "chat"
  | "inspectors"
  | "caregivers"
  | "how"
  | "sources"
  | "feedback";

const NAV: { id: NavItem; label: string; href: string }[] = [
  { id: "search", label: "Search", href: "/" },
  { id: "chat", label: "Chat", href: "/chat" },
  { id: "inspectors", label: "For inspectors", href: "/inspectors" },
  { id: "caregivers", label: "For caregivers", href: "/caregivers" },
  { id: "how", label: "How this works", href: "/how-it-works" },
  { id: "sources", label: "Sources", href: "/sources" },
];

export function SiteHeader({
  activeNav = "search",
  showAsOf = true,
}: {
  activeNav?: NavItem;
  // The data-freshness chip rides in the header on every data-backed page.
  // Pages with no city data (e.g. the feedback form) opt out with showAsOf={false}.
  showAsOf?: boolean;
}) {
  return (
    <header className="pt-6">
      {/* Wraps on narrow screens (logo on top, nav below) so the four nav
          pills never overflow the viewport on mobile; single row on desktop. */}
      <div className="max-w-[1240px] mx-auto px-4 sm:px-8 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        {/* Left cluster: brand + the "Data as of …" freshness chip. Grouped so
            justify-between keeps them together on the left and the nav on the
            right; the chip wraps under the logo on narrow screens. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <HomeLogo />
          {showAsOf && <DataAsOfChip />}
        </div>
        <nav className="flex flex-wrap items-center gap-1 text-sm">
          <CityToggle />
          {NAV.map((item) => {
            const active = item.id === activeNav;
            return (
              <Link
                key={item.id}
                href={item.href}
                className={
                  active
                    ? "px-3 py-1.5 rounded-full bg-ink text-cream"
                    : "px-3 py-1.5 rounded-full hover:bg-tint transition-colors"
                }
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
