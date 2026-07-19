"""Close out the two audit follow-ups with actual tests, not assertions.

1) LA neighborhood FPR: is the observed max-min range across ZIPs bigger than you'd
   expect by chance GIVEN those group sizes, if every ZIP had the same true FPR?
   Parametric null: flagged_g ~ Binomial(n_negatives_g, p_overall). This directly tests
   the "range statistic over many small groups is inflated" claim in the docs.

2) NYC cuisine: is Bangladeshi's miscalibration distinguishable from chance at n=125?
   Under perfect calibration the positives are Binomial(n, mean_predicted); an exact
   two-sided binomial test says whether the observed failure rate is a fluke.
"""

import json
import sys

import numpy as np
from scipy.stats import binomtest

REPORTS = sys.argv[1]
RNG = np.random.default_rng(42)
N_SIM = 20000


def la_permutation_test():
    d = json.load(open(f"{REPORTS}/fairness_audit_la.json"))
    ax = d["model1_risk"]["axes"]["neighborhood"]
    groups = [g for g in ax["group_table"] if g.get("audited") and g.get("fpr") is not None]
    n_neg = np.array([g["n"] - g["positives"] for g in groups], dtype=float)
    fpr = np.array([g["fpr"] for g in groups], dtype=float)
    keep = n_neg > 0
    n_neg, fpr = n_neg[keep], fpr[keep]

    observed = fpr.max() - fpr.min()
    p_overall = float((fpr * n_neg).sum() / n_neg.sum())

    # Null: every ZIP shares p_overall; only sampling noise drives the spread.
    counts = RNG.binomial(n_neg.astype(int)[None, :].repeat(N_SIM, 0), p_overall)
    sim_fpr = counts / n_neg[None, :]
    sim_range = sim_fpr.max(axis=1) - sim_fpr.min(axis=1)

    pval = float((sim_range >= observed).mean())
    print("=== LA neighborhood (ZIP) false-positive-rate range ===")
    print(
        f"  audited ZIPs: {len(n_neg)} | negatives per ZIP: min {int(n_neg.min())} "
        f"median {int(np.median(n_neg))} max {int(n_neg.max())}"
    )
    print(f"  pooled FPR: {p_overall:.4f}")
    print(f"  OBSERVED max-min range: {observed:.4f}")
    print(
        f"  null range (same FPR everywhere): mean {sim_range.mean():.4f} "
        f"median {np.median(sim_range):.4f} p95 {np.percentile(sim_range, 95):.4f} "
        f"max {sim_range.max():.4f}"
    )
    print(f"  p-value P(null >= observed) = {pval:.4f}")
    print(
        f"  => {'NOT distinguishable from chance (inflation claim HOLDS)' if pval > 0.05 else 'BEYOND chance (inflation claim FAILS; gap looks real)'}"
    )
    return {
        "observed": observed,
        "p_value": pval,
        "null_mean": float(sim_range.mean()),
        "null_p95": float(np.percentile(sim_range, 95)),
    }


def nyc_cuisine_test():
    d = json.load(open(f"{REPORTS}/fairness_audit_nyc.json"))
    ax = d["model1_risk"]["axes"]["cuisine"]
    groups = [g for g in ax["group_table"] if g.get("audited") and g.get("ece") is not None]
    print("\n=== NYC cuisine: is each group's miscalibration beyond chance? ===")
    print(f"  {'cuisine':<28} {'n':>5} {'pred':>6} {'obs':>6} {'ECE':>6} {'p(exact)':>10}")
    rows = []
    for g in sorted(groups, key=lambda r: -r["ece"]):
        n, pred, obs = g["n"], g["mean_pred"], g["mean_obs"]
        k = int(round(obs * n))
        p = binomtest(k, n, pred, alternative="two-sided").pvalue
        rows.append(
            {"group": g["group"], "n": n, "pred": pred, "obs": obs, "ece": g["ece"], "p": float(p)}
        )
        print(
            f"  {g['group'][:28]:<28} {n:>5} {pred:>6.3f} {obs:>6.3f} {g['ece']:>6.3f} {p:>10.2e}"
        )
    # Bonferroni across the audited cuisines
    m = len(rows)
    sig = [r for r in rows if r["p"] < 0.05 / m]
    print(f"\n  Bonferroni threshold (alpha .05 / {m} cuisines) = {0.05 / m:.2e}")
    print(f"  cuisines beyond chance: {[r['group'] for r in sig] or 'none'}")
    return rows


if __name__ == "__main__":
    la = la_permutation_test()
    nyc = nyc_cuisine_test()
    json.dump({"la": la, "nyc": nyc}, open(sys.argv[2], "w"), indent=2)
