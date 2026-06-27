# Agent handoff — fix explain_restaurant inspection miscount + find_restaurants error shape

**Branch:** `bella/agent-explain-overpass-fixes` (off `origin/main`)
**Workstream owner:** Deepak (agentic AI / AWS). Bella opened this from a review.
**Files:** `agents/tools/explain_restaurant/handler.py` (`_summarise`) and
`agents/tools/find_restaurants/handler.py` (`handler` error return).

> Delete this note in the commit that lands the fix (or fold it into the PR
> description). It is scaffolding, not a doc to keep.

Two unrelated-but-small bugs, grouped because both are quick and both are in the
tool handlers.

---

## Bug 1 — `explain_restaurant._summarise` miscounts inspection outcomes

```python
result = ev.get("result", "").lower()
if "fail" in result:        counts["fail"] += 1
elif "conditions" in result: counts["pass_w_conditions"] += 1
else:                        counts["pass"] += 1     # <-- catch-all
```

Chicago inspection `results` are not just Pass / Fail / Pass w/ Conditions. They
also include **"Out of Business", "No Entry", "Not Ready", "Business Not
Located"**. All of those fall into the `else` branch and are counted as **Pass**,
inflating the pass count shown to users in the inspection summary.

Second issue in the same function: it assumes `inspection_history` is already
sorted newest-first. It uses `events[0]` as `last_date` (and `handler` slices
`events[:10]` as "most recent 10"). If the JSON is not pre-sorted, the "last
inspection" and the displayed history are wrong.

### Fix

1. Classify explicitly instead of using a catch-all. Map known result strings to
   `pass` / `fail` / `pass_w_conditions`, and add an `other` bucket (or
   `not_inspected`) for Out of Business / No Entry / Not Ready / Business Not
   Located so they are not miscounted as passes. Return the new bucket in the
   summary dict (extend the contract; it is agent-internal, not the cross-team
   parquet schema).
2. Sort `events` by date descending **inside the handler** before summarising and
   before the `[:10]` slice, so correctness does not depend on upstream sort
   order. Guard bad/missing dates.

Check the exact `result` strings present in `app/public/data/inspection_history.json`
before finalising the mapping — match the real data, do not guess.

---

## Bug 2 — `find_restaurants` returns a malformed element on Overpass failure

```python
except urllib.error.URLError as exc:
    return [{"error": f"Overpass API unavailable: {exc}"}]
```

This returns a **list whose element has no `osm_id`**. If the agent then chains
the result into `get_safety_score`, that handler does
`scores_json_matches[r["osm_id"]]` and **raises `KeyError`**, turning a handled
upstream outage into an unhandled crash.

### Fix

Pick one error contract and apply it to all three tools:

- Simplest: return a top-level error object, e.g. `{"error": "..."}` (a dict, not
  a list of fake restaurants), and have `get_safety_score` defensively skip /
  short-circuit any input that is not a well-formed restaurant (no `osm_id`).
- Either way, `get_safety_score` should **not** assume every input element has
  `osm_id`; guard it so one bad element can never crash the batch.

Keep the behaviour graceful: the agent should be able to tell the user "couldn't
reach the restaurant directory right now" rather than erroring out.

---

## Verification (both)

- `uv run ruff check agents/ && uv run ruff format --check agents/`
- Add tests:
  - `_summarise` with a history containing Out of Business / No Entry -> those are
    NOT counted as pass; pass/fail/conditions counts are correct.
  - `_summarise` with out-of-order dates -> `last_date` is the true most recent.
  - `find_restaurants` Overpass-failure path returns the agreed error shape, and
    feeding that into `get_safety_score` does not raise.

## Context to read first

- `app/public/data/inspection_history.json` — the real `result` strings.
- `docs/interface_contracts.md` — confirm you are only changing agent-internal
  shapes, not the cross-team `scores.parquet` / `inspections_labeled.parquet`
  contracts.
