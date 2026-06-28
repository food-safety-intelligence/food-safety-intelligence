"""Publish a chosen model + its data artifacts to S3 (the deploy stage).

Publish-only: this uploads artifacts an earlier local run already built (features +
retrain + history). It does NOT train or re-score. Build first, then publish:

    make features retrain history     # writes the local artifacts
    make publish                      # this script -> S3

The artifacts split into two tiers:

  LIVE-APP-CRITICAL — what the Next.js app reads from S3. The app is a STATIC export
  (next.config ``output: 'export'``), so the ``app`` prebuild (``prebuild-sync-s3.mjs``)
  pulls these into a build cache and ``app/src/lib/scores-server.ts`` reads them during
  ``next build`` — at BUILD time, not per request. Publishing therefore takes effect only
  after the app is rebuilt and redeployed; uploading to S3 alone does not change the live
  site. The deploy is the ``.github/workflows/deploy-web.yml`` GitHub Actions workflow
  (push to ``main`` touching ``app/**``, or a manual ``workflow_dispatch``): it rebuilds
  the static export, ``aws s3 sync``s it to the website bucket, and invalidates CloudFront.
  NOTE: that workflow builds BEFORE configuring AWS creds, so its prebuild S3 pull fails
  and falls back to the COMMITTED ``app/public/data`` JSON — meaning what currently goes
  live is the committed copy, not this S3 upload. So after ``make publish`` you must also
  commit the matching ``app/public/data`` JSON and merge to ``main`` (or dispatch the
  workflow) for it to reach the live site; the S3 copies here are read at build time only
  when creds are present (local build / the SSR path):
      web-app-data/scores.json
      web-app-data/inspection_history.json
      web-app-data/methodology.json
      web-app-data/comments/<xx>.json   (256 full-comment shards, if built)

  ARCHIVAL — never read by the app (the batch-score-to-JSON contract means the app
  never loads the model). Kept in S3 for rollback / re-scoring / provenance:
      models/<model>_sigmoid_<run>.joblib (+ _metadata.json if present)  (VERSIONED — never overwrite)
      processed/features.parquet                                         (overwrite in place)
      processed/inspections_labeled.parquet                              (overwrite in place)
      predictions/scores.parquet                                         (overwrite in place)

The served model is model-agnostic: whichever sigmoid-calibrated model the latest retrain
wrote — ``baseline_sigmoid_<run>.joblib`` (LogReg) or ``xgb_monotone_sigmoid_<run>.joblib``
(XGBoost), per the current production estimator. It is kept VERSIONED because the binary is
gitignored — S3 is the only rollback copy. A ``<model>_metadata.json`` sidecar is published
when the retrain emits one (baseline does; XGB keeps provenance in the git-committed
reports/metrics/<run>.json instead). Everything else overwrites in place.

PICK A COHERENT SET. The model, features, scores.parquet and scores.json must come from
the SAME retrain run — retrain writes them together, so the current on-disk set is
coherent. Use the flags to publish a specific (e.g. older, for rollback) model and its
matching scores instead of the latest. ``--model`` defaults to the newest local model
matching ``--model-glob`` (``*_sigmoid_*.joblib``); the scores / features paths default to
their single current locations.

``inspections_labeled.parquet`` is the notebook-02 label output — an input, not a retrain
product — and changes only on a data refresh, so it is skipped if already in S3 unless
``--force``.

Run:
    PYTHONPATH=src uv run python scripts/publish.py --dry-run        # preview the plan
    PYTHONPATH=src uv run python scripts/publish.py                  # publish latest -> default bucket
    PYTHONPATH=src uv run python scripts/publish.py \\
        --model data/models/baseline_sigmoid_20260627_ac236faed.joblib \\
        --scores-json app/public/data/scores.json \\
        --scores-parquet data/predictions/scores.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

from foodsafety.config import FEATURES_NAME
from foodsafety.io import storage

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
WEB = REPO_ROOT / "app" / "public" / "data"
DEFAULT_DEST = "s3://food-safety-intelligence-data"


def _latest_model(models_dir: str, pattern: str) -> str:
    """Most-recent served model under ``models_dir`` matching ``pattern`` (newest mtime).

    Model-agnostic: the served model is whichever sigmoid-calibrated model a retrain
    last wrote — ``baseline_sigmoid_<run>.joblib`` (LogReg) or
    ``xgb_monotone_sigmoid_<run>.joblib`` (XGBoost), depending on the current production
    estimator. The default pattern ``*_sigmoid_*.joblib`` matches both; newest-by-mtime
    picks the one the most recent retrain produced (not lexical order — same-day reruns
    differ only by the run_id hash). Pass ``--model`` to publish a specific one.
    """
    candidates = storage.glob(models_dir, pattern)
    if not candidates:
        raise SystemExit(
            f"No model matching {pattern!r} under {models_dir}. "
            "Run a retrain (make retrain) first, or pass --model."
        )

    def _mtime(target: str) -> float:
        filesystem, path = storage.resolve(target)
        return filesystem.get_file_info(path).mtime.timestamp()

    return max(candidates, key=_mtime)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dest", default=DEFAULT_DEST, help=f"S3 base (default: {DEFAULT_DEST})")
    ap.add_argument(
        "--model",
        default=None,
        help="model joblib to publish (default: newest data/models match for --model-glob)",
    )
    ap.add_argument(
        "--model-glob",
        default="*_sigmoid_*.joblib",
        help=(
            "glob for picking the latest served model when --model is omitted "
            "(default matches baseline_sigmoid_* and xgb_monotone_sigmoid_*)"
        ),
    )
    ap.add_argument(
        "--features",
        default=str(DATA / "processed" / "features" / f"{FEATURES_NAME}.parquet"),
        help="features parquet to publish",
    )
    ap.add_argument(
        "--labeled",
        default=str(DATA / "processed" / "inspections_labeled.parquet"),
        help="labeled inspections parquet (skipped if already in S3 unless --force)",
    )
    ap.add_argument(
        "--scores-parquet",
        default=str(DATA / "predictions" / "scores.parquet"),
        help="scores.parquet to publish",
    )
    ap.add_argument(
        "--scores-json",
        default=str(WEB / "scores.json"),
        help="scores.json to publish (the app-facing file)",
    )
    ap.add_argument(
        "--src-web",
        default=str(WEB),
        help="dir holding inspection_history.json + methodology.json (default: app/public/data)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-upload inspections_labeled.parquet even if already present in S3",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the upload plan and transfer nothing",
    )
    args = ap.parse_args()

    dest = args.dest.rstrip("/")
    if not storage.is_s3(dest):
        print(f"warning: --dest {dest} is not an s3:// URI; publishing to a local path.")

    model_src = args.model or _latest_model(str(DATA / "models"), args.model_glob)

    # (source, dest, skip_if_exists). The model keeps its versioned name (never
    # overwrite); the data/score/JSON dests are stable keys that overwrite in place.
    plan: list[tuple[str, str, bool]] = [
        (model_src, storage.join(dest, "models", storage.basename(model_src)), False),
        (args.features, storage.join(dest, "processed", "features.parquet"), False),
        (
            args.labeled,
            storage.join(dest, "processed", "inspections_labeled.parquet"),
            True,  # data-refresh input, not a retrain product — skip unless --force
        ),
        (args.scores_parquet, storage.join(dest, "predictions", "scores.parquet"), False),
        (args.scores_json, storage.join(dest, "web-app-data", "scores.json"), False),
    ]
    # Model metadata sidecar, if the retrain wrote one. The baseline retrain emits a
    # `<model>_metadata.json` next to the joblib; the XGBoost retrain doesn't (its
    # provenance lives in the git-committed reports/metrics/<run>.json). So it's optional
    # — publish it when present, otherwise carry on (the model itself is the artifact).
    meta_src = model_src[: -len(".joblib")] + "_metadata.json"
    if storage.exists(meta_src):
        plan.append((meta_src, storage.join(dest, "models", storage.basename(meta_src)), False))
    else:
        print(f"note: no metadata sidecar for {storage.basename(model_src)} — skipping it")
    # The other web-app JSONs (inspection_history, methodology) from --src-web.
    # scores.json is published explicitly above; scores_mock.json is a dev fixture.
    for src in storage.glob(args.src_web, "*.json"):
        name = storage.basename(src)
        if name in ("scores.json", "scores_mock.json"):
            continue
        plan.append((src, storage.join(dest, "web-app-data", name), False))
    # Comment shards (web-app-data/comments/<xx>.json) — the app build reads these from
    # S3 too; each is ~1 MB. Empty/absent dir → glob returns [] and nothing is added.
    for src in storage.glob(storage.join(args.src_web, "comments"), "*.json"):
        name = storage.basename(src)
        plan.append((src, storage.join(dest, "web-app-data", "comments", name), False))

    print(f"Publish target: {dest}")
    print(f"  model:  {model_src}")
    print(f"  scores: {args.scores_json}")
    uploaded = 0
    for src, dst, skip_if_exists in plan:
        if not storage.exists(src):
            raise SystemExit(
                f"Missing local artifact: {src}. "
                "Run the build (make features retrain history) before publishing."
            )
        if skip_if_exists and not args.force and storage.exists(dst):
            print(f"  SKIP  {dst}  (already present; --force to re-upload)")
            continue
        print(f"  {'PLAN' if args.dry_run else 'PUT '}  {src} -> {dst}")
        if not args.dry_run:
            storage.copy(src, dst)
            uploaded += 1

    if args.dry_run:
        print("Dry run — nothing uploaded.")
    else:
        print(f"Publish complete: {uploaded} artifact(s) written to {dest}.")


if __name__ == "__main__":
    main()
