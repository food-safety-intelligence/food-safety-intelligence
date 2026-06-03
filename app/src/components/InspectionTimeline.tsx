import type { InspectionEvent } from "@/lib/scores";
import { formatInspectionDate } from "@/lib/utils";

const RESULT_STYLES = {
  Pass: { bg: "bg-sage", label: "P", text: "" },
  "Pass w/ Conditions": { bg: "bg-amber", label: "!", text: "" },
  Fail: { bg: "bg-terra", label: "×", text: "text-terra" },
} as const;

type ResultKey = keyof typeof RESULT_STYLES;

function styleFor(result: string) {
  return RESULT_STYLES[result as ResultKey] ?? {
    bg: "bg-muted",
    label: "·",
    text: "",
  };
}

/**
 * Vertical timeline of inspection events. The leftmost rail is implied by
 * absolute-positioning a 2px line behind the colored dots. Renders the most
 * recent event first.
 */
export function InspectionTimeline({
  events,
  maxVisible = 9,
}: {
  events: InspectionEvent[];
  maxVisible?: number;
}) {
  if (events.length === 0) {
    return (
      <div className="rounded-3xl bg-card border border-line p-6 text-muted text-[14px]">
        No inspection history on record for this license.
      </div>
    );
  }

  // Most recent first
  const sorted = events.slice().sort((a, b) => (a.date < b.date ? 1 : -1));
  const visible = sorted.slice(0, maxVisible);
  const hidden = sorted.length - visible.length;

  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow p-6 relative">
      {/* Vertical line behind the dots */}
      <div
        className="absolute top-6 bottom-6 w-[2px] bg-line"
        style={{ left: 35 }}
      />
      <ul className="space-y-5 relative">
        {visible.map((e, i) => {
          const s = styleFor(e.result);
          const isFail = e.result === "Fail";
          return (
            <li key={`${e.date}-${i}`} className="flex items-start gap-4">
              <span
                className={`inline-flex w-6 h-6 rounded-full items-center justify-center text-[10px] font-semibold text-white ${s.bg}`}
              >
                {s.label}
              </span>
              <div className="flex-1">
                <div className="flex items-baseline justify-between">
                  <div
                    className={`font-semibold ${
                      isFail ? "text-terra" : ""
                    }`}
                  >
                    {e.result}
                  </div>
                  <div className="num text-[12px] text-muted">
                    {formatInspectionDate(e.date)}
                  </div>
                </div>
                <div
                  className={`text-[13px] mt-0.5 ${
                    isFail ? "text-ink/90" : "text-muted"
                  }`}
                >
                  {e.type}
                  {e.headline && (
                    <>
                      {" · "}
                      <span className={isFail ? "font-medium" : ""}>
                        {e.headline}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {hidden > 0 && (
        <button className="block w-full text-center text-[13px] mt-6 text-teal hover:underline">
          Show {hidden} older inspection{hidden === 1 ? "" : "s"}
        </button>
      )}
    </div>
  );
}

/**
 * Tally card for the result counts. Lives next to the timeline.
 */
export function ResultTally({ events }: { events: InspectionEvent[] }) {
  const counts: Record<string, number> = {
    Pass: 0,
    "Pass w/ Conditions": 0,
    Fail: 0,
  };
  for (const e of events) {
    if (e.result in counts) counts[e.result]++;
  }
  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow p-6">
      <div className="text-[11px] tracking-widest uppercase text-muted mb-3">
        Result tally
      </div>
      <div className="space-y-3">
        {(["Pass", "Pass w/ Conditions", "Fail"] as const).map((r) => {
          const s = styleFor(r);
          return (
            <div key={r} className="flex items-center gap-3">
              <span
                className={`inline-flex w-6 h-6 rounded-full items-center justify-center text-[10px] font-semibold text-white ${s.bg}`}
              >
                {s.label}
              </span>
              <div className="flex-1 text-[14.5px]">{r}</div>
              <div className="num font-medium">{counts[r]}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
