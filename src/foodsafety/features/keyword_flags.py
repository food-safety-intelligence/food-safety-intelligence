"""Layer B NLP — hand-picked keyword flags on the violations text.

The hybrid violation-text NLP strategy in CLAUDE.md is:
  A. Structured code counts  (in `inspection_features.py`)
  B. Hand-picked keyword flags  (this module)
  C. Optional TF-IDF + TruncatedSVD  (Phase 6 stretch)

The keyword choices below are deliberately narrow and grounded in food-safety
domain semantics — temperature failures, vermin / pest evidence, specific
contamination categories. Each flag becomes one SHAP-friendly column whose
contribution we can interpret on the detail page. Phase 5 may extend the
list; never trim it without versioning the change.

Why hand-picked over TF-IDF: a 5000-column sparse TF-IDF matrix going into
XGBoost is awkward to explain in the model card. ~12 named flags with clear
domain meaning are more defensible at write-up time.
"""

from __future__ import annotations

import re

import pandas as pd

# Each flag's regex matches the residual TEXT of the violations field
# (not the code prefix). The text usually contains a "Comments:" section
# describing what the inspector observed. We match case-insensitive on the
# inspector's free-form descriptions.
#
# A flag is True for a row if any of its patterns matches the violations
# text. Patterns are written with word boundaries (\b) where appropriate
# to avoid matching common substrings.
#
# CAVEAT — these patterns are tuned to the actual phrasing patterns in the
# Chicago inspections corpus. If we adopt this for a different city, the
# patterns will need re-tuning.
KEYWORD_PATTERNS: dict[str, str] = {
    # --- temperature / cold chain ---
    "flag_kw_temperature": r"\btemp(?:erature)?\b|holding[- ]?temp|cold[- ]?holding|hot[- ]?holding",
    "flag_kw_cooling": r"\bcooling\b|cool(ed|ing)? properly|cool[- ]?down|within 4 ?hr",
    # --- contamination / handling ---
    "flag_kw_raw_food": r"\braw\s+(chicken|beef|pork|meat|poultry|seafood|fish|egg)",
    "flag_kw_cross_contamination": r"cross[- ]?contam(ination)?|separat(e|ion)\s+raw|ready[- ]?to[- ]?eat",
    "flag_kw_expired": r"\bexpire[ds]?\b|past\s+(?:expir|use)\s+date|date[- ]?mark(ed|ing)?",
    # --- vermin / pest evidence ---
    "flag_kw_rodent": r"\brodent\b|\brat[s]?\b|\bmice\b|\bmouse\b|droppings|gnaw",
    "flag_kw_pest": r"\bpest\b|\bcockroach(es)?\b|\broaches?\b|insect activity",
    # --- handwashing / hygiene ---
    "flag_kw_no_soap": r"\bno\s+(?:hand[- ]?)?soap\b|missing\s+(?:hand[- ]?)?soap",
    "flag_kw_no_paper_towels": r"\bno\s+(?:paper\s+)?towels?\b|missing\s+(?:paper\s+)?towels?",
    "flag_kw_handwash_sink": r"hand[- ]?wash(ing)?\s+sink|handwash\s+sign",
    # --- sanitation / facility ---
    "flag_kw_sewage": r"\bsewage\b|backed[- ]?up|sewer\s+line",
    "flag_kw_certified_manager": r"certified\s+food\s+(?:protection\s+)?manager|cfpm|food\s+manager\s+certif",
}


def add_keyword_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Append boolean ``flag_kw_*`` columns derived from the violations text.

    Each flag is True if any of its regex patterns matches (case-insensitive)
    anywhere in the row's violations field. Missing / NaN violations text
    yields False for every flag.

    The patterns intentionally match the residual prose (not the code prefix),
    so they capture signal that the structured code counts in
    ``inspection_features.py`` would miss — e.g. "expired" appears with many
    different codes depending on what expired.
    """
    out = df.copy()
    text = out["violations"].astype("string").fillna("").str.lower()

    for flag_name, pattern in KEYWORD_PATTERNS.items():
        compiled = re.compile(pattern, re.IGNORECASE)
        # ``apply`` rather than ``str.contains`` so we can use compiled regex
        # consistently; small perf cost is fine for 310k rows.
        out[flag_name] = text.apply(lambda s, r=compiled: bool(r.search(s)))

    return out
