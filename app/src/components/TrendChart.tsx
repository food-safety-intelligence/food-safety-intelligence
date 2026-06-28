import { trendDirection } from "@/lib/scores";

/**
 * Detail-page trend chart. Plots the establishment's recent forecast-model
 * scores at their REAL inspection dates (decision 0010) — the actual trajectory,
 * not a synthetic straight line. Colour follows the same trend direction the
 * indicator shows.
 *
 * Needs >=2 scored inspections; otherwise renders an "insufficient history" note.
 * Inline SVG, no chart library.
 */

const COLOR_BY_DIRECTION = {
  worsening: "#B8634A", // terra
  improving: "#7A8F6A", // sage
  stable: "#9CA3AF", // muted gray
} as const;

export interface TrendPoint {
  /** ISO yyyy-mm-dd inspection date. */
  date: string;
  /** Forecast-model score (calibrated probability, 0..1). */
  score: number;
}

export function TrendChart({
  points,
  slope,
  typicalScore = null,
  width = 320,
  height = 96,
}: {
  points: TrendPoint[];
  /** Trend slope — used only to pick the direction colour (matches the indicator). */
  slope: number | null;
  /** Population median, for the dashed reference midline. Null hides it. */
  typicalScore?: number | null;
  width?: number;
  height?: number;
}) {
  const padX = 8;
  const padY = 10;
  const w = width - padX * 2;
  const h = height - padY * 2;

  const direction = trendDirection(slope);
  const color = COLOR_BY_DIRECTION[direction];

  // Oldest -> newest for left-to-right time.
  const pts = [...points].sort((a, b) => a.date.localeCompare(b.date));

  if (pts.length < 2) {
    return (
      <div
        role="status"
        aria-label="Insufficient history to compute trend"
        className="text-[12px] text-muted text-center py-3"
        style={{ width, height }}
      >
        Not enough scored inspections to show a trend.
      </div>
    );
  }

  const times = pts.map((p) => Date.parse(p.date));
  const tMin = times[0];
  const span = times[times.length - 1] - tMin || 1;

  const yFor = (s: number) => padY + h * (1 - clamp01(s));
  const xFor = (t: number) => padX + (w * (t - tMin)) / span;

  const xy = pts.map((p, i) => ({ x: xFor(times[i]), y: yFor(p.score) }));
  const linePath = xy.map((q, i) => `${i === 0 ? "M" : "L"} ${q.x} ${q.y}`).join(" ");
  const areaPath = `${linePath} L ${xy[xy.length - 1].x} ${padY + h} L ${xy[0].x} ${padY + h} Z`;

  const midlineY = typicalScore !== null ? yFor(typicalScore) : null;
  const fmt = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  const fmtFull = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Forecast-score trajectory across ${pts.length} inspections, ${direction}`}
    >
      {/* Typical-score reference midline — population median, passed in. */}
      {midlineY !== null && typicalScore !== null && (
        <>
          <line
            x1={padX}
            x2={width - padX}
            y1={midlineY}
            y2={midlineY}
            stroke="#EDE6D8"
            strokeWidth={1}
            strokeDasharray="2 4"
          />
          <text
            x={width - padX}
            y={midlineY - 4}
            textAnchor="end"
            fontSize={9}
            fill="#9CA3AF"
            fontFamily="var(--font-manrope), 'Manrope', sans-serif"
          >
            typical {typicalScore.toFixed(2)}
          </text>
        </>
      )}

      {/* Area fill — soft tint of the direction colour */}
      <path d={areaPath} fill={color} fillOpacity={0.1} />

      {/* The trajectory line through the real points */}
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Inspection dots — latest emphasised. Each carries a native tooltip
          (inspection date + forecast score) revealed on hover. */}
      {xy.map((q, i) => {
        const isLast = i === xy.length - 1;
        return (
          <circle
            key={i}
            cx={q.x}
            cy={q.y}
            r={isLast ? 5 : 3}
            fill={isLast ? "#FFFFFF" : color}
            fillOpacity={isLast ? 1 : 0.45}
            stroke={isLast ? color : undefined}
            strokeWidth={isLast ? 2.5 : undefined}
          >
            <title>{`${fmtFull(pts[i].date)} · risk ${pts[i].score.toFixed(2)}`}</title>
          </circle>
        );
      })}

      {/* x-axis labels — real first/last inspection dates */}
      <text
        x={padX}
        y={height - 1}
        fontSize={9}
        fill="#9CA3AF"
        fontFamily="var(--font-manrope), 'Manrope', sans-serif"
      >
        {fmt(pts[0].date)}
      </text>
      <text
        x={width - padX}
        y={height - 1}
        textAnchor="end"
        fontSize={9}
        fill="#9CA3AF"
        fontFamily="var(--font-manrope), 'Manrope', sans-serif"
      >
        {fmt(pts[pts.length - 1].date)}
      </text>
    </svg>
  );
}

function clamp01(v: number): number {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}
