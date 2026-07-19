"""Paired bootstrap CIs for the DL-vs-XGB / ensemble deltas from run_torch_dl_hpo.py.

The HPO run left best configs and point-estimate test metrics, but the gaps are small:
tuned DL sits ~0.01 PR-AUC behind XGB, while the DL-consensus ensemble runs ~0.009 P@10
*ahead*. This settles whether either is real or just test-set sampling noise. It refits
XGB + each tuned DL on the same split (best configs read from the HPO log), rebuilds the
ensembles, and paired-bootstraps the test set: resample rows with replacement, recompute
PR-AUC and precision@10%, and take each method's delta vs XGB on the SAME resample. The
pairing removes the shared test-draw variance, so the delta CI is what matters.

    PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> \
        .venv-torch/bin/python scripts/run_torch_bootstrap_ci.py --iters 2000
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score

from foodsafety.models.baseline import LABEL_COL
from foodsafety.models.evaluate import precision_at_k
from foodsafety.utils.time import temporal_split

# scripts/ is not an installed package; add the repo root so the sibling harnesses import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.run_torch_tabular_benchmark as B  # noqa: E402
from scripts.run_torch_dl_hpo import (  # noqa: E402
    _ranks,
    fit_predict_dl,
    xgb_val_test_probs,
)

OUT_DIR = Path(__file__).resolve().parents[1] / "reports" / "metrics" / "mlp"
DL_KINDS = ("ft", "resnet", "tabm")


def latest_hpo_log() -> Path:
    logs = sorted(glob.glob(str(OUT_DIR / "torch_dl_hpo_*.json")))
    if not logs:
        raise FileNotFoundError("no torch_dl_hpo_*.json found; run run_torch_dl_hpo.py first")
    return Path(logs[-1])


def ci(a: np.ndarray) -> tuple[float, float]:
    return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--hpo-log", default=None, help="path to a torch_dl_hpo_*.json (default: latest)"
    )
    ap.add_argument("--iters", type=int, default=2000, help="bootstrap resamples")
    ap.add_argument("--final-epochs", type=int, default=60)
    ap.add_argument("--final-patience", type=int, default=8)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    args = ap.parse_args()

    import torch

    torch.set_num_threads(args.threads)
    B.DEVICE = (
        ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    )

    hpo_path = Path(args.hpo_log) if args.hpo_log else latest_hpo_log()
    hpo = json.loads(hpo_path.read_text())
    best = {k: hpo["results"][k] for k in DL_KINDS}
    print(f"device={B.DEVICE} | best configs from {hpo_path.name}")

    modelable = B.load_modelable()
    num_f, cat_f = B.split_feature_types(modelable)
    sp = temporal_split(modelable, train_end=B.TRAIN_END, val_end=B.VAL_END)
    yte = sp.test[LABEL_COL].astype(int).to_numpy()
    n = len(yte)
    seeds = (42, 7, 123)

    # --- per-row test probabilities for every method (refit on the same split) ---
    _, xgb_test = xgb_val_test_probs(sp)
    dl_test = {}
    for kind in DL_KINDS:
        cfg = {
            **best[kind]["best_opt"],
            "epochs": args.final_epochs,
            "patience": args.final_patience,
        }
        _, dl_test[kind] = fit_predict_dl(
            kind, best[kind]["best_arch"], cfg, seeds, sp, num_f, cat_f
        )
        print(f"  refit {kind} (seed-avg x{len(seeds)})")

    consensus = np.mean([_ranks(t) for t in dl_test.values()], axis=0)
    probs = {
        "xgb": xgb_test,
        "ft": dl_test["ft"],
        "resnet": dl_test["resnet"],
        "tabm": dl_test["tabm"],
        "xgb+tabm_rank": 0.5 * _ranks(xgb_test) + 0.5 * _ranks(dl_test["tabm"]),
        "dl_consensus_rank": consensus,
        "xgb+consensus_rank": 0.5 * _ranks(xgb_test) + 0.5 * consensus,
    }

    # --- point estimates ---
    point = {
        m: {
            "pr_auc": float(average_precision_score(yte, p)),
            "p10": float(precision_at_k(yte, p, 0.10)),
        }
        for m, p in probs.items()
    }

    # --- paired bootstrap: same resample index across all methods each draw ---
    rng = np.random.default_rng(B.SEED)
    names = list(probs)
    pr_draws = {m: [] for m in names}
    p10_draws = {m: [] for m in names}
    for _ in range(args.iters):
        idx = rng.integers(0, n, n)
        yb = yte[idx]
        if yb.sum() == 0:  # degenerate resample with no positives; skip
            continue
        for m in names:
            pb = probs[m][idx]
            pr_draws[m].append(average_precision_score(yb, pb))
            p10_draws[m].append(precision_at_k(yb, pb, 0.10))
    pr_draws = {m: np.asarray(v) for m, v in pr_draws.items()}
    p10_draws = {m: np.asarray(v) for m, v in p10_draws.items()}

    # --- summarise: CI per method + paired delta vs XGB ---
    print(f"\nbootstrap iters={args.iters} | test n={n} | positives={int(yte.sum())}")
    print(f"{'method':<20} {'PR-AUC [95% CI]':<26} {'dPR vs XGB [CI]':<26} P>XGB")
    summary = {}
    for m in names:
        d_pr = pr_draws[m] - pr_draws["xgb"]
        d_p10 = p10_draws[m] - p10_draws["xgb"]
        lo, hi = ci(pr_draws[m])
        dlo, dhi = ci(d_pr)
        p_win_pr = float((d_pr > 0).mean())
        summary[m] = {
            "pr_auc": point[m]["pr_auc"],
            "pr_auc_ci": [lo, hi],
            "p10": point[m]["p10"],
            "p10_ci": list(ci(p10_draws[m])),
            "delta_pr_vs_xgb": {"mean": float(d_pr.mean()), "ci": [dlo, dhi], "p_gt_0": p_win_pr},
            "delta_p10_vs_xgb": {
                "mean": float(d_p10.mean()),
                "ci": list(ci(d_p10)),
                "p_gt_0": float((d_p10 > 0).mean()),
            },
        }
        tag = "" if m == "xgb" else f"[{dlo:+.4f},{dhi:+.4f}]"
        print(
            f"{m:<20} {point[m]['pr_auc']:.4f} [{lo:.4f},{hi:.4f}]   "
            f"{('' if m == 'xgb' else f'{d_pr.mean():+.4f} ') + tag:<26} "
            f"{'' if m == 'xgb' else f'{p_win_pr:.2f}'}"
        )
    print("\nP@10 deltas vs XGB (mean [95% CI], P>XGB):")
    for m in names:
        if m == "xgb":
            continue
        s = summary[m]["delta_p10_vs_xgb"]
        print(
            f"  {m:<20} {s['mean']:+.4f} [{s['ci'][0]:+.4f},{s['ci'][1]:+.4f}]  P={s['p_gt_0']:.2f}"
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"torch_bootstrap_ci_{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source_hpo_log": hpo_path.name,
                "device": B.DEVICE,
                "test_n": int(n),
                "test_positives": int(yte.sum()),
                "iters": args.iters,
                "seeds": list(seeds),
                "summary": summary,
            },
            indent=2,
        )
    )
    print(f"\nWrote bootstrap CI log -> {out}")


if __name__ == "__main__":
    main()
