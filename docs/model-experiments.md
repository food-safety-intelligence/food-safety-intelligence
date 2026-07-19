# Model Experiments Log

- **Owner**: Bella · **Last updated**: 2026-07-12
- One row per modeling experiment: the change + hypothesis, the measured result, and the
  verdict (kept / reverted). **Negative results are logged too** — knowing what *didn't*
  move the needle is the point.
- Conventions: commit code before a tracked run (provenance), machine metrics land in
  `reports/metrics/<run>.json`, decisions in `docs/decisions/`, and feature-contract
  version bumps in [`interface_contracts.md`](interface_contracts.md#feature-contract-changelog).
- The Chicago experiment **log** is below; a **cross-city ablation** section (Chicago, NYC,
  and LA in one parallel frame) is at the end. Ablation runs land in
  `reports/metrics/{chicago,nyc,la}/`.
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
| 2026-06-21 | **311 redesign — venue-level + neighborhood (Run 2)** — re-attack the flat 300 m radius counts. Address-exact complaint counts + recency + trend (the venue's OWN 311 history, keyed on exact street address, not a radius) + ring-based neighborhood-normalized excess (100 m vs 500 m, strips the density confound). *Does isolating the venue — or its local context — unlock 311 signal the radius missed?* | Clean **univariate** monotonic separation (address-exact fail-rate 0.136→0.219; recency ≤30 d 0.21; rising-trend 0.20) — but **flat on the honest test** (n=13,812; A/B isolating the 5 cols vs v36): LogReg PR-AUC 0.344→0.350 / P@10 0.369→0.371; XGB 0.353→**0.351** / 0.373→0.374 (PR-AUC *down*). Fails the both-metrics gate. Flat on the cold-start cut (prior_*-empty rows). Neighborhood ring-excess: flat, orthogonal to prior_* (corr 0.02) but uninformative. | **Reverted** — 311 is redundant with `prior_*` at every spatial scale (venue, local ring; admin-unit/polygon argued moot + a fairness-proxy risk). Feature code + leak-free tests retained in `complaint_features.py`, unwired | this PR |
| 2026-06-21 | **Inspection-history depth (Run 3)** — extract MORE from the inspection record `prior_*` already summarises: (a) **historical hazard-type** prior counts — the 12 keyword flags aggregated over PRIOR inspections per license (`prior_flag_kw_*_count`, cumsum-minus-self); (b) **chronic / repeat-violation recurrence** — `prior_max_repeat_priority_code`, `prior_n_distinct_priority_codes`, `prior_repeat_priority_rate`. *Does a recurring hazard TYPE, or repeat-offender behaviour, beat the undifferentiated `prior_priority_violations` count?* | **Flat.** Honest test n=13,812, A/B isolating the 15 cols: LogReg PR-AUC 0.3442→0.3443 (flat) / P@10 0.369→0.371; XGB 0.353→0.355 / 0.373→0.378 (faint). XGB add-one attribution: the 12 hazard-type flags are *noise* (PR-AUC −0.0033); only `prior_repeat_priority_rate` looked + on one split (+0.0011 / +0.0022) — **but expanding-window CV killed it** (LogReg mean ΔPR-AUC −0.0001 / ΔP@10 −0.0014; XGB mean ΔPR-AUC −0.0019, std ≫ mean; the lone 2020 fold's +0.0072 was a lucky window). A textbook single-split false positive caught by CV. | **Reverted** — redundant with `prior_*`; the inspection history is already well-summarised by the existing aggregates. Built inline (not formalised into a module). | this PR |
| 2026-06-21 | **Missingness indicator (baseline LogReg)** — `SimpleImputer(add_indicator=True)` so LogReg learns the structural "no prior event" NaNs (`days_since_last_inspection`, `days_since_last_fail`, `last_was_fail`, `prev_priority_violations`, `priority_violation_trend`, `license_age_days` — 6 cols) instead of conflating them with the median. *Does flagging missingness beat plain median-impute?* | **Flat.** Honest test n=13,812, A/B (median-only vs +indicator; ranking metrics are calibration-invariant): PR-AUC 0.3442→0.3449 (+0.0007, noise), P@10 0.3690 unchanged, P@5 0.434→0.428 (slightly down). The 6 indicators are redundant — `prior_inspections` / `prior_fails` / `prior_fail_or_priority_events` already encode the no-prior-history case. (XGBoost unaffected — NaN-native.) | **Reverted** — no change to `baseline.py`. | this PR |
| 2026-06-21 | **Fail-only label — expanding-window CV** (validation of the prototype row above). Build the leak-free Fail-only forward-180 d label (event flag = `results == "Fail"` only, same forward-window logic) and re-run the baseline across **6 expanding-year folds** (RT-filtered, 180 d embargo). *Does the prototype's "more learnable" finding hold up across folds, or was it a single-split artifact?* | **Holds up.** Mean lift over base rate across 6 folds: fail-only **PR-lift 3.61** vs current 3.22; **P@10-lift 3.86** vs 3.70. Fail-only wins **6/6** folds on PR-lift, **4/6** on P@10-lift. (Compared on lift, not raw PR-AUC — fail-only prevalence 6.1% vs current 13.6%.) Unlike Run 3's morsel, CV *confirms* rather than erases it. | **Rejected on product grounds — kept fail-or-priority (DR 0007).** More learnable, but this is a consumer food-safety *risk* product: codes 1–29 are the city's serious tier already used across ~8 features + the UI, and fail-only narrows the target + leans harder on the re-inspection artifact. CV evidence retained as the record that the broad label is a *deliberate* choice, not a default. | this PR, DR 0007 |
| 2026-06-21 | **Violation free-text embeddings (Layer-C dense NLP)** — embed each inspection's own violation comment with Amazon Titan Text Embeddings V2 (Bedrock, 256-dim, offline batch → parquet cache, leak-free per-text join), reduce to 32 PCA comps (fit on TRAIN only) + a `has_violation_text` flag, A/B into both models. *Do dense contextual embeddings beat the 12 keyword flags + structured codes — i.e. is the comment text under-encoded, or just redundant?* | **Flat / fails the gate.** Honest test n=13,812, A/B isolating the 33 cols (32 PCA + flag): production **LogReg fails the both-metrics gate** — PR-AUC 0.3442→0.3446 (flat) / P@10 0.369→**0.367 (down)**. XGB PR-AUC 0.3526→0.3530 (flat) / P@10 0.373→0.387 — a single-split P@10 bump on top of flat PR-AUC, on the non-production model (the same shape Run 3's false positive took before CV killed it). PCA(32) keeps 76% of embedding variance, so the flatness isn't a reduction artifact. Fairness (LogReg): Children's-facility recall@10% 0.435→**0.391 (down)**, School 0.646→0.633; no vulnerable-group win. | **Reverted** — the comment text is **redundant with the structured codes 1–29 + keyword flags**, not under-encoded; the dense embeddings add no signal the flags don't already carry. Feature module (`text_features.py`) + offline builder (`build_text_embeddings.py`) + leak test retained, **unwired** (not in `ALL_FEATURES`). | this PR |
| 2026-06-21 | **Core-code break-out ablation** — split specific CORE codes (30+) out of the undifferentiated `n_core_this_inspection` count: structured boolean flags for codes 33 (hot holding), 48 (warewashing), 50 (hot/cold water), 54 (garbage), 58 (allergen training), built from the current inspection's violation text (leak-free, same basis as the other current-inspection features). Motivated by a univariate scan showing core-code lift spans 1.2×–2.4× over the 15.1% base — i.e. core is *not* uniform. *Does any specific core code carry orthogonal signal the generic core count misses?* | **Flat / fails the gate.** Honest test n=7,008, base 10.8%, A/B vs the v36 baseline (uncalibrated; ranking metrics). **+all-5:** PR-AUC 0.3716→0.3731 (+0.0015) but P@10 0.415→**0.399 (−0.016, down)**. **+allergen-58-only:** PR-AUC +0.0006 / P@10 −0.0014 (flat). No single code passes (33/48/50 ≈0; 54 +0.0010 PR-AUC but −0.013 P@10). The raw data has ~22.8k allergen mentions (~19.9k are code 58, "allergen training") — real but already absorbed by `n_core_this_inspection`. | **Reverted** — same outcome as the 2026-06-15 per-code experiment; the generic core count already captures it. **Allergen has no modeling lift** — its only case is a distinct *product* angle (allergen-awareness for a different vulnerable-diner population), not accuracy. Throwaway script only; nothing wired. | this PR |
| 2026-06-21 | **LLM structured violation-label extraction (Layer-C dense NLP, Spike #2)** — Amazon Nova Lite (Bedrock, forced tool-use) reads each violation comment → 4 observed-conduct labels (hazard type / severity 1–3 / imminent-hazard / corrected-on-site) over the 90,174 distinct comments (offline batch → parquet cache, leak-free per-text-hash join), A/B the 5 label cols into both models. *Does turning prose into clean structured severity/hazard signal beat the codes + 12 keyword flags — the companion bet to the dense embeddings (Spike #1, row above)?* | **Null — fails the gate.** Honest test n=13,812: production **LogReg** PR-AUC 0.3442→0.3442 (flat) / P@10 0.369→**0.367 (down)**. XGB PR-AUC 0.3526→0.3545 (flat) / P@10 0.373→0.386 — single-split wobble on the non-production model (corrected-on-site / severity ride the re-inspection circularity). Fairness recall@10%: Children's 0.435→0.391, School 0.646→0.620 (no win); hazard-mix skew = genuine facility-type differences, not a proxy. | **Reverted** — redundant with codes 1–29 + keyword flags (severity/imminent ≈ `was_fail` + `n_priority_this_inspection`); even the interpretability path is a no (no accuracy, dents vulnerable-group recall). `violation_labels.py` + builder kept in-tree, **unwired**. | this PR |
| 2026-06-21 | **External data — block-face building permits + violations** — first orthogonal-data bet from the modeling-ceiling handoff: physical-plant condition (permits/violations on the venue's block-face). New SODA datasets `ydr8-5enu` (permits) + `22u3-xenr` (violations), fetched 2017+ (730d burn-in), block-face spatial join (BallTree ~30m — exact street-number matching is too brittle, building records file under adjacent numbers, ~40% / ~2% recall), leak-free counts + recency strictly before the anchor. 5 cols A/B'd into XGB. *Does building condition — genuinely independent of inspection history — add signal?* | **Null — fails the gate under CV.** Single-split honest test n=13,812: +building PR-AUC 0.3526→0.3548 / P@10 0.3726→0.3748 (both +0.0022), but add-one attribution is flat-to-negative (no single col carries it). **Expanding-window CV (6 folds, RT-filtered, 180d embargo) kills it:** mean ΔPR-lift +0.0066 (std 0.038 ≫ mean), mean ΔP@10-lift −0.0025, P@10 wins 1/6. Block-face match (~47% of anchors have a record in-window) is the honest granularity — exact-building is unavailable in the data. | **Reverted (unwired).** Confirms the information-ceiling — even orthogonal external data is flat at available granularity. `building_features.py` + leak-free tests + dataset IDs kept in-tree, **not in `ALL_FEATURES`**. | this PR |
| 2026-06-21 | **Leave-one-out feature ablation (diagnostic)** — drop each of the 36 v36 features one at a time, retrain XGB on the canonical split, measure ΔPR-AUC / ΔP@10 on the honest test. *Which features actually carry the model?* | **2 features carry it; the rest are a flat tail.** Removing `n_priority_this_inspection` (−0.0278 PR-AUC) or `was_fail` (−0.0255) costs ~0.05 combined; the other 34 each move PR-AUC within ±0.006, and ~12 *improve* it slightly when dropped (single-split noise). Caveat: leave-one-out *understates* correlated features (the two current-inspection cols mask each other). | **Diagnostic only** — confirms capacity isn't the limit. Not a feature-cut mandate: any drop needs expanding-window CV, same as additions. No code change. | this PR |
| 2026-06-21 | **External data — chain vs. independent (univariate gate)** — derive a chain flag from `dba_name` (distinct-license count per normalized name) and check fail-rate separation chain vs. independent — the cheap gate before building a leak-safe detector. *Does franchise / corporate food-safety structure separate risk?* | **Flat overall; real-but-tiny on cold-start; wrong encoding.** Whole sample: chain fail-rate ≈ independent (ratio 0.86–0.97 across ≥3/5/10/20-location thresholds) — `prior_*` already captures the track record (echoes the flat 2026-06-14 operator-prior). Cold-start (`prior_inspections==0`, ~8.9% of rows): chains fail ~half as often (0.071 vs 0.13–0.14, ratio ~0.5) — but that slice is only ~1.2% of the data, and "chain" is non-monotonic (gas-station food CITGO 0.19 / SHELL 0.19 high-risk vs fast-food TACO BELL 0.06 / CHIPOTLE 0.09 low), so a binary flag is the wrong encoding. | **Not built — gated out.** The only signal is on ~1% of rows, below the noise floor that killed building permits. A *product* note (cold-start chains are lower-risk), not an accuracy feature — same shape as the allergen finding. No code. | this PR |
| 2026-06-21 | **Label deconfounding — exposure / inverse-propensity weighting (3A)** — the label is only observed through an inspection, so it conflates "risky" with "got inspected." Build an exposure-propensity model P(next inspection ≤180d) from leak-free as-of-date cadence cols, then A/B the risk model with `sample_weight ∝ 1/p` (stabilized) vs the unweighted v36 baseline, both models, same gate. *Does reweighting away the inspection-arrival confound clean up the ranking?* | **Null — reverted.** Confound is real but localized: v36 score corr with exposure-propensity **0.86**, top decile **91% just-failed** — but corr with generic cadence is tiny (`prior_inspections` 0.10), so it's the documented `was_fail`→mandated-re-inspection mechanism, not "inspected often." The stabilized two-arm reweighting *does* deconfound (corr 0.86→0.79 LogReg / 0.91→0.75 XGB) but is flat-to-down on the gate (LogReg −0.004/−0.009; XGB −0.010/0.000) with no fairness win (Children's recall@10% 0.43→0.39); the aggressive `1/p` arm is worse (LogReg −0.027/−0.028). Wrinkle: test labels are equally censored, so the gate can't credit deconfounding anyway — the call rests on diagnostic + fairness, both no. | **Reverted (unwired).** The exposure coupling isn't a separable nuisance — it's the legitimate just-failed signal that drove v36. Script `scripts/run_exposure_ipw_experiment.py` + metrics on branch `bella/mle-deconfound-label-ipw`. Open 3A sub-levers: inspector-strictness (no inspector ID), fail-only (DR 0007). | this PR |
| 2026-06-27 | **Building-violation features — re-evaluation + revert (corrects PR #44)** — PR #44 re-added 9 block-face building-violation features (aggregate counts/recency + a 5-bureau split: conservation/refrigeration/plumbing/ventilation/electrical) to `ALL_FEATURES`, reporting XGB **+0.0198 PR-AUC / +0.0231 P@10**. That delta compared a freshly-trained candidate (correct RT-dropped test, n≈6,702, base 10.5%) against a **stale stored control on a different test set** (`xgb_20260621_bef769ef8.json`, RT-kept n=13,812, base 8.85%) — a base-rate artifact, not signal (ROC-AUC and top-decile lift, which are base-rate-invariant, both went *down* −0.021 / −0.458). *Re-run honestly: same rows both arms, all three model families.* | **Null — fails the gate on every model.** Same-split A/B on the correct test (n=7,008, base 10.8%): the control's PR-AUC rises 0.3381→0.3597 once moved onto the correct rows — that +0.0216 IS the fake "gain"; the feature's real contribution is **+0.0015 PR-AUC** (noise). Expanding-window CV (6 folds, 180d embargo): **XGB** mean ΔPR-AUC −0.0055, both-gate 2/6; **LogReg** ΔPR-AUC +0.0005, 2/6; **MLP (nb07)** ΔPR-AUC −0.0045, 1/5. Add-one ablation: all 9 columns negative on both metrics. Even under the relaxed one-model gate (DR 0002 amendment), no model clears it. Reproduces the original 2026-06-21 building-permits-and-violations null (row above). | **Reverted** — 9 features removed from `ALL_FEATURES` + driver labels; `features/building_features.py` (incl. the bureau split) kept in-tree, **unwired**. Also corrected **nb07 (MLP)**: it was evaluating on the wrong RT-kept test set (deflated, base 8.8%) — now drops burn-in + right-truncated before splitting, matching the production scorer. | this PR |
| 2026-06-28 | **Forward-looking trend — last-K-visits slope on a forecast-only model** — the served `trend_slope_90d` (90-day OLS of the *production* score, `predict_batch._compute_trend_slopes`) is null for ~70% of licenses (needs 2 inspections within 90 days) and, when present, tracks the mandated fail→re-inspection swing. Two independent knobs: **window** 90-day→**last-K visits** (coverage) and **score** production→**forecast-only Model 2** (drops `was_fail`/`n_priority_this_inspection`/`n_core_this_inspection`; makes the trend forward-looking). Reconstructs the 2026-06-22 `/tmp` prototype on real data + sweeps K∈{3,4,5,6,8}. Basis: anchors = each license's latest **non-right-truncated** test inspection (n=5,226, base 4.4%, 97.5% clean). XGB both models. | **Coverage 0.29→0.87** (K-independent — only needs 2 of the last K). **Partly forward-looking**: corr(slope, `last_was_fail`) −0.31→−0.19 (residual is legitimate prior-history signal, not the re-inspection bounce). **Clean early-warning** (was_fail==0, base 4.4%): strict top-decile rising slope **2.26× @K=5** (2.1–2.3× for K3–5, decays to 1.74× @K8), strict top-20% ~1.65×, **loose slope>0 ~1.16× (uninformative)**. Reproduces + exceeds the prototype's 1.46×. | **Ship as an additive descriptive trend + early-warning watch-list (DR 0011).** A coverage + honesty win, **not** a predictive improving/worsening/stable label (the loose signal is flat). Replaces `trend_slope_90d` → `trend_slope` (last-K=5 forecast); adds per-inspection forecast scores for a real detail-page chart. | DR 0011, this PR |
| 2026-07-18 | **XGBoost hyperparameter sweep (feature set frozen)** — the served depth-3 monotone config was hand-picked, never swept. 112 configs (one-factor-at-a-time + 80-draw randomized search) scored on 6-fold expanding-window CV over the train+val region (test held out), then seed-robustness-checked. Knobs: `max_depth`, `learning_rate`, `n_estimators`, `min_child_weight`, `reg_lambda`, `reg_alpha`, `gamma`, `subsample`, `colsample_bytree`, `max_delta_step`, `scale_pos_weight` scaling, monotone on/off. *Is the served config at its HPO optimum, or is there headroom?* | **Near-optimal — one small robust lever.** Every knob except one is null-or-worse (deeper trees, higher lr, more estimators, `monotone=False` all regress — re-confirming the DR 0002/0009 choices). The lone sweep "winner" that beat the incumbent on the single test split was a **lucky seed** (across 8 seeds its PR-AUC delta is +0.0000, higher variance) — correctly rejected. The one robust improvement is **`colsample_bytree` 0.85→0.70**: two features dominate (`was_fail`, `n_priority_this_inspection`), so sampling fewer columns per tree decorrelates the ensemble and sharpens the top-decile ranking. Smooth monotone basin (0.6–0.8 all beat 0.85; 1.0 worse), seed-mean over 16 seeds **PR-AUC 0.3813→0.3824, P@10 0.4147→0.4153 at lower variance**. Served seed-42 retrain: **P@10 0.4151→0.4208, P@5 0.484→0.490, top-decile lift 3.85→3.90, Brier better**; PR-AUC a tie (0.38202→0.38199, within noise; +0.0011 in expectation). | **Kept — promoted `colsample_bytree=0.70` in `build_production_xgb`.** A top-decile-precision + calibration win (the worklist operating point) at tie PR-AUC; the seed-averaged evidence has PR-AUC up too. No feature change; serving contract unchanged. Served-JSON republish is the deploy step. | this PR |

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

> **2026-06-27 — XGBoost promoted to production (DR 0009 closed).** A **depth-3
> XGB with monotone constraints** on the risk-count features now beats the served
> LogReg on the served-basis test (n=7,008): **PR-AUC 0.382 vs 0.372**, P@10 0.4151
> (ties this split). The single split isn't the gate — under expanding-window CV
> (0002) XGB wins **both** metrics in **5/6 folds** (mean ΔPR-AUC +0.0051, ΔP@10
> +0.0062). The depth-6 default lost (numbers above) because deep trees can't
> extrapolate the forward-time `prior_*` counts; depth-3 + monotone fixes the top
> decile. Explainability solved with XGBoost **native TreeSHAP** (no `shap` dep);
> the served `scores.json` schema + waterfall are unchanged. Served via
> `scripts/retrain_xgb_sigmoid.py`. The MLP (nb07), properly seed-averaged + sigmoid,
> only ties LogReg (~0.371) — kept as a benchmark, not served.

**Convention going forward:** report each experiment's impact on **both** models
where measured (LogReg + XGB served) — a feature can help one and not the other.
Regenerate this table after any contract change with `operating_point_table` on
both estimators.

## Reading the pattern

Seven-plus feature/text/spatial angles came up **flat** because the risk is largely already
captured by `prior_*` inspection history, and much inspection-outcome variance is
irreducible (inspector + timing noise). Runs 2–3 reinforced it: **311 is redundant at every
spatial scale** (venue/address-exact, local ring, admin-unit), and **deeper inspection-history**
(hazard-type breakdowns, repeat-offender recurrence) adds nothing the existing `prior_*`
aggregates don't already hold — the one marginal candidate was a single-split false positive
that expanding-window CV erased. The two changes that actually moved metrics were a
**methodology fix** (XGB validation) and a **fairness-driven simplification** (proxy
removal) — not added features. The **label** lever is now settled: fail-only was
more learnable under CV but rejected on product grounds (kept fail-or-priority —
DR 0007). The last under-exploited surface — the **violation free-text** — has now
been spiked at **both ends** and came back **null** (see below). That leaves the
**operating point / product**, not more features.

## Deep-learning scoping (Phase 2)

The one genuinely under-exploited surface was the **violation free-text**, so the
Phase-2 DL bets targeted it — and **both spikes came back null** on the
both-metrics gate (honest test n=13,812; v36 baseline LogReg 0.332/0.370, XGB
0.338/0.376):

- **Spike #1 — dense embeddings** (Titan Text V2 → PCA(32) → GBM): flat; LogReg
  P@10 down. (Row above.)
- **Spike #2 — LLM structured severity/hazard labels** (Nova Lite → 5 cols → GBM):
  flat; LogReg P@10 down. (Row above.)

The text is **redundant with codes 1–29 + the 12 keyword flags**, not
under-encoded — so the *information-not-capacity* ceiling holds for text too. The
remaining DL families are **NO-GO at this scale** (documented, not spiked):

- **Sequence model** (RNN / temporal-Transformer over each license's ordered
  inspections) — `prior_*` already encodes recency / trend / 365-day / last-outcome;
  ~80k short sequences would relearn those aggregates with more variance. Default NO-GO.
- **Tabular DL** (FT-Transformer / TabNet) — wrong tool at ~80k rows with heavy
  structural NaNs; GBMs win this regime and XGBoost already pulled even with LogReg
  on v36. Expected lift ≈ 0.
- **Graph** (operator / inspector / address networks) — the cross-license
  **operator-prior already came up flat** (2026-06-14), and an inspector-linked
  graph would re-create the geographic/demographic proxy we dropped `static_zip`
  for (fairness red flag). NO-GO.

**Net:** no untried DL lever has positive expected value at this scale; the next
gains are product/operating-point, not model capacity.

---

# Cross-city ablations (Chicago, NYC, LA)

> **Refreshed 2026-07-19** on the current shipped models (run_id `20260719_c186cf99a`).
> The only material change from the 2026-07-12 baseline below is **NYC**, after the
> closure/tenure feature additions: NYC full PR-AUC **0.583 → 0.615** (prior-only
> 0.540→0.536, current-only 0.488→0.524, LogReg 0.561→**0.615** — the linear model now
> ties XGBoost on NYC). The family-contribution *structure* is unchanged: neither
> family alone matches the full model, and prior history alone gets closest in every
> city. See figures 12–13 in `notebooks/09_cross_city_eda.ipynb`. The detailed table
> below is the 2026-07-12 baseline run.

All three cities' served models now sit in one parallel ablation frame, from
`scripts/run_city_ablations.py`. Each city reuses its **own** production code (so
numbers match the served model), holds its served temporal split fixed, and
evaluates every variant on the **same** held-out test set. Each run is a tracked
JSON under `reports/metrics/<city>/<city>_<variant>_<run_id>.json` (all from
run_id `20260712_b2dc6102d`), carrying the full metric set — pr-auc, roc-auc,
precision/recall/f1 at 5/10/20% and at a 0.5 threshold, top-decile lift, Brier,
log-loss — plus, for each served model, its global feature importance. The runner
never rewrites committed app JSON.

The tables below show the headline set; **precision / recall / f1 are at a 0.5
decision threshold**, which is stringent under class imbalance — for LA (base
8.7%) the calibrated scores rarely exceed 0.5, so recall there is near-zero and
the ranking metrics (P@10, R@10, lift) are the meaningful operating point.

**The frames are parallel by analogy, not identical numbers** — the cities differ
in pipeline, label, and feature taxonomy, so compare the *shape* across cities,
never the absolute values:

| | Chicago | NYC / LA |
|---|---|---|
| Source | `features.parquet` pipeline | inline `build_events` from a raw SODA/ArcGIS snapshot |
| Label | fail-or-critical within 180d | next inspection graded B/C |
| Served fit | depth-3 monotone XGB + Platt | XGB + Platt |
| "prior-only" variant | `xgb_forecast_only` (drop current-outcome) | `xgb_prior_only` |
| "current-only" variant | `xgb_current_outcome_only` (3 cols) | `xgb_current_only` |
| "drop text layer" | `xgb_no_keywords` (the 12 `flag_kw_*`) | `xgb_no_theme_sev` (crosswalk theme/severity) |

**Caveat:** these are a **single split**, not expanding-window CV. Chicago's
richer CV-gated verdicts are in the log above; NYC/LA have only ~3 post-COVID
years, so CV folds are thin. Read the deltas as directional. As a sanity check,
Chicago's `served_xgb_full` here (PR-AUC **0.382**) reproduces the served model
(DR 0009) — the ablation fits match production.

### Chicago — test n=7,008, base rate 10.8% (`chicago_*_20260712_b2dc6102d.json`)

Metrics: PR-AUC, ROC-AUC, then precision / recall / f1 at the **0.5 threshold**,
then precision@10% / recall@10% / lift@10%.

| Variant | n | PR-AUC | ROC-AUC | P(.5) | R(.5) | F1(.5) | P@10 | R@10 | lift@10 |
|---|---|---|---|---|---|---|---|---|---|
| **served_xgb_full** | 36 | **0.382** | **0.806** | 0.583 | 0.148 | 0.236 | **0.415** | **0.385** | **3.85** |
| xgb_forecast_only (drop current-outcome) | 33 | 0.336 | 0.775 | 0.610 | 0.066 | 0.119 | 0.359 | 0.333 | 3.33 |
| xgb_current_outcome_only (3 cols) | 3 | 0.324 | 0.752 | 0.528 | 0.099 | 0.167 | 0.377 | 0.349 | 3.49 |
| xgb_no_keywords (drop 12 `flag_kw_*`) | 24 | 0.371 | 0.803 | 0.551 | 0.130 | 0.210 | 0.412 | 0.382 | 3.82 |
| logreg_full | 36 | 0.372 | 0.800 | 0.553 | 0.152 | 0.239 | 0.415 | 0.385 | 3.85 |

### NYC — test n=9,456, base rate 41.0% (`nyc_*_20260712_b2dc6102d.json`)

| Variant | n | PR-AUC | ROC-AUC | P(.5) | R(.5) | F1(.5) | P@10 | R@10 | lift@10 |
|---|---|---|---|---|---|---|---|---|---|
| **served_xgb_full** | 29 | **0.583** | **0.674** | 0.607 | 0.407 | 0.487 | **0.693** | **0.169** | **1.69** |
| xgb_prior_only | 11 | 0.540 | 0.651 | 0.591 | 0.317 | 0.413 | 0.627 | 0.153 | 1.53 |
| xgb_current_only | 18 | 0.489 | 0.579 | 0.559 | 0.195 | 0.290 | 0.569 | 0.139 | 1.39 |
| xgb_no_theme_sev (drop theme+severity) | 12 | 0.575 | 0.669 | 0.605 | 0.397 | 0.479 | 0.669 | 0.163 | 1.63 |
| xgb_plus_keywords (+12 keyword flags) | 41 | 0.580 | 0.674 | 0.606 | 0.403 | 0.484 | 0.683 | 0.167 | 1.67 |
| logreg_full | 29 | 0.561 | 0.666 | 0.600 | 0.401 | 0.481 | 0.641 | 0.156 | 1.56 |

### LA — test n=7,197, base rate 8.7% (`la_*_20260712_b2dc6102d.json`)

| Variant | n | PR-AUC | ROC-AUC | P(.5) | R(.5) | F1(.5) | P@10 | R@10 | lift@10 |
|---|---|---|---|---|---|---|---|---|---|
| **served_xgb_full** | 28 | **0.187** | **0.721** | 0.667 | 0.003 | 0.006 | **0.218** | **0.252** | **2.52** |
| xgb_prior_only | 11 | 0.161 | 0.667 | 0.000 | 0.000 | 0.000 | 0.206 | 0.238 | 2.37 |
| xgb_current_only | 17 | 0.152 | 0.695 | 0.000 | 0.000 | 0.000 | 0.161 | 0.186 | 1.86 |
| xgb_no_theme_sev (drop theme+severity) | 12 | 0.184 | 0.713 | 0.000 | 0.000 | 0.000 | 0.208 | 0.241 | 2.41 |
| xgb_plus_keywords (+12 keyword flags) | 40 | 0.183 | 0.722 | 0.333 | 0.002 | 0.003 | 0.217 | 0.250 | 2.50 |
| logreg_full | 28 | 0.166 | 0.721 | 0.192 | 0.071 | 0.103 | 0.183 | 0.212 | 2.12 |

LA's low PR-AUC is the 8.7% base rate — read the base-rate-invariant lift (2.52×)
and ROC (0.72). The **0.5-threshold P/R/F1 are near-degenerate** here (the
calibrated XGB rarely scores an LA event above 0.5, so most variants predict no
positives → 0/0); this is the imbalance caveat above in action, not a bug —
LA's meaningful operating point is the top-10% (P@10 / R@10 / lift).

## Served-model operating points

The 0.5-threshold P/R/F1 above are the textbook default, but not what the product
uses (and for LA, barely usable). The product ranks establishments and works the
top slice, so the meaningful cutoffs are **worklist depth** (top-K) and, if a
single hard threshold is ever needed, the **F1-optimal** one. Both are recorded
in each `*_served_xgb_full_*.json` (`operating_points`, `f1_optimal_threshold`).

Served model — precision / recall / lift at each worklist depth:

| City (base rate) | top 5% | top 10% | top 20% |
|---|---|---|---|
| Chicago (10.8%) | 0.486 / 0.23 / 4.50× | 0.415 / 0.39 / 3.85× | 0.317 / 0.59 / 2.94× |
| NYC (41.0%) | 0.704 / 0.09 / 1.72× | 0.693 / 0.17 / 1.69× | 0.651 / 0.32 / 1.59× |
| LA (8.7%) | 0.244 / 0.14 / 2.82× | 0.218 / 0.25 / 2.52× | 0.199 / 0.46 / 2.30× |

Served model — F1-optimal single threshold (vs the arbitrary 0.5):

| City | best threshold | P | R | F1 | (F1 at 0.5) |
|---|---|---|---|---|---|
| Chicago | 0.225 | 0.357 | 0.508 | **0.419** | 0.236 |
| NYC | 0.316 | 0.484 | 0.819 | **0.609** | 0.487 |
| LA | 0.122 | 0.199 | 0.467 | **0.279** | 0.006 |

Takeaways: (1) **0.5 is the wrong cutoff** — moving to the F1-optimal threshold
roughly doubles Chicago's F1 (0.236 → 0.419) and rescues LA's from ~0 (0.006 →
0.279), because the calibrated scores for a rare event sit well below 0.5. (2)
**Lift falls with depth** (Chicago 4.5× at 5% → 2.9× at 20%): going deeper catches
more (recall up) at lower precision — a **capacity decision**, not a model change.
(3) This is a *diagnostic*. The served product uses base-rate-anchored **tiers**
(DR 0017), not a binary threshold, so there is no served cutoff to tune.

## Deployed-model feature importance

Global importance for each city's **served** XGB = mean |TreeSHAP| per feature over
the test set (margin space) — the same explainability the app's per-row driver
waterfalls are built on. Full ranked lists live in each `*_served_xgb_full_*.json`
under `feature_importance` (with each feature's share of total); top 8 shown here.
The rankings **corroborate the ablations**: Chicago is carried by the current
inspection, NYC by prior history, LA by a mix.

| Rank | Chicago (share) | NYC (share) | LA (share) |
|---|---|---|---|
| 1 | was_fail (0.26) | prior_inspections (0.17) | cur_score (0.22) |
| 2 | n_priority_this_inspection (0.14) | days_since_last_inspection (0.11) | prior_inspections (0.18) |
| 3 | license_age_days (0.11) | prior_n_critical (0.11) | days_since_last_inspection (0.14) |
| 4 | prior_complaint_inspections (0.10) | cur_score (0.09) | prior_mean_score (0.10) |
| 5 | n_core_this_inspection (0.07) | prior_bad_rate (0.09) | prev_score (0.05) |
| 6 | temporal_month (0.06) | prior_mean_score (0.07) | cur_n_viol (0.05) |
| 7 | static_inspection_type (0.06) | cur_n_viol (0.05) | cur_sev_T3 (0.03) |
| 8 | static_risk_tier (0.02) | cur_theme_temperature_control (0.04) | cur_theme_pest_vermin (0.03) |

Chicago's top two are the current inspection's own outcome (`was_fail` +
`n_priority_this_inspection`, 40% of total SHAP combined) — the same two the
leave-one-out ablation flagged as carrying the model (log, 2026-06-21). NYC's top
three are all prior-history features; LA leads with the current score but leans on
prior history right behind it. The theme/severity and keyword-analog features sit
low in every ranking, consistent with the "text layer is marginal" ablation
result.

## Reading the pattern (cross-city)

- **The full feature set wins in all three cities** — no single family matches it,
  so history and the current inspection are **complementary**, not substitutes.
- **The dominant family flips across cities.** In **Chicago** the current
  inspection's own outcome is the biggest lever: dropping it
  (`xgb_forecast_only`) is the largest single cut (0.382 → **0.336**, −0.046), and
  just the 3 current-outcome columns alone (`xgb_current_outcome_only`) already
  reach **0.324** PR-AUC (85% of the full model). In **NYC and LA it's the
  reverse** — `xgb_prior_only` (0.540 / 0.161) beats `xgb_current_only` (0.489 /
  0.152). The likely cause: NYC/LA inspect **roughly annually**, so the "current"
  snapshot is staler and the prior track record carries relatively more.
- **Keyword flags help a little in Chicago, not at all when transferred.** Now
  measured in one frame: dropping Chicago's 12 `flag_kw_*` (`xgb_no_keywords`)
  costs **+0.011 PR-AUC** (0.382 → 0.371) — small but positive, which is why
  Chicago ships them. Bolting that *same* Chicago-tuned regex set onto NYC/LA
  (`xgb_plus_keywords`) is instead flat-to-slightly-negative — NYC 0.583 →
  **0.580**, LA 0.187 → **0.183**. The transfer fails because NYC/LA already
  encode those hazards via their crosswalk theme/severity features, and the
  regexes are tuned to Chicago's phrasing (see the caveat in `keyword_flags.py`).
  So **Chicago keeps its keyword layer; NYC/LA don't need one.**
- **NYC/LA's crosswalk theme + severity layer is also marginal** — dropping it
  (`xgb_no_theme_sev`) costs only +0.008 (NYC) / +0.003 (LA) PR-AUC; 12 features
  recover ~99% of the model. It's the code→category analog of Chicago's structured
  codes (from `reference/violation_crosswalk.csv`), not free-text NLP. Worth
  keeping for the driver labels, but not where the signal lives.
- **XGBoost beats LogReg in all three cities** (Chicago +0.010: 0.382 vs 0.372;
  NYC +0.022; LA +0.021 PR-AUC), consistent with Chicago's 2026-06-27 XGB
  promotion (DR 0009). XGB is the right served estimator everywhere.

**Net:** the served config (full XGB + Platt) is the right call for every city;
the signal is carried by inspection history + current outcome together, with the
text/theme layer a small extra (a genuine +0.011 in Chicago, redundant in
NYC/LA). Next step if pursued: expanding-window CV on the thin NYC/LA post-COVID
windows before treating those deltas as gate-passing verdicts.

## Closing the Chicago feature gap (NYC / LA feature additions, 2026-07-18)

NYC/LA shipped a leaner feature set than Chicago: they lacked the time-windowed
(recent) priors, calendar/seasonality, recency-to-last-bad, trend, tenure, and
visit-type families. Added each MISSING family **leak-free** and A/B'd it under
**expanding-window CV** + a **seed-robustness** confirm on the held-out test (8
seeds), per city, via `scripts/run_city_feature_experiments.py`. A family is kept
only if it clears the both-metrics gate AND holds up across seeds. Deliberately
NOT tried: Chicago's keyword text flags (the ablation above already showed them
flat-to-negative when transferred) and inspector id / facility-type / geography
(fairness/legal).

| City | Change + hypothesis | Result | Verdict |
|---|---|---|---|
| **NYC** | **Add DOHMH enforcement (`cur_closed` / `prior_closures`) + establishment `tenure_days`.** *Does the closure/enforcement action carry signal beyond the numeric score, and does tenure help?* | **Yes, both.** CV both-gate pass; holdout seed-check (8 seeds): **+0.024 PR-AUC / +0.043 P@10, both up 8/8**. `cur_closed` is the current visit's own outcome (→ CURRENT); `prior_closures` + `tenure_days` are forecast-safe (→ PRIOR). Interesting: a closure predicts *lower* next-inspection risk (remediate + re-inspect to reopen), so it's a clean separator. `recent365`, `recency_bad`, `trend`, `calendar` all failed the gate for NYC. | **Kept** — wired into `build_nyc_scores.py` + driver labels. |
| **NYC (HPO)** | **Regularize Model 1 harder** now that it has the new features: `max_depth` 3→2, `min_child_weight` 5→20. *Did the extra features make the old depth-3 config over-fit?* | **Yes.** Seed-check (8 seeds): **+0.011 PR-AUC / +0.006 P@10, both up 7/8** on top of the feature gain. | **Kept.** **Combined served NYC (features + HPO), same test n=9,456: PR-AUC 0.583 → 0.615 (+0.032), ROC 0.674 → 0.698, top-decile lift 1.69 → 1.80.** Regenerated + republished. |
| **LA** | Same candidate families (tenure, calendar, visit-type = ROUTINE vs OWNER-INITIATED, recent priors, trend). | **Null.** LA's CV region is a single fold (short post-COVID window). On the holdout across 8 seeds every family is flat-to-negative: tenure **−0.0055 PR-AUC** (both-gate 1/8), visit-type −0.008, calendar −. LA sits at its information ceiling (base 8.7%, ~98% A-grades). | **Reverted (no change).** Kept the incumbent; negative result logged (`reports/metrics/la/la_feature_experiments.json`). |

**Standardization note:** the *methodology* (leak-free guards, expanding-window
CV, both-metrics + seed gate, Platt-on-margin, TreeSHAP drivers) and the *feature
concepts* are shared across cities; the *label* and *raw encoding* are not (data-
dictated). The same families produced different winners per city — NYC gains from
the closure signal it uniquely has, LA has no equivalent — which is why the code
is standardized but the served features differ.
