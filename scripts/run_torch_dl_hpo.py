"""Fair-shot HPO + TabM + XGB-ensemble follow-up to run_torch_tabular_benchmark.py.

The fixed-config benchmark left FT-Transformer / ResNet-MLP / TabM all beating the
incumbent sklearn MLP but landing ~0.01 PR-AUC short of the served XGBoost -- while
using *default* hyperparameters, where the served XGB had a 112-config HPO sweep. This
script closes three questions the benchmark raised:

  1. Fair shot: give each DL model the same tuning budget XGB got. Random search over
     the SAME expanding-window CV discipline (score by CV PR-AUC), the winner evaluated
     once on the 2025-07-01+ test, seed-averaged. Does tuning change the verdict?
  2. TabM (Gorishniy 2024, parameter-efficient deep ensemble) tuned in the same sweep --
     one of the current strongest tabular-DL methods.
  3. Ensemble: blend the served XGB with the tuned DL models. Blend weight is picked on
     the validation split, never on test. Does the blend beat XGB alone?

Everything reuses the harness in run_torch_tabular_benchmark.py (Encoder, models, train
loop) and the served XGB in foodsafety.models.xgb -- so the DL side is identical to the
benchmark and the XGB side is the production build, scored on the same split.

    PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> \
        .venv-torch/bin/python scripts/run_torch_dl_hpo.py --model all
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score

from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import expanding_year_folds, temporal_split

# scripts/ is not an installed package; add the repo root so the sibling benchmark
# harness imports whether this file is run directly or as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.run_torch_tabular_benchmark as B  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "reports" / "metrics" / "mlp"

# --------------------------------------------------------------------------- #
# Random-search spaces. arch_* keys go to the model constructor; the rest (lr/wd/
# batch) are optimiser/loader config shared by the train loop. n_heads always
# divides every d below, so no invalid FT attention configs are sampled.
# --------------------------------------------------------------------------- #
SPACES = {
    "ft": {
        "arch": {
            "d": [32, 64, 96, 128],
            "n_layers": [2, 3, 4],
            "n_heads": [4, 8],
            "d_ff": [64, 128, 256],
            "dropout": [0.0, 0.1, 0.2],
        },
        "opt": {
            "lr": [3e-4, 5e-4, 1e-3, 2e-3],
            "wd": [1e-5, 1e-4, 1e-3],
            "batch": [256, 512, 1024],
        },
    },
    "resnet": {
        "arch": {
            "d": [96, 128, 192, 256],
            "d_hidden": [128, 256, 384],
            "n_blocks": [2, 3, 4],
            "dropout": [0.0, 0.1, 0.2, 0.3],
        },
        "opt": {
            "lr": [3e-4, 5e-4, 1e-3, 2e-3],
            "wd": [1e-5, 1e-4, 1e-3],
            "batch": [256, 512, 1024],
        },
    },
    "tabm": {
        "arch": {
            "d": [128, 256, 384, 512],
            "n_blocks": [2, 3, 4],
            "k": [8, 16, 32],
            "dropout": [0.0, 0.1, 0.2],
        },
        "opt": {
            "lr": [3e-4, 5e-4, 1e-3, 2e-3],
            "wd": [1e-5, 1e-4, 1e-3],
            "batch": [256, 512, 1024],
        },
    },
}


def sample_config(rng: random.Random, kind: str) -> tuple[dict, dict]:
    arch = {k: rng.choice(v) for k, v in SPACES[kind]["arch"].items()}
    opt = {k: rng.choice(v) for k, v in SPACES[kind]["opt"].items()}
    return arch, opt


def hpo_search(kind, cv_df, folds, num_f, cat_f, n_trials, epochs, patience, rng) -> dict:
    """Random search over CV; return the best config by mean CV PR-AUC + all trials."""
    trials = []
    for i in range(n_trials):
        arch, opt = sample_config(rng, kind)
        cfg = {**opt, "epochs": epochs, "patience": patience}
        t0 = time.time()
        cv = B.cv_score(kind, cv_df, folds, num_f, cat_f, cfg, arch=arch)
        trials.append(
            {
                "arch": arch,
                "opt": opt,
                "cv_pr_auc": cv["pr_auc_mean"],
                "cv_p10": cv["p10_mean"],
                "cv_pr_folds": cv["pr_auc_folds"],
            }
        )
        print(
            f"  [{kind} trial {i + 1}/{n_trials}] cv_pr={cv['pr_auc_mean']:.4f} "
            f"cv_p10={cv['p10_mean']:.4f} arch={arch} opt={opt} ({time.time() - t0:.0f}s)"
        )
    best = max(trials, key=lambda r: r["cv_pr_auc"])
    return {"best": best, "trials": trials}


def fit_predict_dl(kind, arch, cfg, seeds, sp, num_f, cat_f) -> tuple[np.ndarray, np.ndarray]:
    """Fit the DL model on train (early-stop on val) per seed; return seed-averaged
    (val_probs, test_probs). The encoder is fit on train once and shared across seeds."""
    enc = B.Encoder(num_f, cat_f).fit(sp.train)
    ytr = sp.train[LABEL_COL].astype(int).to_numpy()
    yva = sp.val[LABEL_COL].astype(int).to_numpy()
    val_p, test_p = [], []
    for sd in seeds:
        model = B.train_one(kind, enc, sp.train, sp.val, ytr, yva, cfg, sd, arch=arch)
        val_p.append(B.predict(kind, enc, model, sp.val))
        test_p.append(B.predict(kind, enc, model, sp.test))
    return np.mean(val_p, axis=0), np.mean(test_p, axis=0)


def xgb_val_test_probs(sp) -> tuple[np.ndarray, np.ndarray]:
    """The served production XGB fit on train, predicting val + test on the same split."""
    ytr = sp.train[LABEL_COL].astype(int).to_numpy()
    Xtr = prepare_xgb_features(sp.train)
    cd = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(sp.val, categorical_dtypes=cd)
    Xte = prepare_xgb_features(sp.test, categorical_dtypes=cd)
    clf = build_production_xgb(
        scale_pos_weight=compute_scale_pos_weight(ytr), features=ALL_FEATURES
    )
    clf.fit(Xtr, ytr)
    return clf.predict_proba(Xva)[:, 1], clf.predict_proba(Xte)[:, 1]


def _ranks(p: np.ndarray) -> np.ndarray:
    """Map scores to uniform ranks in (0, 1] -- scale-free, so blending an XGB prob with
    a DL prob is not dominated by whichever is worse-calibrated."""
    order = np.argsort(np.argsort(p))
    return (order + 1) / len(p)


def best_blend_weight(xgb_val, dl_val, yva) -> float:
    """Grid-search the blend weight w (on XGB) that maximises validation PR-AUC."""
    grid = np.linspace(0.0, 1.0, 21)
    aps = [average_precision_score(yva, w * xgb_val + (1 - w) * dl_val) for w in grid]
    return float(grid[int(np.argmax(aps))])


def eval_probs(y, p) -> dict:
    r = evaluate(y, p).to_dict()
    return {"pr_auc": r["pr_auc"], "p10": r["precision_at_10pct"], "lift": r["top_decile_lift"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="all", choices=["ft", "resnet", "tabm", "all"])
    ap.add_argument("--trials", type=int, default=16, help="random-search trials per model")
    ap.add_argument("--hpo-folds", type=int, default=3, help="last-N CV folds used in search")
    ap.add_argument("--hpo-epochs", type=int, default=35)
    ap.add_argument("--hpo-patience", type=int, default=5)
    ap.add_argument("--final-epochs", type=int, default=60)
    ap.add_argument("--final-patience", type=int, default=8)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    ap.add_argument("--quick", action="store_true", help="tiny run to validate wiring")
    args = ap.parse_args()

    import torch

    torch.set_num_threads(args.threads)
    B.DEVICE = (
        ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    )

    if args.quick:
        args.trials, args.hpo_folds, args.hpo_epochs, args.hpo_patience = 2, 2, 6, 2
        args.final_epochs, args.final_patience = 6, 2
    seeds = (42,) if args.quick else (42, 7, 123)
    kinds = ["ft", "resnet", "tabm"] if args.model == "all" else [args.model]

    modelable = B.load_modelable()
    num_f, cat_f = B.split_feature_types(modelable)
    cv_df = modelable.loc[modelable["inspection_date"] < B.VAL_END].reset_index(drop=True)
    folds = expanding_year_folds(cv_df)[-args.hpo_folds :]
    sp = temporal_split(modelable, train_end=B.TRAIN_END, val_end=B.VAL_END)
    yva = sp.val[LABEL_COL].astype(int).to_numpy()
    yte = sp.test[LABEL_COL].astype(int).to_numpy()
    rng = random.Random(B.SEED)

    print(f"device={B.DEVICE} | features={len(ALL_FEATURES)} | test n={len(sp.test):,}")
    print(f"HPO: {args.trials} trials x {args.hpo_folds} folds x {args.hpo_epochs} epochs")

    # --- XGB baseline on this exact split (fit train, predict val+test) ---
    xgb_val, xgb_test = xgb_val_test_probs(sp)
    xgb_metrics = eval_probs(yte, xgb_test)
    print(
        f"\nXGB (served, this split): TEST pr_auc={xgb_metrics['pr_auc']:.4f} "
        f"p10={xgb_metrics['p10']:.4f} lift={xgb_metrics['lift']:.3f}"
    )

    results = {}
    dl_probs = {}  # kind -> (val_probs, test_probs), for the all-model consensus ensemble
    for kind in kinds:
        print(f"\n=== {kind.upper()} : HPO ===")
        t0 = time.time()
        search = hpo_search(
            kind,
            cv_df,
            folds,
            num_f,
            cat_f,
            args.trials,
            args.hpo_epochs,
            args.hpo_patience,
            rng,
        )
        best = search["best"]
        print(
            f"  best {kind}: cv_pr={best['cv_pr_auc']:.4f} cv_p10={best['cv_p10']:.4f} "
            f"arch={best['arch']} opt={best['opt']} (search {time.time() - t0:.0f}s)"
        )

        # --- final: refit winner on full train, seed-avg val+test probs ---
        cfg = {**best["opt"], "epochs": args.final_epochs, "patience": args.final_patience}
        dl_val, dl_test = fit_predict_dl(kind, best["arch"], cfg, seeds, sp, num_f, cat_f)
        dl_probs[kind] = (dl_val, dl_test)
        dl_metrics = eval_probs(yte, dl_test)
        beats_xgb = (
            dl_metrics["pr_auc"] >= xgb_metrics["pr_auc"]
            and dl_metrics["p10"] >= xgb_metrics["p10"]
        )
        print(
            f"  TEST (tuned, seed-avg) pr_auc={dl_metrics['pr_auc']:.4f} "
            f"p10={dl_metrics['p10']:.4f} lift={dl_metrics['lift']:.3f} beats_XGB={beats_xgb}"
        )

        # --- ensemble: XGB + this DL, weight picked on val (weighted + rank-avg) ---
        w = best_blend_weight(xgb_val, dl_val, yva)
        w_test = eval_probs(yte, w * xgb_test + (1 - w) * dl_test)
        rank_test = eval_probs(yte, 0.5 * _ranks(xgb_test) + 0.5 * _ranks(dl_test))
        print(
            f"  ENSEMBLE XGB+{kind}: weighted(w_xgb={w:.2f}) pr_auc={w_test['pr_auc']:.4f} "
            f"p10={w_test['p10']:.4f} | rank-avg pr_auc={rank_test['pr_auc']:.4f} p10={rank_test['p10']:.4f}"
        )

        results[kind] = {
            "best_arch": best["arch"],
            "best_opt": best["opt"],
            "cv_pr_auc": best["cv_pr_auc"],
            "cv_p10": best["cv_p10"],
            "test_tuned": dl_metrics,
            "beats_xgb": beats_xgb,
            "ensemble_weighted": {"w_xgb": w, **w_test},
            "ensemble_rank_avg": rank_test,
            "trials": search["trials"],
        }

    # --- headline ensemble: XGB + the rank-averaged consensus of all tuned DL models ---
    consensus = None
    if len(dl_probs) > 1:
        dl_val_consensus = np.mean([_ranks(v) for v, _ in dl_probs.values()], axis=0)
        dl_test_consensus = np.mean([_ranks(t) for _, t in dl_probs.values()], axis=0)
        w = best_blend_weight(_ranks(xgb_val), dl_val_consensus, yva)
        w_test = eval_probs(yte, w * _ranks(xgb_test) + (1 - w) * dl_test_consensus)
        consensus = {"models": list(dl_probs), "w_xgb": w, **w_test}
        print(
            f"\nENSEMBLE XGB + DL-consensus({'+'.join(dl_probs)}): rank-blend "
            f"(w_xgb={w:.2f}) pr_auc={w_test['pr_auc']:.4f} p10={w_test['p10']:.4f} "
            f"lift={w_test['lift']:.3f} | XGB-alone pr_auc={xgb_metrics['pr_auc']:.4f} "
            f"p10={xgb_metrics['p10']:.4f}"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"torch_dl_hpo_{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "device": B.DEVICE,
                "test_n": int(len(sp.test)),
                "hpo": {
                    "trials": args.trials,
                    "folds": args.hpo_folds,
                    "epochs": args.hpo_epochs,
                    "patience": args.hpo_patience,
                },
                "final": {
                    "epochs": args.final_epochs,
                    "patience": args.final_patience,
                    "seeds": list(seeds),
                },
                "xgb_served_this_split": xgb_metrics,
                "results": results,
                "ensemble_xgb_plus_dl_consensus": consensus,
            },
            indent=2,
        )
    )
    print(f"\nWrote HPO+ensemble log -> {out}")


if __name__ == "__main__":
    main()
