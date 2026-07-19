/**
 * The chronological split date windows and the expanding-window cross-validation
 * results, read from methodology.json. Shared by the Chicago page and the NYC/LA
 * model cards. Server component (static; no interactivity). Renders nothing when
 * the JSON predates these fields, so older builds degrade gracefully.
 */

import type { CrossValidation, DateWindow } from "@/lib/methodology-server";

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
  cv,
}: {
  windows?: { train: DateWindow; val: DateWindow; test: DateWindow };
  cv?: CrossValidation;
}) {
  const hasCv = cv != null && cv.folds.length > 0;
  if (!windows && !hasCv) return null;

  const maxAuc = hasCv ? Math.max(...cv.folds.map((f) => f.pr_auc)) : 1;

  return (
    <div className="mt-8 space-y-6">
      {windows && (
        <div>
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
                <p className="num text-muted text-xs mt-0.5">{nf(w.n)} inspections</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasCv && (
        <div>
          <p className="text-xs uppercase tracking-[0.08em] text-sage font-medium">
            Cross-validated PR-AUC
          </p>
          <p className="text-sm text-muted leading-relaxed mt-1.5 max-w-[62ch]">
            Expanding-window cross-validation: each past calendar year is validated in
            turn, training only on earlier data with a 180-day gap so no future outcome
            leaks in.{" "}
            {cv.n_folds >= 2 ? (
              <>
                Mean{" "}
                <span className="num text-ink/85 font-medium">
                  {cv.pr_auc_mean?.toFixed(3)}
                </span>
                {cv.pr_auc_std != null && (
                  <>
                    {" "}
                    &plusmn;{" "}
                    <span className="num text-ink/85">{cv.pr_auc_std.toFixed(3)}</span>
                  </>
                )}{" "}
                across {cv.n_folds} folds.
              </>
            ) : (
              <>
                This city&apos;s usable history is short, so only one year can be held
                out: PR-AUC{" "}
                <span className="num text-ink/85 font-medium">
                  {cv.pr_auc_mean?.toFixed(3)}
                </span>{" "}
                on that fold.
              </>
            )}
          </p>
          <div className="mt-3 rounded-2xl border border-line bg-card p-4 max-w-[62ch]">
            <ul className="space-y-2">
              {cv.folds.map((f) => (
                <li key={f.val_year} className="flex items-center gap-3 text-sm">
                  <span className="num text-muted w-12 shrink-0">{f.val_year}</span>
                  <span
                    className="flex-1 h-4 rounded bg-tint overflow-hidden"
                    aria-hidden="true"
                  >
                    <span
                      className="block h-full rounded bg-sage"
                      style={{ width: `${Math.round((f.pr_auc / maxAuc) * 100)}%` }}
                    />
                  </span>
                  <span className="num text-ink/85 w-12 text-right shrink-0">
                    {f.pr_auc.toFixed(3)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <p className="text-xs text-muted leading-relaxed mt-2 max-w-[62ch]">
            Reported on the development set (train + validation); the test window above
            is never used for cross-validation.
          </p>
        </div>
      )}
    </div>
  );
}
