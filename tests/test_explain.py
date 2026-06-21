"""Tests for the SHAP driver labelling (``foodsafety.explain.shap_drivers``).

The silent failure mode this guards against: a model feature with no
``FEATURE_LABELS`` entry renders its raw ``snake_case`` column name in the UI
driver list. That ships to the demo unnoticed because nothing else checks it.

Pinned down here:
  - **Label completeness** — every feature in ``ALL_FEATURES`` has a label, so
    no driver can surface as a raw column name.
  - **Sign-aware binary labels** — ``was_fail`` reads "Failed..." for the fail
    case and "Passed..." for the pass case (it surfaces as a driver in both
    directions), including when the value is a numpy integer.
  - **Raw-name fallback** — an unmapped feature degrades to its column name
    rather than crashing.

``top_drivers_for_row`` is pure (two ``pd.Series`` in), so these need no model,
parquet, or sklearn.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from foodsafety.explain.shap_drivers import FEATURE_LABELS, top_drivers_for_row
from foodsafety.models.baseline import ALL_FEATURES


def test_every_model_feature_has_a_label():
    """Every feature the models consume must have a UI label."""
    missing = [f for f in ALL_FEATURES if f not in FEATURE_LABELS]
    assert not missing, f"features with no FEATURE_LABELS entry: {missing}"


def test_was_fail_label_is_sign_aware():
    """The same binary feature reads oppositely for the fail vs pass case."""
    fail = top_drivers_for_row(
        pd.Series({"was_fail": 1}), pd.Series({"was_fail": 2.0}), k=1
    )[0]
    assert fail.label == "Failed the current inspection"

    passed = top_drivers_for_row(
        pd.Series({"was_fail": 0}), pd.Series({"was_fail": -0.4}), k=1
    )[0]
    assert passed.label == "Passed the current inspection"


def test_sign_aware_label_handles_numpy_value():
    """Row values arrive as numpy scalars from the parquet, not python ints."""
    d = top_drivers_for_row(
        pd.Series({"was_fail": np.int8(1)}), pd.Series({"was_fail": 2.0}), k=1
    )[0]
    assert d.label == "Failed the current inspection"


def test_unmapped_feature_falls_back_to_raw_name():
    """A feature with no label degrades to its column name, not an error."""
    d = top_drivers_for_row(
        pd.Series({"some_unmapped_feat": 5}),
        pd.Series({"some_unmapped_feat": 1.0}),
        k=1,
    )[0]
    assert d.label == "some_unmapped_feat"


def test_count_label_formats_as_integer():
    """Float-typed counts render without a trailing '.0'."""
    d = top_drivers_for_row(
        pd.Series({"n_priority_this_inspection": 6.0}),
        pd.Series({"n_priority_this_inspection": 1.6}),
        k=1,
    )[0]
    assert d.label == "6 priority violations at this inspection"
