# Experiments Log

- **Owner**: Bella · **Last updated**: 2026-06-21
- One row per modeling experiment: the change + hypothesis, the measured result, and the
  verdict (kept / reverted). **Negative results are logged too** — knowing what *didn't*
  move the needle is the point.
- Conventions: commit code before a tracked run (provenance), machine metrics land in
  `reports/metrics/<run>.json`, decisions in `docs/decisions/`, and feature-contract
  version bumps in [`interface_contracts.md`](interface_contracts.md#feature-contract-changelog).
- **Metric basis matters.** "served" = baseline LogReg + sigmoid, review-time-filtered
  test (n≈7,008); "honest test" = unfiltered test (n≈13,812). The two bases are not
  directly comparable; each row says which it used.

## Log

| Date | Experiment (change + hypothesis) | Result | Verdict | Refs |
|---|---|---|---|---|
| 2026-06-14 | **XGBoost validation double-dip fix** — early-stop on an embargoed train tail (val reserved for calibration only); add expanding-window CV. *Does fixing the leak change the honest estimate?* | honest test PR-AUC 0.254→**0.268**, log_loss 0.282→0.261; CV PR-AUC 0.326±0.029 | **Kept** (methodology). Baseline still the production estimator on the both-metrics gate (XGB misses precision@10%) | DR 0002 |
| 2026-06-14 | **Operator + license-status priors** — `operator_prior_fail_rate` (cross-license, by `account_number`), license renewals-to-date, days-to-expiration. *Does cross-license operator history add signal?* | served PR-AUC 0.3147→0.3151 (**flat**); P@10 / R@10 unchanged | **Reverted**. (Also found `license_status` is uniformly "AAI" → the planned REV/AAC counts are impossible) | — |
| 2026-06-14 | **Visit-trigger + near-miss priors** — add `prior_pass_w_conditions`, `prior_reinspections`, `prior_complaint_inspections`, `static_inspection_type` (26→30) | incremental over 26 (served settled ≈0.3147) | **Kept** | contract v30 |
| 2026-06-15 | **Per-code 1–29 prior violation-count features** — one prior-count column per priority code. *Does code-level detail beat the rollups?* | flat | **Reverted** (branch deleted) | — |
| 2026-06-15 | **Comment-severity text features** — severity signal mined from violation comments | flat / slightly negative (collinear with `prior_*`) | **Reverted** | — |
| 2026-06-15 | **Recency / trend features** — `last_was_fail`, `prev_priority_violations`, `priority_violation_trend`, `prior_fails_365d`, `prior_priority_violations_365d`. *Does recent history beat lifetime totals on a non-stationary process?* | served PR-AUC +≈0.005 | **Kept** — the only own-history lever that moved | contract v33 |
| 2026-06-15 | **Layer-C TF-IDF → TruncatedSVD(50)** on residual violation text (leak-free prior-mean) | flat, both models | **Kept local** (`mle/layer-c-tfidf-svd`, not merged) as the "we did NLP" deliverable | — |
| 2026-06-15 | **311 geotemporal complaint counts** — `n_311_*` within 300 m × 90/180 d prior window (BallTree). *Does neighbourhood complaint density add signal?* | served PR-AUC 0.3147→0.3152 (**flat**); bottom-of-gain in XGBoost | **Excluded** from the model; code retained in `complaint_features.py`. Redundant with the rodent/pest/sewage keyword flags | — |
| 2026-06-15 | **Fairness audit + proxy removal** — drop `static_zip` and `static_facility_type`, ship alongside recency/trend (30→33). *Can we cut geographic/business-type proxies without losing accuracy?* | served PR-AUC 0.3147→**0.3246**, P@10 0.352→**0.364**; XGB 0.2681→**0.2882**. Both metrics up, both models, **+ fairness win**. (Within this: dropping `static_facility_type` ≈free 0.3147→0.3139; dropping `static_zip` *improved* 0.3147→0.3188 — its sparse dummies overfit the chronological split) | **Kept** | DR 0004, contract v33 |
| 2026-06-21 | **Sharper label prototype** — Fail-only (and priority-only) vs current fail-or-priority, 180 d, same pipeline + chronological split, full 33 features. *Is a crisper target more learnable?* | **Yes.** Top-decile lift over base rate: fail-only **4.1×** vs current 3.4× vs priority-only 3.2×; PR-AUC/prevalence 4.12 vs 3.01. Raw PR-AUC is lower (0.236 vs 0.324) only because prevalence is lower (5.7% vs 10.8%); priority-only is the noisy half diluting the current label. | **Promising** — add CV + label-owner (Aurelia/Arun) sign-off before any contract change | this PR |
| 2026-06-21 | **Current-inspection own outcome (33→36)** — keep the anchor inspection's own `was_fail` + `n_priority_this_inspection` + `n_core_this_inspection` (already computed as intermediates, then dropped). Leak-free: observed at as_of_date, label window strictly after. *Does the current visit's own result/counts add signal beyond the PRIOR outcomes + keyword flags?* | **Yes — both models, both metrics** (honest test n=13,812; controlled A/B isolating just the 3 cols). LogReg PR-AUC 0.291→**0.344**, P@10 0.326→**0.369**; XGB 0.280→**0.344**, P@10 0.306→**0.367**; top-decile lift ~4.2. (Calibrated artifacts: LogReg 0.332 / XGB 0.338.) **Caveat:** top decile ~91% recent-failers (mandated re-inspection lands in the window) — but the gain persists on never-failed rows (PR-AUC 0.128→0.146) and helps cold-start (0.36→0.40). Ethics review cleared: vulnerable-pop recall@10% 0.50→0.60; the lone Children's PR-AUC dip is small-group noise. | **Kept** — clears the both-metrics gate (0002); resets the baseline for Runs 2–3 | contract v36, DR 0005 (principle 6) |

## Model comparison: LogReg vs XGBoost

The **served LogReg baseline is the production estimator** (both-metrics gate,
decision 0002). On the time-held-out test (n=7,008, 11% prevalence) it edges
XGBoost at the operating points that matter:

| top-k | LogReg precision / recall / lift | XGBoost precision / recall / lift |
|---|---|---|
| 5% | **0.451** / 0.21 / **4.18** | 0.437 / 0.20 / 4.05 |
| 10% | **0.364** / **0.34** / **3.38** | 0.344 / 0.32 / 3.19 |
| 20% | 0.289 / 0.54 / 2.68 | 0.288 / 0.53 / 2.67 |
| 50% | 0.180 / 0.83 | 0.180 / 0.84 |

PR-AUC: LogReg **0.325** vs XGB 0.312. (XGB's ROC-AUC is a hair higher — 0.772 vs
0.770 — but ROC-AUC is the wrong metric under this imbalance.) They converge past
the top 20%.

> **v36 update (2026-06-21, current-inspection features).** The table above is the
> **v33 served-basis** comparison. Under v36 the gap closes: on the honest test
> (n=13,812) XGBoost slightly *leads* — PR-AUC LogReg 0.332 vs XGB **0.338**, P@10
> 0.370 vs **0.376**. The **served LogReg stays the production estimator** (it feeds
> `scores.json`; v36 served test PR-AUC **0.372**, P@10 **0.415**, n=7,008), but XGB
> pulling even is worth a production-model revisit — a separate decision, not this
> PR. A full v36 **served-basis** refresh of the operating-point table is pending an
> XGB served-filter run.

**Convention going forward:** report each experiment's impact on **both** models
where measured (LogReg served + XGB) — a feature can help one and not the other.
Regenerate this table after any contract change with `operating_point_table` on
both estimators.

## Reading the pattern

Five-plus feature/text/spatial angles came up **flat** because the risk is largely already
captured by `prior_*` inspection history, and much inspection-outcome variance is
irreducible (inspector + timing noise). The two changes that actually moved metrics were a
**methodology fix** (XGB validation) and a **fairness-driven simplification** (proxy
removal) — not added features. That's why the next bets are the **label** (this log's last
row) and the **operating point / product**, not more features.
