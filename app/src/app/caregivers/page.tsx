import { ArrowLeft, Heart } from "lucide-react";
import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata = {
  title: "For caregivers · Food Safety",
  description:
    "How to read a food establishment risk signal when you're choosing for someone with compromised immunity.",
};

export default function CaregiversPage() {
  return (
    <>
      <SiteHeader activeNav="caregivers" />

      <main className="max-w-[820px] mx-auto px-8 pt-10 pb-24 flex-1">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-[13px] text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>

        <header className="mt-6">
          <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3 inline-flex items-center gap-2">
            <Heart className="w-3.5 h-3.5" strokeWidth={2} />
            For caregivers
          </p>
          <h1 className="text-[3rem] font-light leading-[1.05] tracking-tight">
            The drivers matter more than the score.
          </h1>
          <p className="text-[17px] text-muted leading-[1.65] mt-5 max-w-[58ch]">
            Two food establishments can share the same predicted risk score for
            very
            different reasons. If you&apos;re ordering for someone with
            compromised immunity — an older parent, a chemo patient, a
            transplant recipient — the kind of pattern matters far more than
            the number.
          </p>
        </header>

        <section className="mt-12 grid gap-5">
          <div className="rounded-3xl bg-card border border-line p-6 soft-shadow">
            <p className="text-[11px] tracking-widest uppercase text-terra mb-2">
              Patterns worth weighing
            </p>
            <h2 className="text-[1.4rem] font-medium tracking-tight">
              Recurring violations
            </h2>
            <p className="text-[14.5px] text-muted leading-relaxed mt-2">
              Multiple priority violations in prior history — especially
              temperature, handwashing, or cross-contamination — describe how
              the kitchen actually operates. These are the drivers your care
              team would most want to consider.
            </p>
          </div>

          <div className="rounded-3xl bg-card border border-line p-6 soft-shadow">
            <p className="text-[11px] tracking-widest uppercase text-terra mb-2">
              Patterns worth weighing
            </p>
            <h2 className="text-[1.4rem] font-medium tracking-tight">
              Nearby pest complaints
            </h2>
            <p className="text-[14.5px] text-muted leading-relaxed mt-2">
              Rodent or vermin complaints filed near the establishment in the
              last 90 days. A cluster suggests neighborhood pest pressure that
              spills into nearby kitchens.
            </p>
          </div>

          <div className="rounded-3xl bg-tint border border-line p-6">
            <p className="text-[11px] tracking-widest uppercase text-muted mb-2">
              Patterns worth weighing less
            </p>
            <h2 className="text-[1.4rem] font-medium tracking-tight">
              Long since last inspection
            </h2>
            <p className="text-[14.5px] text-muted leading-relaxed mt-2">
              An administrative gap, not evidence of a problem. The score
              treats it as a risk signal because inspection cadence correlates
              with risk in Chicago&apos;s data — but it doesn&apos;t tell you
              anything about the kitchen itself.
            </p>
          </div>
        </section>

        <section className="mt-12 rounded-3xl bg-card border border-line p-7 soft-shadow">
          <p className="text-teal text-[12.5px] tracking-[0.18em] uppercase mb-2">
            What this is not
          </p>
          <p className="text-[16px] leading-relaxed text-ink/90">
            A &quot;High&quot; prediction does not mean a food establishment is
            unsafe to eat at today. It means the patterns in the public record
            resemble those that historically precede a failed inspection. Use
            it as one input alongside the precautions your care team
            recommends — not as a verdict.
          </p>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
