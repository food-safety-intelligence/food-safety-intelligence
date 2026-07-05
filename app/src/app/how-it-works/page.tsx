import {
  ArrowLeft,
  BookMarked,
  BookOpen,
  ClipboardList,
  type LucideIcon,
  MessageSquarePlus,
  ShieldCheck,
  Target,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { TierPill } from "@/components/TierPill";
import { TrendIndicator } from "@/components/TrendIndicator";
import { loadMethodology } from "@/lib/methodology-server";
import { CityGate } from "@/components/CityGate";
import { HowItWorksNyc } from "@/components/HowItWorksNyc";
import { HowItWorksLa } from "@/components/HowItWorksLa";
import { MethodologyHero } from "@/components/HowItWorksCards";
import { GLOSSARY, GLOSSARY_ORDER } from "@/lib/glossary";
import type { RiskTier } from "@/lib/scores";
import { cn } from "@/lib/utils";

/**
 * Human labels for the internal model-family slug stored in methodology.json's
 * `model_version`. An unrecognised slug falls back to the raw value, so the card
 * stays correct — never blank or a stale friendly name — if the served model
 * changes.
 */
const MODEL_TYPE_LABELS: Record<string, string> = {
  xgb_monotone: "Gradient-boosted trees (XGBoost)",
  baseline_logreg: "Logistic regression",
};

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
      <span className={cn("text-sm", strong ? "text-ink font-medium" : "text-ink/85")}>
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
 * A part divider — a numbered, icon-led marker over a hairline that groups the
 * page into "read it / how it's built / how well it works / caveats / reference".
 * The serif numeral and tinted icon give each part a clear visual anchor while
 * staying in the Clinical Quiet palette.
 */
function SectionLabel({
  children,
  id,
  number,
  icon: Icon,
}: {
  children: string;
  id?: string;
  number: string;
  icon: LucideIcon;
}) {
  return (
    <div
      id={id}
      className="scroll-mt-20 pt-9 mt-4 border-t border-line flex items-center gap-4"
    >
      <span className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-sage/12 text-sage shrink-0">
        <Icon className="w-[19px] h-[19px]" strokeWidth={1.75} />
      </span>
      <span className="flex items-baseline gap-3">
        <span className="serif italic text-2xl text-teal/70 leading-none">
          {number}
        </span>
        <span className="text-sage text-xs tracking-[0.18em] uppercase">
          {children}
        </span>
      </span>
    </div>
  );
}

/**
 * A single headline metric in the hero — a big number over a one-line gloss.
 * `accent` colours the figure terra for the one stat we most want to land.
 */
function HeroStat({
  value,
  label,
  accent = false,
}: {
  value: string;
  label: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-line bg-card/70 backdrop-blur px-4 py-3.5 soft-shadow">
      <div
        className={cn(
          "num text-3xl font-medium leading-none",
          accent ? "text-terra-strong" : "text-ink",
        )}
      >
        {value}
      </div>
      <div className="text-xs text-muted mt-1.5 leading-snug">{label}</div>
    </div>
  );
}

export const metadata = {
  title: "How this works · Food Safety",
  description:
    "How the risk score works: what it predicts, what the model looks at, how it's tested, why a score is what it is, and its limits.",
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

  // Model-card provenance — the served model, when its metrics were last built,
  // and the test window — read from methodology.json so the card can never drift
  // from the numbers rendered above it. ISO date sliced to YYYY-MM-DD (the JSON
  // stores a UTC timestamp) to avoid any locale/hydration formatting surprises.
  const modelVersion = methodology.model_version || null;
  const modelType = modelVersion
    ? (MODEL_TYPE_LABELS[modelVersion] ?? modelVersion)
    : null;
  const metricsDate = methodology.generated_at
    ? methodology.generated_at.slice(0, 10)
    : null;
  const testFrom = methodology.test.split_from || null;
  const testN = methodology.test.n || null;

  return (
    <>
      <SiteHeader activeNav="how" />

      {/* max-w-full on mobile (capped to the viewport) so the prose wraps
          instead of forcing a horizontal scroll; overflow-x-clip trims the small
          residual overhang from intrinsic-width content (operating-points table)
          without clipping text. Desktop keeps the 820 reading cap. */}
      <main className="w-full max-w-full lg:max-w-[820px] overflow-x-clip mx-auto px-8 pt-10 pb-24 flex-1">
        <CityGate nyc={<HowItWorksNyc />} la={<HowItWorksLa />}>
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-xs text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>

        {/* Hero band — the shared MethodologyHero card (soft cream→white wash +
            faint sage glow), so Chicago, NYC, and LA open identically. The
            headline metrics sit here as stat cards so the page leads with what
            the model actually does. */}
        <MethodologyHero
          eyebrow="Methodology · Chicago"
          title={<>How this <span className="serif italic text-teal">works</span></>}
          stats={
            <>
              <HeroStat
                value={`${methodology.headline.top_decile_lift.toFixed(1)}×`}
                label="more hits than random, working the top 10% by risk"
                accent
              />
              <HeroStat
                value={methodology.headline.roc_auc.toFixed(2)}
                label="ROC-AUC: ranks venues headed for a fail or priority citation above those that won't"
              />
            </>
          }
        >
          A gradient-boosted decision-tree model (XGBoost) fit on six years
          of Chicago inspection history. The score is a calibrated
          probability that a food establishment will fail an inspection or be
          cited for a priority violation in the next 180 days.
        </MethodologyHero>

        {/* Sticky jump-nav — lets a reader skip to any part without scrolling
            the whole methodology. Plain anchors (server component); deep-links
            like #definitions still work. bg matches the page so content scrolls
            cleanly underneath. */}
        <nav
          aria-label="Sections"
          className="sticky top-0 z-20 -mx-8 mt-8 px-8 py-2.5 bg-cream/85 backdrop-blur border-y border-line flex flex-wrap gap-x-1.5 gap-y-1 text-xs"
        >
          <a
            href="#reading-the-score"
            className="px-2.5 py-1 rounded-full text-muted hover:text-ink hover:bg-tint transition-colors"
          >
            Reading the score
          </a>
          <a
            href="#how-its-built"
            className="px-2.5 py-1 rounded-full text-muted hover:text-ink hover:bg-tint transition-colors"
          >
            How it&apos;s built
          </a>
          <a
            href="#how-well-it-works"
            className="px-2.5 py-1 rounded-full text-muted hover:text-ink hover:bg-tint transition-colors"
          >
            How well it works
          </a>
          <a
            href="#model-card"
            className="px-2.5 py-1 rounded-full text-muted hover:text-ink hover:bg-tint transition-colors"
          >
            Model card
          </a>
          <a
            href="#data-governance"
            className="px-2.5 py-1 rounded-full text-muted hover:text-ink hover:bg-tint transition-colors"
          >
            Data governance
          </a>
          <a
            href="#reference"
            className="px-2.5 py-1 rounded-full text-muted hover:text-ink hover:bg-tint transition-colors"
          >
            Reference
          </a>
        </nav>

        <section className="mt-10 space-y-8">
          <SectionLabel id="reading-the-score" number="01" icon={BookOpen}>
            Reading the score
          </SectionLabel>
          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              How to read a score
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              Every establishment gets one number — a calibrated probability,
              shown as a percentage, that it fails an inspection or draws a
              priority violation in the next 180 days. &ldquo;Calibrated&rdquo;
              means the number is honest about its own odds: across the
              establishments the model scores around 20%, about 1 in 5 actually
              has an event. The map and list summarise that number two ways: a
              risk band and a recent trend. Each score is anchored to the
              establishment&apos;s{" "}
              <span className="font-medium text-ink/80">most recent inspection on
              file</span>{" "}— its{" "}
              <span className="font-medium text-ink/80">current inspection</span>. The
              score is the risk{" "}
              <span className="font-medium text-ink/80">as of that date</span>{" "}
              (shown next to &ldquo;Last inspected&rdquo; on the detail page), not a
              fixed window — so an establishment inspected long ago shows older data
              throughout, not a fresh reading.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Risk bands
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
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
                <div className="flex items-center justify-between gap-4 px-4 py-2 border-b border-line text-xs uppercase tracking-[0.08em] text-sage">
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
                      <span className="w-24 text-right text-sm text-ink/85">
                        {tierRange(t)}
                      </span>
                      {tierShare(t) && (
                        <span className="w-14 text-right text-xs text-muted">
                          {tierShare(t)}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted mt-3">
                Run the metrics pipeline to populate the tier bands.
              </p>
            )}
            <p className="text-xs text-muted leading-relaxed mt-3">
              Bands are fixed cutoffs on the predicted probability, set once
              (decision record 0008) — they don&apos;t shift per establishment.
              &ldquo;Share&rdquo; is the portion of all scored establishments in
              each band: real scores cluster low, so most sit in Low or Moderate
              and only the small Elevated / High slice is the signal worth acting
              on.
            </p>

            <h3
              id="recent-trend"
              className="text-lg font-medium tracking-tight mt-8 scroll-mt-24"
            >
              The recent trend
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              Next to each score, an arrow shows which way risk has been heading
              across the establishment&apos;s recent inspections:
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-x-7 gap-y-2 text-sm text-ink/85">
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
            <p className="text-sm text-muted leading-relaxed mt-3">
              On the detail page this becomes a small chart. Each dot is the{" "}
              <span className="font-medium text-ink/80">trend estimate</span> — the
              forecast model&apos;s 180-day-forward read{" "}
              <span className="font-medium text-ink/80">as of that inspection&apos;s
              date</span>, from 0 to 100, with that visit&apos;s own result removed
              (the pass/fail is in the inspection list below). Hover a dot for its
              date and value. A dashed line marks the headline{" "}
              <span className="font-medium text-ink/80">risk score</span>; because
              that score counts the latest inspection&apos;s result and the trend
              does not, the last dot can sit above or below it. A 2019 dot is what
              the model would have estimated back in 2019, not a guess made in
              hindsight. Only inspections the model can score appear — 2019 onward,
              each with a usable result, up to the five most recent — so a place may
              show just two or three dots.
            </p>
            <p className="text-sm text-muted leading-relaxed mt-2">
              The score and the trend come from{" "}
              <span className="font-medium text-ink/80">two related models</span>.
              The headline score{" "}
              <span className="font-medium text-ink/80">uses the current
              inspection&apos;s own outcome</span>{" "}— whether it passed that day and
              what violations were cited — the strongest signal of near-term risk.
              The trend uses a separate{" "}
              <span className="font-medium text-ink/80">forecast model</span>: the
              same 180-day prediction, but trained{" "}
              <span className="font-medium text-ink/80">without</span>{" "}that outcome.
              That sidesteps a quirk — a failed inspection triggers a required
              re-inspection that usually passes, which would otherwise pull the score
              down and read as &quot;improving&quot; for procedural reasons. So the
              trend shows direction over time, not a second risk number.
            </p>
          </article>

          <SectionLabel id="how-its-built" number="02" icon={Wrench}>
            How it&apos;s built
          </SectionLabel>
          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              What the score predicts
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
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
            <h2 className="text-2xl font-medium tracking-tight">
              What the model looks at
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              Thirty-six features, all built leak-free from the public record:
            </p>
            <ul className="text-md leading-relaxed mt-3 space-y-2 list-disc pl-5 text-ink/85">
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
            <h2 className="text-2xl font-medium tracking-tight">
              How the datasets connect
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              Food Inspections is the backbone — one row per inspection, keyed by the
              establishment&apos;s license number. Business Licenses join on that same
              license number to add license age and history. Everything else is built
              per establishment from its own earlier inspections: every prior-history
              and recency feature looks only at that establishment&apos;s record
              strictly before the inspection being scored. There is no
              cross-establishment or map-proximity join — each place is scored from its
              own history and the current visit.
            </p>
          </article>

          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              The model
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              Gradient-boosted decision trees (XGBoost), shallow (depth-3) with{" "}
              <code className="num text-sm bg-tint px-1.5 py-0.5 rounded">
                monotone constraints
              </code>{" "}
              on the risk-count features, weighted for the ~11% positive rate and
              calibrated with Platt (sigmoid) scaling. On the time-held-out test
              split: PR-AUC{" "}
              {methodology.headline.pr_auc.toFixed(2)}, ROC-AUC{" "}
              {methodology.headline.roc_auc.toFixed(2)}, top-decile lift{" "}
              {methodology.headline.top_decile_lift.toFixed(1)}×.
            </p>
          </article>

          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              Tested on the future, not the past
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
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

          <SectionLabel id="how-well-it-works" number="03" icon={Target}>
            How well it works
          </SectionLabel>
          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              What it catches
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              Inspectors are capacity-limited, so the score is really a ranked
              work-list. The honest read isn&apos;t a single number — it&apos;s
              how much of the real risk you catch at the slice you can actually
              staff:
            </p>
            <div className="mt-4 rounded-2xl border border-line bg-card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="text-left text-sage text-xs tracking-[0.08em] uppercase border-b border-line bg-tint/40">
                      <th className="py-2.5 px-4 font-medium">Inspect top</th>
                      <th className="py-2.5 px-4 font-medium">Establishments</th>
                      <th className="py-2.5 px-4 font-medium">Precision</th>
                      <th className="py-2.5 px-4 font-medium">Events caught</th>
                      <th className="py-2.5 px-4 font-medium">Lift</th>
                    </tr>
                  </thead>
                  <tbody className="num text-ink/85">
                    {methodology.operating_points.map((p) => (
                      <tr
                        key={p.frac}
                        className="border-b border-line last:border-b-0"
                      >
                        <td className="py-2.5 px-4">
                          {Math.round(p.frac * 100)}%
                        </td>
                        <td className="py-2.5 px-4">
                          {p.n_flagged.toLocaleString("en-US")}
                        </td>
                        <td className="py-2.5 px-4">
                          {Math.round(p.precision * 100)}%
                        </td>
                        <td className="py-2.5 px-4">
                          {Math.round(p.recall * 100)}%
                        </td>
                        <td className="py-2.5 px-4">{p.lift.toFixed(1)}×</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <p className="text-xs text-muted leading-relaxed mt-3">
              Working the top 20% by risk surfaces{" "}
              {top20 ? Math.round(top20.recall * 100) : 54}% of the next-180-day
              events — {top20 ? top20.lift.toFixed(1) : "2.7"}× better than
              inspecting a random 20%. Baseline model, time-held-out test from{" "}
              {methodology.test.split_from || "2025-07-01"} onward (n ≈{" "}
              {methodology.test.n
                ? methodology.test.n.toLocaleString("en-US")
                : "7,000"}{" "}
              inspections, {Math.round(methodology.test.prevalence * 100) || 11}%
              with an event). &ldquo;Lift&rdquo; is precision divided by that
              base rate.
            </p>

            <p className="text-md text-muted leading-relaxed mt-4">
              These are also the two numbers we{" "}
              <span className="text-ink/85">select</span> the model on:{" "}
              <span className="text-ink/85">PR-AUC</span> and{" "}
              <span className="text-ink/85">precision in the top 10%</span>, both
              measured on this held-out split and required to hold up under
              expanding-window cross-validation before a model is promoted. Lift
              and ROC-AUC describe how well the chosen model works; these two are
              how it was chosen.
            </p>

            <div className="mt-5 rounded-md bg-tint/60 px-4 py-3 text-sm leading-relaxed text-ink/85">
              <p className="font-medium mb-1.5">
                Reading the two tightest slices
              </p>
              <ul className="space-y-1.5 list-disc pl-5">
                <li>
                  <span className="font-medium">Top 5%</span>
                  {top5
                    ? ` (~${top5.n_flagged.toLocaleString("en-US")} food establishments): about ${Math.round(
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
                    ? ` (~${top10.n_flagged.toLocaleString("en-US")} food establishments): roughly ${Math.round(
                        top10.precision * 100,
                      )}% of visits find a problem (${top10.lift.toFixed(
                        1,
                      )}× random), catching about ${Math.round(
                        top10.recall * 100,
                      )}% of all problems.`
                    : ""}
                </li>
              </ul>
              <p className="mt-2 text-xs text-muted">
                The tighter the slice, the higher the hit-rate but the fewer
                problems you cover — that&apos;s the precision/recall trade an
                inspection team tunes to its capacity.
              </p>
            </div>
          </article>

          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              Why a score is what it is
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              Per-establishment SHAP attribution — log-odds contributions from
              each feature, summed to recover the model&apos;s logit. The detail
              page surfaces the top drivers, signed so positive contributions
              push risk up and negative contributions push it down.
            </p>

            {/* Global feature impact — which features move the score most,
                averaged over the whole test set. Magnitude only (mean |log-odds|),
                so all bars read the same direction. */}
            <h3 className="text-lg font-medium tracking-tight mt-6">
              Which features matter most, overall
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
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
                      <span className="text-sm text-ink/85">{d.label}</span>
                      <span className="num text-xs text-muted tabular-nums shrink-0">
                        {d.mean_abs_logodds.toFixed(2)}
                      </span>
                    </div>
                    <span className="mt-1 block h-2.5 rounded-full bg-tint overflow-hidden">
                      <span
                        className="block h-full rounded-full"
                        style={{
                          width: `${maxImpact > 0 ? (d.mean_abs_logodds / maxImpact) * 100 : 0}%`,
                          background:
                            "linear-gradient(90deg, var(--color-teal), var(--color-sage))",
                        }}
                      />
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted mt-3">
                Run the metrics pipeline to populate the feature-impact chart.
              </p>
            )}
            <p className="text-xs text-muted leading-relaxed mt-3">
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
              className="scroll-mt-24 text-lg font-medium tracking-tight mt-8"
            >
              A worked example
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              For one (anonymised) establishment, here is how the score is built.
              The rows are in{" "}
              <span className="font-medium text-ink/80">calibrated log-odds</span>{" "}
              — the model&apos;s internal additive scale (a running sum, not a
              percentage), adjusted so the total lands on the real-world
              probability. So the base, the drivers, and everything else add up to
              one number, which a sigmoid then turns into the % on the gauge.
            </p>
            {waterfall ? (
              <div className="mt-4 rounded-2xl border border-line bg-card overflow-hidden text-sm">
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
                  <span className="num font-semibold text-terra-strong text-lg">
                    {(waterfall.probability * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted mt-3">
                Run the metrics pipeline to populate the worked example.
              </p>
            )}
            <p className="text-xs text-muted leading-relaxed mt-3">
              A positive number pushes risk up; a negative number pulls it down.
              The detail page shows the same drivers as bars — this page shows
              the arithmetic behind a single score.
            </p>
          </article>

          <SectionLabel id="model-card" number="04" icon={ClipboardList}>
            Model card
          </SectionLabel>
          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              What this model is for
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              A model card gathers, in one place, who the model is for, how it was
              tested, where it falls short, and how it&apos;s kept up to date. The
              points below restate and link to the fuller detail elsewhere on this
              page. It covers <span className="font-medium text-ink/80">two
              models</span> — the risk score and a separate trend forecast,
              introduced just below.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-8">
              The two models
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              The product ships two models, trained together. One produces the
              headline score; the other drives the trend.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-line bg-card p-4">
                <p className="text-xs uppercase tracking-[0.08em] text-sage font-medium">
                  Model 1 · Risk score
                </p>
                <p className="text-sm text-muted leading-relaxed mt-2">
                  The headline percentage — the chance of a Fail or priority
                  violation in the next 180 days. It uses the current
                  inspection&apos;s own outcome, the strongest near-term signal. The
                  model details and evaluation on this card describe this model.
                </p>
              </div>
              <div className="rounded-2xl border border-line bg-card p-4">
                <p className="text-xs uppercase tracking-[0.08em] text-sage font-medium">
                  Model 2 · Trend forecast
                </p>
                <p className="text-sm text-muted leading-relaxed mt-2">
                  Drives the trend arrow and chart. It predicts the same 180-day
                  risk but <span className="font-medium text-ink/80">ignores the
                  current inspection&apos;s own pass/fail</span>, so a failed visit
                  and its mandated re-inspection don&apos;t read as a swing. It is
                  used only to show direction over time; it never sets the risk
                  score.
                </p>
              </div>
            </div>

            {/* Provenance strip — the served risk-score model's type, when its
                metrics were built, and the test window, read from methodology.json
                so the card can't drift from the numbers above it. The internal
                model slug is mapped to a human label via MODEL_TYPE_LABELS. */}
            {(modelType || metricsDate || testFrom) && (
              <>
                <p className="mt-6 text-xs uppercase tracking-[0.08em] text-sage font-medium">
                  Risk-score model
                </p>
                <dl className="mt-2 rounded-2xl border border-line bg-card overflow-hidden text-sm">
                  {modelType && (
                    <div className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-line last:border-b-0">
                      <dt className="text-muted">Model type</dt>
                      <dd className="text-ink/85">{modelType}</dd>
                    </div>
                  )}
                  {metricsDate && (
                    <div className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-line last:border-b-0">
                      <dt className="text-muted">Metrics generated</dt>
                      <dd className="num text-ink/85">{metricsDate}</dd>
                    </div>
                  )}
                  {testFrom && (
                    <div className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-line last:border-b-0">
                      <dt className="text-muted">Tested on</dt>
                      <dd className="num text-ink/85">
                        inspections from {testFrom} onward
                        {testN ? ` (n ${testN.toLocaleString("en-US")})` : ""}
                      </dd>
                    </div>
                  )}
                </dl>
              </>
            )}

            <h3 className="text-lg font-medium tracking-tight mt-8">
              Intended users
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              The model is built for the people who plan food-safety inspections —
              a public-health department or inspection team deciding where limited
              inspector time should go. The web app opens the same signal to the
              public for transparency, but the model is designed as decision
              support for inspection planning, not a consumer safety rating.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Intended use
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              Prioritisation. The score ranks food establishments by their risk of
              failing an inspection or drawing a priority violation in the next 180
              days, so a capacity-limited team can work the riskiest places first.
              It is a triage signal that routes a human inspector — the value is in
              the ranking, not in any single establishment&apos;s number.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Out-of-scope uses
            </h3>
            <ul className="text-sm leading-relaxed mt-2 space-y-2 list-disc pl-5 text-ink/85">
              <li>
                <span className="font-medium">Not a verdict.</span> A high score is
                not a finding that an establishment is unsafe or dirty — most
                flagged places do not actually have an event in the window.
              </li>
              <li>
                <span className="font-medium">Not an enforcement or licensing
                input.</span> It should not be used on its own to fine, close, deny
                a licence, or otherwise penalise a business without a human
                inspection.
              </li>
              <li>
                <span className="font-medium">Not a live diner guarantee.</span> It
                does not tell a diner whether a specific meal is safe right now.
              </li>
              <li>
                <span className="font-medium">Not another city.</span> It is trained
                only on Chicago data and is not validated anywhere else.
              </li>
              <li>
                <span className="font-medium">Not automated action.</span> No
                decision should be taken from the score without a person in the
                loop.
              </li>
            </ul>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              How the models are evaluated
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              The <span className="font-medium text-ink/80">risk score</span> is
              measured on a time-held-out test set, never a random shuffle: the
              model is trained on the earliest inspections, calibrated on a later
              held-out slice, and tested on the most recent window ({testFrom ||
              "2025-07-01"} onward) — with every feature computed only from data
              strictly before the inspection it describes.
              We report ranked-work-list metrics at the operating points a team
              would actually staff — precision, coverage, and lift by top-K —
              rather than one headline number, and a retrained model is promoted
              only if it holds up on <span className="font-medium">both</span>{" "}
              precision–recall and ROC area, not just one. The full table and a
              worked example are under{" "}
              <a href="#how-well-it-works" className="text-teal hover:underline">
                How well it works
              </a>
              .
            </p>

            <p className="text-sm text-muted leading-relaxed mt-2">
              The <span className="font-medium text-ink/80">trend forecast</span> is
              judged differently — as direction over time, not a second risk number.
              We publish it for coverage and transparency, but the loose{" "}
              <span className="font-medium text-ink/80">improving / worsening /
              stable</span> direction is descriptive: on its own it barely beats
              chance. Only a strict slice — steeply rising{" "}
              <span className="font-medium text-ink/80">and</span> currently clean —
              carries a real forward signal, and that slice is treated as an
              early-warning watch-list, never a verdict. How it reads on the page is
              under{" "}
              <a href="#recent-trend" className="text-teal hover:underline">
                The recent trend
              </a>
              .
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Fairness testing
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              Group performance is checked across facility type and ZIP — precision,
              coverage, and ranking quality per group — and the known proxy features
              were removed: ZIP and facility type were dropped so the model keys on
              an establishment&apos;s own conduct, not who-lives-where. Any
              demographic data is used only to audit disparate impact, never as a
              model input. Known residual risks — a detection feedback loop in the
              prior-history and current-outcome signals, geographic miscalibration
              where history is sparse, and unstable metrics for very small groups —
              are documented, and a fuller demographic disparate-impact audit is
              planned before any real deployment.
            </p>

            <h3
              id="limits"
              className="scroll-mt-24 text-lg font-medium tracking-tight mt-6"
            >
              Limitations
            </h3>
            <ul className="text-sm leading-relaxed mt-2 space-y-2 list-disc pl-5 text-ink/85">
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

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Retraining policy
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              Both models are retrained together, on demand — when new data or a
              feature change warrants it — not on a fixed automatic schedule; there
              is no live or streaming update. Each training run is tied to the exact code that
              produced it (its commit is recorded with the run), and a retrained
              model replaces the served one only after it clears the promotion gate
              on the held-out test set. Saved model files are versioned and never
              overwritten, so any published score set can be traced back to the
              model and data that produced it. The risk-score model&apos;s type and
              the date its metrics were generated are shown at the top of this card.
            </p>
          </article>

          <SectionLabel id="data-governance" number="05" icon={ShieldCheck}>
            Data governance
          </SectionLabel>
          <article>
            <h2 className="text-2xl font-medium tracking-tight">
              Where the data comes from and how it&apos;s handled
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
              Every input is a public record from the Chicago Open Data portal.
              The app itself collects nothing from the people who visit it — no
              accounts, no login, no personal data — so the governance questions
              below are mostly about public business records, not private user
              data.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-8">
              Data sources &amp; retention
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              The inputs are Chicago&apos;s public Food Inspections and Business
              Licenses datasets. We keep a cached copy of
              the fields needed to build features and scores for as long as the
              product is maintained; it is refreshed in place rather than kept as a
              growing archive of dated snapshots. Because no visitor data is
              gathered, there is no personal information to retain.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Deletion policy
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              The app stores no visitor or user data, so there is nothing personal
              to delete. The establishment records it shows are public
              business-inspection records — not ours to erase; they mirror the
              city&apos;s source and change only when the city&apos;s record
              changes. Cached working files and each published score set can be
              regenerated from scratch from the public source at any time, and each
              publish replaces the previous served score file rather than keeping a
              back-history.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Storage &amp; security
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              Scores are published as static JSON and served through a
              content-delivery network. The website is read-only static pages with
              no login and no server-side database, and it never runs the model on a
              page load — it only ever reads the pre-computed JSON (the
              batch-score-to-JSON contract). Source and working data sit in a
              private cloud-storage bucket that is not publicly readable or
              writable; access is limited to the project team&apos;s own
              credentials. Because the site holds no user data and does no live
              computation, its exposure surface is a set of public-record JSON
              files.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Handling of updated source data
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              Chicago updates its inspection and licence records continuously
              — new inspections, late-arriving results, and corrections to old ones.
              We do not read the city&apos;s feed live; instead we re-pull it and
              re-score in a batch job, then publish a fresh JSON. The scores you see
              are a snapshot as of the last publish — the detail page shows each
              establishment&apos;s &ldquo;as of&rdquo; date — not a live reading.
              When the city corrects or adds a record, the next batch run picks it
              up; the ingest resumes from where it left off rather than re-pulling
              the whole history.
            </p>

            <h3 className="text-lg font-medium tracking-tight mt-6">
              Use and retention of location data
            </h3>
            <p className="text-sm text-muted leading-relaxed mt-1.5">
              The only location data is the establishment&apos;s own address and map
              coordinates, taken straight from the public inspection record — it
              locates a business, not a person. We use it to place the establishment
              on the map and include it in the published JSON. The app never asks
              for, collects, or stores a visitor&apos;s location — there is no
              geolocation prompt and no device tracking. Establishment coordinates
              are retained on the same terms as the rest of the public record.
            </p>
          </article>

          <SectionLabel id="reference" number="06" icon={BookMarked}>
            Reference
          </SectionLabel>
          <article id="definitions">
            <h2 className="text-2xl font-medium tracking-tight">
              Definitions
            </h2>
            <p className="text-md text-muted leading-relaxed mt-2">
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
                    <dd className="text-sm text-muted leading-relaxed mt-1">
                      {entry.short}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </article>
        </section>
        </CityGate>

        {/* Feedback CTA — readers who reach the end of the methodology are the
            most engaged, so invite a note here alongside the footer link.
            Outside CityGate so both Chicago and NYC readers see it. */}
        <aside className="mt-12 rounded-3xl border border-line bg-tint p-7 flex flex-col sm:flex-row sm:items-center gap-5 justify-between">
          <div>
            <h2 className="text-xl font-medium tracking-tight">
              Was this useful?
            </h2>
            <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[52ch]">
              If something here is wrong, unclear, or missing, tell us — it goes
              straight to the team.
            </p>
          </div>
          <Link
            href="/feedback?source=how-it-works"
            className="shrink-0 inline-flex items-center gap-2 px-5 py-3 rounded-full bg-ink text-cream text-base font-medium hover:bg-teal transition-colors min-h-[44px]"
          >
            <MessageSquarePlus className="w-4 h-4" strokeWidth={2} />
            Give feedback
          </Link>
        </aside>
      </main>

      <SiteFooter />
    </>
  );
}
