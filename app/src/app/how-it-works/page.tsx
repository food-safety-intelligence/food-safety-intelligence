import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { TierPill } from "@/components/TierPill";
import { TrendIndicator } from "@/components/TrendIndicator";
import { loadMethodology } from "@/lib/methodology-server";
import { GLOSSARY, GLOSSARY_ORDER } from "@/lib/glossary";
import type { RiskTier } from "@/lib/scores";
import { cn } from "@/lib/utils";

/**
 * One row of the worked-example waterfall: a label on the left and its signed
 * calibrated log-odds on the right. Positive (raises risk) reads terra,
 * negative (lowers) reads sage; structural rows (base / other / total) are
 * neutral. `strong` styles the running-total row.
 */
function WaterfallRow({
  label,
  value,
  muted = false,
  strong = false,
}: {
  label: string;
  value: number;
  muted?: boolean;
  strong?: boolean;
}) {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  const valueColor = muted
    ? "text-muted"
    : value > 0
      ? "text-terra-strong"
      : value < 0
        ? "text-sage-strong"
        : "text-muted";
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 px-4 py-2.5 border-b border-line",
        strong && "bg-tint/50",
      )}
    >
      <span className={cn("text-[14px]", strong ? "text-ink font-medium" : "text-ink/85")}>
        {label}
      </span>
      <span
        className={cn(
          "num tabular-nums shrink-0",
          strong ? "text-ink font-semibold" : valueColor,
        )}
      >
        {sign}
        {Math.abs(value).toFixed(2)}
      </span>
    </div>
  );
}

/**
 * A part divider — an uppercase eyebrow over a hairline that groups the page
 * into "read it / how it's built / how well it works / caveats". Matches the
 * "Methodology" eyebrow in the header.
 */
function SectionLabel({ children, id }: { children: string; id?: string }) {
  return (
    <p
      id={id}
      className="scroll-mt-20 text-sage text-[12px] tracking-[0.18em] uppercase pt-8 border-t border-line"
    >
      {children}
    </p>
  );
}

export const metadata = {
  title: "How this works · Food Safety",
  description:
    "Methodology: data, label, features, model, calibration, and known limitations.",
};

export default async function HowItWorksPage() {
  const methodology = await loadMethodology();
  const top5 = methodology.operating_points.find((p) => p.frac === 0.05);
  const top10 = methodology.operating_points.find((p) => p.frac === 0.1);
  const top20 = methodology.operating_points.find((p) => p.frac === 0.2);

  // Score→tier bands for the badge legend (sourced from the served thresholds
  // via methodology.json, so they can't drift from Python's score_to_tier).
  const tiers = methodology.risk_tiers ?? [];
  const pct = (n: number) => `${Math.round(n * 100)}%`;
  const tierRange = (t: { min: number; max: number | null }) =>
    t.max === null
      ? `${pct(t.min)} and up`
      : t.min <= 0
        ? `under ${pct(t.max)}`
        : `${pct(t.min)}–${pct(t.max)}`;

  // Share of scored establishments per band comes straight from methodology.json
  // (the build script reads the served scores.json totals), so this page loads
  // only its own JSON — no coupling to the 18 MB scores file.
  const tierShare = (t: { share?: number }) =>
    t.share != null ? `${Math.round(t.share * 100)}%` : null;
  const hasShares = tiers.some((t) => t.share != null);

  const importance = methodology.global_importance ?? [];
  const maxImpact = Math.max(...importance.map((d) => d.mean_abs_logodds), 0);

  // Round the waterfall to the precision the rows display (2 dp) and make the
  // "everything else" bucket the residual, so the visible column sums EXACTLY to
  // the total. The stored JSON stays full-precision; this is presentation only.
  const round2 = (n: number) => Math.round(n * 100) / 100;
  const wf = methodology.waterfall;
  const waterfall = wf
    ? (() => {
        const base = round2(wf.base);
        const drivers = wf.drivers.map((d) => ({ ...d, contribution: round2(d.contribution) }));
        const total = round2(wf.total_logit);
        const other = round2(
          total - base - drivers.reduce((sum, d) => sum + d.contribution, 0),
        );
        return { base, drivers, other, total, probability: wf.probability };
      })()
    : null;

  return (
    <>
      <SiteHeader activeNav="how" />

      {/* max-w-full on mobile (capped to the viewport) so the prose wraps
          instead of forcing a horizontal scroll; overflow-x-clip trims the small
          residual overhang from intrinsic-width content (operating-points table)
          without clipping text. Desktop keeps the 820 reading cap. */}
      <main className="w-full max-w-full lg:max-w-[820px] overflow-x-clip mx-auto px-8 pt-10 pb-24 flex-1">
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
            history. The score is a calibrated probability that a food
            establishment will fail an inspection or be cited for a priority
            violation in the next 180 days.
          </p>
        </header>

        {/* Sticky jump-nav — lets a reader skip to any part without scrolling
            the whole methodology. Plain anchors (server component); deep-links
            like #definitions still work. bg matches the page so content scrolls
            cleanly underneath. */}
        <nav
          aria-label="Sections"
          className="sticky top-0 z-20 -mx-8 mt-8 px-8 py-3 bg-cream/85 backdrop-blur border-y border-line flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px]"
        >
          <a href="#reading-the-score" className="text-muted hover:text-ink transition-colors">
            Reading the score
          </a>
          <a href="#how-its-built" className="text-muted hover:text-ink transition-colors">
            How it&apos;s built
          </a>
          <a href="#how-well-it-works" className="text-muted hover:text-ink transition-colors">
            How well it works
          </a>
          <a href="#limits" className="text-muted hover:text-ink transition-colors">
            Limits
          </a>
          <a href="#reference" className="text-muted hover:text-ink transition-colors">
            Reference
          </a>
        </nav>

        <section className="mt-10 space-y-8">
          <SectionLabel id="reading-the-score">Reading the score</SectionLabel>
          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              How to read a score
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Every establishment gets one number — a calibrated probability,
              shown as a percentage, that it fails an inspection or draws a
              priority violation in the next 180 days. &ldquo;Calibrated&rdquo;
              means the number is honest about its own odds: across the
              establishments the model scores around 20%, about 1 in 5 actually
              has an event. The map and list summarise that number two ways: a
              risk band and a 90-day trend.
            </p>

            <h3 className="text-[1.05rem] font-medium tracking-tight mt-6">
              Risk bands
            </h3>
            <p className="text-[14px] text-muted leading-relaxed mt-1.5">
              The percentage is bucketed into four bands — the coloured badges on
              the map, list, and detail pages. These are the model&apos;s{" "}
              <span className="font-medium text-ink/80">output</span>{" "}bands;
              don&apos;t confuse them with Chicago&apos;s own Risk 1/2/3
              classification, which is an{" "}
              <span className="font-medium text-ink/80">input</span>{" "}feature
              (see &ldquo;What the model looks at&rdquo;).
            </p>
            {tiers.length > 0 ? (
              <div className="mt-4 rounded-2xl border border-line bg-card overflow-hidden">
                <div className="flex items-center justify-between gap-4 px-4 py-2 border-b border-line text-[11px] uppercase tracking-[0.08em] text-sage">
                  <span>Tier</span>
                  <span className="flex items-center gap-4">
                    <span className="w-24 text-right">Score</span>
                    {hasShares && <span className="w-14 text-right">Share</span>}
                  </span>
                </div>
                {tiers.map((t) => (
                  <div
                    key={t.label}
                    className="flex items-center justify-between gap-4 px-4 py-3 border-b border-line last:border-b-0"
                  >
                    <TierPill tier={t.label as RiskTier} />
                    <span className="flex items-center gap-4 num tabular-nums">
                      <span className="w-24 text-right text-[14px] text-ink/85">
                        {tierRange(t)}
                      </span>
                      {tierShare(t) && (
                        <span className="w-14 text-right text-[13px] text-muted">
                          {tierShare(t)}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[13.5px] text-muted mt-3">
                Run the metrics pipeline to populate the tier bands.
              </p>
            )}
            <p className="text-[12.5px] text-muted leading-relaxed mt-3">
              Bands are fixed cutoffs on the predicted probability, set once
              (decision record 0008) — they don&apos;t shift per establishment.
              &ldquo;Share&rdquo; is the portion of all scored establishments in
              each band: real scores cluster low, so most sit in Low or Moderate
              and only the small Elevated / High slice is the signal worth acting
              on.
            </p>

            <h3 className="text-[1.05rem] font-medium tracking-tight mt-8">
              The 90-day trend
            </h3>
            <p className="text-[14px] text-muted leading-relaxed mt-1.5">
              Next to each score, an arrow shows where risk has been heading over
              the last 90 days:
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-x-7 gap-y-2 text-[14px] text-ink/85">
              <span className="inline-flex items-center gap-2">
                <TrendIndicator slope={-0.01} /> — risk falling
              </span>
              <span className="inline-flex items-center gap-2">
                <TrendIndicator slope={0.01} /> — risk rising
              </span>
              <span className="inline-flex items-center gap-2">
                <TrendIndicator slope={0} /> — little change
              </span>
            </div>
            <p className="text-[12.5px] text-muted leading-relaxed mt-3">
              We don&apos;t store a full score history, so the trendline is
              reconstructed from a single slope — a quick read of direction and
              size, not a day-by-day reproduction.
            </p>
          </article>

          <SectionLabel id="how-its-built">How it&apos;s built</SectionLabel>
          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              What the score predicts
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              For each inspection, we ask: in the 180 days that follow, does
              the same food establishment have either a Fail result OR a priority
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
              What the model looks at
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Thirty-six features, all built leak-free from the public record:
            </p>
            <ul className="text-[15px] leading-relaxed mt-3 space-y-2 list-disc pl-5 text-ink/85">
              <li>
                <span className="font-medium">Prior history</span> — counts of
                inspections, failures, priority and core violations across the
                food establishment&apos;s full prior record, plus near-miss and
                visit-trigger history (Pass w/ Conditions, re-inspections,
                complaint visits)
              </li>
              <li>
                <span className="font-medium">Recency &amp; trend</span> — days
                since the last inspection/failure, the previous inspection&apos;s
                outcome, and 365-day rolling failure and violation counts — so
                the model can see a food establishment improving, not just its
              lifetime
                totals
              </li>
              <li>
                <span className="font-medium">Static facility</span> —
                Chicago&apos;s own Risk 1/2/3 classification (a model{" "}
                <span className="font-medium text-ink/80">input</span>, not the
                output risk bands above), license age/history, and the scheduled
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
              Tested on the future, not the past
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Train, validation, and test are carved by date, not shuffled. We{" "}
              <span className="font-medium">train</span> on inspections before
              2024-07, <span className="font-medium">calibrate</span> on
              2024-07 → 2025-07, and <span className="font-medium">test</span>{" "}
              on 2025-07 onward — and every feature at a given inspection is
              computed only from data strictly before it. A random shuffle would
              let the model peek at a food establishment&apos;s future to predict
              its
              past, inflating the score into a number that would never hold up
              in production. The chronological split mirrors how the model is
              actually used: trained on history, scored on what comes next.
            </p>
          </article>

          <SectionLabel id="how-well-it-works">How well it works</SectionLabel>
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
                    <th className="py-2 pr-4 font-medium">Establishments</th>
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

            <div className="mt-5 rounded-md bg-tint/60 px-4 py-3 text-[14px] leading-relaxed text-ink/85">
              <p className="font-medium mb-1.5">
                Reading the two tightest slices
              </p>
              <ul className="space-y-1.5 list-disc pl-5">
                <li>
                  <span className="font-medium">Top 5%</span>
                  {top5
                    ? ` (~${top5.n_flagged.toLocaleString()} food establishments): about ${Math.round(
                        top5.precision * 100,
                      )}% of those visits find a real problem — ${top5.lift.toFixed(
                        1,
                      )}× better than picking at random — and that sliver alone covers ${Math.round(
                        top5.recall * 100,
                      )}% of every problem city-wide.`
                    : " — run the metrics pipeline to populate."}
                </li>
                <li>
                  <span className="font-medium">Top 10%</span>
                  {top10
                    ? ` (~${top10.n_flagged.toLocaleString()} food establishments): roughly ${Math.round(
                        top10.precision * 100,
                      )}% of visits find a problem (${top10.lift.toFixed(
                        1,
                      )}× random), catching about ${Math.round(
                        top10.recall * 100,
                      )}% of all problems.`
                    : ""}
                </li>
              </ul>
              <p className="mt-2 text-[13px] text-muted">
                The tighter the slice, the higher the hit-rate but the fewer
                problems you cover — that&apos;s the precision/recall trade an
                inspection team tunes to its capacity.
              </p>
            </div>
          </article>

          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              Why a score is what it is
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              Per-establishment SHAP attribution — log-odds contributions from
              each feature, summed to recover the model&apos;s logit. The detail
              page surfaces the top drivers, signed so positive contributions
              push risk up and negative contributions push it down.
            </p>

            {/* Global feature impact — which features move the score most,
                averaged over the whole test set. Magnitude only (mean |log-odds|),
                so all bars read the same direction. */}
            <h3 className="text-[1.05rem] font-medium tracking-tight mt-6">
              Which features matter most, overall
            </h3>
            <p className="text-[14px] text-muted leading-relaxed mt-1.5">
              Averaged across every establishment in the test set, this is how
              much each feature moves the prediction — the mean size of its
              log-odds contribution. It says nothing about direction; that&apos;s
              per-establishment.
            </p>
            {importance.length > 0 ? (
              <ul className="mt-4 space-y-3">
                {importance.map((d) => (
                  <li key={d.feature}>
                    {/* Label above its bar so the full feature name always shows
                        — these run long and a fixed column would truncate them. */}
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[13.5px] text-ink/85">{d.label}</span>
                      <span className="num text-[12px] text-muted tabular-nums shrink-0">
                        {d.mean_abs_logodds.toFixed(2)}
                      </span>
                    </div>
                    <span className="mt-1 block h-2.5 rounded-full bg-tint overflow-hidden">
                      <span
                        className="block h-full rounded-full bg-teal/70"
                        style={{
                          width: `${maxImpact > 0 ? (d.mean_abs_logodds / maxImpact) * 100 : 0}%`,
                        }}
                      />
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13.5px] text-muted mt-3">
                Run the metrics pipeline to populate the feature-impact chart.
              </p>
            )}
            <p className="text-[12.5px] text-muted leading-relaxed mt-3">
              Each number is the <span className="font-medium">mean |log-odds|</span>{" "}
              — the feature&apos;s average influence on the model&apos;s internal
              score, counted in either direction. It&apos;s a relative scale
              (bigger = more sway), not a probability or a percentage.
            </p>

            {/* Worked example: how one establishment's calibrated log-odds add
                up to its published probability. Additive in calibrated space, so
                the parts sum exactly to the score on the gauge. */}
            <h3
              id="calibrated-log-odds"
              className="scroll-mt-24 text-[1.05rem] font-medium tracking-tight mt-8"
            >
              A worked example
            </h3>
            <p className="text-[14px] text-muted leading-relaxed mt-1.5">
              For one (anonymised) establishment, here is how the score is built.
              The rows are in{" "}
              <span className="font-medium text-ink/80">calibrated log-odds</span>{" "}
              — the model&apos;s internal additive scale (a running sum, not a
              percentage), adjusted so the total lands on the real-world
              probability. So the base, the drivers, and everything else add up to
              one number, which a sigmoid then turns into the % on the gauge.
            </p>
            {waterfall ? (
              <div className="mt-4 rounded-2xl border border-line bg-card overflow-hidden text-[14px]">
                <WaterfallRow
                  label="Base (model intercept)"
                  value={waterfall.base}
                  muted
                />
                {waterfall.drivers.map((d, i) => (
                  <WaterfallRow key={d.feature + i} label={d.label} value={d.contribution} />
                ))}
                <WaterfallRow
                  label="Everything else (remaining features)"
                  value={waterfall.other}
                  muted
                />
                <WaterfallRow
                  label="Total (calibrated log-odds)"
                  value={waterfall.total}
                  strong
                />
                <div className="flex items-center justify-between px-4 py-3 bg-cream/50">
                  <span className="font-medium">
                    Squashed to a probability (the gauge)
                  </span>
                  <span className="num font-semibold text-terra-strong text-[16px]">
                    {(waterfall.probability * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-[13.5px] text-muted mt-3">
                Run the metrics pipeline to populate the worked example.
              </p>
            )}
            <p className="text-[12.5px] text-muted leading-relaxed mt-3">
              A positive number pushes risk up; a negative number pulls it down.
              The detail page shows the same drivers as bars — this page shows
              the arithmetic behind a single score.
            </p>
          </article>

          <SectionLabel id="limits">Limits</SectionLabel>
          <article>
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              What it doesn&apos;t do
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
                No establishment-level traffic or revenue data — the score
                doesn&apos;t adjust for kitchen volume.
              </li>
              <li>
                Group performance is audited across facility type and ZIP —
                per-group precision, coverage, and ranking quality. No systematic
                unfairness shows up on the coverage lens, though a few small,
                low-event groups dip on the strictest ranking metric (a base-rate
                artifact, not bias). The fuller demographic disparate-impact audit
                — joining census data — is deferred to a later phase, so expect
                uneven calibration where training history is sparse.
              </li>
            </ul>
          </article>

          <SectionLabel id="reference">Reference</SectionLabel>
          <article id="definitions">
            <h2 className="text-[1.5rem] font-medium tracking-tight">
              Definitions
            </h2>
            <p className="text-[15.5px] text-muted leading-relaxed mt-2">
              The recurring terms used across the score, the drivers, and the
              inspection history.
            </p>
            <dl className="mt-4 space-y-4">
              {GLOSSARY_ORDER.map((key) => {
                const entry = GLOSSARY[key];
                return (
                  <div
                    key={entry.id}
                    id={entry.id}
                    className="scroll-mt-24 rounded-2xl border border-line bg-card p-4"
                  >
                    <dt className="font-medium text-ink">{entry.term}</dt>
                    <dd className="text-[14.5px] text-muted leading-relaxed mt-1">
                      {entry.short}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </article>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
