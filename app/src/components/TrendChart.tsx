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
}

export function TrendChart({
  points,
  slope,
  width = 320,
  height = 116,
}: {
  points: TrendPoint[];
  /** Trend slope — only used for the chart's `aria-label` direction word. */
  slope: number | null;
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

  const yFor = (s: number) => padTop + h * (1 - clamp01(s));
  const xFor = (t: number) => padL + (w * (t - tMin)) / span;

  const xy = pts.map((p, i) => ({ x: xFor(times[i]), y: yFor(p.score) }));
  const linePath = xy.map((q, i) => `${i === 0 ? "M" : "L"} ${q.x} ${q.y}`).join(" ");
  const areaPath = `${linePath} L ${xy[xy.length - 1].x} ${padTop + h} L ${xy[0].x} ${padTop + h} Z`;

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
        aria-label={`Predicted-risk trajectory across ${pts.length} inspections, ${direction}`}
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
              aria-label={`${fmtFull(pts[i].date)}, predicted risk ${pts[i].score.toFixed(2)}`}
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
          className="pointer-events-none absolute z-10 whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-medium shadow-lg"
          style={{
            background: "#2A2724",
            color: "#FBF8F1",
            left: Math.min(Math.max(xy[hover].x, 60), width - 60),
            top: xy[hover].y - 10,
            transform: "translate(-50%, -100%)",
          }}
        >
          {fmtFull(pts[hover].date)} · predicted risk {pts[hover].score.toFixed(2)}
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
