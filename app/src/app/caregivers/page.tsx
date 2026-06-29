import {
  ArrowLeft,
  ArrowRight,
  Bug,
  CalendarClock,
  Heart,
  History,
  type LucideIcon,
  Search,
} from "lucide-react";
import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "For caregivers · Food Safety",
  description:
    "How to read a food establishment risk signal when you're choosing for someone with compromised immunity.",
};

/**
 * One "what to weigh" pattern. Each is grounded in a real model driver
 * (see src/foodsafety/explain/feature_labels.py) so the guidance matches what a
 * reader will actually find on a detail page. `weight` drives the visual
 * treatment: "more" reads terra (a pattern about the kitchen itself), "less"
 * reads muted (administrative, not evidence of a problem).
 */
type Pattern = {
  icon: LucideIcon;
  title: string;
  body: string;
  weight: "more" | "less";
};

const PATTERNS: Pattern[] = [
  {
    icon: History,
    title: "Recurring violations",
    body: "Multiple priority violations in prior history — especially temperature, handwashing, or cross-contamination — describe how the kitchen actually operates. These are the drivers your care team would most want to consider.",
    weight: "more",
  },
  {
    // Driver: flag_kw_rodent / flag_kw_pest — vermin/pest noted in the
    // establishment's OWN recent violation text. (The model does not use
    // nearby 311 complaints; that 311 feature is not wired into the contract.)
    icon: Bug,
    title: "Pest or vermin on inspection",
    body: "Rodent, vermin, or pest activity recorded in the establishment's own recent inspection violations. Repeated pest findings point to a sanitation problem in the kitchen itself — exactly the kind of pattern that matters most for a vulnerable diner.",
    weight: "more",
  },
  {
    icon: CalendarClock,
    title: "Long since last inspection",
    body: "An administrative gap, not evidence of a problem. The score treats it as a risk signal because inspection cadence correlates with risk in Chicago's data — but it doesn't tell you anything about the kitchen itself.",
    weight: "less",
  },
];

function PatternCard({ icon: Icon, title, body, weight }: Pattern) {
  const more = weight === "more";
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
        <div className="min-w-0">
          {/* Non-colour label so the weigh-more / weigh-less distinction isn't
              carried by the terra/muted colour alone. */}
          <p
            className={cn(
              "text-2xs tracking-widest uppercase",
              more ? "text-terra-strong" : "text-muted",
            )}
          >
            {more ? "Weigh more" : "Weigh less"}
          </p>
          <h3 className="text-xl font-medium tracking-tight">{title}</h3>
        </div>
      </div>
      <p className="text-base text-muted leading-relaxed mt-3">{body}</p>
    </div>
  );
}

export default function CaregiversPage() {
  return (
    <>
      <SiteHeader activeNav="caregivers" />

      <main className="max-w-[820px] mx-auto px-8 pt-10 pb-24 flex-1">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>

        <header className="mt-6">
          <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3 inline-flex items-center gap-2">
            <Heart className="w-3.5 h-3.5" strokeWidth={2} />
            For caregivers
          </p>
          <h1 className="text-5xl font-light leading-[1.05] tracking-tight">
            The <span className="serif italic text-teal">drivers</span> matter
            more than the score.
          </h1>
          <p className="text-lg text-muted leading-[1.65] mt-5 max-w-[58ch]">
            Two food establishments can share the same predicted risk score for
            very different reasons. If you&apos;re ordering for someone with
            compromised immunity — an older parent, a chemo patient, a transplant
            recipient — the kind of pattern matters far more than the number.
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
            drivers — the specific patterns pushing risk up or down. Some
            describe the kitchen itself; others are administrative. Here&apos;s
            how to weigh the ones you&apos;ll see most.
          </p>
          <div className="mt-6 grid gap-5">
            {PATTERNS.map((p) => (
              <PatternCard key={p.title} {...p} />
            ))}
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
            as one input alongside the precautions your care team recommends —
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
