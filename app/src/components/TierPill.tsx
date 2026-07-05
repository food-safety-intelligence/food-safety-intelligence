import { cn } from "@/lib/utils";
import type { RiskTier } from "@/lib/scores";

interface TierPillProps {
  tier: RiskTier;
  size?: "sm" | "md";
  withCount?: number;
  /**
   * Renders the pill in its "toggled off" state (transparent bg, hairline
   * border, muted text) — used by the inspectors page's tier filter chips.
   */
  inactive?: boolean;
  className?: string;
}

/**
 * Risk-tier badge. The four tier variants are spelled out so Tailwind 4 can
 * see the class strings statically and emit them into the build. Don't
 * compute these strings — Tailwind 4's CSS-first scanning won't find them
 * if they're built from template literals.
 */
export function TierPill({
  tier,
  size = "md",
  withCount,
  inactive = false,
  className,
}: TierPillProps) {
  const sizing =
    size === "sm" ? "text-2xs px-2 py-0.5" : "text-xs px-3.5 py-1.5";

  const variant = inactive
    ? "bg-transparent border border-line text-muted"
    : {
        Low: "bg-tier-low-bg text-tier-low-fg",
        Moderate: "bg-tier-mod-bg text-tier-mod-fg",
        Elevated: "bg-tier-elev-bg text-tier-elev-fg",
        High: "bg-tier-high-bg text-tier-high-fg",
      }[tier];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full font-medium tracking-[0.04em]",
        sizing,
        variant,
        className,
      )}
    >
      <span className="w-[7px] h-[7px] rounded-full bg-current" />
      {tier}
      {withCount !== undefined && (
        <span className="num text-2xs opacity-75 ml-0.5">
          {withCount.toLocaleString()}
        </span>
      )}
    </span>
  );
}

/**
 * Neutral badge for an out-of-business venue — shown in place of the tier
 * pill so a closed venue never presents its historical tier as current.
 */
export function ClosedPill({
  size = "md",
  className,
}: {
  size?: "sm" | "md";
  className?: string;
}) {
  const sizing =
    size === "sm" ? "text-2xs px-2 py-0.5" : "text-xs px-3.5 py-1.5";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full font-medium tracking-[0.04em]",
        "bg-tint text-muted",
        sizing,
        className,
      )}
    >
      <span aria-hidden="true">×</span>
      Closed
    </span>
  );
}
