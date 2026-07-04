"use client";

// NYC-specific "how it works" content, driven by nyc/methodology.json (DR 0014).
// NYC's label, data window, and model differ enough from Chicago that a
// dedicated, honest page is clearer than parameterising the Chicago essay.

import { useEffect, useState } from "react";
import { dataUrl } from "@/lib/city";

interface NycMethodology {
  data_source: string;
  label: string;
  train_window: string;
  caveat: string;
  test: { n: number; prevalence: number; events: number; split_from: string };
  headline: { pr_auc: number; roc_auc: number; top_decile_lift: number };
  risk_tiers: { label: string; min: number; max: number | null; share: number }[];
  operating_points: { frac: number; n_flagged: number; precision: number; recall: number; lift: number; events_caught: number }[];
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

  return (
    <div className="prose-none">
      <p className="text-sage text-xs tracking-[0.2em] uppercase mb-3">
        Research preview · New York City
      </p>
      <h1 className="text-5xl font-light leading-[1.05] tracking-tight">
        How this works — New York City
      </h1>
      <p className="text-lg text-muted leading-[1.6] mt-5 max-w-[62ch]">
        NYC is a second city we added to show the same tool works beyond Chicago.
        The score is a calibrated probability that an establishment&apos;s{" "}
        <strong className="text-ink font-medium">next inspection is graded B or C</strong>{" "}
        — New York&apos;s letter-grade system, where more violation points mean a
        worse grade.
      </p>
      <div className="mt-5 rounded-xl border border-amber/40 bg-amber/5 p-4 text-sm text-ink/80 leading-relaxed max-w-[62ch]">
        <strong className="font-medium">An honest note.</strong> NYC is a coverage
        feature, not a quality upgrade. Its signal is weaker than Chicago&apos;s
        (see the numbers below), and its data only covers the ~3 years since
        inspections restarted after the 2020 COVID pause. Treat NYC scores as a
        rougher guide.
      </div>

      <section className="mt-12">
        <h2 className="text-2xl font-medium tracking-tight">The letter-grade label</h2>
        <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
          Every NYC inspection produces a numeric <em>score</em> — the sum of
          points across cited violations (public-health hazards ≥ 7 points,
          critical ≥ 5, general ≥ 2). Lower is cleaner. The score maps to a grade:
          <strong className="text-ink"> A = 0–13, B = 14–27, C = 28+</strong>. We
          predict whether the <em>next</em> inspection lands at B or C
          (score ≥ 14). {m ? `In the test period, ${(m.test.prevalence * 100).toFixed(0)}% of next inspections were B/C.` : ""}
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-medium tracking-tight">Data &amp; window</h2>
        <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
          Source: {m?.data_source ?? "NYC DOHMH Restaurant Inspection Results"}.
          Training window: {m?.train_window ?? "post-COVID, 2022 onward"}. NYC
          inspects on a roughly annual cycle, so &ldquo;next inspection&rdquo; is
          anchored to whenever the next one occurs — not a fixed 180-day window
          like Chicago. Everything else matches Chicago: batch-scored to JSON, a
          calibrated logistic-regression model, and SHAP drivers you can read on
          each detail page.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-medium tracking-tight">How well it works</h2>
        {m ? (
          <>
            <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
              On a time-held-out test set (n = {m.test.n.toLocaleString()},{" "}
              {(m.test.prevalence * 100).toFixed(0)}% B/C base rate): PR-AUC{" "}
              <strong className="text-ink">{m.headline.pr_auc.toFixed(2)}</strong>,
              ROC-AUC <strong className="text-ink">{m.headline.roc_auc.toFixed(2)}</strong>,
              top-decile lift{" "}
              <strong className="text-ink">{m.headline.top_decile_lift.toFixed(1)}×</strong>.
              For comparison, Chicago&apos;s model reaches ROC-AUC ~0.78 and
              lift ~3.4× — NYC is meaningfully weaker, which is why we label it a
              preview.
            </p>
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
            </div>
          </>
        ) : (
          <p className="text-muted mt-3">Metrics loading…</p>
        )}
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-medium tracking-tight">Risk tiers</h2>
        <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
          Tiers are recalibrated to NYC&apos;s own score distribution (NYC&apos;s
          base rate is far higher than Chicago&apos;s, so the same cutoffs
          wouldn&apos;t transfer).
        </p>
        {m && (
          <div className="mt-4 grid gap-2 max-w-[62ch]">
            {m.risk_tiers.map((t) => (
              <div
                key={t.label}
                className="flex items-center justify-between rounded-lg border border-line px-4 py-2 text-sm"
              >
                <span className="font-medium">{t.label}</span>
                <span className="num text-muted">
                  {t.min.toFixed(2)}–{t.max === null ? "1.00" : t.max.toFixed(2)}
                </span>
                <span className="num text-muted">{(t.share * 100).toFixed(0)}% of index</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-medium tracking-tight">Limitations</h2>
        <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
          {m?.caveat ??
            "NYC is a research preview with a weaker signal than Chicago and a shallow (post-COVID) data window."}{" "}
          The trend chart is sparser than Chicago&apos;s because NYC establishments
          have fewer inspections on record. As with Chicago, this is a risk signal
          for prioritisation — not a verdict on any establishment.
        </p>
      </section>
    </div>
  );
}
