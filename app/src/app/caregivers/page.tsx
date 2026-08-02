import {
  ArrowRight,
  Bug,
  CalendarClock,
  Heart,
  History,
  IdCard,
  type LucideIcon,
  Search,
} from "lucide-react";
import Link from "next/link";
import { BackToSearch } from "@/components/BackToSearch";
import { RegisterChatPersona } from "@/components/RegisterChatPersona";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "For caregivers · Eatelligence Food Safety",
  description:
    "How to read a food establishment risk signal when you're choosing for someone with compromised immunity.",
};

/**
 * One "what to weigh" pattern. Each is grounded in a real model driver
 * (see src/foodsafety/explain/feature_labels.py) so the guidance matches what a
 * reader will actually find on a detail page. Patterns are split into two
 * groups — kitchen signals vs administrative signals — so the more/less
 * distinction is carried by the page structure, not just a per-card colour.
 */
type Pattern = {
  icon: LucideIcon;
  title: string;
  body: string;
};

// Signals that describe what's happening in the kitchen — weigh these more.
const KITCHEN_PATTERNS: Pattern[] = [
  {
    icon: History,
    title: "Recurring violations",
    body: "Multiple priority violations in prior history (especially temperature, handwashing, or cross-contamination) describe how the kitchen actually operates. These are the drivers your care team would most want to consider.",
  },
  {
    // Driver: flag_kw_rodent / flag_kw_pest — vermin/pest noted in the
    // establishment's OWN recent violation text. (The model does not use
    // nearby 311 complaints; that 311 feature is not wired into the contract.)
    icon: Bug,
    title: "Pest or vermin on inspection",
    body: "Rodent, vermin, or pest activity recorded in the establishment's own recent inspection violations. Repeated pest findings point to a sanitation problem in the kitchen itself, exactly the kind of pattern that matters most for a vulnerable diner.",
  },
];

// Administrative signals the score uses but that don't reflect the kitchen —
// real drivers, but not something to base a choice on. Weigh these less.
const ADMIN_PATTERNS: Pattern[] = [
  {
    icon: CalendarClock,
    title: "Long since last inspection",
    body: "An administrative gap, not evidence of a problem. The score treats it as a risk signal because inspection cadence correlates with risk in Chicago's data, but it doesn't tell you anything about the kitchen itself.",
  },
  {
    icon: IdCard,
    title: "License age",
    body: "How long the business has held its license. The score uses it because tenure correlates with risk in Chicago's data, but it's a proxy for the business, not a measure of what happens in the kitchen, so it shouldn't sway your choice much.",
  },
];

function PatternCard({
  pattern: { icon: Icon, title, body },
  tone,
}: {
  pattern: Pattern;
  tone: "more" | "less";
}) {
  const more = tone === "more";
  return (
    <div
      className={cn(
        "rounded-3xl border border-line p-6",
        more ? "bg-card soft-shadow" : "bg-tint",
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "inline-flex items-center justify-center w-10 h-10 rounded-full shrink-0",
            more ? "bg-terra/12 text-terra-strong" : "bg-ink/[0.05] text-muted",
          )}
        >
          <Icon className="w-[19px] h-[19px]" strokeWidth={1.75} />
        </span>
        <h3 className="text-xl font-medium tracking-tight min-w-0">{title}</h3>
      </div>
      <p className="text-base text-muted leading-relaxed mt-3">{body}</p>
    </div>
  );
}

/**
 * The label above each pattern group. The "weigh these (less)" wording carries
 * the more/less distinction in text, so it never depends on the dot's colour
 * alone.
 */
function GroupLabel({ tone, children }: { tone: "more" | "less"; children: string }) {
  const more = tone === "more";
  return (
    <p
      className={cn(
        "flex items-center gap-2.5 text-xs tracking-[0.14em] uppercase font-medium",
        more ? "text-terra-strong" : "text-muted",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "w-2 h-2 rounded-full shrink-0",
          more ? "bg-terra" : "bg-muted",
        )}
      />
      {children}
    </p>
  );
}

export default function CaregiversPage() {
  return (
    <>
      {/* Scopes the site-wide floating chat to the caregiver persona while this
          page is in view (cleared on unmount) — see RegisterChatPersona. */}
      <RegisterChatPersona persona="caregiver" />
      <SiteHeader activeNav="caregivers" />

      <main className="max-w-[820px] mx-auto px-8 pt-10 pb-24 flex-1">
        <BackToSearch className="inline-flex items-center gap-2 text-sm text-teal hover:underline" />

        <header className="mt-6">
          {/* Hero banner: wholesome foods on the left of the photo, heading over
              the dark negative space on the right; gradient keeps the text legible.
              Image is self-hosted (free Unsplash); basePath prefix is a no-op in
              prod (only set for the local proxy preview). */}
          <div className="relative rounded-3xl overflow-hidden min-h-[280px] sm:min-h-[340px] flex items-center soft-shadow">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/images/caregivers-hero.jpg`}
              alt="Wholesome fresh foods (oats, almonds, milk, avocado, kale and carrots) on a dark table"
              className="absolute inset-0 w-full h-full object-cover"
            />
            <div
              className="absolute inset-0 bg-gradient-to-r from-ink/35 via-ink/55 to-ink/80"
              aria-hidden
            />
            <div className="relative w-full sm:w-[58%] sm:ml-auto px-7 sm:px-10 py-9">
              <p className="text-cream/90 text-xs tracking-[0.18em] uppercase mb-3 inline-flex items-center gap-2">
                <Heart className="w-3.5 h-3.5" strokeWidth={2} />
                For caregivers
              </p>
              <h1 className="text-4xl sm:text-5xl font-light leading-[1.05] tracking-tight text-white">
                The <span className="serif italic">drivers</span> matter more than
                the score.
              </h1>
            </div>
          </div>
          <p className="text-lg text-muted leading-[1.65] mt-6 max-w-[58ch]">
            Two food establishments can share the same predicted risk score for
            very different reasons. If you&apos;re ordering for someone with
            compromised immunity (an older parent, a chemo patient, a transplant
            recipient), the kind of pattern matters far more than the number.
          </p>
        </header>

        <section className="mt-12">
          <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">
            What to weigh
          </p>
          <h2 className="text-2xl font-medium tracking-tight">
            Read the pattern, not just the number
          </h2>
          <p className="text-base text-muted leading-relaxed mt-2 max-w-[60ch]">
            On an establishment&apos;s detail page, the score comes with its top
            drivers: the specific patterns pushing risk up or down. Some
            describe the kitchen itself; others are administrative. The score
            counts both, but for your decision they don&apos;t carry the same
            weight.
          </p>

          <div className="mt-8">
            <GroupLabel tone="more">About the kitchen: weigh these</GroupLabel>
            <div className="mt-4 grid gap-5">
              {KITCHEN_PATTERNS.map((p) => (
                <PatternCard key={p.title} pattern={p} tone="more" />
              ))}
            </div>
          </div>

          <div className="mt-8">
            <GroupLabel tone="less">
              Administrative: weigh these less
            </GroupLabel>
            <div className="mt-4 grid gap-5">
              {ADMIN_PATTERNS.map((p) => (
                <PatternCard key={p.title} pattern={p} tone="less" />
              ))}
            </div>
          </div>
        </section>

        <section className="mt-12 rounded-3xl bg-card border border-line p-7 soft-shadow">
          <p className="text-teal text-xs tracking-[0.18em] uppercase mb-2">
            What this is not
          </p>
          <p className="text-lg leading-relaxed text-ink/90">
            A &quot;High&quot; prediction does not mean a food establishment is
            unsafe to eat at today. It means the patterns in the public record
            resemble those that historically precede a failed inspection. Use it
            as one input alongside the precautions your care team recommends,
            not as a verdict.
          </p>
        </section>

        {/* Next step — the page used to dead-end after the explainer. Send the
            reader to actually look something up, or to the methodology. */}
        <section className="mt-8 rounded-3xl bg-tint border border-line p-7 flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-2xl font-medium tracking-tight">
              Look up a place
            </h2>
            <p className="text-base text-muted leading-relaxed mt-2 max-w-[46ch]">
              Search an establishment to see its score, its recent trend, and the
              top drivers behind it.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 shrink-0">
            <Link
              href="/"
              className="inline-flex items-center gap-2 px-5 py-3 rounded-full bg-ink text-cream text-base font-medium hover:bg-teal transition-colors"
            >
              <Search className="w-4 h-4" strokeWidth={2.5} />
              Search establishments
            </Link>
            <Link
              href="/how-it-works"
              className="inline-flex items-center gap-2 px-5 py-3 rounded-full border border-line bg-card text-base font-medium hover:bg-tint transition-colors"
            >
              How the score works
              <ArrowRight className="w-3.5 h-3.5" strokeWidth={2.5} />
            </Link>
          </div>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
