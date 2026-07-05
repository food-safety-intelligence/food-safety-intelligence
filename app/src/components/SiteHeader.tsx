import Link from "next/link";
import { MapPin } from "lucide-react";
import { CityToggle } from "@/components/CityPicker";

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
  | "caregivers"
  | "how"
  | "sources"
  | "feedback";

const NAV: { id: NavItem; label: string; href: string }[] = [
  { id: "search", label: "Search", href: "/" },
  { id: "chat", label: "Chat", href: "/chat" },
  { id: "caregivers", label: "For caregivers", href: "/caregivers" },
  { id: "how", label: "How this works", href: "/how-it-works" },
  { id: "sources", label: "Sources", href: "/sources" },
];

export function SiteHeader({ activeNav = "search" }: { activeNav?: NavItem }) {
  return (
    <header className="pt-6">
      {/* Wraps on narrow screens (logo on top, nav below) so the four nav
          pills never overflow the viewport on mobile; single row on desktop. */}
      <div className="max-w-[1240px] mx-auto px-4 sm:px-8 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <Link href="/" className="flex items-center gap-3 group">
          <span className="inline-flex items-center justify-center w-9 h-9 rounded-full bg-sage/15">
            <MapPin className="w-[18px] h-[18px] text-sage" strokeWidth={2} />
          </span>
          <div className="leading-tight">
            <div className="text-lg font-semibold tracking-tight group-hover:text-teal transition-colors">
              Food Safety
            </div>
            <div className="text-2xs text-muted tracking-wide">
              public-data preview
            </div>
          </div>
        </Link>
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
