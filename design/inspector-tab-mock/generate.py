"""Regenerate inspector-tab.html from the live scores.json + inspection history.

The mock is template + data, not hand-typed rows: every establishment, tier,
score, driver, date and slope comes from the same artifacts the app serves.
Re-run after a data refresh:

    python3 design/inspector-tab-mock/generate.py \
        [scores.json] [inspection_history.json]

Defaults: /tmp/fsi-build-cache/scores.json (the app build cache), falling back
to app/public/data/scores.json; history from app/public/data/.

The DRIVER_CHECKS mapping below is the proposal for the production
`app/src/lib/driver-checks.ts`: a deterministic feature -> on-site-action
translation over the existing ``top_drivers`` — current predictions only, no
new model output, no LLM at render time. This script prints mapping coverage
across the full population so the team can see how far the 22 driver features
stretch before the tab is built for real.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / "inspector-tab.html"
TODAY = date(2026, 7, 4)

CLOSED_RESULTS = {"Out of Business", "Business Not Located"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


# ---------------------------------------------------------------------------
# Driver -> "what to check on-site" mapping (the future driver-checks.ts).
# Each entry: title(value), detail(value, label). Direction comes from the
# driver's shap sign: positive -> a check item, negative -> a reassurance.
# Features with no on-site action (temporal anchors, license age, the fail
# outcome itself) are deliberately absent: was_fail feeds the row's "why"
# line, not the checklist.
# ---------------------------------------------------------------------------

DRIVER_CHECKS = {
    "flag_kw_cooling": lambda v, lb: (
        "Cooling practices & walk-in temperatures",
        "Improper cooling was cited at the last visit.",
    ),
    "flag_kw_temperature": lambda v, lb: (
        "Probe hot/cold holding temperatures",
        "A temperature-related violation appears in recent history.",
    ),
    "flag_kw_pest": lambda v, lb: (
        "Pest evidence sweep",
        "Pest activity was noted — check traps, droppings, entry points.",
    ),
    "flag_kw_rodent": lambda v, lb: (
        "Rodent / vermin evidence",
        "A vermin or rodent violation was recorded previously.",
    ),
    "n_priority_this_inspection": lambda v, lb: (
        f"Re-check the {v} priority violation{'s' if v != '1' else ''} from the last report",
        "Verify correction; these were open at the last inspection.",
    ),
    "n_core_this_inspection": lambda v, lb: (
        "Core sanitation sweep",
        f"{v} core violations recorded at the last visit — expect general upkeep issues.",
    ),
    "prior_priority_violations_365d": lambda v, lb: (
        f"Review the {v} priority violations cited in the past year",
        "Repeat priority items are the strongest predictor in the model.",
    ),
    "prior_fails_365d": lambda v, lb: (
        f"History: {v} failed inspection{'s' if v != '1' else ''} in the last year",
        "Read the prior fail reports before the visit.",
    ),
    "prior_fail_or_priority_events": lambda v, lb: (
        f"History: {v} prior fail-or-priority events",
        "Long pattern — check whether past corrections stuck.",
    ),
    "prior_pass_w_conditions": lambda v, lb: (
        f"History: {v} prior 'Pass with conditions' results",
        "Conditional passes often recur — verify the conditions were resolved.",
    ),
    "prior_core_violations": lambda v, lb: (
        "Review recurring core violations in the file",
        f"{v} core violations across prior history.",
    ),
    "days_since_last_fail": lambda v, lb: (
        "Verify corrections from the last fail",
        f"Most recent fail was {v} days ago.",
    ),
    "days_since_last_inspection": lambda v, lb: (
        "Full canvass — long gap since the last visit",
        f"Last inspected {v} days ago; treat as a fresh baseline.",
    ),
    "prior_complaint_inspections": lambda v, lb: (
        ("Complaint history is clean", "No complaint-driven inspections on record.")
        if v in ("0", "0.0")
        else (
            f"Review the {v} complaint-driven inspections",
            "311 complaints preceded these — check the complaint topics.",
        )
    ),
}


def check_items(drivers: list[dict], k: int = 4) -> list[dict]:
    """Translate top_drivers into at most ``k`` on-site check items.

    Positive-shap mapped drivers become checks (strongest first); the single
    strongest negative-shap mapped driver becomes a reassurance line so the
    list keeps the raises/lowers honesty of the detail page's DriverList.
    """
    checks: list[dict] = []
    reassure: dict | None = None
    for d in sorted(drivers, key=lambda d: -abs(d["shap"])):
        fn = DRIVER_CHECKS.get(d["feature"])
        if fn is None or "<NA>" in d["label"]:
            continue
        title, detail = fn(str(d["value"]), d["label"])
        item = {"title": title, "detail": detail, "reassure": d["shap"] < 0}
        if d["shap"] < 0:
            reassure = reassure or item
        else:
            checks.append(item)
    out = checks[: k - 1 if reassure else k]
    if reassure:
        out.append(reassure)
    return out


# ---------------------------------------------------------------------------
# Data selection (same rules the tab would use)
# ---------------------------------------------------------------------------


def months_between(iso: str) -> int:
    y, m, _ = map(int, iso.split("-"))
    return (TODAY.year - y) * 12 + (TODAY.month - m)


def fmt_month(iso: str) -> str:
    y, m, _ = map(int, iso.split("-"))
    return f"{MONTHS[m - 1]} {y}"


def load(scores_path: Path, history_path: Path) -> dict:
    payload = json.loads(scores_path.read_text())
    history = json.loads(history_path.read_text())

    def last_visit(lic: str) -> str | None:
        ev = history.get(lic) or []
        return max((e["date"] for e in ev), default=None)

    def active(r: dict) -> bool:
        # Prefer the DR 0014 contract flag; fall back to deriving it from
        # history for pre-0.6.0 files.
        if "is_out_of_business" in r:
            return not r["is_out_of_business"]
        ev = history.get(r["license_id"]) or []
        latest = max(ev, key=lambda e: e["date"]) if ev else None
        return not (latest and latest["result"] in CLOSED_RESULTS)

    rows = []
    for r in payload["scores"]:
        if r["risk_tier"] not in ("High", "Elevated"):
            continue
        if not (r.get("lat") and r.get("lon")):
            continue
        # Territory stand-in: a Northwest-side lat/lon box until the feed
        # carries community areas (see data asks in the notes section).
        if not (41.88 <= r["lat"] <= 41.96 and -87.78 <= r["lon"] <= -87.66):
            continue
        if not active(r):
            continue
        last = last_visit(r["license_id"])
        if last is None:
            continue
        mo = months_between(last)
        rows.append({"r": r, "mo": mo, "last": last, "rank_score": r["risk_score"] * (1 + mo / 12)})
    rows.sort(key=lambda x: -x["rank_score"])

    worsening = sorted(
        (
            r
            for r in payload["scores"]
            if (r.get("trend_slope") or 0) > 0.004 and active(r) and r.get("dba_name")
        ),
        key=lambda r: -r["trend_slope"],
    )[:3]

    briefing = rows[0]
    briefing_visits = sorted(
        history.get(briefing["r"]["license_id"], []), key=lambda e: e["date"], reverse=True
    )[:4]

    return {
        "worklist": rows[:6],
        "worsening": worsening,
        "briefing": briefing,
        "briefing_visits": briefing_visits,
        "payload": payload,
    }


def coverage(payload: dict) -> str:
    """% of establishments whose top drivers yield at least one check item."""
    n_any = sum(1 for r in payload["scores"] if check_items(r["top_drivers"]))
    return f"{n_any / len(payload['scores']):.1%}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

TIER_CLASS = {"High": "high", "Elevated": "elev", "Moderate": "mod"}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def title_case(name: str) -> str:
    return " ".join(w.capitalize() if w.isalpha() else w for w in name.lower().split())


def why_line(r: dict) -> str:
    top = r["top_drivers"][0] if r["top_drivers"] else None
    fail = any(d["feature"] == "was_fail" and str(d["value"]) == "1" for d in r["top_drivers"])
    bits = []
    if fail:
        bits.append("<strong>Failed its last inspection</strong>")
    if top and top["feature"] != "was_fail" and "<NA>" not in top["label"]:
        bits.append(esc(top["label"]))
    elif not fail and top:
        bits.append(esc(top["label"]))
    return " · ".join(bits) or "Elevated predicted risk"


def worklist_html(items: list[dict]) -> str:
    rows = []
    for i, it in enumerate(items, 1):
        r, mo, last = it["r"], it["mo"], it["last"]
        width = min(100, round(mo / 12 * 100))
        sel = ' class="selected"' if i == 1 else ""
        cur = ' aria-current="true"' if i == 1 else ""
        rows.append(f"""          <li{sel}>
            <a class="row" href="#briefing"{cur}>
              <span class="rank">{i}</span>
              <span class="who">
                <span class="nm">{esc(r["dba_name"])} <span class="pill {TIER_CLASS[r["risk_tier"]]}">{r["risk_tier"]}</span></span>
                <span class="addr">{esc(title_case(r["address"]))}</span>
                <span class="why">{why_line(r)}</span>
              </span>
              <span class="due past">
                <span class="mo">{mo} <small>mo</small></span>
                <span class="meter" role="img" aria-label="{mo} months since last inspection, target 6"><i style="width:{width}%"></i></span>
                <span class="since">last visited {fmt_month(last)}</span>
              </span>
            </a>
          </li>""")
    return "\n".join(rows)


def worsening_html(rows: list[dict]) -> str:
    cards = []
    for r in rows:
        cards.append(f"""          <div class="wcard">
            <div class="nm">{esc(r["dba_name"])}</div>
            <div class="addr">{esc(title_case(r["address"]))}</div>
            <div class="slope">↗ +{r["trend_slope"]:.4f}<small> / day · {r["risk_tier"]}</small></div>
          </div>""")
    return "\n".join(cards)


def briefing_html(b: dict, visits: list[dict]) -> dict:
    r = b["r"]
    checks = []
    for c in check_items(r["top_drivers"]):
        cls = ' class="low"' if c["reassure"] else ""
        checks.append(
            f"            <li{cls}><span>{esc(c['title'])}"
            f"<small>{esc(c['detail'])}</small></span></li>"
        )
    vrows = []
    for e in visits:
        res = e["result"] or "—"
        cls = " fail" if res == "Fail" else ""
        vrows.append(
            f'            <tr><td class="d">{fmt_month(e["date"])}</td>'
            f"<td>{esc(e['type'] or 'Inspection')}</td>"
            f'<td class="r{cls}">{esc(res)}</td></tr>'
        )
    return {
        "name": esc(title_case(r["dba_name"])),
        "addr": esc(title_case(r["address"])),
        "license": r["license_id"],
        "tier": r["risk_tier"],
        "score": f"{r['risk_score']:.2f}",
        "last": fmt_month(b["last"]),
        "checks": "\n".join(checks),
        "visits": "\n".join(vrows),
    }


def main() -> None:
    scores_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else (
            "/tmp/fsi-build-cache/scores.json"
            if Path("/tmp/fsi-build-cache/scores.json").exists()
            else REPO / "app/public/data/scores.json"
        )
    )
    history_path = Path(sys.argv[2] if len(sys.argv) > 2 else REPO / "app/public/data/inspection_history.json")

    data = load(scores_path, history_path)
    b = briefing_html(data["briefing"], data["briefing_visits"])
    template = (Path(__file__).resolve().parent / "template.html").read_text()
    html = (
        template.replace("<!--WORKLIST-->", worklist_html(data["worklist"]))
        .replace("<!--WORSENING-->", worsening_html(data["worsening"]))
        .replace("{B_NAME}", b["name"])
        .replace("{B_ADDR}", b["addr"])
        .replace("{B_LICENSE}", b["license"])
        .replace("{B_TIER}", b["tier"])
        .replace("{B_SCORE}", b["score"])
        .replace("{B_LAST}", b["last"])
        .replace("<!--B_CHECKS-->", b["checks"])
        .replace("<!--B_VISITS-->", b["visits"])
    )
    OUT.write_text(html)
    print(f"wrote {OUT} from {scores_path.name} (schema {data['payload'].get('schema_version')})")
    print(f"check-item coverage across all establishments: {coverage(data['payload'])}")


if __name__ == "__main__":
    main()
