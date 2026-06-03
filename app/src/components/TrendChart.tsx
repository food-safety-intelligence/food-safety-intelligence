import { trendDirection } from "@/lib/scores";

/**
 * Minimal 90-day trend chart. We don't ship per-restaurant historical scores
 * in scores.json (would balloon the payload), so the line is reconstructed
 * from the linear slope: past_score = current - slope * days_ago. That makes
 * it a straight line by definition; the chart is a quick visual read of
 * direction + magnitude, not a precise historical reproduction.
 *
 * For slope = null (insufficient history) we render a flat dashed baseline.
 *
 * Inline SVG, no chart library.
 */

const COLOR_BY_DIRECTION = {
  worsening: "#B8634A", // terra
  improving: "#7A8F6A", // sage
  stable: "#9CA3AF", // muted gray
} as const;

export function TrendChart({
  score,
  slope,
  typicalScore = null,
  days = 90,
  width = 320,
  height = 96,
}: {
  score: number;
  slope: number | null;
  /** Population median, used for the dashed reference midline. Pass null to
   * hide the reference. */
  typicalScore?: number | null;
  days?: number;
  width?: number;
  height?: number;
}) {
  const padX = 4;
  const padY = 10;
  const w = width - padX * 2;
  const h = height - padY * 2;

  const direction = trendDirection(slope);
  const color = COLOR_BY_DIRECTION[direction];

  // y: 0 at bottom (score=0), h at top (score=1). Flip in SVG (y grows down).
  const yFor = (s: number) => padY + h * (1 - clamp01(s));
  const xFor = (t: number) => padX + (w * t) / days; // t in [0, days]

  const midlineY = typicalScore !== null ? yFor(typicalScore) : null;

  if (slope === null) {
    // No chart at all when there's no trend to draw — a dashed line over
    // empty space reads as a glitch. Caller renders any surrounding label.
    return (
      <div
        role="status"
        aria-label="Insufficient history to compute trend"
        className="text-[12px] text-muted text-center py-3"
        style={{ width, height }}
      >
        Not enough scored inspections in the last 90 days.
      </div>
    );
  }

  // Reconstruct past score from slope. clamp so visually the line stays inside
  // the 0..1 plot area even when the linear extrapolation overshoots.
  const pastScore = clamp01(score - slope * days);

  const x0 = xFor(0);
  const xN = xFor(days);
  const y0 = yFor(pastScore);
  const yN = yFor(score);

  // Build area-fill path: line + drop to baseline.
  const areaPath = `M ${x0} ${y0} L ${xN} ${yN} L ${xN} ${padY + h} L ${x0} ${padY + h} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`90-day score trajectory, ${direction}`}
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

      {/* The line itself */}
      <line
        x1={x0}
        x2={xN}
        y1={y0}
        y2={yN}
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
      />

      {/* Past-score dot — smaller, faded */}
      <circle cx={x0} cy={y0} r={3} fill={color} fillOpacity={0.45} />

      {/* Current-score dot — emphasised */}
      <circle cx={xN} cy={yN} r={5} fill="#FFFFFF" stroke={color} strokeWidth={2.5} />

      {/* x-axis labels */}
      <text
        x={padX}
        y={height - 1}
        fontSize={9}
        fill="#9CA3AF"
        fontFamily="var(--font-manrope), 'Manrope', sans-serif"
      >
        −{days}d
      </text>
      <text
        x={width - padX}
        y={height - 1}
        textAnchor="end"
        fontSize={9}
        fill="#9CA3AF"
        fontFamily="var(--font-manrope), 'Manrope', sans-serif"
      >
        today
      </text>
    </svg>
  );
}

function clamp01(v: number): number {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}
