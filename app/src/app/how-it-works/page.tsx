import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { loadMethodology } from "@/lib/methodology-server";

export const metadata = {
  title: "How this works · Food Safety",
  description:
    "Methodology: data, label, features, model, calibration, and known limitations.",
};

export default async function HowItWorksPage() {
  const methodology = await loadMethodology();
  const top20 = methodology.operating_points.find((p) => p.frac === 0.2);

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
              Thirty-three features, all built leak-free from the public record:
            </p>
            <ul className="text-[15px] leading-relaxed mt-3 space-y-2 list-disc pl-5 text-ink/85">
              <li>
                <span className="font-medium">Prior history</span> — counts of
                inspections, failures, priority and core violations across the
                restaurant&apos;s full prior record, plus near-miss and
                visit-trigger history (Pass w/ Conditions, re-inspections,
                complaint visits)
              </li>
              <li>
                <span className="font-medium">Recency &amp; trend</span> — days
                since the last inspection/failure, the previous inspection&apos;s
                outcome, and 365-day rolling failure and violation counts — so
                the model can see a restaurant improving, not just its lifetime
                totals
              </li>
              <li>
                <span className="font-medium">Static facility</span> —
                Chicago&apos;s risk tier, license age/history, and the scheduled
                visit trigger. ZIP and facility type were dropped as
                geographic/business-type proxies (see limitations)
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
              to handle the ~11% positive rate, calibrated with Platt (sigmoid)
              scaling. On the time-held-out test split: PR-AUC{" "}
              {methodology.headline.pr_auc.toFixed(2)}, ROC-AUC{" "}
              {methodology.headline.roc_auc.toFixed(2)}, top-decile lift{" "}
              {methodology.headline.top_decile_lift.toFixed(1)}×.
            </p>
          </article>

          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              The split is by time, never random
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Train, validation, and test are carved by date, not shuffled. We{" "}
              <span className="font-medium">train</span> on inspections before
              2024-07, <span className="font-medium">calibrate</span> on
              2024-07 → 2025-07, and <span className="font-medium">test</span>{" "}
              on 2025-07 onward — and every feature at a given inspection is
              computed only from data strictly before it. A random shuffle would
              let the model peek at a restaurant&apos;s future to predict its
              past, inflating the score into a number that would never hold up
              in production. The chronological split mirrors how the model is
              actually used: trained on history, scored on what comes next.
            </p>
          </article>

          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              What it catches
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Inspectors are capacity-limited, so the score is really a ranked
              work-list. The honest read isn&apos;t a single number — it&apos;s
              how much of the real risk you catch at the slice you can actually
              staff:
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-[14px] border-collapse">
                <thead>
                  <tr className="text-left text-sage text-[12px] tracking-[0.08em] uppercase border-b border-ink/15">
                    <th className="py-2 pr-4 font-medium">Inspect top</th>
                    <th className="py-2 pr-4 font-medium">Restaurants</th>
                    <th className="py-2 pr-4 font-medium">Precision</th>
                    <th className="py-2 pr-4 font-medium">Events caught</th>
                    <th className="py-2 font-medium">Lift</th>
                  </tr>
                </thead>
                <tbody className="num text-ink/85">
                  {methodology.operating_points.map((p) => (
                    <tr key={p.frac} className="border-b border-ink/10">
                      <td className="py-2 pr-4">{Math.round(p.frac * 100)}%</td>
                      <td className="py-2 pr-4">
                        {p.n_flagged.toLocaleString()}
                      </td>
                      <td className="py-2 pr-4">
                        {Math.round(p.precision * 100)}%
                      </td>
                      <td className="py-2 pr-4">
                        {Math.round(p.recall * 100)}%
                      </td>
                      <td className="py-2">{p.lift.toFixed(1)}×</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[13.5px] text-muted leading-relaxed mt-3">
              Working the top 20% by risk surfaces{" "}
              {top20 ? Math.round(top20.recall * 100) : 54}% of the next-180-day
              events — {top20 ? top20.lift.toFixed(1) : "2.7"}× better than
              inspecting a random 20%. Baseline model, time-held-out test from{" "}
              {methodology.test.split_from || "2025-07-01"} onward (n ≈{" "}
              {methodology.test.n
                ? methodology.test.n.toLocaleString()
                : "7,000"}{" "}
              inspections, {Math.round(methodology.test.prevalence * 100) || 11}%
              with an event). &ldquo;Lift&rdquo; is precision divided by that
              base rate.
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
