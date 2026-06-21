import type { Driver } from "@/lib/scores";
import { iconForFeature } from "@/lib/driver-icons";
import { descriptionForFeature } from "@/lib/driver-descriptions";
import { glossaryKeyForFeature } from "@/lib/glossary";
import { DefineTerm } from "@/components/DefineTerm";
import { cn } from "@/lib/utils";

/**
 * Pure geometry for one diverging driver bar. The bar spans up to half the
 * track on its side, sized by this factor's |shap| relative to the largest
 * |shap| in the list. `maxMagnitude <= 0` (every contribution zero, or an empty
 * list) falls back to a denominator of 1 so the width is 0, not `NaN%`.
 */
export function driverBarGeometry(
  shap: number,
  maxMagnitude: number,
): { isPositive: boolean; sign: "+" | "−" | ""; halfPct: number } {
  const denom = maxMagnitude > 0 ? maxMagnitude : 1;
  return {
    isPositive: shap > 0,
    sign: shap > 0 ? "+" : shap < 0 ? "−" : "",
    halfPct: (Math.abs(shap) / denom) * 50,
  };
}

/**
 * Ranked drivers as a diverging bar chart. Each row leads with a topic icon
 * (so a reader scanning the column can parse pest / temperature / time-since-
 * inspection at a glance) and a plain-English label. The bar diverges from a
 * centre zero axis: factors that RAISE risk extend right (terra), factors that
 * LOWER it extend left (sage). The signed value gives the precise log-odds
 * contribution.
 *
 * Layout is responsive: on desktop the icon, label, bar, and value sit in one
 * 12-col row; on mobile (where a half-column bar reads as a floating dot and
 * the value clips) the row stacks — icon + label + value on top, a full-width
 * diverging bar below.
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
      {/* Axis legend — full width on mobile (bars stack full width below each
          label); aligned over the bar column on desktop. */}
      <div className="px-5 sm:px-6 pt-5 pb-2 border-b border-line">
        <div className="flex justify-center gap-8 text-[11px] uppercase tracking-[0.12em] sm:grid sm:grid-cols-12 sm:gap-4">
          <span className="text-sage-strong sm:col-start-7 sm:col-span-3 sm:text-right">
            &larr; lowers risk
          </span>
          <span className="text-terra-strong sm:col-start-10 sm:col-span-2 sm:text-left">
            raises risk &rarr;
          </span>
        </div>
      </div>

      <ol>
        {drivers.map((d, i) => {
          const { isPositive, sign, halfPct } = driverBarGeometry(d.shap, maxMagnitude);
          const Icon = iconForFeature(d.feature);
          // Prefer a server-provided detail; otherwise explain the feature.
          const description = d.detail || descriptionForFeature(d.feature);
          // If this factor maps to a defined term, offer an in-context definition.
          const termKey = glossaryKeyForFeature(d.feature);
          const barStyle = isPositive
            ? { left: "50%", width: `${halfPct}%` }
            : { right: "50%", width: `${halfPct}%` };
          const direction = isPositive ? "raises" : "lowers";
          const rowTitle = `${d.label} — ${direction} risk by ${Math.abs(d.shap).toFixed(2)} (log-odds contribution)`;
          return (
            <li
              key={d.feature + i}
              title={rowTitle}
              className={cn(
                // mobile: icon | label | value on row 1, full-width bar on row 2;
                // desktop: original single-row 12-col grid (bar between label
                // and value via order utilities).
                "grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-2.5 px-5 py-4",
                "sm:grid-cols-12 sm:gap-4 sm:gap-y-0 sm:px-6 sm:py-5",
                i < drivers.length - 1 && "border-b border-line",
              )}
            >
              <span
                className={cn(
                  "inline-flex w-9 h-9 rounded-xl items-center justify-center shrink-0 sm:col-span-1",
                  isPositive ? "bg-terra/10 text-terra" : "bg-sage/15 text-sage",
                )}
              >
                <Icon className="w-[18px] h-[18px]" strokeWidth={1.8} />
              </span>

              <div className="min-w-0 sm:col-span-5">
                <div className="flex items-center gap-2">
                  <span className="num text-muted text-[11.5px] tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div className="font-semibold">{d.label}</div>
                  {termKey && <DefineTerm termKey={termKey} />}
                </div>
                {description && (
                  <div className="text-[12.5px] text-muted mt-0.5 leading-snug">
                    {description}
                  </div>
                )}
              </div>

              <div
                className={cn(
                  "num text-right font-medium tabular-nums shrink-0 sm:col-span-1 sm:order-last",
                  isPositive ? "text-terra-strong" : "text-sage-strong",
                )}
              >
                {sign}
                {Math.abs(d.shap).toFixed(2)}
              </div>

              <div className="col-span-3 sm:col-span-5">
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
            </li>
          );
        })}
      </ol>
      <p className="px-5 sm:px-6 py-4 text-[12px] text-muted leading-relaxed border-t border-line">
        Bar length shows each factor&apos;s relative influence; the number is its
        log-odds contribution to this food establishment&apos;s risk (larger
        magnitude = more influence). These show what moves the score up or down,
        not a sum equal to it.
      </p>
    </div>
  );
}
