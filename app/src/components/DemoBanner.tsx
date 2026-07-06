import { Info } from "lucide-react";

/**
 * Yellow demo-data notice. Shown whenever `loadScores()` returns a payload
 * with `is_mock=true`. The real production scores file will not carry that
 * flag, and this banner will not render.
 */
export function DemoBanner() {
  return (
    <div className="max-w-[1240px] mx-auto px-8 mt-6">
      <div className="rounded-3xl bg-card border border-line px-5 py-3 flex items-start gap-3 soft-shadow">
        <span className="inline-flex w-7 h-7 rounded-full bg-amber/20 items-center justify-center shrink-0 mt-0.5">
          <Info className="w-3.5 h-3.5 text-tier-mod-fg" strokeWidth={2.2} />
        </span>
        <p className="text-sm leading-relaxed">
          <span className="font-semibold">This is a research preview.</span>{" "}
          Risk scores shown here are{" "}
          <em className="serif italic text-lg mx-0.5">synthetic</em>:
          randomly generated for design review. The model is not yet trained.
          Don&apos;t make dining decisions on this page yet.
        </p>
      </div>
    </div>
  );
}
