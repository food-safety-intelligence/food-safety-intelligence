"use client";

import { useState } from "react";
import { trendDirection } from "@/lib/scores";

/**
 * Detail-page trend chart. Plots the establishment's recent FORECAST-MODEL scores
 * (predictions — not inspection pass/fail results) at their real inspection dates:
 * the actual trajectory, not a synthetic line. Hovering or focusing a point shows
 * its date + predicted risk.
 *
 * The line/area/dots are a NEUTRAL colour on purpose (decision 0011): the
 * authoritative direction signal — the coloured Improving/Worsening/Stable arrow
 * + label — lives in the ScoreCard header, driven by `trend_slope` (a regression
 * over the points). Colouring the drawn line by first-vs-last would be noisier
 * than that slope and could visibly disagree with it, so the chart stays neutral.
 *
 * Client component for the hover tooltip.
 */

// Neutral ink-muted — the drawn trajectory carries no direction meaning of its own.
const LINE = "#6B7280";

export interface TrendPoint {
  /** ISO yyyy-mm-dd inspection date. */
  date: string;
  /** Forecast-model score (calibrated probability, 0..1). */
  score: number;
  /**
   * The actual inspection result at this date (Pass / Fail / Pass w/ Conditions).
   * Shown as context in the tooltip — NOT what the dot predicts. The dot is the
   * forecast model's read of the *next 180 days* as of this date, and it
   * deliberately ignores this visit's own outcome (see DR 0011), so this is
   * "what happened here," not "what the score predicted."
   */
  result?: string;
}

export function TrendChart({
  points,
  slope,
  windowSize,
  width = 320,
  height = 116,
}: {
  points: TrendPoint[];
  /** Trend slope — only used for the chart's `aria-label` direction word. */
  slope: number | null;
  /**
   * How many of the most-recent points form the trend window (what `slope` is
   * fit over, DR 0011). A full-height band shades that window so the long-run
   * trajectory is visible without the chart contradicting the header direction.
   * Defaults to all points (no band) when omitted.
   */
  windowSize?: number;
  width?: number;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const padL = 24; // y-axis label gutter
  const padR = 10;
  const padTop = 10;
  const padBot = 20; // x-axis date label gutter
  const w = width - padL - padR;
  const h = height - padTop - padBot;

  const direction = trendDirection(slope);

  // Oldest -> newest for left-to-right time.
  const pts = [...points].sort((a, b) => a.date.localeCompare(b.date));

  if (pts.length < 2) {
    return (
      <div
        role="status"
        aria-label="Insufficient history to compute trend"
        className="text-xs text-muted text-center py-3"
        style={{ width, height }}
      >
        Not enough scored inspections to show a trend.
      </div>
    );
  }

  const times = pts.map((p) => Date.parse(p.date));
  const tMin = times[0];
  const span = times[times.length - 1] - tMin || 1;

  const yFor = (s: number) => padTop + h * (1 - clamp01(s));
  const xFor = (t: number) => padL + (w * (t - tMin)) / span;

  const xy = pts.map((p, i) => ({ x: xFor(times[i]), y: yFor(p.score) }));
  const linePath = xy.map((q, i) => `${i === 0 ? "M" : "L"} ${q.x} ${q.y}`).join(" ");
  const areaPath = `${linePath} L ${xy[xy.length - 1].x} ${padTop + h} L ${xy[0].x} ${padTop + h} Z`;

  // Trend-window band: a full-height shade over the last `windowSize` points (the
  // visits the slope is fit over). Only drawn when older points sit outside it,
  // else it would cover the whole chart. Left edge sits midway between the last
  // out-of-window point and the first in-window one.
  const winStart = windowSize == null ? 0 : Math.max(0, pts.length - windowSize);
  const bandLeft = winStart > 0 ? (xy[winStart - 1].x + xy[winStart].x) / 2 : null;

  const fmtAxis = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", year: "numeric" });
  const fmtFull = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });

  return (
    <div style={{ position: "relative", width, height }}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Predicted-risk trajectory across ${pts.length} inspections${
          bandLeft !== null ? `, recent ${windowSize} highlighted as the trend window` : ""
        }, ${direction}`}
      >
        {/* y-axis: 0..1 risk scale (most establishments sit low). */}
        {[0, 1].map((t) => (
          <text
            key={t}
            x={padL - 5}
            y={yFor(t) + 3}
            textAnchor="end"
            fontSize={8}
            fill="#6B7280"
            fontFamily="var(--font-manrope), 'Manrope', sans-serif"
          >
            {t.toFixed(1)}
          </text>
        ))}
        <text
          x={9}
          y={padTop + h / 2}
          fontSize={8}
          fill="#6B7280"
          textAnchor="middle"
          transform={`rotate(-90 9 ${padTop + h / 2})`}
          fontFamily="var(--font-manrope), 'Manrope', sans-serif"
        >
          risk
        </text>

        {/* Trend-window band — full plot height over the most-recent points the
            slope is fit over. Drawn first so it sits behind the trajectory. */}
        {bandLeft !== null && (
          <>
            <rect
              x={bandLeft}
              y={padTop}
              width={padL + w - bandLeft}
              height={h}
              fill="#2A2724"
              fillOpacity={0.06}
            />
            <line
              x1={bandLeft}
              y1={padTop}
              x2={bandLeft}
              y2={padTop + h}
              stroke="#2A2724"
              strokeOpacity={0.25}
              strokeWidth={1}
              strokeDasharray="2 2"
            />
            {/* Right-anchored so it always sits inside the band (which ends at
                the right plot edge) — a centred label clips when the band is
                narrow. The caption below the chart carries the full wording. */}
            <text
              x={padL + w - 2}
              y={padTop + 7}
              textAnchor="end"
              fontSize={7}
              fill="#2A2724"
              fillOpacity={0.55}
              fontFamily="var(--font-manrope), 'Manrope', sans-serif"
            >
              trend
            </text>
          </>
        )}

        <path d={areaPath} fill={LINE} fillOpacity={0.08} />
        <path
          d={linePath}
          fill="none"
          stroke={LINE}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Inspection dots — latest emphasised; hover/focus reveals the tooltip. */}
        {xy.map((q, i) => {
          const isLast = i === xy.length - 1;
          const active = hover === i;
          return (
            <circle
              key={i}
              cx={q.x}
              cy={q.y}
              r={isLast || active ? 5 : 3}
              fill={isLast ? "#FFFFFF" : LINE}
              fillOpacity={isLast ? 1 : active ? 0.9 : 0.5}
              stroke={isLast || active ? LINE : "none"}
              strokeWidth={2.5}
              tabIndex={0}
              role="button"
              aria-label={`${fmtFull(pts[i].date)}, predicted risk ${pts[i].score.toFixed(2)}${
                pts[i].result ? `, inspection result ${pts[i].result}` : ""
              }`}
              style={{ cursor: "pointer", outline: "none" }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            />
          );
        })}

        {/* x-axis — real first/last inspection dates (month + full year). */}
        <text
          x={padL}
          y={height - 5}
          fontSize={8.5}
          fill="#6B7280"
          fontFamily="var(--font-manrope), 'Manrope', sans-serif"
        >
          {fmtAxis(pts[0].date)}
        </text>
        <text
          x={width - padR}
          y={height - 5}
          textAnchor="end"
          fontSize={8.5}
          fill="#6B7280"
          fontFamily="var(--font-manrope), 'Manrope', sans-serif"
        >
          {fmtAxis(pts[pts.length - 1].date)}
        </text>
      </svg>

      {/* Hover/focus tooltip — makes clear the value is a model prediction. */}
      {hover !== null && (
        <div
          className="pointer-events-none absolute z-10 whitespace-nowrap rounded-md px-2 py-1 text-2xs font-medium shadow-lg"
          style={{
            background: "#2A2724",
            color: "#FBF8F1",
            left: Math.min(Math.max(xy[hover].x, 60), width - 60),
            top: xy[hover].y - 10,
            transform: "translate(-50%, -100%)",
          }}
        >
          <div>
            {fmtFull(pts[hover].date)} · predicted risk {pts[hover].score.toFixed(2)}
          </div>
          {pts[hover].result && (
            <div className="opacity-70">
              At this inspection: {pts[hover].result}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function clamp01(v: number): number {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}
