import type { Driver } from "@/lib/scores";
import { iconForFeature } from "@/lib/driver-icons";
import { cn } from "@/lib/utils";

/**
 * Ranked list of contributing drivers. Each row leads with a topic icon
 * (so a reader scanning the column can parse pest / temperature / time-
 * since-inspection at a glance). The horizontal bar conveys magnitude;
 * the numeric SHAP value gives the precise log-odds contribution.
 *
 * Bars normalise against the largest |shap| in the list. Negative SHAP
 * (improving the score) renders sage; positive (worsening) renders terra.
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
      <ol>
        {drivers.map((d, i) => {
          const widthPct = (Math.abs(d.shap) / maxMagnitude) * 100;
          const isPositive = d.shap > 0;
          const sign = d.shap > 0 ? "+" : d.shap < 0 ? "−" : "";
          const Icon = iconForFeature(d.feature);
          return (
            <li
              key={d.feature + i}
              className={cn(
                "grid grid-cols-12 gap-4 items-center px-6 py-5",
                i < drivers.length - 1 && "border-b border-line",
              )}
            >
              <div className="col-span-1 flex items-center gap-2">
                <span
                  className={cn(
                    "inline-flex w-9 h-9 rounded-xl items-center justify-center shrink-0",
                    isPositive ? "bg-terra/10 text-terra" : "bg-sage/15 text-sage",
                  )}
                >
                  <Icon className="w-[18px] h-[18px]" strokeWidth={1.8} />
                </span>
              </div>
              <div className="col-span-6">
                <div className="flex items-center gap-2">
                  <span className="num text-muted text-[11.5px] tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div className="font-semibold">{d.label}</div>
                </div>
                {d.detail && (
                  <div className="text-[12.5px] text-muted mt-0.5">
                    {d.detail}
                  </div>
                )}
              </div>
              <div className="col-span-4">
                <div className="h-1.5 bg-tint rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      isPositive ? "bg-terra" : "bg-sage",
                    )}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
              </div>
              <div
                className={cn(
                  "col-span-1 num text-right font-medium",
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
