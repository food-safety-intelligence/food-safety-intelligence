"use client";

import { useId, useState } from "react";
import type { RiskTier } from "@/lib/scores";
import { TIER_HEX, trendDirection } from "@/lib/scores";

/**
 * PROTOTYPE (throwaway) — the merged "risk trajectory" panel that folds the
 * gauge's headline number into the trend chart.
 *
 *   - horizontal TIER BANDS carry the Low/Moderate/Elevated/High meaning the
 *     ArcGauge used to (background zones + labels at the left edge);
 *   - the neutral MODEL 2 line is the forward-looking trajectory over past
 *     inspections (ignores each visit's own pass/fail — the existing chart);
 *   - the MODEL 1 `risk_score` is a distinct "current" diamond in its own right
 *     gutter, in the tier colour — the headline number shown in context (the
 *     value itself lives in the card headline, so the marker isn't re-labelled).
 *
 * No forward/extrapolated line (DR 0011: the loose direction does not predict).
 */

const LINE = "#6B7280";

// DR 0008 tier cutoffs (upper bound of each tier). Bands are drawn between them.
const TIER_BANDS: { tier: RiskTier; lo: number; hi: number }[] = [
  { tier: "Low", lo: 0, hi: 0.04 },
  { tier: "Moderate", lo: 0.04, hi: 0.13 },
  { tier: "Elevated", lo: 0.13, hi: 0.3 },
  { tier: "High", lo: 0.3, hi: 1.0 },
];

// Bands are a NEUTRAL grey ramp (higher tier = slightly darker) rather than the
// tier colours — a wall of coral/terra reads as alarm, which DR 0011 says the
// risk surface must avoid. Colour is kept only for the current-tier label, the
// current-level guide, and the value tag (the one meaningful accent).
const INK = "#2A2724";
const TIER_BAND_SHADE: Record<RiskTier, number> = {
  Low: 0.025,
  Moderate: 0.05,
  Elevated: 0.08,
  High: 0.11,
};

export interface TrendPoint {
  date: string;
  score: number;
  result?: string;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export function MergedRiskChart({
  points,
  slope,
  currentScore,
  currentTier,
  windowSize = 5,
  width = 720,
  height = 260,
}: {
  points: TrendPoint[];
  slope: number | null;
  /** Model 1 production risk_score — the headline "current" marker. */
  currentScore: number;
  currentTier: RiskTier;
  windowSize?: number;
  width?: number;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const clipId = useId();

  const padL = 34;
  const padR = 56; // right gutter for the current-value tag
  const padTop = 14;
  const padBot = 24;
  const w = width - padL - padR;
  const h = height - padTop - padBot;

  const pts = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const direction = trendDirection(slope);

  // Auto-scale the y-axis to what matters — the recent window + the current
  // score + a robust p90 of the whole series — so one ancient spike can't
  // squash the recent trajectory into a sliver (older outliers clamp at top).
  const scores = pts.map((p) => p.score);
  const recent = pts.slice(-windowSize).map((p) => p.score);
  const sorted = [...scores].sort((a, b) => a - b);
  const p90 = sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.9))] : 0;
  const focusMax = Math.max(currentScore, ...(recent.length ? recent : [0]), p90, 0.05);
  const yMax = clamp(Math.ceil(focusMax * 1.2 * 20) / 20, 0.15, 1);

  const yFor = (s: number) => padTop + h * (1 - Math.min(s, yMax) / yMax);
  const times = pts.map((p) => Date.parse(p.date));
  const dataMin = times[0] ?? 0;
  const dataMax = times[times.length - 1] ?? 1;
  const span = dataMax - dataMin || 1;
  const xFor = (t: number) => padL + (w * (t - dataMin)) / span;

  const xy = pts.map((p, i) => ({ x: xFor(times[i]), y: yFor(p.score) }));
  const linePath = xy.map((q, i) => `${i === 0 ? "M" : "L"} ${q.x} ${q.y}`).join(" ");
  const areaPath =
    xy.length > 0
      ? `${linePath} L ${xy[xy.length - 1].x} ${padTop + h} L ${xy[0].x} ${padTop + h} Z`
      : "";

  const winStart = Math.max(0, pts.length - windowSize);
  const bandLeft = winStart > 0 ? (xy[winStart - 1].x + xy[winStart].x) / 2 : null;

  // Current assessment (Model 1) shown as a value tag pinned to the right axis
  // at its risk level — no leader line. Clamped off the top/bottom gutters so
  // the tag text never clips the axis labels.
  const curY = yFor(currentScore);
  const tagY = clamp(curY, padTop + 9, padTop + h - 9);

  const fmtAxis = (ms: number) =>
    new Date(ms).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
  const fmtFull = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });

  return (
    <div style={{ position: "relative", width: "100%", maxWidth: width }}>
      <svg
        width="100%"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Predicted-risk trajectory across ${pts.length} inspections, ${direction}; current risk ${currentScore.toFixed(2)}, ${currentTier}`}
      >
        {/* Tier bands — background zones up to the visible yMax, labelled at the
            LEFT edge so they never collide with the right-gutter marker. */}
        {TIER_BANDS.map((b) => {
          if (b.lo >= yMax) return null;
          const top = yFor(Math.min(b.hi, yMax));
          const bot = yFor(b.lo);
          const isCur = b.tier === currentTier;
          const labelY = clamp((top + bot) / 2 + 3, top + 10, bot - 3);
          return (
            <g key={b.tier}>
              <rect
                x={padL}
                y={top}
                width={w}
                height={Math.max(0, bot - top)}
                fill={INK}
                fillOpacity={TIER_BAND_SHADE[b.tier] + (isCur ? 0.025 : 0)}
              />
              <text
                x={padL + 5}
                y={labelY}
                textAnchor="start"
                fontSize={9}
                fill={isCur ? TIER_HEX[b.tier] : "#6B7280"}
                fillOpacity={isCur ? 0.95 : 0.7}
                fontFamily="var(--font-manrope), sans-serif"
                fontWeight={isCur ? 700 : 500}
              >
                {b.tier}
              </text>
            </g>
          );
        })}

        {/* y-axis ticks */}
        {[0, yMax].map((t) => (
          <text
            key={t}
            x={padL - 6}
            y={yFor(t) + 3}
            textAnchor="end"
            fontSize={9}
            fill="#6B7280"
            fontFamily="var(--font-manrope), sans-serif"
          >
            {t.toFixed(2)}
          </text>
        ))}

        <defs>
          <clipPath id={clipId}>
            <rect x={padL} y={padTop} width={w} height={h} />
          </clipPath>
        </defs>

        <g clipPath={`url(#${clipId})`}>
          {/* Trend window = the last K visits the direction is fit over. Marked
              with a single dashed divider + label (NOT a grey fill) so it can't
              be confused with the horizontal tier ramp. */}
          {bandLeft !== null && (
            <>
              <line x1={bandLeft} y1={padTop} x2={bandLeft} y2={padTop + h} stroke={INK} strokeOpacity={0.3} strokeWidth={1} strokeDasharray="3 3" />
              <text x={padL + w - 3} y={padTop + 8} textAnchor="end" fontSize={8} fill={INK} fillOpacity={0.5} fontFamily="var(--font-manrope), sans-serif">
                trend window
              </text>
            </>
          )}

          {areaPath && <path d={areaPath} fill={LINE} fillOpacity={0.08} />}
          {xy.length > 1 && (
            <path d={linePath} fill="none" stroke={LINE} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          )}

          {xy.map((q, i) => {
            const active = hover === i;
            const isLast = i === xy.length - 1;
            return (
              <circle
                key={i}
                cx={q.x}
                cy={q.y}
                r={isLast || active ? 4.5 : 3}
                fill={isLast ? "#FFFFFF" : LINE}
                fillOpacity={isLast ? 1 : active ? 0.9 : 0.5}
                stroke={isLast || active ? LINE : "none"}
                strokeWidth={2}
                tabIndex={0}
                role="button"
                aria-label={`${fmtFull(pts[i].date)}, predicted risk ${pts[i].score.toFixed(2)}${pts[i].result ? `, result ${pts[i].result}` : ""}`}
                style={{ cursor: "pointer", outline: "none" }}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
              />
            );
          })}
        </g>

        {/* Current assessment (Model 1) — a faint horizontal guide marks the
            current risk level across the trajectory + tier bands, and a value
            tag sits on the right axis at that level. No leader line; the tag's
            position vs the last trajectory dot shows how today's result moved
            the assessment off the underlying trend. */}
        <line
          x1={padL}
          y1={tagY}
          x2={padL + w}
          y2={tagY}
          stroke={TIER_HEX[currentTier]}
          strokeOpacity={0.3}
          strokeWidth={1}
          strokeDasharray="4 3"
        />
        <g transform={`translate(${padL + w} ${tagY})`}>
          <path d="M 0 0 L 7 -5 L 7 5 Z" fill={TIER_HEX[currentTier]} />
          <rect x={6} y={-9} width={40} height={18} rx={4} fill={TIER_HEX[currentTier]} />
          <text
            x={26}
            y={4}
            textAnchor="middle"
            fontSize={11}
            fontWeight={700}
            fill="#FFFFFF"
            fontFamily="var(--font-manrope), sans-serif"
          >
            {currentScore.toFixed(2)}
          </text>
        </g>

        {/* x-axis */}
        <text x={padL} y={height - 6} fontSize={9} fill="#6B7280" fontFamily="var(--font-manrope), sans-serif">
          {times.length ? fmtAxis(dataMin) : ""}
        </text>
        <text x={padL + w} y={height - 6} textAnchor="end" fontSize={9} fill="#6B7280" fontFamily="var(--font-manrope), sans-serif">
          {times.length ? fmtAxis(dataMax) : ""}
        </text>
      </svg>

      {hover !== null && xy[hover] && (
        <div
          className="pointer-events-none absolute z-10 whitespace-nowrap rounded-md px-2 py-1 text-2xs font-medium shadow-lg"
          style={{
            background: "#2A2724",
            color: "#FBF8F1",
            left: `${(xy[hover].x / width) * 100}%`,
            top: xy[hover].y - 10,
            transform: "translate(-50%, -100%)",
          }}
        >
          <div>{fmtFull(pts[hover].date)} · predicted risk {pts[hover].score.toFixed(2)}</div>
          {pts[hover].result && <div className="opacity-70">At this inspection: {pts[hover].result}</div>}
        </div>
      )}
    </div>
  );
}
