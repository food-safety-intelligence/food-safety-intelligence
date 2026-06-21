"""Tests for the dense violation-text embedding join.

The contract being locked down: ``add_text_embedding_features`` is a pure
per-text left join — a row's embedding depends ONLY on its own violations text,
never on another row, never on order, never on the (non-unique) inspection key.
Rows with empty / missing text get a zero vector and ``has_violation_text=0``.
"""

from __future__ import annotations

import pandas as pd

from foodsafety.features.text_features import (
    HAS_TEXT_COL,
    add_text_embedding_features,
    embedding_columns,
    violation_text_hash,
)


def _cache(texts: list[str]) -> pd.DataFrame:
    """Embedding cache keyed by text_hash, one fake 2-d vector per distinct text."""
    hashes = violation_text_hash(pd.Series(texts))
    return pd.DataFrame(
        {
            "text_hash": hashes,
            "txt_emb_000": [0.1 * (i + 1) for i in range(len(texts))],
            "txt_emb_001": [0.2 * (i + 1) for i in range(len(texts))],
        }
    )


def _frame(violations: list[str | None], license_ids=None) -> pd.DataFrame:
    n = len(violations)
    return pd.DataFrame(
        {
            "license_id": license_ids or [f"L{i}" for i in range(n)],
            "as_of_date": pd.to_datetime(["2019-04-01"] * n),
            "violations": pd.array(violations, dtype="string"),
        }
    )


def test_join_matches_own_text():
    cache = _cache(["rodent droppings", "no soap at sink"])
    out = add_text_embedding_features(
        _frame(["rodent droppings", "no soap at sink"]), cache
    ).set_index("license_id")
    assert out.loc["L0", "txt_emb_000"] == 0.1
    assert out.loc["L1", "txt_emb_000"] == 0.2
    assert (out[HAS_TEXT_COL] == 1).all()


def test_empty_or_missing_text_is_zero_filled_and_flagged():
    cache = _cache(["rodent droppings"])
    out = add_text_embedding_features(_frame(["rodent droppings", "", None]), cache).set_index(
        "license_id"
    )
    assert out.loc["L0", HAS_TEXT_COL] == 1
    for lic in ("L1", "L2"):  # empty string and missing both -> no text
        assert out.loc[lic, "txt_emb_000"] == 0.0
        assert out.loc[lic, "txt_emb_001"] == 0.0
        assert out.loc[lic, HAS_TEXT_COL] == 0


def test_duplicate_inspection_key_each_gets_own_text():
    # Same (license_id, as_of_date) twice with DIFFERENT text — the old key-based
    # join broke here; the content join gives each row its own embedding.
    cache = _cache(["rodent droppings", "no soap at sink"])
    frame = _frame(["rodent droppings", "no soap at sink"], license_ids=["Lx", "Lx"])
    out = add_text_embedding_features(frame, cache)
    assert sorted(out["txt_emb_000"].tolist()) == [0.1, 0.2]


def test_row_order_does_not_change_per_row_output():
    cache = _cache(["a", "b", "c"])
    frame = _frame(["a", "b", "c"])
    a = add_text_embedding_features(frame, cache).set_index("license_id").sort_index()
    b = (
        add_text_embedding_features(frame.iloc[::-1].reset_index(drop=True), cache)
        .set_index("license_id")
        .sort_index()
    )
    cols = embedding_columns(a) + [HAS_TEXT_COL]
    pd.testing.assert_frame_equal(a[cols], b[cols])
