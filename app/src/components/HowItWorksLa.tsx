"use client";

// LA-specific "how it works" content, driven by la/methodology.json (DR 0016).
// Mirrors the Chicago page's structure + formatting (hero + stat cards, sticky
// jump-nav, numbered sections, TierPill bands, a worked calibrated-log-odds
// example, and a Reference/definitions list) with LA-accurate content. LA's big
// difference: grades run the OPPOSITE way (A = 90-100, higher is cleaner).

import {
  BookMarked,
  BookOpen,
  type LucideIcon,
  Target,
  Wrench,
} from "lucide-react";
import { useEffect, useState } from "react";
import { dataUrl } from "@/lib/city";
import type { RiskTier } from "@/lib/scores";
import { TierPill } from "@/components/TierPill";
import { ModelCard, DataGovernance, MethodologyHero } from "@/components/HowItWorksCards";
import { cn } from "@/lib/utils";

interface LaMethodology {
  data_source: string;
  train_window: string;
  test: { n: number; prevalence: number; events: number; split_from: string };
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

// LA-appropriate definitions. LA's grade direction is the opposite of NYC's, so
// the letter-grade and score entries are LA-specific.
const LA_GLOSSARY: { id: string; term: string; short: string }[] = [
  { id: "letter-grade", term: "Letter grade (A / B / C)", short: "Los Angeles County's public restaurant grade. It's a threshold on the 0–100 inspection score: A = 90–100, B = 80–89, C = 70–79. Higher is cleaner, the opposite of New York's scale." },
  { id: "inspection-score", term: "Inspection score", short: "100 minus the points deducted for violations at one inspection (major and critical violations deduct more). The score maps to the letter grade; a place is 'bad' next time if it drops below 90 (a B or C)." },
  { id: "risk-tier", term: "Risk tier", short: "The Low / Moderate / Elevated / High band shown on the map, list, and detail pages. A bucketing of the predicted probability, recalibrated to LA's own distribution." },
  { id: "severity-tier", term: "Severity tier", short: "A shared way to describe how serious a violation is across all three cities (imminent-hazard, critical, or general) mapped from each city's own codes via the shared violation dictionary." },
  { id: "violation-dictionary", term: "Violation dictionary", short: "A lookup that maps each city's own violation codes to a shared set of plain-language themes (temperature, pest, hygiene, contamination, …) and severity tiers, so one vocabulary describes violations across all three cities even though each city files them differently." },
  { id: "pr-auc", term: "PR-AUC / ROC-AUC", short: "Ranking-quality scores. PR-AUC rewards finding the minority (B/C) cases; ROC-AUC is base-rate independent, so it's the fairest number to compare LA (~0.74) with NYC (~0.66) and Chicago (~0.78)." },
  { id: "lift", term: "Top-decile lift", short: "How much better than chance the top 10% by predicted risk is. 2.1× means that slice has 2.1× the B/C rate of the whole population." },
  { id: "calibration", term: "Calibration", short: "A final step that makes the 0–1 score read as a real probability, so a 0.30 really means ~30% of similar establishments were graded B/C next time." },
  { id: "shap", term: "SHAP driver", short: "A per-establishment breakdown of which features pushed the score up or down, in log-odds: the signed list you see under 'what's driving the score' on a detail page." },
  { id: "forecast-trend", term: "Forecast-only model / trend", short: "A second model that scores each past inspection without seeing its own outcome; the slope of its recent scores is the Improving / Worsening / Stable trend." },
];

export function HowItWorksLa() {
  const [m, setM] = useState<LaMethodology | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(dataUrl("la", "methodology.json"))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d: LaMethodology) => alive && setM(d))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const prevPct = m ? Math.round(m.test.prevalence * 100) : 8;

  return (
    <div>
      <MethodologyHero
        eyebrow="Methodology · Los Angeles"
        title={<>How this <span className="serif italic text-teal">works</span></>}
        stats={
          <>
            <HeroStat accent value={m ? `${m.headline.top_decile_lift.toFixed(1)}×` : "—"} label="more hits than random, working the top 10% by predicted risk" />
            <HeroStat value={m ? m.headline.roc_auc.toFixed(2) : "—"} label="ROC-AUC: ranks venues headed for a B or C grade above those that won't" />
          </>
        }
      >
        Los Angeles County is a third city, added to show the same tool works
        beyond Chicago and New York. Each score is a calibrated probability that
        an establishment&apos;s{" "}
        <strong className="text-ink font-medium">next inspection is graded B or C</strong>{" "}
        under LA&apos;s letter-grade system: the same batch-scored-to-JSON
        pipeline, calibrated model, and SHAP drivers as Chicago, on LA data.
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
            Every LA County inspection produces a numeric <em>score</em> out of 100:
            100 minus the points deducted across cited violations (major and critical
            violations deduct more). <strong className="text-ink">Higher is cleaner</strong>,
            the opposite of New York. The score maps to a letter grade:{" "}
            <strong className="text-ink">A = 90–100, B = 80–89, C = 70–79</strong>. The
            model predicts whether the <em>next</em> inspection drops to B or C
            (score below 90). In the test window, {prevPct}% of next inspections were B/C.
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">Risk bands</h2>
          <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
            The percentage is bucketed into four bands, the coloured badges on the
            map, list, and detail pages. They&apos;re recalibrated to LA&apos;s own
            distribution: LA&apos;s B/C base rate is low (~{prevPct}%), so Chicago&apos;s
            and NYC&apos;s cutoffs wouldn&apos;t transfer.
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
          <h2 className="text-2xl font-medium tracking-tight">The recent-trend chart</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            Each detail page plots a forecast-only model&apos;s score across the
            establishment&apos;s recent inspections, and reads the slope of the last
            few visits as Improving / Worsening / Stable. Because LA inspects on a
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
          <h2 className="text-2xl font-medium tracking-tight">The model</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            A logistic-regression pipeline with sigmoid (Platt) calibration:
            identical machinery to Chicago&apos;s production model, so the
            per-establishment SHAP driver breakdown and the calibrated-log-odds
            waterfall on each detail page work the same way. Scores are computed in
            a batch job and written to JSON; the site never calls a model at request
            time.
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">What we predict</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            For each inspection we ask: at this establishment&apos;s <em>next</em>
            inspection, does the grade drop to B or C (score below 90)? Like NYC and
            unlike Chicago&apos;s fixed 180-day window, the LA label is anchored to
            the next inspection whenever it occurs. LA&apos;s ~annual cadence makes a
            short fixed window empty. Source:{" "}
            {m?.data_source ?? "LA County Environmental Health Restaurant and Market Inspections"}.
            Training window: {m?.train_window ?? "2023-04-01 onward"}. LA County&apos;s
            open feed is already post-COVID, so there&apos;s no pre-pandemic cutoff to
            carve out (unlike Chicago&apos;s 2019 or NYC&apos;s 2022).
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">What goes in</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            Leak-free history features: prior inspection count, prior B/C count,
            average and previous score, prior critical-violation counts, days since
            the last inspection, plus the current inspection&apos;s own outcome
            (score, violation counts). LA&apos;s inspections and violations arrive as
            two feeds, joined on the inspection&apos;s serial number; those violations
            are mapped through a shared violation dictionary into severity tiers
            (imminent-hazard / critical / general) and themes (temperature, pest,
            hygiene, contamination, …) so the same vocabulary describes all three cities. No cuisine or demographic proxy is
            used. LA&apos;s feed carries no coordinates, so map pins are geocoded from
            each establishment&apos;s address.
          </p>
        </article>
      </div>

      {/* 03 — How well it works */}
      <div className="mt-10 space-y-8">
        <SectionLabel id="how-well-it-works" number="03" icon={Target}>How well it works</SectionLabel>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">Performance</h2>
          {m && (
            <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
              On a time-held-out test set (n = {m.test.n.toLocaleString("en-US")}, {prevPct}%
              B/C base rate): PR-AUC <strong className="text-ink">{m.headline.pr_auc.toFixed(2)}</strong>,
              ROC-AUC <strong className="text-ink">{m.headline.roc_auc.toFixed(2)}</strong>,
              top-decile lift <strong className="text-ink">{m.headline.top_decile_lift.toFixed(1)}×</strong>.
              For context, Chicago reaches ROC-AUC ~0.78 and lift ~3.4×, and NYC ~0.66. LA sits between them, still a preview rather than a production model.
            </p>
          )}
          {m && (
            <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
              The two numbers we judge the model on are here, not in the header:{" "}
              <span className="text-ink">PR-AUC</span> and{" "}
              <span className="text-ink">precision in the top 10%</span>, on the
              held-out split. The lift and ROC-AUC above describe how well the
              chosen model works; these two are how it was chosen.
            </p>
          )}
          {m && (
            <dl className="mt-4 grid gap-2.5 sm:grid-cols-2 max-w-[62ch] text-sm">
              <div className="rounded-xl border border-line bg-card px-3.5 py-2.5">
                <dt className="font-medium text-ink">ROC-AUC {m.headline.roc_auc.toFixed(2)}</dt>
                <dd className="text-muted leading-snug mt-0.5">How often it ranks a B/C inspection above one that isn&apos;t. Base-rate-independent, so it&apos;s the fair way to compare LA with Chicago and NYC.</dd>
              </div>
              <div className="rounded-xl border border-line bg-card px-3.5 py-2.5">
                <dt className="font-medium text-ink">PR-AUC {m.headline.pr_auc.toFixed(2)}</dt>
                <dd className="text-muted leading-snug mt-0.5">Ranking quality for the rare B/C class. Its floor is the {prevPct}% base rate, so it only compares fairly to cities with a similar base rate, not to NYC&apos;s ~40%.</dd>
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
          {m && (
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left text-muted border-b border-line">
                    <th className="py-2 pr-4 font-medium">Inspect top…</th>
                    <th className="py-2 pr-4 font-medium">Flagged</th>
                    <th className="py-2 pr-4 font-medium">Precision</th>
                    <th className="py-2 pr-4 font-medium">Recall</th>
                    <th className="py-2 pr-4 font-medium">Lift</th>
                  </tr>
                </thead>
                <tbody>
                  {m.operating_points.map((p) => (
                    <tr key={p.frac} className="border-b border-line/60">
                      <td className="py-2 pr-4 num">{Math.round(p.frac * 100)}%</td>
                      <td className="py-2 pr-4 num">{p.n_flagged.toLocaleString("en-US")}</td>
                      <td className="py-2 pr-4 num">{(p.precision * 100).toFixed(0)}%</td>
                      <td className="py-2 pr-4 num">{(p.recall * 100).toFixed(0)}%</td>
                      <td className="py-2 pr-4 num">{p.lift.toFixed(2)}×</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-muted mt-2">
                Read a row as: inspect the top X% by predicted risk and you catch
                that share of the next B/C inspections, at that precision and lift
                over chance.
              </p>
            </div>
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
            for one real elevated-risk establishment (predicted 66%).
          </p>
          <div className="mt-4 rounded-2xl border border-line bg-card overflow-hidden max-w-[62ch]">
            <WaterfallRow label="Base rate (model intercept)" value={-0.44} muted />
            <WaterfallRow label="Average past inspection score 71/100" value={4.42} />
            <WaterfallRow label="Previous inspection was B or C" value={1.62} />
            <WaterfallRow label="644 days since the last inspection" value={1.02} />
            <WaterfallRow label="Previous inspection score 71/100" value={-1.22} />
            <WaterfallRow label="Past B/C rate 1.0" value={-2.58} />
            <WaterfallRow label="Everything else (remaining features)" value={-2.15} muted />
            <WaterfallRow label="Total (calibrated log-odds)" value={0.68} strong />
            <div className="flex items-center justify-between gap-3 px-4 py-2.5 bg-tint/50">
              <span className="text-sm text-ink font-medium">Squashed to a probability (the gauge)</span>
              <span className="num text-terra-strong font-semibold">66.4%</span>
            </div>
          </div>
          <p className="text-xs text-muted leading-relaxed mt-3 max-w-[62ch]">
            Rows are in <span className="font-medium text-ink/80">calibrated log-odds</span>:
            additive in that space, so they sum to the total, and a sigmoid turns the
            total into the probability shown on the gauge. Because LA&apos;s scale is
            inverted, a <em>low</em> average past score pushes risk up.
          </p>
        </article>
      </div>

      {/* 04 — Model card (Limitations folded in, like Chicago) */}
      <ModelCard
        city="la"
        m={m}
        number="04"
        limitations={
          <div className="space-y-4 text-muted leading-[1.7]">
            <p>
              <strong className="text-ink">LA is a coverage feature, not a quality
              upgrade.</strong> Its signal is weaker than Chicago&apos;s
              (ROC-AUC ~0.74 vs ~0.78; lift ~2.1× vs ~3.4×), though stronger than
              NYC&apos;s. Treat LA scores as a rougher guide.
            </p>
            <p>
              <strong className="text-ink">The grade scale is inverted.</strong> LA
              grades A–C run 90-100 / 80-89 / 70-79, where higher is cleaner, the
              opposite of NYC. The risk score already accounts for this; it is always
              the chance of a <em>worse</em> (B or C) next grade.
            </p>
            <p>
              <strong className="text-ink">The data window is shallow, and pins are
              approximate.</strong> Only ~3 post-2023 years are usable, so
              per-establishment history is thin. The feed carries no coordinates, so
              map pins are geocoded from the street address and a few fall back to a
              ZIP-code centroid.
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
      <DataGovernance city="la" m={m} number="05" />

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
            {LA_GLOSSARY.map((entry) => (
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
