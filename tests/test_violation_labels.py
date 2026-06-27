"""Tests for the LLM violation-label join.

Contract: ``add_violation_label_features`` is a pure per-text left join — a row's
labels depend only on its own comment, never on another row, never on order,
never on the (non-unique) inspection key. Rows with no comment get the no-text
defaults (hazard "none", severity 0, flags False, has_violation_text 0).
"""

from __future__ import annotations

import pandas as pd

from foodsafety.features.violation_labels import (
    HAS_TEXT_COL,
    NO_TEXT_HAZARD,
    add_violation_label_features,
    violation_text_hash,
)


def _cache(texts: list[str], rows: list[dict]) -> pd.DataFrame:
    out = pd.DataFrame(rows)
    out.insert(0, "text_hash", violation_text_hash(pd.Series(texts)))
    return out


def _frame(violations: list[str | None], license_ids=None) -> pd.DataFrame:
    n = len(violations)
    return pd.DataFrame(
        {
            "license_id": license_ids or [f"L{i}" for i in range(n)],
            "as_of_date": pd.to_datetime(["2019-04-01"] * n),
            "violations": pd.array(violations, dtype="string"),
        }
    )


def _mice():
    return {
        "llm_hazard": "pest_vermin",
        "llm_severity": 3,
        "llm_imminent_health_hazard": True,
        "llm_corrected_on_site": False,
    }


def _floors():
    return {
        "llm_hazard": "sanitation_cleaning",
        "llm_severity": 2,
        "llm_imminent_health_hazard": False,
        "llm_corrected_on_site": False,
    }


def test_join_matches_own_text():
    cache = _cache(["live mice", "dirty floors"], [_mice(), _floors()])
    out = add_violation_label_features(_frame(["live mice", "dirty floors"]), cache).set_index(
        "license_id"
    )
    assert out.loc["L0", "llm_hazard"] == "pest_vermin"
    assert out.loc["L0", "llm_severity"] == 3
    assert bool(out.loc["L0", "llm_imminent_health_hazard"]) is True
    assert out.loc["L1", "llm_hazard"] == "sanitation_cleaning"
    assert (out[HAS_TEXT_COL] == 1).all()


def test_no_text_gets_defaults_and_flag_zero():
    cache = _cache(["live mice"], [_mice()])
    out = add_violation_label_features(_frame(["live mice", "", None]), cache).set_index(
        "license_id"
    )
    for lic in ("L1", "L2"):
        assert out.loc[lic, "llm_hazard"] == NO_TEXT_HAZARD
        assert out.loc[lic, "llm_severity"] == 0
        assert bool(out.loc[lic, "llm_imminent_health_hazard"]) is False
        assert bool(out.loc[lic, "llm_corrected_on_site"]) is False
        assert out.loc[lic, HAS_TEXT_COL] == 0


def test_duplicate_inspection_key_each_gets_own_labels():
    cache = _cache(["live mice", "dirty floors"], [_mice(), _floors()])
    frame = _frame(["live mice", "dirty floors"], license_ids=["Lx", "Lx"])
    out = add_violation_label_features(frame, cache)
    assert sorted(out["llm_hazard"].tolist()) == ["pest_vermin", "sanitation_cleaning"]


def test_row_order_does_not_change_per_row_output():
    cache = _cache(["live mice", "dirty floors"], [_mice(), _floors()])
    frame = _frame(["live mice", "dirty floors"])
    cols = ["llm_hazard", "llm_severity", HAS_TEXT_COL]
    a = add_violation_label_features(frame, cache).set_index("license_id").sort_index()
    b = (
        add_violation_label_features(frame.iloc[::-1].reset_index(drop=True), cache)
        .set_index("license_id")
        .sort_index()
    )
    pd.testing.assert_frame_equal(a[cols], b[cols])
