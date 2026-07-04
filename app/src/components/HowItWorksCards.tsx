"use client";

// Shared Model-card + Data-governance sections for the preview-city how-it-works
// pages (NYC, LA), so they carry the same structure Chicago's page gained in the
// Model card + Data governance work — one card format across all cities. Content
// that differs per city is driven by CITY_CONFIG + the city's methodology.json;
// the governance prose is largely city-agnostic (public records, no visitor data)
// with the city name / sources injected. Chicago keeps its own inline version.

import type { ReactNode } from "react";
import { ClipboardList, ShieldCheck, type LucideIcon } from "lucide-react";
import { CITY_CONFIG, type City } from "@/lib/city";

// "a" vs "an" for a percentage read aloud (e.g. "an 8%", "a 41%"). For whole
// percents 0–100 the vowel-sound-initial numbers are 8, 11, 18, and the 80s.
export function articleFor(pct: number): "a" | "an" {
  const n = Math.round(pct);
  const vowelSound = n === 8 || n === 11 || n === 18 || (n >= 80 && n <= 89);
  return vowelSound ? "an" : "a";
}

// Shared hero band for the how-it-works pages: the soft cream→white gradient
// card with a faint sage glow that Chicago's methodology page uses, so all three
// cities open identically. `eyebrow`/`title` are the header text, the intro
// paragraph is `children`, and `stats` holds the row of <HeroStat> cards (each
// city keeps its own HeroStat + values).
export function MethodologyHero({
  eyebrow,
  title,
  stats,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  stats: ReactNode;
  children: ReactNode;
}) {
  return (
    <header
      className="relative mt-6 overflow-hidden rounded-3xl border border-line p-7 sm:p-10 soft-shadow"
      style={{
        background: "linear-gradient(135deg, #EFE9DC 0%, #F6F1E9 48%, #FFFFFF 100%)",
      }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-24 -right-20 w-72 h-72 rounded-full blur-3xl"
        style={{ background: "rgba(122, 143, 106, 0.16)" }}
      />
      <div className="relative">
        <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">{eyebrow}</p>
        <h1 className="text-5xl font-light leading-[1.05] tracking-tight">{title}</h1>
        <p className="text-lg text-muted leading-[1.65] mt-5 max-w-[58ch]">{children}</p>
        <dl className="mt-8 grid grid-cols-2 sm:grid-cols-3 gap-3">{stats}</dl>
      </div>
    </header>
  );
}

// Friendly labels for the served model slug (mirrors the Chicago page's map).
const MODEL_TYPE_LABELS: Record<string, string> = {
  la_logreg_sigmoid: "Calibrated logistic regression (Platt-scaled)",
  nyc_logreg_sigmoid: "Calibrated logistic regression (Platt-scaled)",
};

interface Methodology {
  model_version?: string;
  data_source?: string;
  train_window?: string;
  test?: { split_from?: string; n?: number };
}

function CardSectionLabel({ id, number, icon: Icon, children }: {
  id: string; number: string; icon: LucideIcon; children: string;
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

export function ModelCard({ city, m, number, limitations }: {
  city: City; m: Methodology | null; number: string; limitations?: ReactNode;
}) {
  const c = CITY_CONFIG[city];
  const modelType = m?.model_version ? (MODEL_TYPE_LABELS[m.model_version] ?? m.model_version) : null;
  const testFrom = m?.test?.split_from;
  const testN = m?.test?.n;

  return (
    <div className="mt-10 space-y-8">
      <CardSectionLabel id="model-card" number={number} icon={ClipboardList}>Model card</CardSectionLabel>
      <article>
        <h2 className="text-2xl font-medium tracking-tight">What this model is for</h2>
        <p className="text-md text-muted leading-relaxed mt-2 max-w-[62ch]">
          A model card gathers, in one place, who the model is for, how it was tested,
          where it falls short, and how it&apos;s kept up to date. The mechanics and
          numbers restate and link to{" "}
          <a href="#how-its-built" className="text-teal hover:underline">How it&apos;s built</a>{" "}
          and{" "}
          <a href="#how-well-it-works" className="text-teal hover:underline">How well it works</a>
          {" "}above; the intended-use, limits, and retraining points below are what the
          card adds. It covers <span className="font-medium text-ink/80">two models</span> —
          the risk score and a separate trend forecast — the same pair as Chicago,
          retrained on {c.label} data.
        </p>

        <h3 className="text-lg font-medium tracking-tight mt-8">The two models</h3>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-line bg-card p-4">
            <p className="text-xs uppercase tracking-[0.08em] text-sage font-medium">Model 1 · Risk score</p>
            <p className="text-sm text-muted leading-relaxed mt-2">
              The headline percentage — {c.predictionBlurb}. It uses the current
              inspection&apos;s own outcome, the strongest near-term signal. The details
              and evaluation on this card describe this model.
            </p>
          </div>
          <div className="rounded-2xl border border-line bg-card p-4">
            <p className="text-xs uppercase tracking-[0.08em] text-sage font-medium">Model 2 · Trend forecast</p>
            <p className="text-sm text-muted leading-relaxed mt-2">
              Drives the trend arrow and chart. It forecasts the same outcome but{" "}
              <span className="font-medium text-ink/80">ignores the current
              inspection&apos;s own result</span>, so a bad visit and its re-inspection
              don&apos;t read as a swing. It only shows direction over time; it never
              sets the risk score.
            </p>
          </div>
        </div>

        {(modelType || testFrom) && (
          <>
            <p className="mt-6 text-xs uppercase tracking-[0.08em] text-sage font-medium">Risk-score model</p>
            <dl className="mt-2 rounded-2xl border border-line bg-card overflow-hidden text-sm max-w-[62ch]">
              {modelType && (
                <div className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-line last:border-b-0">
                  <dt className="text-muted">Model type</dt>
                  <dd className="text-ink/85">{modelType}</dd>
                </div>
              )}
              {m?.data_source && (
                <div className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-line last:border-b-0">
                  <dt className="text-muted">Data source</dt>
                  <dd className="text-ink/85 text-right">{m.data_source}</dd>
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

        <h3 className="text-lg font-medium tracking-tight mt-8">Intended users &amp; use</h3>
        <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
          Built for the people who plan food-safety inspections — the {c.healthDept} or
          an inspection team deciding where limited inspector time should go. It is a
          triage signal that ranks {c.nounPlural} by forward risk so a capacity-limited
          team can work the riskiest first; the value is in the ranking, not any single
          establishment&apos;s number. The public web app opens the same signal for
          transparency, but it is decision support, not a consumer safety rating.
        </p>

        <h3 className="text-lg font-medium tracking-tight mt-6">Out-of-scope uses</h3>
        <ul className="text-sm leading-relaxed mt-2 space-y-2 list-disc pl-5 text-ink/85 max-w-[62ch]">
          <li><span className="font-medium">Not a verdict.</span> A high score is not a finding that a place is unsafe — most flagged establishments have no event in the window.</li>
          <li><span className="font-medium">Not an enforcement or licensing input.</span> It shouldn&apos;t be used on its own to fine, close, or penalise a business without a human inspection.</li>
          <li><span className="font-medium">Not a live diner guarantee.</span> It doesn&apos;t say whether a specific meal is safe right now.</li>
          <li><span className="font-medium">Not another city.</span> Trained only on {c.label} data and not validated elsewhere.</li>
          <li><span className="font-medium">Preview quality.</span> {c.label} is a research-preview coverage feature with a weaker signal than Chicago — treat its scores as a rougher guide.</li>
        </ul>

        <h3 className="text-lg font-medium tracking-tight mt-6">How it&apos;s evaluated</h3>
        <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
          On a strictly time-held-out split, with every feature computed only from data
          before the inspection it describes (no leakage) and no cuisine or demographic
          proxy as an input; cities are compared by ROC-AUC (base-rate-independent). The
          full metrics table + operating points are under{" "}
          <a href="#how-well-it-works" className="text-teal hover:underline">How well it works</a>.
        </p>

        {limitations && (
          <>
            <h3 id="limits" className="scroll-mt-24 text-lg font-medium tracking-tight mt-6">Limitations</h3>
            <div className="mt-2 max-w-[62ch]">{limitations}</div>
          </>
        )}

        <h3 className="text-lg font-medium tracking-tight mt-6">Retraining</h3>
        <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
          Retrained on demand from the public source, not on a fixed schedule and never
          live — each run is tied to the exact commit that produced it, and a published
          score set can always be regenerated from scratch. The model type and the date
          its metrics were generated are shown above.
        </p>
      </article>
    </div>
  );
}

export function DataGovernance({ city, m, number }: { city: City; m: Methodology | null; number: string }) {
  const c = CITY_CONFIG[city];
  return (
    <div className="mt-10 space-y-8">
      <CardSectionLabel id="data-governance" number={number} icon={ShieldCheck}>Data governance</CardSectionLabel>
      <article>
        <h2 className="text-2xl font-medium tracking-tight">Where the data comes from and how it&apos;s handled</h2>
        <p className="text-md text-muted leading-relaxed mt-2 max-w-[62ch]">
          Every input is a public record — {m?.data_source ?? c.sources.join(", ")}. The
          app collects nothing from the people who visit it — no accounts, no login, no
          personal data — so the questions below are about public business records, not
          private user data. The full source list is on the{" "}
          <a href="/sources" className="text-teal hover:underline">Sources</a> page.
        </p>

        <h3 className="text-lg font-medium tracking-tight mt-8">Sources &amp; retention</h3>
        <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
          The inputs are {c.label}&apos;s public inspection records. We keep a cached
          copy of the fields needed to build features and scores, refreshed in place
          rather than kept as a growing archive of dated snapshots. Because no visitor
          data is gathered, there is no personal information to retain.
        </p>

        <h3 className="text-lg font-medium tracking-tight mt-6">Storage &amp; security</h3>
        <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
          Scores are published as static JSON served through a content-delivery network.
          The website is read-only static pages with no login and no server-side
          database, and it never runs the model on a page load — it only reads the
          pre-computed JSON (the batch-score-to-JSON contract). Source and working data
          sit in a private cloud bucket limited to the team&apos;s own credentials.
        </p>

        <h3 className="text-lg font-medium tracking-tight mt-6">Updated source data</h3>
        <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
          We don&apos;t read the source feed live; we re-pull and re-score in a batch
          job, then publish a fresh JSON. The scores you see are a snapshot as of the
          last publish — the detail page shows each establishment&apos;s &ldquo;as
          of&rdquo; date — not a live reading.
        </p>

        <h3 className="text-lg font-medium tracking-tight mt-6">Location data</h3>
        <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
          The only location data is an establishment&apos;s own address and map
          coordinates — it locates a business, not a person.{" "}
          {city === "la"
            ? "The LA feed carries no coordinates, so they're geocoded from the public street address (a few fall back to a ZIP-code centroid)."
            : "They come straight from the public inspection record."}{" "}
          The app never asks for, collects, or stores a visitor&apos;s location.
        </p>
      </article>
    </div>
  );
}
