"""FT-Transformer + ResNet-MLP tabular deep-learning benchmark on the frozen v36 features.

Purpose: put two modern tabular-DL architectures on the record against the served
XGBoost (test PR-AUC 0.382 / P@10 0.421) and the incumbent sklearn MLP (0.333 / 0.402),
under the SAME discipline as scripts/run_mlp_hpo.py:
  * expanding-window CV over the train+val region only (inspection_date < 2025-07-01),
    the 2025-07-01+ test held out and touched once;
  * PR-AUC and precision@10% are rank metrics, so we score raw sigmoid outputs (no
    calibration needed for the head-to-head — matches the MLP harness);
  * the final test number is seed-averaged (single-seed DL gains are noise here).

Feature set is FROZEN at v36 ``ALL_FEATURES`` — this is a pure architecture comparison,
not feature work. Two faithful implementations:
  * FT-Transformer (Gorishniy 2021): per-feature tokenizer (numeric linear-embed +
    categorical embeddings) + CLS token + transformer encoder + CLS-head.
  * ResNet-MLP (Gorishniy 2021): flat standardized+one-hot input through pre-norm
    residual blocks.

Runs in the isolated .venv-torch — torch is deliberately NOT in the project lockfile;
this is a benchmark, not a serving dependency (XGB stays served).

    PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> \
        .venv-torch/bin/python scripts/run_torch_tabular_benchmark.py --model both
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

from foodsafety.config import FEATURES_PATH, RANDOM_STATE
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate, precision_at_k
from foodsafety.utils.time import expanding_year_folds, temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "reports" / "metrics" / "mlp"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"  # test = inspection_date >= VAL_END; CV lives strictly before it
SEED = RANDOM_STATE
RARE_MIN_FREQ = 25  # matches the MLP harness OneHotEncoder(min_frequency=25)

# Compute device. Metrics are device-invariant (same math, only float noise differs);
# the GPU path just makes the 6-fold x 2-model x 3-seed protocol finish in minutes not
# hours. Set in main() from --device; default "cpu" so importing never touches CUDA.
DEVICE = "cpu"

# Reference points for the head-to-head printout (from reports/metrics + changelog).
REFERENCE = {
    "xgb_served": {"pr_auc": 0.382, "p10": 0.421},
    "mlp_incumbent": {"pr_auc": 0.333, "p10": 0.402},
    "logreg": {"pr_auc": 0.372, "p10": None},
}


# --------------------------------------------------------------------------- #
# Data + preprocessing (mirrors run_mlp_hpo.py: median-impute+scale numeric,
# rare-bucketed categoricals)
# --------------------------------------------------------------------------- #
def load_modelable() -> pd.DataFrame:
    feat = pd.read_parquet(FEATURES_PATH)
    mask = pd.Series(True, index=feat.index)
    if "is_burnin" in feat.columns:
        mask &= ~feat["is_burnin"]
    if "right_truncated" in feat.columns:
        mask &= ~feat["right_truncated"]
    return feat[mask].reset_index(drop=True)


def split_feature_types(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    cat = [
        c
        for c in ALL_FEATURES
        if df[c].dtype == "object" or str(df[c].dtype).startswith("category")
    ]
    num = [c for c in ALL_FEATURES if c not in cat]
    return num, cat


class Encoder:
    """Fit on train only. Produces (X_num float32, X_cat int64) plus a flat one-hot.

    Categoricals map rare (<RARE_MIN_FREQ) / unseen levels to index 0 so the val/test
    folds never leak a category the train fold did not see.
    """

    def __init__(self, num_feats: list[str], cat_feats: list[str]):
        self.num_feats = num_feats
        self.cat_feats = cat_feats
        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()
        self.vocabs: dict[str, dict[str, int]] = {}
        self.cardinalities: list[int] = []

    def fit(self, df: pd.DataFrame) -> Encoder:
        self.imputer.fit(df[self.num_feats])
        self.scaler.fit(self.imputer.transform(df[self.num_feats]))
        for c in self.cat_feats:
            vc = df[c].astype("string").fillna("__nan__").value_counts()
            keep = vc[vc >= RARE_MIN_FREQ].index.tolist()
            # index 0 reserved for rare/unknown; kept levels start at 1
            self.vocabs[c] = {lvl: i + 1 for i, lvl in enumerate(keep)}
            self.cardinalities.append(len(keep) + 1)
        return self

    def _num(self, df: pd.DataFrame) -> np.ndarray:
        return self.scaler.transform(self.imputer.transform(df[self.num_feats])).astype(np.float32)

    def _cat(self, df: pd.DataFrame) -> np.ndarray:
        cols = []
        for c in self.cat_feats:
            s = df[c].astype("string").fillna("__nan__")
            cols.append(s.map(self.vocabs[c]).fillna(0).astype(np.int64).to_numpy())
        if not cols:
            return np.zeros((len(df), 0), dtype=np.int64)
        return np.stack(cols, axis=1)

    def transform_tokens(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        return self._num(df), self._cat(df)

    def transform_flat(self, df: pd.DataFrame) -> np.ndarray:
        x_num = self._num(df)
        x_cat = self._cat(df)
        onehots = []
        for j, card in enumerate(self.cardinalities):
            oh = np.zeros((len(df), card), dtype=np.float32)
            oh[np.arange(len(df)), x_cat[:, j]] = 1.0
            onehots.append(oh)
        if onehots:
            return np.concatenate([x_num, *onehots], axis=1)
        return x_num


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class FTTransformer(nn.Module):
    def __init__(
        self,
        n_num: int,
        cardinalities: list[int],
        d: int = 64,
        n_layers: int = 3,
        n_heads: int = 8,
        d_ff: int = 128,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.n_num = n_num
        # numeric tokenizer: per-feature weight/bias -> a d-vector token
        self.num_weight = nn.Parameter(torch.empty(n_num, d))
        self.num_bias = nn.Parameter(torch.empty(n_num, d))
        nn.init.normal_(self.num_weight, std=0.02)
        nn.init.normal_(self.num_bias, std=0.02)
        self.cat_embs = nn.ModuleList([nn.Embedding(card, d) for card in cardinalities])
        self.cls = nn.Parameter(torch.empty(1, 1, d))
        nn.init.normal_(self.cls, std=0.02)
        layer = nn.TransformerEncoderLayer(
            d_model=d,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers)
        self.head = nn.Sequential(nn.LayerNorm(d), nn.ReLU(), nn.Linear(d, 1))

    def forward(self, x_num: torch.Tensor, x_cat: torch.Tensor) -> torch.Tensor:
        b = x_num.shape[0]
        num_tok = x_num.unsqueeze(-1) * self.num_weight + self.num_bias  # [B, n_num, d]
        toks = [num_tok]
        for j, emb in enumerate(self.cat_embs):
            toks.append(emb(x_cat[:, j]).unsqueeze(1))  # [B, 1, d]
        tokens = torch.cat([self.cls.expand(b, -1, -1), *toks], dim=1)
        z = self.encoder(tokens)
        return self.head(z[:, 0]).squeeze(-1)


class ResNetMLP(nn.Module):
    def __init__(
        self, d_in: int, d: int = 128, d_hidden: int = 256, n_blocks: int = 3, dropout: float = 0.1
    ):
        super().__init__()
        self.first = nn.Linear(d_in, d)
        self.blocks = nn.ModuleList()
        for _ in range(n_blocks):
            self.blocks.append(
                nn.ModuleDict(
                    {
                        "norm": nn.BatchNorm1d(d),
                        "lin1": nn.Linear(d, d_hidden),
                        "lin2": nn.Linear(d_hidden, d),
                    }
                )
            )
        self.drop = nn.Dropout(dropout)
        self.head_norm = nn.BatchNorm1d(d)
        self.head = nn.Linear(d, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.first(x)
        for blk in self.blocks:
            z = blk["norm"](x)
            z = torch.relu(blk["lin1"](z))
            z = self.drop(z)
            z = blk["lin2"](z)
            z = self.drop(z)
            x = x + z
        x = torch.relu(self.head_norm(x))
        return self.head(x).squeeze(-1)


class BatchEnsembleLinear(nn.Module):
    """A linear layer shared across ``k`` ensemble members via rank-1 adapters.

    Each member i multiplies the input by its own vector ``r[i]`` and the output by
    ``s[i]`` (BatchEnsemble, Wen 2020) — so k members cost one shared weight matrix
    plus 2*k vectors instead of k full matrices. ``r`` is sign-initialised (+/-1) so
    members start decorrelated. Input/output carry a member axis: (B, k, d).
    """

    def __init__(self, d_in: int, d_out: int, k: int):
        super().__init__()
        self.weight = nn.Parameter(torch.empty(d_out, d_in))
        nn.init.kaiming_uniform_(self.weight, a=5**0.5)
        self.bias = nn.Parameter(torch.zeros(k, d_out))
        # random +/-1 signs decorrelate the members at init (BatchEnsemble recipe)
        self.r = nn.Parameter(torch.randint(0, 2, (k, d_in)).float() * 2 - 1)
        self.s = nn.Parameter(torch.randint(0, 2, (k, d_out)).float() * 2 - 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x * self.r  # (B, k, d_in)
        x = torch.einsum("bki,oi->bko", x, self.weight)  # (B, k, d_out)
        return x * self.s + self.bias


class TabM(nn.Module):
    """TabM (Gorishniy 2024): a plain MLP turned into a parameter-efficient deep
    ensemble of ``k`` members via BatchEnsemble adapters, with per-member heads.

    Training scores every member against the label; inference averages the k member
    probabilities. This is the ``TabM`` (full) variant: adapters on every layer.
    Output is per-member logits (B, k) — the shared train loop reduces them.
    """

    def __init__(
        self, d_in: int, d: int = 256, n_blocks: int = 3, k: int = 32, dropout: float = 0.1
    ):
        super().__init__()
        self.k = k
        dims = [d_in] + [d] * n_blocks
        self.layers = nn.ModuleList(
            [BatchEnsembleLinear(dims[i], dims[i + 1], k) for i in range(n_blocks)]
        )
        self.drop = nn.Dropout(dropout)
        self.head = BatchEnsembleLinear(d, 1, k)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.unsqueeze(1).expand(-1, self.k, -1)  # (B, k, d_in)
        for lin in self.layers:
            x = self.drop(torch.relu(lin(x)))
        return self.head(x).squeeze(-1)  # (B, k) per-member logits


def _flat_dim(enc: Encoder) -> int:
    """Width of the flat one-hot input the ResNet/TabM heads consume."""
    return len(enc.num_feats) + int(sum(enc.cardinalities))


def build_model(kind: str, enc: Encoder, arch: dict | None = None) -> nn.Module:
    """Construct a model of the given kind, overriding architecture defaults with arch."""
    arch = arch or {}
    if kind == "ft":
        return FTTransformer(len(enc.num_feats), enc.cardinalities, **arch)
    if kind == "resnet":
        return ResNetMLP(_flat_dim(enc), **arch)
    if kind == "tabm":
        return TabM(_flat_dim(enc), **arch)
    raise ValueError(f"unknown model kind: {kind}")


# --------------------------------------------------------------------------- #
# Train / predict
# --------------------------------------------------------------------------- #
def _tensors(enc: Encoder, df: pd.DataFrame, kind: str):
    if kind == "ft":
        xn, xc = enc.transform_tokens(df)
        return torch.from_numpy(xn), torch.from_numpy(xc)
    return (torch.from_numpy(enc.transform_flat(df)),)


def _forward_prob(model: nn.Module, xs: tuple) -> torch.Tensor:
    """Sigmoid probability, reduced to (B,). Deep-ensemble heads (TabM) emit
    per-member logits (B, k); average their probabilities."""
    p = torch.sigmoid(model(*xs))
    return p.mean(dim=1) if p.ndim == 2 else p


def train_one(
    kind: str,
    enc: Encoder,
    tr: pd.DataFrame,
    va: pd.DataFrame,
    ytr: np.ndarray,
    yva: np.ndarray,
    cfg: dict,
    seed: int,
    arch: dict | None = None,
) -> nn.Module:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = build_model(kind, enc, arch).to(DEVICE)

    xtr = tuple(t.to(DEVICE) for t in _tensors(enc, tr, kind))
    xva = tuple(t.to(DEVICE) for t in _tensors(enc, va, kind))
    ytr_t = torch.from_numpy(ytr.astype(np.float32)).to(DEVICE)
    yva_t = torch.from_numpy(yva.astype(np.float32)).to(DEVICE)

    pos = float(ytr.sum())
    neg = float(len(ytr) - pos)
    pos_weight = torch.tensor([neg / max(pos, 1.0)], device=DEVICE)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["wd"])

    ds = TensorDataset(*xtr, ytr_t)
    dl = DataLoader(ds, batch_size=cfg["batch"], shuffle=True, drop_last=False)

    best_ap, best_state, bad = -1.0, None, 0
    for _epoch in range(cfg["epochs"]):
        model.train()
        for batch in dl:
            *xb, yb = batch
            opt.zero_grad()
            logit = model(*xb)
            # per-member heads (TabM) emit (B, k): score every member against y
            target = yb.unsqueeze(1).expand_as(logit) if logit.ndim == 2 else yb
            loss_fn(logit, target).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            va_prob = _forward_prob(model, xva).cpu().numpy()
        ap = average_precision_score(yva, va_prob)
        if ap > best_ap + 1e-5:
            best_ap = ap
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            bad = 0
        else:
            bad += 1
            if bad >= cfg["patience"]:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    del yva_t
    return model


def predict(kind: str, enc: Encoder, model: nn.Module, df: pd.DataFrame) -> np.ndarray:
    model.eval()
    x = tuple(t.to(DEVICE) for t in _tensors(enc, df, kind))
    with torch.no_grad():
        return _forward_prob(model, x).cpu().numpy()


# --------------------------------------------------------------------------- #
# Protocol: CV then seed-averaged test
# --------------------------------------------------------------------------- #
def cv_score(kind, cv_df, folds, num_f, cat_f, cfg, arch=None) -> dict:
    pr, p10 = [], []
    y_all = cv_df[LABEL_COL].astype(int).to_numpy()
    for tr_idx, va_idx in folds:
        tr, va = cv_df.iloc[tr_idx], cv_df.iloc[va_idx]
        enc = Encoder(num_f, cat_f).fit(tr)
        model = train_one(kind, enc, tr, va, y_all[tr_idx], y_all[va_idx], cfg, SEED, arch=arch)
        s = predict(kind, enc, model, va)
        pr.append(float(average_precision_score(y_all[va_idx], s)))
        p10.append(float(precision_at_k(y_all[va_idx], s, 0.10)))
    return {
        "pr_auc_mean": float(np.mean(pr)),
        "p10_mean": float(np.mean(p10)),
        "pr_auc_folds": [round(x, 4) for x in pr],
        "p10_folds": [round(x, 4) for x in p10],
    }


def holdout_eval(kind, modelable, num_f, cat_f, cfg, seeds) -> dict:
    """Fit on train, early-stop on val, eval on test; seed-average the test probs.

    Rank metrics (PR-AUC/P@10/ROC/lift) are calibration-invariant, so we score raw
    sigmoid outputs like the MLP harness. Brier/log-loss in the returned dict are
    therefore uncalibrated and only indicative.
    """
    sp = temporal_split(modelable, train_end=TRAIN_END, val_end=VAL_END)
    ytr = sp.train[LABEL_COL].astype(int).to_numpy()
    yva = sp.val[LABEL_COL].astype(int).to_numpy()
    yte = sp.test[LABEL_COL].astype(int).to_numpy()
    enc = Encoder(num_f, cat_f).fit(sp.train)
    probs = []
    for sd in seeds:
        model = train_one(kind, enc, sp.train, sp.val, ytr, yva, cfg, sd)
        probs.append(predict(kind, enc, model, sp.test))
    p_te = np.mean(probs, axis=0)
    return evaluate(yte, p_te).to_dict()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="both", choices=["ft", "resnet", "tabm", "both", "all"])
    ap.add_argument("--fast", action="store_true", help="last 4 CV folds instead of 6")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--wd", type=float, default=1e-5)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda"],
        help="auto uses CUDA when available, else CPU",
    )
    args = ap.parse_args()
    torch.set_num_threads(args.threads)

    global DEVICE
    DEVICE = (
        ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    )

    cfg = {
        "epochs": args.epochs,
        "patience": args.patience,
        "batch": args.batch,
        "lr": args.lr,
        "wd": args.wd,
    }

    modelable = load_modelable()
    num_f, cat_f = split_feature_types(modelable)
    cv_df = modelable.loc[modelable["inspection_date"] < VAL_END].reset_index(drop=True)
    folds = expanding_year_folds(cv_df)
    if args.fast:
        folds = folds[-4:]
    fold_years = [
        int(pd.to_datetime(cv_df["inspection_date"].iloc[va]).dt.year.mode().iloc[0])
        for _, va in folds
    ]
    print(f"features: {len(ALL_FEATURES)} ({len(num_f)} num / {len(cat_f)} cat)")
    print(f"CV region n={len(cv_df):,} | {len(folds)} folds val_years={fold_years}")
    print(f"config: {cfg} | torch threads={args.threads} | device={DEVICE}")
    print(
        f"reference  XGB(served) PR={REFERENCE['xgb_served']['pr_auc']:.3f} "
        f"P10={REFERENCE['xgb_served']['p10']:.3f} | "
        f"MLP(incumbent) PR={REFERENCE['mlp_incumbent']['pr_auc']:.3f} "
        f"P10={REFERENCE['mlp_incumbent']['p10']:.3f}"
    )

    if args.model == "both":
        kinds = ["ft", "resnet"]
    elif args.model == "all":
        kinds = ["ft", "resnet", "tabm"]
    else:
        kinds = [args.model]
    results = {}
    for kind in kinds:
        t0 = time.time()
        print(f"\n=== {kind.upper()} : CV ({len(folds)} folds) ===")
        cv = cv_score(kind, cv_df, folds, num_f, cat_f, cfg)
        print(
            f"  CV pr_auc={cv['pr_auc_mean']:.4f} p10={cv['p10_mean']:.4f} "
            f"folds_pr={cv['pr_auc_folds']} ({time.time() - t0:.0f}s)"
        )
        print(f"=== {kind.upper()} : TEST (seed-avg x3) ===")
        te = holdout_eval(kind, modelable, num_f, cat_f, cfg, seeds=(42, 7, 123))
        beats_xgb = (
            te["pr_auc"] >= REFERENCE["xgb_served"]["pr_auc"]
            and te["precision_at_10pct"] >= REFERENCE["xgb_served"]["p10"]
        )
        beats_mlp = (
            te["pr_auc"] >= REFERENCE["mlp_incumbent"]["pr_auc"]
            and te["precision_at_10pct"] >= REFERENCE["mlp_incumbent"]["p10"]
        )
        print(
            f"  TEST pr_auc={te['pr_auc']:.4f} p10={te['precision_at_10pct']:.4f} "
            f"roc_auc={te['roc_auc']:.4f} lift={te['top_decile_lift']:.3f} "
            f"| beats_XGB={beats_xgb} beats_MLP={beats_mlp} ({time.time() - t0:.0f}s)"
        )
        results[kind] = {"cv": cv, "test": te, "beats_xgb": beats_xgb, "beats_mlp": beats_mlp}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"torch_tabular_benchmark_{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "cv_region": f"inspection_date < {VAL_END}",
                "fold_val_years": fold_years,
                "device": DEVICE,
                "config": cfg,
                "reference": REFERENCE,
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nWrote benchmark log -> {out}")


if __name__ == "__main__":
    main()
