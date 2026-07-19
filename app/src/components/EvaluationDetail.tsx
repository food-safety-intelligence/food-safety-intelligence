/**
 * The chronological split date windows (train / validation / test), read from
 * methodology.json. Shared by the Chicago page and the NYC/LA model cards. Server
 * component (static; no interactivity). Renders nothing when the JSON predates the
 * `windows` field, so older builds degrade gracefully.
 */

import type { DateWindow } from "@/lib/methodology-server";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** "2019-01-02" -> "Jan 2019" (parsed by hand so there's no timezone shift). */
function monthYear(iso: string): string {
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
