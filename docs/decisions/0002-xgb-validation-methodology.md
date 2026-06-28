# 0002 — XGBoost validation methodology: no val double-dip, expanding-window CV

- **Status**: Accepted
- **Date**: 2026-06-14 (amended 2026-06-27 — feature-promotion gate relaxed to one model)
- **Owners to ack**: Bella, Deepak, Jun (modeling); Arun, Aurelia (consumers)

## Context

The XGBoost path reused the validation split twice. Early stopping selected
`best_iteration` by watching the validation set, and the *same* validation set
was then used to fit the probability calibrator and to report headline metrics.
That is a double-dip: tree count is tuned to the very rows the model is later
graded on, so the reported PR-AUC / log_loss are optimistic and not comparable
to the baseline (which never saw val during fitting).

Separately, we had no inner cross-validation to tell whether a config was
stable across time or whether a single train/val draw got lucky, and no
principled rule for choosing the calibration method (isotonic vs sigmoid).

Constraint: no AWS, no MLflow, no hyperparameter-search infra this iteration
(see CLAUDE.md scope). Whatever we adopt must run on a laptop in seconds and
respect the chronological-only rule (never shuffle, never cross the
train/val/test boundary — see `utils/time.py:temporal_split`).

## Decision

1. **Early stopping no longer touches val.** It runs on an **embargoed tail of
   train** (`train_es` — the last ~6 months of train, held out behind a 180-day
   embargo gap from the rest of train) to find `best_iteration`. The model is
   then **refit on full train** at that fixed tree count. **Val is reserved for
   calibration only**, and the test set for the final honest read. No split is
   used for two purposes.

2. **Inner CV is `expanding_year_folds` (full-year, expanding, 180-day
   embargo), on the TRAIN subset only.** For each validation year Y, train =
   all history before `Y-01-01 − 180d`; val = calendar year Y. The embargo
   drops the train tail whose forward 180-day label window would overlap year Y
   (the label is `*_next_180d`, so without the embargo an anchor near the year
   boundary sees outcomes inside the validation period → optimistic).

   - **Expanding, not rolling.** The production estimator refits on *all* train
     history up to the cutoff, so CV must validate that same regime; a rolling
     window would estimate a model we don't ship. Compute is not a reason to
     switch — the full 5-fold sweep on ~79k×30 rows runs in well under a minute
     (LogReg sub-second per fold; XGBoost a few seconds). And the CV showed
     **PR-AUC 0.326 ± 0.029 stable across 2020–2024**, i.e. no concept drift
     where old data hurts — the only condition that would justify discarding
     history. The one real regime change (the July 2018 procedure change) is
     already handled by the 2019 training-data cutoff.
   - **Full-year folds, not quarterly.** At ~10% prevalence, quarterly folds
     hold too few positives to give stable per-fold estimates. Rolling would
     compound this (fewer positives per fold); expanding keeps every positive.

3. **Calibration method chosen by mean Brier across the CV folds → sigmoid.**
   This is consistent with decision record 0001 (served model = sigmoid): the
   choice is now justified by an out-of-sample score, not asserted. Sigmoid vs
   isotonic preserves ranking, so it does not move PR-AUC / precision — it
   improves probability quality (Brier / log_loss) and avoids isotonic's
   ~60-distinct-value tie problem in the UI.

4. **The production-estimator gate is unchanged: a challenger must clear the
   baseline on PR-AUC AND precision@10%.** The corrected XGBoost run, on the
   honest unfiltered test (n=13,812), improved to **PR-AUC 0.254 → 0.268** and
   **log_loss 0.282 → 0.261**, clearing the baseline on PR-AUC but missing
   precision@10% by ~0.003. Per the both-metrics gate, **the baseline logistic
   regression remains the production estimator**; XGBoost is not promoted.

## Consequences

- XGBoost's tracked metrics are now honest and comparable to the baseline
  (neither model's reported numbers are tuned on the rows they're graded on).
- The corrected numbers are *lower* than the pre-fix ones — that is the point;
  the earlier figures were inflated by the double-dip, not a regression.
- `expanding_year_folds` is the standard inner-CV convention for this repo's
  modeling work, with 5 leak-guard tests in `tests/`. Quarterly / rolling
  variants are intentionally not provided.
- A few seconds of extra compute per training run (the CV sweep + the refit).
  Negligible on a laptop; revisit only if a real hyperparameter search lands
  (Phase 2), which is out of scope now.
- The both-metrics promotion gate is the explicit, recorded rule for swapping
  the production estimator — future challengers are judged the same way.

## Amendment (2026-06-27) — feature-promotion gate needs only one model

Point 4 above is the **production-estimator** gate: it decides which single
model (baseline LogReg vs XGBoost challenger) is *served*, and a challenger must
clear the baseline on **both** PR-AUC and precision@10%. That is unchanged.

This amendment governs **feature promotion** — whether a new feature stays in
`ALL_FEATURES`. The rule was previously read as "the feature must improve
**both** models." It is relaxed to:

> A feature clears if it improves **at least one model** (LogReg or XGBoost) on
> **both** PR-AUC and precision@10%, with both arms evaluated on the **same
> temporal split** (control vs candidate, identical rows), judged on lift over
> base rate, and stable under expanding-window CV (a single-split move of
> ~±0.002 is noise, not a pass). Ship the model the feature improves; if that is
> not the current production estimator, switching the served model is part of
> promoting the feature.

**Why relax it.** We serve the better model, so a feature that helps the model
we ship is worth keeping even if it does not help the other family. Requiring
both families to agree was stricter than the decision we actually make (which
single model to serve) and would reject features that genuinely improve the
served model.

**Same-split requirement is now explicit.** A candidate and its control must be
graded on the *identical* test rows. Comparing a fresh candidate against a
stored control from a different split — different row count or base rate — is
not a valid read; base-rate differences alone move PR-AUC. (Surfaced by the
building-violations feature review: a stale control on a wider,
right-truncation-kept test set, base rate 8.85%, was compared against a
candidate on the correct fully-observed test set, base rate 10.5% — manufacturing
a +0.0198 PR-AUC "gain" that shrank to +0.0015 on the same test set and went
negative under expanding-window CV. The feature failed even this relaxed gate
on all three model families — LogReg, XGBoost, and the nb07 MLP — and was reverted.)

## References

- `src/foodsafety/utils/time.py` (`expanding_year_folds`, `temporal_split`),
  `notebooks/05_xgboost_model.ipynb`, `tests/` (leak guards)
- Code commit `70075e9`; metrics commit `0d3de14`
  (`reports/metrics/xgb_20260614_70075e927.json`)
- Decision record `0001` (experiment tracking; served = sigmoid), CLAUDE.md
  § "What NOT to do" (no shuffle, leakage guards)
