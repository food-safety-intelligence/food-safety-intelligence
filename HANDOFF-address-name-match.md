# Agent handoff — disambiguate score matches by name, not address alone

**Branch:** `bella/agent-address-name-match` (off `origin/main`)
**Workstream owner:** Deepak (agentic AI / AWS). Bella opened this from a review.
**File:** `agents/tools/get_safety_score/handler.py`
(`_load_scores_index`, `_normalise_address`, `_fuzzy_lookup`).

> Delete this note in the commit that lands the fix (or fold it into the PR
> description). It is scaffolding, not a doc to keep.

## The problem

`get_safety_score` attaches a Chicago inspection record (license_id, risk score,
trend, percentile) to each OSM restaurant by matching on **normalised address
only**:

```python
index = { _normalise_address(r["address"]): r for r in scores }   # keyed by address
...
matches = difflib.get_close_matches(key, index.keys(), n=1, cutoff=0.72)
```

Two failure modes:

1. **Shared addresses.** Many Chicago food establishments share one street
   address — food courts, malls, hospitals, schools, and especially **O'Hare /
   Midway** (dozens of licenses at one airport address). Address-only matching
   picks *one arbitrary* record for that address, so restaurant A can be shown
   restaurant B's license, score, and inspection history.
2. **Last-writer-wins index.** `_load_scores_index` builds a `dict` keyed by
   address, so when several records share a normalised address, **all but the
   last are silently dropped** from the index before matching even runs.

This is a consumer-facing reputational-harm bug: it can pin a bad (or good) score
on the wrong named business. The ethics charter (decision record 0005,
principle 1) treats exactly this kind of wrong individual signal as the harm to
avoid.

## The fix

Match on **address AND name**, and stop collapsing the index:

1. **Index by address to a LIST**, not a single record:
   `dict[str, list[dict]]` so shared-address records are all retained.
2. On lookup, find the candidate address bucket (exact, then fuzzy via
   `difflib.get_close_matches` over the keys as today), then **choose within the
   bucket by name similarity** between the OSM `name` and each record's
   `dba_name`.
3. Add a `_normalise_name()` helper: uppercase, strip punctuation, collapse
   whitespace, and drop trailing store numbers (`"MCDONALD'S #1234"` ->
   `"MCDONALDS"`). OSM names and city `dba_name` values are formatted very
   differently, so normalise hard before comparing.
4. **Require both to clear a threshold.** Accept the match only if the address is
   close AND the best name similarity (e.g. `difflib.SequenceMatcher` ratio) is
   above a cutoff (start ~0.6 and tune on fixtures). If no name clears the bar,
   return `None` -> `matched_scores_json: false` (the prompt already handles "no
   Chicago inspection record found"). A missed match is far safer than a
   confident wrong one.

`get_safety_score` currently passes only `address` into `_fuzzy_lookup`; thread
the restaurant `name` through too.

## Verification

- `uv run ruff check agents/ && uv run ruff format --check agents/`
- Add `agents/tools/get_safety_score/test_*` fixtures covering:
  - two records at the same normalised address with different names -> each OSM
    name maps to the correct license (the core bug);
  - a name that matches nothing in the bucket -> `None` (no false match);
  - store-number / punctuation normalisation (`"Dunkin'"` vs `"DUNKIN #305"`).
- Sanity-check against the real `app/public/data/scores.json` for a known
  shared-address site (an airport terminal) if available.

## Context to read first

- `docs/interface_contracts.md` §3 — `scores.json` has `dba_name` and `address`.
- `docs/decisions/0005-ethics-bias-and-responsible-ai.md` principle 1 — a wrong
  per-establishment signal is the harm we are guarding against.
