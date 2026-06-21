import type { Driver } from "@/lib/scores";
import { iconForFeature } from "@/lib/driver-icons";
import { cn } from "@/lib/utils";

/**
 * Ranked drivers as a diverging bar chart. Each row leads with a topic icon
 * (so a reader scanning the column can parse pest / temperature / time-since-
 * inspection at a glance) and a plain-English label. The bar diverges from a
 * centre zero axis: factors that RAISE risk extend right (terra), factors that
 * LOWER it extend left (sage). The signed value gives the precise log-odds
 * contribution.
 *
 * Bar length normalises against the largest |shap| in the list. We deliberately
 * show relative magnitude and direction only — NOT a running total to the final
 * score. The displayed risk score is a calibrated probability while these
 * contributions live in log-odds space, so a "base + parts = score" waterfall
 * would not reconcile with the gauge. That worked example lives on the
 * methodology page instead.
 */
export function DriverList({ drivers }: { drivers: Driver[] }) {
  if (drivers.length === 0) {
    return (
      <div className="rounded-3xl bg-card border border-line p-6 text-muted text-[14px]">
        No driver data available for this prediction.
      </div>
    );
  }

  const maxMagnitude = Math.max(...drivers.map((d) => Math.abs(d.shap)));

  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow overflow-hidden">
      {/* Axis legend — frames the centre zero so the diverging bars read on their own */}
      <div className="grid grid-cols-12 gap-4 items-center px-6 pt-5 pb-2 border-b border-line">
        <div className="col-span-6" />
        <div className="col-span-5 flex justify-between text-[11px] uppercase tracking-[0.12em] text-muted">
          <span className="text-sage">&larr; lowers risk</span>
          <span className="text-terra">raises risk &rarr;</span>
        </div>
        <div className="col-span-1" />
      </div>

      <ol>
        {drivers.map((d, i) => {
          const halfPct = (Math.abs(d.shap) / maxMagnitude) * 50;
          const isPositive = d.shap > 0;
          const sign = d.shap > 0 ? "+" : d.shap < 0 ? "−" : "";
          const Icon = iconForFeature(d.feature);
          const barStyle = isPositive
            ? { left: "50%", width: `${halfPct}%` }
            : { right: "50%", width: `${halfPct}%` };
          return (
            <li
              key={d.feature + i}
              className={cn(
                "grid grid-cols-12 gap-4 items-center px-6 py-5",
                i < drivers.length - 1 && "border-b border-line",
              )}
            >
              <div className="col-span-1 flex items-center">
                <span
                  className={cn(
                    "inline-flex w-9 h-9 rounded-xl items-center justify-center shrink-0",
                    isPositive ? "bg-terra/10 text-terra" : "bg-sage/15 text-sage",
                  )}
                >
                  <Icon className="w-[18px] h-[18px]" strokeWidth={1.8} />
                </span>
              </div>
              <div className="col-span-5">
                <div className="flex items-center gap-2">
                  <span className="num text-muted text-[11.5px] tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div className="font-semibold">{d.label}</div>
                </div>
                {d.detail && (
                  <div className="text-[12.5px] text-muted mt-0.5">{d.detail}</div>
                )}
              </div>
              <div className="col-span-5">
                <div className="relative h-2">
                  {/* centre zero axis */}
                  <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line" />
                  <div
                    className={cn(
                      "absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full",
                      isPositive ? "bg-terra" : "bg-sage",
                    )}
                    style={barStyle}
                  />
                </div>
              </div>
              <div
                className={cn(
                  "col-span-1 num text-right font-medium tabular-nums",
                  isPositive ? "text-terra" : "text-sage",
                )}
              >
                {sign}
                {Math.abs(d.shap).toFixed(2)}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
