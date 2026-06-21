"""Layer-C (dense) NLP — violation free-text embeddings as model features.

The hybrid violation-text strategy in CLAUDE.md is A (structured code counts),
B (hand-picked keyword flags), C (dense text). This module is the *dense* arm
of C: instead of the flat TF-IDF -> TruncatedSVD that came up flat, it joins
**precomputed sentence-embedding columns** onto the feature frame. The
embeddings themselves are produced offline by ``scripts/build_text_embeddings.py``
(a one-time Bedrock batch pass, cached to parquet) — never at request time and
never inside this module. This is the permanent batch -> cache -> features
pattern; nothing here calls a model.

Join key is the **text itself** (a content hash), not the inspection key: the
embedding is a pure function of the violation comment, and ``(license_id,
as_of_date)`` is NOT unique (a licence can have two inspections on one day with
different text). Hashing the text dedupes natively and matches each row to the
embedding of its OWN comment.

Leak-free contract (the WHY, per CLAUDE.md):
  Each row receives the embedding of its OWN current violations text, which is
  observed at ``as_of_date`` — the exact same justification as the ``was_fail``
  / ``n_priority_this_inspection`` current-inspection features (label window is
  strictly AFTER as_of_date). The join is a pure per-text lookup: NO cross-row
  aggregation, NO prior-mean embedding, NO ``.shift()``. A prior-mean embedding
  WOULD need the exclusive-window guard the prior_* features use, so we do not
  build one here.
"""

from __future__ import annotations

import hashlib

import pandas as pd

# Cache column convention. The offline builder writes one float column per
# embedding dimension as ``txt_emb_000``..``txt_emb_NNN`` plus the ``text_hash``
# join key. Reduction (PCA fit on TRAIN only) happens at modelling time, not here
# — a train-fit transform can't be precomputed without leaking the split.
EMBED_PREFIX: str = "txt_emb_"
HAS_TEXT_COL: str = "has_violation_text"
TEXT_HASH_COL: str = "text_hash"


def embedding_columns(df: pd.DataFrame) -> list[str]:
    """The ``txt_emb_*`` columns present in ``df``, in sorted (dimension) order."""
    return sorted(c for c in df.columns if c.startswith(EMBED_PREFIX))


def violation_text_hash(violations: pd.Series) -> pd.Series:
    """Stable content hash of each row's normalised violations text.

    Normalisation (string-cast -> fill missing -> strip) MUST match the offline
    builder so the hashes line up. Rows with empty/missing text hash to ``<NA>``
    so they don't join to any embedding (they get the zero vector instead).
    """
    norm = violations.astype("string").fillna("").str.strip()
    return norm.map(lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest() if s else pd.NA).astype(
        "string"
    )


def add_text_embedding_features(
    df: pd.DataFrame,
    embeddings: pd.DataFrame,
) -> pd.DataFrame:
    """Left-join the cached violation-text embedding columns by text content.

    Args:
        df: feature frame; must contain the ``violations`` text column.
        embeddings: cache from ``scripts/build_text_embeddings.py`` — one row per
            distinct comment, with ``text_hash`` plus ``txt_emb_*`` columns.

    Returns:
        New frame = ``df`` plus the ``txt_emb_*`` columns and a
        ``has_violation_text`` 0/1 flag. Rows with empty / missing violations
        text (or text not in the cache) get a **zero vector** and
        ``has_violation_text=0`` — the flag lets the model separate "text says
        nothing risky" from "there was no text".

    Leak-free: a pure left join on the row's OWN text hash. The output for a row
    depends only on that row's own comment; row order does not matter and no
    other row's text is consulted.
    """
    emb_cols = embedding_columns(embeddings)
    if not emb_cols:
        raise ValueError("embeddings frame has no txt_emb_* columns")

    out = df.copy()
    out[TEXT_HASH_COL] = violation_text_hash(out["violations"])
    cache = embeddings[[TEXT_HASH_COL, *emb_cols]].copy()
    cache[TEXT_HASH_COL] = cache[TEXT_HASH_COL].astype("string")
    # Defend against an accidentally-duplicated cache; the embedding is identical
    # for a given hash, so keeping the first is lossless and keeps the join 1:m.
    cache = cache.drop_duplicates(TEXT_HASH_COL)

    out = out.merge(cache, on=TEXT_HASH_COL, how="left", validate="many_to_one")
    out[HAS_TEXT_COL] = out[emb_cols[0]].notna().astype("int8")
    out[emb_cols] = out[emb_cols].fillna(0.0)
    return out.drop(columns=[TEXT_HASH_COL])
