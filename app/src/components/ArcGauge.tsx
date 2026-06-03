import type { RiskTier } from "@/lib/scores";
import { TIER_HEX } from "@/lib/scores";

/**
 * 270° arc gauge — the design's score-screen.png centerpiece. Renders the
 * model's calibrated probability as a number out of 100 (multiplied for
 * display), with a needle marker at the score's position along the arc.
 *
 * Inline SVG rather than a chart library: ~80 LOC, no extra bundle weight.
 */
export function ArcGauge({
  score,
  tier,
  size = 220,
}: {
  score: number; // 0..1
  tier: RiskTier;
  size?: number;
}) {
  // Geometry — 270° arc centred on bottom-left-to-bottom-right, opening down.
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 22;
  const startAngle = 135; // degrees from 3 o'clock, going CCW
  const endAngle = -135; // 135° + 270° span
  const sweep = 270;

  const trackPath = arcPath(cx, cy, r, startAngle, sweep);
  const valuePath = arcPath(cx, cy, r, startAngle, sweep * Math.min(1, Math.max(0, score)));

  // Marker position at the score's angle.
  const markerAngle = startAngle - sweep * Math.min(1, Math.max(0, score));
  const markerRad = (Math.PI / 180) * markerAngle;
  const markerX = cx + r * Math.cos(markerRad);
  const markerY = cy - r * Math.sin(markerRad);

  const display = Math.round(score * 100);
  const color = TIER_HEX[tier];

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Risk score ${display} out of 100, tier ${tier}`}
    >
      {/* Track */}
      <path
        d={trackPath}
        stroke="#EDE6D8"
        strokeWidth={14}
        fill="none"
        strokeLinecap="round"
      />
      {/* Value */}
      <path
        d={valuePath}
        stroke={color}
        strokeWidth={14}
        fill="none"
        strokeLinecap="round"
      />
      {/* Marker dot — sits on top of the value path at the score angle */}
      <circle
        cx={markerX}
        cy={markerY}
        r={9}
        fill="#FFFFFF"
        stroke={color}
        strokeWidth={3}
      />

      {/* Center label */}
      <text
        x={cx}
        y={cy + 2}
        textAnchor="middle"
        dominantBaseline="central"
        className="num"
        fontFamily="var(--font-plex-sans), 'IBM Plex Sans', sans-serif"
        fontSize={size * 0.32}
        fontWeight={600}
        fill="#2B3239"
      >
        {display}
      </text>
      <text
        x={cx}
        y={cy + size * 0.22}
        textAnchor="middle"
        fontFamily="var(--font-manrope), 'Manrope', sans-serif"
        fontSize={11}
        fontWeight={600}
        letterSpacing={1.6}
        fill="#6B7280"
      >
        / 100
      </text>
    </svg>
  );
}

/**
 * Build the SVG path string for an arc centred at (cx, cy) of radius r,
 * starting at `startAngleDeg` (measured from +x axis, CCW) and sweeping
 * `sweepDeg` degrees clockwise (decreasing angle).
 */
function arcPath(
  cx: number,
  cy: number,
  r: number,
  startAngleDeg: number,
  sweepDeg: number,
): string {
  if (sweepDeg <= 0) return "";

  const startRad = (Math.PI / 180) * startAngleDeg;
  const endRad = (Math.PI / 180) * (startAngleDeg - sweepDeg);
  const x1 = cx + r * Math.cos(startRad);
  const y1 = cy - r * Math.sin(startRad);
  const x2 = cx + r * Math.cos(endRad);
  const y2 = cy - r * Math.sin(endRad);
  // SVG sweep-flag=0 means CCW (visually CW because y is flipped).
  const largeArc = sweepDeg > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 0 ${x2} ${y2}`;
}
