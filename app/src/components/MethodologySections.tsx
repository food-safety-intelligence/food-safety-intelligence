/**
 * The shared, static blocks of the how-it-works methodology sections: the
 * train/validation/test window cards, the feature inventory, and the
 * chronological-split explanation. Used by all three cities so each one
 * describes its split and its inputs the same way.
 *
 * Server components (no interactivity), so Chicago's server-rendered page can
 * use them directly and the NYC/LA client components can import them too.
 * Anything windows-driven renders nothing (or drops the dates) when the JSON
 * predates the `windows` field, so older builds degrade gracefully.
 */

import type { ReactNode } from "react";
import type { DateWindow } from "@/lib/methodology-server";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** "2019-01-02" -> "Jan 2019" (parsed by hand so there's no timezone shift). */
export function monthYear(iso: string): string {
  const [y, m] = iso.split("-");
  const idx = Number(m) - 1;
  return idx >= 0 && idx < 12 ? `${MONTHS[idx]} ${y}` : iso;
}

function nf(n: number): string {
  return n.toLocaleString("en-US");
}

export function EvaluationDetail({
  windows,
}: {
  windows?: { train: DateWindow; val: DateWindow; test: DateWindow };
}) {
  if (!windows) return null;

  const total = windows.train.n + windows.val.n + windows.test.n;
  const pct = (n: number) => (total > 0 ? Math.round((n / total) * 100) : 0);

  return (
    <div className="mt-8">
      <p className="text-xs uppercase tracking-[0.08em] text-sage font-medium">
        Train / validation / test windows
      </p>
      <div className="mt-2 grid gap-3 sm:grid-cols-3">
        {(
          [
            ["Training", windows.train],
            ["Validation", windows.val],
            ["Test (held out)", windows.test],
          ] as const
        ).map(([label, w]) => (
          <div key={label} className="rounded-2xl border border-line bg-card p-4">
            <p className="text-xs uppercase tracking-[0.08em] text-sage font-medium">
              {label}
            </p>
            <p className="num text-ink/85 text-sm mt-1.5">
              {monthYear(w.start)} to {monthYear(w.end)}
            </p>
            <p className="num text-muted text-xs mt-0.5">
              {nf(w.n)} inspections · {pct(w.n)}%
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
/** One bucket of the model's inputs, as shown in "What the model looks at". */
export interface FeatureGroup {
  /** Bucket name, e.g. "Prior history". */
  name: string;
  /** How many of the model's features are in this bucket. */
  count: number;
  /** Plain-language description of what the bucket contains. */
  detail: string;
}

/**
 * "What the model looks at" — the feature inventory, grouped, with a count per
 * group and a stated total. Shared so every city describes its inputs the same
 * way rather than one city getting a bulleted breakdown and the others a
 * paragraph. `total` is the model's real feature count; the group counts sum
 * to it, so a reader can check the list is complete.
 */
export function FeatureGroups({
  total,
  groups,
  lead,
}: {
  total: number;
  groups: FeatureGroup[];
  lead?: ReactNode;
}) {
  return (
    <>
      <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
        {total} features, all built leak-free from the public record{lead ? <> {lead}</> : null}:
      </p>
      <ul className="text-md leading-relaxed mt-3 space-y-2 list-disc pl-5 text-ink/85 max-w-[62ch]">
        {groups.map((g) => (
          <li key={g.name}>
            <span className="font-medium">{g.name}</span>{" "}
            <span className="num text-muted text-sm">({g.count})</span>: {g.detail}
          </li>
        ))}
      </ul>
    </>
  );
}

/**
 * "Tested on the future, not the past" — the chronological-split explanation,
 * with the actual boundaries read from methodology.json's `windows` rather than
 * written into the copy, so they can't drift from the served model. Falls back
 * to the explanation alone when a build predates the `windows` field.
 */
export function ChronologicalSplit({
  windows,
}: {
  windows?: { train: DateWindow; val: DateWindow; test: DateWindow };
}) {
  return (
    <article>
      <h2 className="text-2xl font-medium tracking-tight">
        Tested on the future, not the past
      </h2>
      <p className="text-muted leading-[1.7] mt-3 max-w-[62ch]">
        Train, validation, and test are carved by date, not shuffled.
        {windows ? (
          <>
            {" "}We <span className="font-medium">train</span> on inspections from{" "}
            {monthYear(windows.train.start)} to {monthYear(windows.train.end)},{" "}
            <span className="font-medium">calibrate</span> on{" "}
            {monthYear(windows.val.start)} to {monthYear(windows.val.end)}, and{" "}
            <span className="font-medium">test</span> on{" "}
            {monthYear(windows.test.start)} to {monthYear(windows.test.end)}.
          </>
        ) : null}{" "}
        Every feature at a given inspection is computed only from data strictly
        before it. A random shuffle would let the model peek at an
        establishment&apos;s future to predict its past, inflating the score into a
        number that would never hold up in production. The chronological split
        mirrors how the model is actually used: trained on history, scored on what
        comes next.
      </p>
    </article>
  );
}
