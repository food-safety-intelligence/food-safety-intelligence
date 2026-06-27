import type { Calibration, RestaurantScore } from "@/lib/scores";
import { computeWaterfall } from "@/lib/scores";
import { cn } from "@/lib/utils";

/**
 * One row of the per-establishment waterfall: a label and its signed calibrated
 * log-odds. Positive (raises risk) reads terra, negative (lowers) reads sage;
 * structural rows (base / other / total) are neutral. `strong` styles the
 * running-total row. Mirrors the methodology page's worked example, but computed
 * client-side per establishment from the shipped calibration triple.
 */
function Row({
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
 * "How the score adds up" for one establishment — the same drivers as the bars
 * above, but as an additive, reconciling waterfall in calibrated log-odds. The
 * rows are rounded to the displayed precision and the "everything else" bucket
 * is the residual, so the visible column sums EXACTLY to the total, and
 * sigmoid(total) is the probability on the gauge.
 */
export function Waterfall({
  restaurant,
  calibration,
}: {
  restaurant: RestaurantScore;
  calibration: Calibration;
}) {
  const wf = computeWaterfall(restaurant, calibration);
  const round2 = (n: number) => Math.round(n * 100) / 100;
  const base = round2(wf.base);
  const steps = wf.steps.map((s) => ({ ...s, c: round2(s.contribution) }));
  const total = round2(wf.total);
  const other = round2(total - base - steps.reduce((sum, s) => sum + s.c, 0));

  return (
    <div className="rounded-2xl border border-line bg-card overflow-hidden text-[14px]">
      <Row label="Base rate (model intercept)" value={base} muted />
      {steps.map((s, i) => (
        <Row key={s.feature + i} label={s.label} value={s.c} />
      ))}
      <Row label="Everything else (remaining features)" value={other} muted />
      <Row label="Total (calibrated log-odds)" value={total} strong />
      <div className="flex items-center justify-between px-4 py-3 bg-cream/50">
        <span className="font-medium">Squashed to a probability (the gauge)</span>
        <span className="num font-semibold text-terra-strong text-[16px]">
          {(wf.probability * 100).toFixed(1)}%
        </span>
      </div>
    </div>
  );
}
