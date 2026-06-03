import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { trendDirection, type TrendDirection } from "@/lib/scores";
import { cn } from "@/lib/utils";

const STYLES: Record<
  TrendDirection,
  { label: string; color: string; Icon: typeof TrendingUp }
> = {
  worsening: { label: "Worsening", color: "text-terra", Icon: TrendingUp },
  improving: { label: "Improving", color: "text-sage", Icon: TrendingDown },
  stable: { label: "Stable", color: "text-muted", Icon: Minus },
};

interface TrendIndicatorProps {
  slope: number | null;
  /** Render compact (just icon + delta) or full (label + delta). */
  compact?: boolean;
  className?: string;
}

export function TrendIndicator({
  slope,
  compact = false,
  className,
}: TrendIndicatorProps) {
  if (slope === null) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 text-[11px] text-muted",
          className,
        )}
      >
        <span className="num">—</span>
      </span>
    );
  }
  const direction = trendDirection(slope);
  const { label, color, Icon } = STYLES[direction];
  const sign = slope > 0 ? "+" : slope < 0 ? "−" : "";
  const formatted = `${sign}${Math.abs(slope).toFixed(4)}`;

  if (compact) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 text-[13px]",
          color,
          className,
        )}
      >
        <Icon className="w-[13px] h-[13px]" strokeWidth={2.5} />
        <span className="num">{formatted}</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-[11px]",
        color,
        className,
      )}
    >
      <Icon className="w-[11px] h-[11px]" strokeWidth={2.5} />
      {label}
    </span>
  );
}
