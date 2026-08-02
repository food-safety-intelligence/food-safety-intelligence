"use client";

// NYC-specific "how it works" content, driven by nyc/methodology.json (DR 0016).
// Mirrors the Chicago page's structure + formatting (hero + stat cards, sticky
// jump-nav, numbered sections, TierPill bands, a worked calibrated-log-odds
// example, and a Reference/definitions list) with NYC-accurate content.

import {
  BookMarked,
  BookOpen,
  type LucideIcon,
  Target,
  Wrench,
} from "lucide-react";
import { ChronologicalSplit, ModelCard, DataGovernance, FeatureGroups, type FeatureGroup, MethodologyHero, OperatingPointsTable, TightestSlices, useChicagoHeadline } from "@/components/HowItWorksCards";
import { useEffect, useState } from "react";
import { dataUrl } from "@/lib/city";
import { glossaryFor } from "@/lib/glossary";
import type { DateWindow } from "@/lib/methodology-server";
import type { RiskTier } from "@/lib/scores";
import { TierPill } from "@/components/TierPill";
import { cn } from "@/lib/utils";

interface NycMethodology {
  data_source: string;
  train_window: string;
  test: { n: number; prevalence: number; events: number; split_from: string };
  windows?: { train: DateWindow; val: DateWindow; test: DateWindow };
  headline: { pr_auc: number; roc_auc: number; top_decile_lift: number };
  risk_tiers: { label: string; min: number; max: number | null; share: number }[];
  operating_points: { frac: number; n_flagged: number; precision: number; recall: number; lift: number; events_caught: number }[];
}

function SectionLabel({ children, id, number, icon: Icon }: {
  children: string; id?: string; number: string; icon: LucideIcon;
}) {
  return (
    <div id={id} className="scroll-mt-20 pt-9 mt-4 border-t border-line flex items-center gap-4">
      <span className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-sage/12 text-sage shrink-0">
        <Icon className="w-[19px] h-[19px]" strokeWidth={1.75} />
      </span>
      <span className="flex items-baseline gap-3">
        <span className="serif italic text-2xl text-teal/70 leading-none">{number}</span>
        <span className="text-sage text-xs tracking-[0.18em] uppercase">{children}</span>
      </span>
    </div>
  );
}

function HeroStat({ value, label, accent = false }: { value: string; label: string; accent?: boolean }) {
  return (
    <div className="rounded-2xl border border-line bg-card/70 backdrop-blur px-4 py-3.5 soft-shadow">
      <div className={`num text-3xl font-medium leading-none ${accent ? "text-terra-strong" : "text-ink"}`}>
        {value}
      </div>
      <div className="text-xs text-muted mt-1.5 leading-snug">{label}</div>
    </div>
  );
}

// One row of the worked calibrated-log-odds waterfall (mirrors Chicago's).
function WaterfallRow({ label, value, muted = false, strong = false }: {
  label: string; value: number; muted?: boolean; strong?: boolean;
}) {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  const color = muted ? "text-muted" : value > 0 ? "text-terra-strong" : value < 0 ? "text-sage-strong" : "text-muted";
  return (
    <div className={cn("flex items-center justify-between gap-3 px-4 py-2.5 border-b border-line", strong && "bg-tint/50")}>
      <span className={cn("text-sm", strong ? "text-ink font-medium" : "text-ink/85")}>{label}</span>
      <span className={cn("num tabular-nums shrink-0", strong ? "text-ink font-semibold" : color)}>
        {sign}{Math.abs(value).toFixed(2)}
      </span>
    </div>
  );
}

const NAV = [
  ["reading-the-score", "Reading the score"],
  ["how-its-built", "How it's built"],
  ["how-well-it-works", "How well it works"],
  ["model-card", "Model card"],
  ["data-governance", "Data governance"],
  ["reference", "Reference"],
];


// The model's inputs, grouped for the "What the model looks at" list. Counts are
// from the served artifact's feature list (nyc_xgb_sigmoid: 32) and sum to it.
const NYC_FEATURE_GROUPS: FeatureGroup[] = [
  {
    name: "Prior history",
    count: 5,
    detail:
      "how many inspections the establishment has on record, how many were graded B or C, its prior critical-violation count, and its average past score and past B/C rate",
  },
  {
    name: "Recency & previous visit",
    count: 3,
    detail:
      "days since the last inspection, plus the previous inspection's score and whether it was B or C, so the model sees direction and not just lifetime totals",
  },
  {
    name: "Establishment record",
    count: 2,
    detail:
      "how long the establishment has been in the inspection record, and how many times it has previously been closed",
  },
  {
    name: "Prior violation severity",
    count: 3,
    detail:
      "counts of past violations at each severity tier (imminent-hazard, critical, general), mapped from DOHMH codes via the shared violation dictionary",
  },
  {
    name: "Current inspection outcome",
    count: 5,
    detail:
      "this visit's own score, total and critical violation counts, whether it landed in the B/C range, and whether it resulted in a closure",
  },
  {
    name: "Current violation severity",
    count: 3,
    detail: "this visit's violations counted at each of the three severity tiers",
  },
  {
    name: "Current violation themes",
    count: 11,
    detail:
      "this visit's violations counted by plain-language theme (temperature control, pest/vermin, pest-proofing, hygiene and handwashing, cross-contamination, food-contact surfaces, plumbing and sewage, approved source, equipment, management certification, administrative)",
  },
];

export function HowItWorksNyc() {
  const [m, setM] = useState<NycMethodology | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(dataUrl("nyc", "methodology.json"))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: NycMethodology) => alive && setM(d))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const prevPct = m ? Math.round(m.test.prevalence * 100) : 41;
  // Chicago's numbers come from its own methodology.json, not the copy.
  const chi = useChicagoHeadline();

  return (
    <div>
      <MethodologyHero
        eyebrow="Methodology · New York City"
        title={<>How this <span className="serif italic text-teal">works</span></>}
        stats={
          <>
            <HeroStat accent value={m ? `${m.headline.top_decile_lift.toFixed(1)}×` : "—"} label="more hits than random, working the top 10% by predicted risk" />
            <HeroStat value={m ? m.headline.roc_auc.toFixed(2) : "—"} label="ROC-AUC: ranks venues headed for a B or C grade above those that won't" />
          </>
        }
      >
        New York City is a second city, added to show the same tool works beyond
        Chicago. Each score is a calibrated probability that an establishment&apos;s{" "}
        <strong className="text-ink font-medium">next inspection is graded B or C</strong>{" "}
        under New York&apos;s letter-grade system: the same batch-scored-to-JSON
        pipeline, calibrated model, and SHAP drivers as Chicago, on New York data.
      </MethodologyHero>

      {/* Sticky jump-nav */}
      <nav
        aria-label="Sections"
        className="sticky top-0 z-20 -mx-8 mt-8 px-8 py-2.5 bg-cream/85 backdrop-blur border-y border-line flex flex-wrap gap-x-1.5 gap-y-1 text-xs"
      >
        {NAV.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="px-2.5 py-1 rounded-full text-muted hover:text-ink hover:bg-tint transition-colors">
            {label}
          </a>
        ))}
      </nav>

      {/* 01 — Reading the score */}
      <div className="mt-6 space-y-8">
        <SectionLabel id="reading-the-score" number="01" icon={BookOpen}>Reading the score</SectionLabel>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">The letter-grade label</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            Every NYC inspection produces a numeric <em>score</em>: the sum of
            points across cited violations (public-health hazards ≥ 7 points,
            critical ≥ 5, general ≥ 2). Lower is cleaner. The score maps to a
            letter grade: <strong className="text-ink">A = 0–13, B = 14–27, C = 28+</strong>.
            The model predicts whether the <em>next</em> inspection lands at B or C
            (score ≥ 14). In the test window, {prevPct}% of next inspections were B/C.
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">Risk bands</h2>
          <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
            The percentage is bucketed into four bands, the coloured badges on the
            map, list, and detail pages. They&apos;re recalibrated to NYC&apos;s own
            distribution: NYC&apos;s base rate is far higher than Chicago&apos;s, so
            Chicago&apos;s cutoffs wouldn&apos;t transfer.
          </p>
          {m && (
            <div className="mt-4 rounded-2xl border border-line bg-card overflow-hidden max-w-[62ch]">
              <div className="flex items-center justify-between gap-4 px-4 py-2 border-b border-line text-xs uppercase tracking-[0.08em] text-sage">
                <span>Tier</span>
                <span className="flex items-center gap-4">
                  <span className="w-24 text-right">Score</span>
                  <span className="w-14 text-right">Share</span>
                </span>
              </div>
              {m.risk_tiers.map((t) => (
                <div key={t.label} className="flex items-center justify-between gap-4 px-4 py-3 border-b border-line last:border-b-0">
                  <TierPill tier={t.label as RiskTier} />
                  <span className="flex items-center gap-4 num tabular-nums">
                    <span className="w-24 text-right text-sm text-ink/85">
                      {t.min.toFixed(2)}–{t.max === null ? "1.00" : t.max.toFixed(2)}
                    </span>
                    <span className="w-14 text-right text-xs text-muted">{(t.share * 100).toFixed(0)}%</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </article>
        <article>
          <h2 id="recent-trend" className="scroll-mt-24 text-2xl font-medium tracking-tight">The recent-trend chart</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            Each detail page plots a forecast-only model&apos;s score across the
            establishment&apos;s recent inspections, and reads the slope of the last
            few visits as Improving / Worsening / Stable. Because NYC inspects on a
            roughly annual cycle, most places have only a handful of scored visits,
            so the trend is sparser than Chicago&apos;s and often reads
            &ldquo;insufficient history.&rdquo; It is a descriptive read of the
            trajectory, not a separate prediction.
          </p>
        </article>
      </div>

      {/* 02 — How it's built */}
      <div className="mt-10 space-y-8">
        <SectionLabel id="how-its-built" number="02" icon={Wrench}>How it&apos;s built</SectionLabel>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">What the score predicts</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            For each inspection we ask: at this establishment&apos;s <em>next</em>{" "}
            inspection, is the grade B or C (score 14 or more)? Unlike Chicago&apos;s
            fixed 180-day window, the NYC label is anchored to the next inspection
            whenever it occurs, because NYC&apos;s roughly annual cadence leaves a
            short fixed window empty. Source:{" "}
            {m?.data_source ?? "NYC DOHMH Restaurant Inspection Results"}. Training
            window: {m?.train_window ?? "post-COVID, 2022 onward"}. Inspections halted
            in the 2020 COVID shutdown, so earlier data isn&apos;t comparable (the
            analog of Chicago&apos;s 2019 cutoff).
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">What the model looks at</h2>
          <FeatureGroups total={32} groups={NYC_FEATURE_GROUPS} />
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">How the datasets connect</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            Everything comes from a single DOHMH feed, so unlike Chicago there is no
            cross-dataset join: inspections and their violation rows arrive together,
            keyed by the establishment&apos;s record id. Every prior-history and
            recency feature looks only at that establishment&apos;s own earlier
            inspections, strictly before the one being scored. There is no
            cross-establishment or map-proximity join. Cuisine is deliberately left
            out, along with any demographic proxy.
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">The model</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            A gradient-boosted tree model (XGBoost, depth-3) with sigmoid (Platt)
            calibration. The per-establishment SHAP driver breakdown and the
            calibrated-log-odds waterfall on each detail page show which factors
            moved the score. Scores are computed in a batch job and written to JSON;
            the site never calls a model at request time.
            {m ? (
              <>
                {" "}On the time-held-out test split: PR-AUC{" "}
                {m.headline.pr_auc.toFixed(2)}, ROC-AUC{" "}
                {m.headline.roc_auc.toFixed(2)}, top-decile lift{" "}
                {m.headline.top_decile_lift.toFixed(1)}×.
              </>
            ) : null}
          </p>
        </article>
        <ChronologicalSplit windows={m?.windows} />
      </div>

      {/* 03 — How well it works */}
      <div className="mt-10 space-y-8">
        <SectionLabel id="how-well-it-works" number="03" icon={Target}>How well it works</SectionLabel>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">What it catches</h2>
          {m && (
            <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
              Inspectors are capacity-limited, so the score is really a ranked
              work-list. The honest read isn&apos;t a single number. It&apos;s how
              much of the real risk you catch at the slice you can actually staff.
              NYC&apos;s signal is weaker than Chicago&apos;s (ROC-AUC{" "}
              {m.headline.roc_auc.toFixed(2)}
              {chi ? ` vs ${chi.roc_auc.toFixed(2)}` : ""}), so it stays a preview:
            </p>
          )}
          {m && <OperatingPointsTable ops={m.operating_points} />}
          {m && (
            <p className="text-xs text-muted leading-relaxed mt-3">
              Working the top 20% by risk surfaces{" "}
              {Math.round((m.operating_points.find((p) => p.frac === 0.2)?.recall ?? 0) * 100)}% of
              the next B/C inspections,{" "}
              {(m.operating_points.find((p) => p.frac === 0.2)?.lift ?? 0).toFixed(1)}× better than
              inspecting a random 20%. Time-held-out test from {m.test.split_from} onward (n ≈{" "}
              {m.test.n.toLocaleString()}, {prevPct}% graded B/C). &ldquo;Lift&rdquo; is precision
              divided by that base rate.
            </p>
          )}
          {m && (
            <p className="text-muted leading-[1.7] mt-4 max-w-[62ch]">
              These are also the two numbers we{" "}
              <span className="text-ink">select</span> the model on:{" "}
              <span className="text-ink">PR-AUC</span> and{" "}
              <span className="text-ink">precision in the top 10%</span>, on the
              held-out split. Lift and ROC-AUC describe how well the chosen model
              works; these two are how it was chosen.
            </p>
          )}
          {m && (
            <TightestSlices
              top5={m.operating_points.find((p) => p.frac === 0.05)}
              top10={m.operating_points.find((p) => p.frac === 0.1)}
              unit="establishments"
            />
          )}
          {m && (
            <dl className="mt-6 grid gap-2.5 sm:grid-cols-2 max-w-[62ch] text-sm">
              <div className="rounded-xl border border-line bg-card px-3.5 py-2.5">
                <dt className="font-medium text-ink">ROC-AUC {m.headline.roc_auc.toFixed(2)}</dt>
                <dd className="text-muted leading-snug mt-0.5">How often it ranks a B/C inspection above one that isn&apos;t. Base-rate-independent, so it&apos;s the fair way to compare NYC with Chicago and LA, and it shows NYC is the weakest of the three.</dd>
              </div>
              <div className="rounded-xl border border-line bg-card px-3.5 py-2.5">
                <dt className="font-medium text-ink">PR-AUC {m.headline.pr_auc.toFixed(2)}</dt>
                <dd className="text-muted leading-snug mt-0.5">Ranking quality for the B/C class. Its floor is the {prevPct}% base rate. NYC&apos;s is high, so this number looks strong but mostly reflects how common B/C is, not skill. Don&apos;t compare it to Chicago&apos;s PR-AUC.</dd>
              </div>
              <div className="rounded-xl border border-line bg-card px-3.5 py-2.5">
                <dt className="font-medium text-ink">Top-decile lift {m.headline.top_decile_lift.toFixed(1)}×</dt>
                <dd className="text-muted leading-snug mt-0.5">Work the top 10% by predicted risk and you find {m.headline.top_decile_lift.toFixed(1)}× as many B/C inspections as picking at random.</dd>
              </div>
              <div className="rounded-xl border border-line bg-card px-3.5 py-2.5">
                <dt className="font-medium text-ink">Base rate {prevPct}%</dt>
                <dd className="text-muted leading-snug mt-0.5">Share of next inspections that are actually B/C: what &ldquo;random&rdquo; and the PR-AUC floor are measured against.</dd>
              </div>
            </dl>
          )}
        </article>
        <article>
          <h2 id="calibrated-log-odds" className="scroll-mt-24 text-2xl font-medium tracking-tight">
            Why a score is what it is
          </h2>
          <p className="text-md text-muted leading-relaxed mt-2 max-w-[62ch]">
            Per-establishment SHAP attribution: signed log-odds contributions from
            each feature, summed and squashed to recover the probability on the
            gauge. The detail page surfaces the top drivers; here is how they add up
            for one real high-risk establishment (risk score 84).
          </p>
          <div className="mt-4 rounded-2xl border border-line bg-card overflow-hidden max-w-[62ch]">
            <WaterfallRow label="Base rate (model intercept)" value={-0.46} muted />
            <WaterfallRow label="15 critical violations in prior inspections" value={0.64} />
            <WaterfallRow label="Past B/C rate: 1.0" value={0.37} />
            <WaterfallRow label="8 prior imminent-hazard-tier violations" value={0.37} />
            <WaterfallRow label="3 prior inspections on record" value={-0.35} />
            <WaterfallRow label="10 prior critical-tier violations" value={0.28} />
            <WaterfallRow label="Everything else (remaining features)" value={0.81} muted />
            <WaterfallRow label="Total (calibrated log-odds)" value={1.66} strong />
            <div className="flex items-center justify-between gap-3 px-4 py-2.5 bg-tint/50">
              <span className="text-sm text-ink font-medium">Squashed to a probability (the gauge)</span>
              <span className="num text-terra-strong font-semibold">84.1%</span>
            </div>
          </div>
          <p className="text-xs text-muted leading-relaxed mt-3 max-w-[62ch]">
            Rows are in <span className="font-medium text-ink/80">calibrated log-odds</span>:
            additive in that space, so they sum exactly to the total, and a sigmoid
            turns the total into the probability shown on the gauge.
          </p>
        </article>
      </div>

      {/* 04 — Model card (Limitations folded in, like Chicago) */}
      <ModelCard
        city="nyc"
        m={m}
        number="04"
        limitations={
          <div className="space-y-4 text-muted leading-[1.7]">
            <p>
              <strong className="text-ink">NYC is a coverage feature, not a quality
              upgrade.</strong> Its signal is weaker than Chicago&apos;s
              {m && chi ? (
                <>
                  {" "}(ROC-AUC {m.headline.roc_auc.toFixed(2)} vs{" "}
                  {chi.roc_auc.toFixed(2)}; lift {m.headline.top_decile_lift.toFixed(1)}× vs{" "}
                  {chi.top_decile_lift.toFixed(1)}×)
                </>
              ) : null}
              , so treat NYC scores as a rougher guide.
            </p>
            <p>
              <strong className="text-ink">The data window is shallow.</strong> Only
              ~3 years are usable (inspections restarted after the 2020 COVID pause,
              and the open-data feed keeps a rolling ~3-year window), so
              per-establishment history is thin and the trend chart is sparser than
              Chicago&apos;s.
            </p>
            <p>
              <strong className="text-ink">It is a risk signal, not a verdict.</strong>{" "}
              A high score doesn&apos;t mean a place is unsafe today. It means its
              record resembles establishments that went on to be graded B or C. Use
              it for prioritisation, not judgement.
            </p>
          </div>
        }
      />

      {/* 05 — Data governance */}
      <DataGovernance city="nyc" m={m} number="05" />

      {/* 06 — Reference */}
      <div className="mt-10 space-y-8">
        <SectionLabel id="reference" number="06" icon={BookMarked}>Reference</SectionLabel>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">Definitions</h2>
          <p className="text-md text-muted leading-relaxed mt-2 max-w-[62ch]">
            The recurring terms used across the score, the drivers, and the
            inspection history.
          </p>
          <dl className="mt-4 space-y-4 max-w-[62ch]">
            {glossaryFor("nyc").map((entry) => (
              <div key={entry.id} id={entry.id} className="scroll-mt-24 rounded-2xl border border-line bg-card p-4">
                <dt className="font-medium text-ink">{entry.term}</dt>
                <dd className="text-sm text-muted leading-relaxed mt-1">{entry.short}</dd>
              </div>
            ))}
          </dl>
        </article>
      </div>
    </div>
  );
}
