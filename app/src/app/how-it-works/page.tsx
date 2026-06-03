import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata = {
  title: "How this works · Food Safety",
  description:
    "Methodology: data, label, features, model, calibration, and known limitations.",
};

export default function HowItWorksPage() {
  return (
    <>
      <SiteHeader activeNav="how" />

      <main className="max-w-[820px] mx-auto px-8 pt-10 pb-24 flex-1">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-[13px] text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>

        <header className="mt-6">
          <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3">
            Methodology
          </p>
          <h1 className="text-[3rem] font-light leading-[1.05] tracking-tight">
            How this works
          </h1>
          <p className="text-[17px] text-muted leading-[1.65] mt-5 max-w-[58ch]">
            A logistic-regression model fit on six years of Chicago inspection
            history. The score is a calibrated probability that a restaurant
            will fail an inspection or be cited for a priority violation in
            the next 180 days.
          </p>
        </header>

        <section className="mt-10 space-y-8">
          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              The label
            </h2>
            <p
              id="priority-violations"
              className="text-[15.5px] text-muted leading-relaxed mt-2"
            >
              For each inspection, we ask: in the 180 days that follow, does
              the same restaurant have either a Fail result OR a priority
              violation (Chicago codes 1–29)? Priority violations are the
              serious tier — temperature abuse, handwashing failures,
              cross-contamination, sewage/plumbing issues. Pre-2019
              inspections are used only as burn-in to compute prior-history
              features, never as training labels (Chicago changed inspection
              procedures in July 2018).
            </p>
          </article>

          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              The features
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Twenty-six features, all built leak-free from the public record:
            </p>
            <ul className="text-[15px] leading-relaxed mt-3 space-y-2 list-disc pl-5 text-ink/85">
              <li>
                <span className="font-medium">Prior history</span> — counts of
                inspections, failures, priority violations, and core violations
                in the trailing 2 years
              </li>
              <li>
                <span className="font-medium">Recency</span> — days since the
                last inspection, days since the last failure
              </li>
              <li>
                <span className="font-medium">Static facility</span> — facility
                type, risk tier, ZIP code, license age
              </li>
              <li>
                <span className="font-medium">Violation keywords</span> —
                twelve regex flags on prior violation text (temperature,
                rodent/pest, raw food, cross-contamination, handwashing, sewage,
                etc.)
              </li>
              <li>
                <span className="font-medium">Calendar</span> — month + quarter
                (year is excluded — it doesn&apos;t generalise across the
                chronological train/test split)
              </li>
            </ul>
          </article>

          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              The model
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Logistic regression with{" "}
              <code className="num text-[13.5px] bg-tint px-1.5 py-0.5 rounded">
                class_weight=&quot;balanced&quot;
              </code>{" "}
              to handle the ~10% positive rate, fit on training data through
              2024-07. Calibrated on a held-out validation set
              (2024-07 → 2025-07) with Platt scaling. Final metrics on the
              2025-07-onward test split: PR-AUC 0.27, ROC-AUC 0.77, top-decile
              lift 3.4×.
            </p>
          </article>

          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              What&apos;s explained
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Per-restaurant SHAP attribution — log-odds contributions from
              each feature, summed to recover the model&apos;s logit. The
              detail page surfaces the top four drivers, signed so positive
              contributions push risk up and negative contributions push it
              down.
            </p>
          </article>

          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              Known limitations
            </h2>
            <ul className="text-[15px] leading-relaxed mt-3 space-y-2 list-disc pl-5 text-ink/85">
              <li>
                Only six years of training data. The model can&apos;t recognise
                patterns that pre-date 2019.
              </li>
              <li>
                The label is a proxy for food-safety risk, not food-safety risk
                itself. Inspections measure what inspectors see, not what
                diners experience.
              </li>
              <li>
                No restaurant-level traffic or revenue data — the score
                doesn&apos;t adjust for kitchen volume.
              </li>
              <li>
                Group performance across facility type and neighborhood
                hasn&apos;t yet been audited end-to-end; expect uneven
                calibration in segments with sparse training history.
              </li>
            </ul>
          </article>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
