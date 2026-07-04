import clsx, { type ClassValue } from "clsx";

/**
 * Tiny className combiner. Keeps JSX readable when conditionally combining
 * Tailwind utility classes. We avoid `tailwind-merge` for now because the
 * theme is small and we don't have conflicting utility overrides.
 */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}

export function formatScore(score: number): string {
  return score.toFixed(2);
}

export function formatDelta(delta: number): string {
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  return `${sign}${Math.abs(delta).toFixed(4)}`;
}

/**
 * Human-readable inspection date. Static format chosen to be unambiguous
 * across locales: "22 May 2026".
 */
export function formatInspectionDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]} ${y}`;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// ---------------------------------------------------------------------------
// Trend-chart zoom. The visible window is held as [start, end] FRACTIONS of the
// full time span (0..1). Shared so the inline chart's +/- buttons and the
// enlarge modal's wheel/pinch/drag narrow the window identically.
// ---------------------------------------------------------------------------

/**
 * Floor on the visible fraction of the full time span — caps zoom at ~25x so a
 * dense history can be opened up without zooming past a couple of points.
 */
export const TREND_MIN_WIDTH = 0.04;

export function clampFrac(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

/**
 * Narrow the [start, end] window toward `focus` (0..1 across the plot), keeping
 * the focused instant fixed under the pointer. `factor` < 1 zooms in, > 1 out.
 */
export function applyTrendZoom(
  start: number,
  end: number,
  focus: number,
  factor: number,
): [number, number] {
  const width = end - start;
  const domainFrac = start + focus * width;
  const nw = clampFrac(width * factor, TREND_MIN_WIDTH, 1);
  const ns = clampFrac(domainFrac - focus * nw, 0, 1 - nw);
  return [ns, ns + nw];
}

/** Slide the window by a pixel delta, holding its width. */
export function applyTrendPan(
  start: number,
  end: number,
  dxPx: number,
  rectW: number,
): [number, number] {
  const width = end - start;
  const dFrac = (dxPx / rectW) * width;
  const ns = clampFrac(start - dFrac, 0, 1 - width);
  return [ns, ns + width];
}

// ---------------------------------------------------------------------------
// Trend-chart x-axis ticks. "Nice" calendar ticks across the visible range so
// labels land on round dates, and the unit shrinks as the view zooms in (year →
// half → quarter → month → week → day) — giving more, finer date ticks the
// further you zoom. All arithmetic is UTC to stay aligned with the yyyy-mm-dd
// inspection dates.
// ---------------------------------------------------------------------------

export interface DateTick {
  ms: number;
  label: string;
}

const DAY_MS = 86400000;

// Step ladder, coarsest granularity chosen so the tick count is near `target`.
// `unit` drives alignment: "day" steps snap to day boundaries, "month" steps to
// month boundaries (multiples of `size` months, so quarters/halves land on
// Jan/Apr/Jul/Oct etc.), "year" steps to Jan 1 on multiples of `size` years.
const TICK_STEPS: { unit: "day" | "month" | "year"; size: number; approxDays: number }[] = [
  { unit: "day", size: 1, approxDays: 1 },
  { unit: "day", size: 2, approxDays: 2 },
  { unit: "day", size: 7, approxDays: 7 },
  { unit: "day", size: 14, approxDays: 14 },
  { unit: "month", size: 1, approxDays: 30 },
  { unit: "month", size: 3, approxDays: 91 },
  { unit: "month", size: 6, approxDays: 182 },
  { unit: "year", size: 1, approxDays: 365 },
  { unit: "year", size: 2, approxDays: 730 },
  { unit: "year", size: 5, approxDays: 1825 },
  { unit: "year", size: 10, approxDays: 3650 },
];

function fmtDay(ms: number): string {
  const d = new Date(ms);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}
function fmtMonthYear(ms: number): string {
  const d = new Date(ms);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function dateAxisTicks(startMs: number, endMs: number, target: number): DateTick[] {
  const span = Math.max(1, endMs - startMs);
  const idealDays = span / DAY_MS / Math.max(2, target);
  const step = TICK_STEPS.find((s) => s.approxDays >= idealDays) ?? TICK_STEPS[TICK_STEPS.length - 1];

  const ticks: DateTick[] = [];
  if (step.unit === "day") {
    const stepMs = step.size * DAY_MS;
    // First day-boundary at or after startMs.
    let t = Math.ceil(startMs / DAY_MS) * DAY_MS;
    for (; t <= endMs; t += stepMs) ticks.push({ ms: t, label: fmtDay(t) });
  } else if (step.unit === "year") {
    let year = Math.ceil(new Date(startMs).getUTCFullYear() / step.size) * step.size;
    let t = Date.UTC(year, 0, 1);
    while (t < startMs) {
      year += step.size;
      t = Date.UTC(year, 0, 1);
    }
    for (; t <= endMs; year += step.size, t = Date.UTC(year, 0, 1)) {
      ticks.push({ ms: t, label: String(year) });
    }
  } else {
    // Sub-year month steps (1, 3, 6): align to a month that's a multiple of size.
    const d0 = new Date(startMs);
    let year = d0.getUTCFullYear();
    let month = Math.ceil(d0.getUTCMonth() / step.size) * step.size;
    const norm = () => {
      while (month > 11) {
        month -= 12;
        year += 1;
      }
    };
    norm();
    let t = Date.UTC(year, month, 1);
    while (t < startMs) {
      month += step.size;
      norm();
      t = Date.UTC(year, month, 1);
    }
    while (t <= endMs) {
      ticks.push({ ms: t, label: fmtMonthYear(t) });
      month += step.size;
      norm();
      t = Date.UTC(year, month, 1);
    }
  }

  // Degenerate span (all inspections near the same instant) — label the edges.
  if (ticks.length === 0) {
    return [
      { ms: startMs, label: fmtMonthYear(startMs) },
      { ms: endMs, label: fmtMonthYear(endMs) },
    ];
  }
  return ticks;
}
