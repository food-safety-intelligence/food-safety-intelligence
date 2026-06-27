"""Layer-C (structured) NLP — LLM-extracted hazard/severity labels as features.

The hybrid violation-text strategy in CLAUDE.md is A (structured code counts),
B (hand-picked keyword flags), C (dense text). This module is a *structured*
take on C: instead of dense embeddings (see the sibling embedding spike), it
joins a handful of **interpretable categorical labels** an LLM extracted from
each comment — hazard type, severity, imminent-hazard, corrected-on-site. The
labels are produced offline by ``scripts/build_violation_labels.py`` (a one-time
Bedrock batch, cached to parquet) — never at request time, never in this module.

Join key is the **text itself** (a content hash), not the inspection key: the
labels are a pure function of the comment, and ``(license_id, as_of_date)`` is
NOT unique (a licence can have two same-day inspections with different text).

Leak-free contract (the WHY, per CLAUDE.md):
  Each row gets the labels of its OWN current comment, observed at ``as_of_date``
  — same justification as the ``was_fail`` current-inspection feature (the label
  window is strictly AFTER as_of_date). Pure per-text lookup: no cross-row
  aggregation, no ``.shift()``.

CIRCULARITY WATCH (per the deep-learning handoff): ``llm_corrected_on_site`` and
the severity of the current visit describe the current inspection's own outcome.
That is leak-free (observed at as_of_date) but, like ``was_fail``, can lean on the
mandated-re-inspection dynamic — interpret any lift with that in mind.
"""

from __future__ import annotations

import hashlib

import pandas as pd

TEXT_HASH_COL: str = "text_hash"
HAS_TEXT_COL: str = "has_violation_text"

# The categorical hazard vocabulary the extractor is constrained to. Kept here so
# the builder, the feature join, and the tests share one source of truth.
HAZARD_VALUES: tuple[str, ...] = (
    "temperature",
    "pest_vermin",
    "contamination",
    "sanitation_cleaning",
    "handwashing_hygiene",
    "facility_maintenance",
    "documentation_certification",
    "other",
)
NO_TEXT_HAZARD: str = "none"  # rows with no comment — distinct from the model's "other"

# Cache columns the builder writes (besides text_hash).
LABEL_COLS: tuple[str, ...] = (
    "llm_hazard",
    "llm_severity",
    "llm_imminent_health_hazard",
    "llm_corrected_on_site",
)


def violation_text_hash(violations: pd.Series) -> pd.Series:
    """Stable content hash of each row's normalised violations text.

    Normalisation (string-cast -> fill missing -> strip) MUST match the offline
    builder so the hashes line up. Empty/missing text hashes to ``<NA>`` so it
    joins to nothing (and falls through to the no-text defaults).
    """
    norm = violations.astype("string").fillna("").str.strip()
    return norm.map(lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest() if s else pd.NA).astype(
        "string"
    )


def add_violation_label_features(
    df: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    """Left-join the cached LLM hazard/severity labels by text content.

    Args:
        df: feature frame; must contain the ``violations`` text column.
        labels: cache from ``scripts/build_violation_labels.py`` — ``text_hash``
            plus the ``llm_*`` columns, one row per distinct comment.

    Returns:
        New frame = ``df`` plus ``llm_hazard`` (categorical, ``"none"`` when there
        was no comment), ``llm_severity`` (0–3, 0 = no comment), the two boolean
        ``llm_*`` flags, and ``has_violation_text``. Rows whose text isn't in the
        cache get the no-text defaults.

    Leak-free: a pure left join on the row's OWN text hash; row order is
    irrelevant and no other row's comment is consulted.
    """
    missing = [c for c in LABEL_COLS if c not in labels.columns]
    if missing:
        raise ValueError(f"labels frame missing columns: {missing}")

    out = df.copy()
    out[TEXT_HASH_COL] = violation_text_hash(out["violations"])
    cache = labels[[TEXT_HASH_COL, *LABEL_COLS]].copy()
    cache[TEXT_HASH_COL] = cache[TEXT_HASH_COL].astype("string")
    cache = cache.drop_duplicates(TEXT_HASH_COL)

    out = out.merge(cache, on=TEXT_HASH_COL, how="left", validate="many_to_one")

    out[HAS_TEXT_COL] = out["llm_hazard"].notna().astype("int8")
    out["llm_hazard"] = out["llm_hazard"].fillna(NO_TEXT_HAZARD).astype("category")
    out["llm_severity"] = out["llm_severity"].fillna(0).astype("int8")
    out["llm_imminent_health_hazard"] = out["llm_imminent_health_hazard"].fillna(False).astype(bool)
    out["llm_corrected_on_site"] = out["llm_corrected_on_site"].fillna(False).astype(bool)
    return out.drop(columns=[TEXT_HASH_COL])
