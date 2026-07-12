import type { RiskTier } from "@/lib/scores";
import { TIER_FG_VAR, TIER_HEX } from "@/lib/scores";

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
  // Geometry — 270° arc opening at the bottom: the two endpoints sit at
  // lower-left (225°) and lower-right (-45°), mirror images across the vertical
  // centre line, leaving a symmetric 90° gap centred at the bottom.
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 22;
  // 225° = lower-left endpoint (measured from 3 o'clock, CCW). Sweeping 270°
  // clockwise from here runs up over the top and down to the lower-right, so
  // the score fills left-to-right and the gap lands at the bottom.
  const startAngle = 225;
  const sweep = 270;

  // Clamp to [0, 1] once, and fall back to 0 for a non-finite score (NaN/±∞).
  // Both the arc geometry and the centre number derive from this, so a bad
  // input can't produce a broken SVG path or a "NaN" / "150" label.
  const frac = Number.isFinite(score) ? Math.min(1, Math.max(0, score)) : 0;

  const trackPath = arcPath(cx, cy, r, startAngle, sweep);
  const valuePath = arcPath(cx, cy, r, startAngle, sweep * frac);

  // Marker position at the score's angle.
  const markerAngle = startAngle - sweep * frac;
  const markerRad = (Math.PI / 180) * markerAngle;
  const markerX = cx + r * Math.cos(markerRad);
  const markerY = cy - r * Math.sin(markerRad);

  const display = Math.round(frac * 100);
  const color = TIER_HEX[tier];
  // Centre number takes the tier's foreground colour so the score reads as its
  // risk tier (the darker pill-text palette, not the lighter arc fill — see
  // TIER_FG_VAR).
  const numberColor = TIER_FG_VAR[tier];

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
        fill={numberColor}
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
export function arcPath(
  cx: number,
  cy: number,
  r: number,
  startAngleDeg: number,
  sweepDeg: number,
): string {
  // `!(x > 0)` (not `x <= 0`) so a NaN sweep also yields an empty path rather
  // than "M NaN NaN A …" — a zero/empty value arc just renders nothing.
  if (!(sweepDeg > 0)) return "";

  const startRad = (Math.PI / 180) * startAngleDeg;
  const endRad = (Math.PI / 180) * (startAngleDeg - sweepDeg);
  const x1 = cx + r * Math.cos(startRad);
  const y1 = cy - r * Math.sin(startRad);
  const x2 = cx + r * Math.cos(endRad);
  const y2 = cy - r * Math.sin(endRad);
  // Two independent flags:
  //  - large-arc-flag depends on the sweep SIZE (minor <180°, major >180°).
  //  - sweep-flag is the rotational DIRECTION and is constant: we always draw
  //    from startAngle toward decreasing angle, which under flipped y (screen
  //    y-down) is the clockwise sense, i.e. sweep-flag = 1.
  // Tying the sweep-flag to large-arc (the old bug) only worked for the full
  // 270° track; partial value arcs ≤180° then reversed and bulged through the
  // centre.
  const largeArc = sweepDeg > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
}
