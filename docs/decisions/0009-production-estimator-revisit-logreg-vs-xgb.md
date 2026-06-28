# 0009 — Production estimator revisit: LogReg vs XGBoost under v36

- **Status**: **Accepted** (2026-06-27 — XGBoost promoted to production; see Resolution)
- **Date**: 2026-06-21 (resolved 2026-06-27)
- **Owners to ack**: Bella (modeling / eval), Deepak (modeling backup), Jun (PM)

> [0002](0002-xgb-validation-methodology.md) made the served LogReg the production
> estimator on the both-metrics gate, judged on the **v33-era** honest test. Under
> the **v36** contract (current-inspection features) the gap closed, so the
> estimator choice is worth revisiting. This record **supersedes only 0002's
> estimator conclusion** — 0002's methodology (no val double-dip, expanding-window
> CV, the both-metrics gate, sigmoid calibration) still stands and is inherited here.

## Current state (v36)
- **Honest test (n=13,812):** XGB slightly *leads* — PR-AUC LogReg 0.332 vs XGB
  **0.338**; P@10 LogReg 0.370 vs XGB **0.376**. On this basis XGB would clear
  0002's gate.
- **But the comparison is not apples-to-apples.** Served LogReg (production) is
  measured on the **served RT-filtered basis** (n≈7,008: PR-AUC 0.372, P@10 0.415);
  the XGB lead is **honest-basis + isotonic-calibrated** only. **No served-basis XGB
  run exists.** (See [`experiments.md`](../experiments.md) "Model comparison" + the
  v36 note.)

## Decision (for now)
**Do not switch. LogReg remains the served production estimator.** This is an open
revisit, recorded so the question is tracked rather than scattered — not a decision
to promote XGB.

## What's needed to close
1. **A served-basis, sigmoid-calibrated XGB run** on the RT-filtered test (n≈7,008)
   that beats LogReg on **both** PR-AUC and P@10 *on that same basis*. (The current
   XGB run is isotonic; 0002/0001 deliberately moved to sigmoid for the UI score-tie
   problem, so an apples-to-apples challenger must be sigmoid + served-basis.)
2. **A costed plan for XGB explainability — the real blast radius.**
   `src/foodsafety/explain/shap_drivers.py` is **linear-only** (`coef × value`) and
   feeds every restaurant's `top_drivers` in `scores.json` / the detail-page bars.
   A tree model needs a TreeExplainer path + the `shap` dependency the repo
   currently avoids (already flagged as Phase-6 backlog in that file).

## Resolution (2026-06-27) — XGBoost promoted

Both close criteria are met, so the estimator switches.

1. **Served-basis, sigmoid-calibrated XGB beats LogReg.** A **depth-3 XGB with
   monotone constraints** on the risk-count features, Platt-calibrated on the raw
   margin, on the served RT-filtered test (n≈7,008): **PR-AUC 0.382 vs LogReg
   0.372**; P@10 0.4151 (ties on this single split). The single split isn't the
   gate — under **expanding-window CV (6 folds, 0002's stability test)** XGB beats
   LogReg on **both** metrics in **5/6 folds** (mean ΔPR-AUC +0.0051, ΔP@10
   +0.0062). The monotone constraints are the lever: on a forward-time split the
   `prior_*` counts run past the training range, and unconstrained deep trees
   saturate at the top threshold and lose the top decile — depth-3 + monotone
   keeps that ordering. (`build_production_xgb` in `models/xgb.py`.)
2. **Explainability solved without the `shap` dependency.** XGBoost's **native
   TreeSHAP** (`Booster.predict(pred_contribs=True)`) gives exact margin/log-odds
   contributions — `tree_contributions` in `explain/shap_drivers.py`. Fitting the
   Platt map on the **raw margin** keeps the served `calibration {a, b, intercept}`
   in margin space (intercept = the TreeSHAP base margin), so `intercept + Σshap ==
   margin` per row and the app's `computeWaterfall` reconciles to the gauge
   **unchanged**. No new dependency; the `scores.json` schema is identical.

**Served via** `scripts/retrain_xgb_sigmoid.py` (`model_version =
xgb_monotone_sigmoid`). Building-violation features are **not** included — they
failed the gate under CV on every model family and were reverted in the same
change.

## Not blockers (noted so they aren't mistaken for one)
- **Feature contract:** both models already consume the same `ALL_FEATURES` from
  `baseline.py`; `xgb.py` imports it directly — no contract work needed.
- **Calibration/serving wiring:** the `CalibratedClassifierCV(FrozenEstimator(...),
  method="sigmoid")` pattern in `scripts/retrain_baseline_sigmoid.py` is
  estimator-agnostic and reusable.

## Cross-references
- [0002](0002-xgb-validation-methodology.md) — the methodology + the gate this inherits.
- [`experiments.md`](../experiments.md) — the LogReg-vs-XGB comparison + v36 note.
- [0007](0007-target-label-definition-and-scope.md) — the label both models predict.
