import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { MergedRiskChart } from "@/components/MergedRiskChart";
import { ScoreCard } from "@/components/ScoreCard";
import { TierPill } from "@/components/TierPill";
import { trendDirection } from "@/lib/scores";
import { POP_MEDIAN, PROTO_CASES } from "./fixture";

/**
 * THROWAWAY prototype route (/proto) — eyeball the merged risk-trajectory chart
 * against the current gauge+trend ScoreCard on real establishments. Not linked
 * from anywhere; delete with the fixture + MergedRiskChart when done.
 */
export default function ProtoPage() {
  const populationStats = { total: 23621, median: POP_MEDIAN, mean: POP_MEDIAN };

  return (
    <main className="w-full max-w-[1000px] mx-auto px-8 py-12 space-y-16">
      <header>
        <h1 className="text-4xl font-light tracking-tight">Trend-chart prototype</h1>
        <p className="text-muted mt-2 max-w-[70ch] leading-relaxed">
          For each real establishment: the <strong>current</strong> ScoreCard (arc gauge +
          separate trend chart) above the <strong>merged</strong> prototype (one risk-trajectory
          chart — tier bands + Model&nbsp;2 line + Model&nbsp;1 &ldquo;current&rdquo; diamond).
          Y-axis is auto-scaled per establishment (open question).
        </p>
      </header>

      {PROTO_CASES.map((c) => {
        const dir = trendDirection(c.restaurant.trend_slope);
        const DirIcon = dir === "worsening" ? TrendingUp : dir === "improving" ? TrendingDown : Minus;
        const dirColor = dir === "worsening" ? "text-terra" : dir === "improving" ? "text-sage" : "text-muted";
        const scoredPoints = c.history
          .filter((e): e is typeof e & { score: number } => e.score != null)
          .map((e) => ({ date: e.date, score: e.score, result: e.result }))
          .reverse();

        return (
          <section key={c.restaurant.license_id} className="space-y-4">
            <div className="flex items-baseline gap-3 border-b border-line pb-2">
              <span className="text-2xs tracking-widest uppercase text-sage">{c.kind}</span>
              <h2 className="text-2xl font-light tracking-tight">{c.restaurant.dba_name}</h2>
              <span className="text-sm text-muted">
                score {c.restaurant.risk_score.toFixed(3)} · {c.restaurant.risk_tier} ·{" "}
                {scoredPoints.length} scored pts
              </span>
            </div>

            {/* CURRENT */}
            <div>
              <p className="text-2xs tracking-widest uppercase text-muted mb-2">Current (shipped)</p>
              <ScoreCard restaurant={c.restaurant} populationStats={populationStats} history={c.history} />
            </div>

            {/* PROTOTYPE */}
            <div>
              <p className="text-2xs tracking-widest uppercase text-muted mb-2">Prototype — merged</p>
              <div className="rounded-3xl bg-card border border-line soft-shadow-lg p-7 lg:p-8">
                <div className="text-2xs tracking-widest uppercase text-muted">Predicted 180-day risk</div>
                <div className="flex items-center gap-4 mt-2 mb-4">
                  <span className="text-5xl font-light tracking-tight num">
                    {c.restaurant.risk_score.toFixed(2)}
                  </span>
                  <TierPill tier={c.restaurant.risk_tier} />
                  <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${dirColor}`}>
                    <DirIcon className="w-4 h-4" strokeWidth={2.5} />
                    {c.restaurant.trend_slope !== null && scoredPoints.length >= 2
                      ? dir.charAt(0).toUpperCase() + dir.slice(1)
                      : "Insufficient history"}
                  </span>
                </div>
                <MergedRiskChart
                  points={scoredPoints}
                  slope={c.restaurant.trend_slope}
                  currentScore={c.restaurant.risk_score}
                  currentTier={c.restaurant.risk_tier}
                />
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-2xs text-muted">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block w-4 h-[2px] bg-[#6B7280]" /> trend (forecast — ignores each visit&rsquo;s result)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block w-5 h-3 rounded-sm bg-[#B8634A] align-middle" /> current assessment (includes latest result)
                  </span>
                </div>
              </div>
            </div>
          </section>
        );
      })}
    </main>
  );
}
