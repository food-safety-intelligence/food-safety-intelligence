"use client";

// NYC-specific "how it works" content, driven by nyc/methodology.json (DR 0014).
// Mirrors the Chicago page's structure + formatting (hero + stat cards, numbered
// section labels, worked sections, limits, reference) with NYC-accurate content.

import { BookOpen, type LucideIcon, Target, TriangleAlert, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { dataUrl } from "@/lib/city";

interface NycMethodology {
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

  return (
    <div>
      {/* Hero */}
      <p className="text-sage text-xs tracking-[0.2em] uppercase mb-3">Research preview · New York City</p>
      <h1 className="text-5xl font-light leading-[1.05] tracking-tight">How this works — New York City</h1>
      <p className="text-lg text-muted leading-[1.6] mt-5 max-w-[62ch]">
        New York City is a second city, added to show the same tool works beyond
        Chicago. Each score is a calibrated probability that an establishment&apos;s{" "}
        <strong className="text-ink font-medium">next inspection is graded B or C</strong>{" "}
        under New York&apos;s letter-grade system — the same batch-scored-to-JSON
        pipeline, calibrated model, and SHAP drivers as Chicago, on New York data.
      </p>
      <dl className="mt-8 grid grid-cols-2 sm:grid-cols-3 gap-3">
        <HeroStat accent value={m ? `${m.headline.top_decile_lift.toFixed(1)}×` : "—"} label="top-decile lift over the base rate" />
        <HeroStat value={m ? m.headline.roc_auc.toFixed(2) : "—"} label="ROC-AUC on the held-out test set" />
        <HeroStat value={m ? `${prevPct}%` : "—"} label="of next inspections are B or C (base rate)" />
      </dl>

      {/* 01 — Reading the score */}
      <div className="mt-10 space-y-8">
        <SectionLabel id="reading-the-score" number="01" icon={BookOpen}>Reading the score</SectionLabel>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">The letter-grade label</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            Every NYC inspection produces a numeric <em>score</em> — the sum of
            points across cited violations (public-health hazards ≥ 7 points,
            critical ≥ 5, general ≥ 2). Lower is cleaner. The score maps to a
            letter grade: <strong className="text-ink">A = 0–13, B = 14–27, C = 28+</strong>.
            The model predicts whether the <em>next</em> inspection lands at B or C
            (score ≥ 14). In the test window, {prevPct}% of next inspections were B/C.
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">Risk tiers</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            The score band is recalibrated to NYC&apos;s own distribution — NYC&apos;s
            base rate is far higher than Chicago&apos;s, so Chicago&apos;s cutoffs
            wouldn&apos;t transfer.
          </p>
          {m && (
            <div className="mt-4 grid gap-2 max-w-[62ch]">
              {m.risk_tiers.map((t) => (
                <div key={t.label} className="flex items-center justify-between rounded-lg border border-line px-4 py-2 text-sm">
                  <span className="font-medium">{t.label}</span>
                  <span className="num text-muted">{t.min.toFixed(2)}–{t.max === null ? "1.00" : t.max.toFixed(2)}</span>
                  <span className="num text-muted">{(t.share * 100).toFixed(0)}% of index</span>
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
          <h2 className="text-2xl font-medium tracking-tight">The model</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            A logistic-regression pipeline with sigmoid (Platt) calibration —
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
            inspection, is the grade B or C (score ≥ 14)? Unlike Chicago&apos;s fixed
            180-day window, the NYC label is anchored to the next inspection whenever
            it occurs — NYC&apos;s ~annual cadence makes a short fixed window empty.
            Source: {m?.data_source ?? "NYC DOHMH Restaurant Inspection Results"}.
            Training window: {m?.train_window ?? "post-COVID, 2022 onward"} —
            inspections halted in the 2020 COVID shutdown, so earlier data isn&apos;t
            comparable (the analog of Chicago&apos;s 2019 cutoff).
          </p>
        </article>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">What goes in</h2>
          <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
            Leak-free history features — prior inspection count, prior B/C count,
            average and previous score, prior critical-violation counts, days since
            the last inspection — plus the current inspection&apos;s own outcome
            (score, violation counts). Violations are mapped through a shared
            crosswalk into severity tiers (imminent-hazard / critical / general) and
            themes (temperature, pest, hygiene, contamination, …) so the same
            vocabulary describes both cities. No cuisine or demographic proxy is used.
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
              On a time-held-out test set (n = {m.test.n.toLocaleString()}, {prevPct}%
              B/C base rate): PR-AUC <strong className="text-ink">{m.headline.pr_auc.toFixed(2)}</strong>,
              ROC-AUC <strong className="text-ink">{m.headline.roc_auc.toFixed(2)}</strong>,
              top-decile lift <strong className="text-ink">{m.headline.top_decile_lift.toFixed(1)}×</strong>.
              For context, Chicago reaches ROC-AUC ~0.78 and lift ~3.4× — NYC is
              meaningfully weaker, which is why it&apos;s labelled a preview.
            </p>
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
                      <td className="py-2 pr-4 num">{p.n_flagged.toLocaleString()}</td>
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
      </div>

      {/* 04 — Limits (the honest note lives here now) */}
      <div className="mt-10 space-y-8">
        <SectionLabel id="limits" number="04" icon={TriangleAlert}>Limits</SectionLabel>
        <article>
          <h2 className="text-2xl font-medium tracking-tight">What to keep in mind</h2>
          <div className="mt-3 max-w-[62ch] space-y-4 text-muted leading-[1.7]">
            <p>
              <strong className="text-ink">NYC is a coverage feature, not a quality
              upgrade.</strong> Its signal is weaker than Chicago&apos;s
              (ROC-AUC ~0.66 vs ~0.78; lift ~1.6× vs ~3.4×), so treat NYC scores as
              a rougher guide.
            </p>
            <p>
              <strong className="text-ink">The data window is shallow.</strong> Only
              ~3 years are usable — inspections restarted after the 2020 COVID pause,
              and the open-data feed keeps a rolling ~3-year window — so
              per-establishment history is thin and the trend chart is sparser than
              Chicago&apos;s.
            </p>
            <p>
              <strong className="text-ink">It is a risk signal, not a verdict.</strong>{" "}
              A high score doesn&apos;t mean a place is unsafe today — it means its
              record resembles establishments that went on to be graded B or C. Use
              it for prioritisation, not judgement.
            </p>
          </div>
        </article>
      </div>
    </div>
  );
}
