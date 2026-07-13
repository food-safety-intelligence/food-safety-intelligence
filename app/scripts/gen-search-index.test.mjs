import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SCRIPT = fileURLToPath(new URL("./gen-search-index.mjs", import.meta.url));

function writeFixtures(withComments) {
  const dir = mkdtempSync(path.join(tmpdir(), "fsi-genidx-"));
  const scores = {
    generated_at: "2026-07-01T00:00:00Z",
    as_of_date: "2026-06-30",
    totals: {
      establishments: 2,
      tier_counts: { Low: 1, Moderate: 0, Elevated: 0, High: 1 },
    },
    scores: [
      {
        license_id: "111", dba_name: "A", address: "1 St",
        lat: 41.9, lon: -87.6, risk_score: 0.9, risk_tier: "High",
        trend_slope: 0.001, as_of_date: "2026-05-01",
        top_drivers: [{ feature: "was_fail", label: "Failed", shap: 0.5 }],
      },
      {
        license_id: "222", dba_name: "B", address: "2 St",
        lat: 41.8, lon: -87.7, risk_score: 0.1, risk_tier: "Low",
        trend_slope: null, as_of_date: "2026-04-01", top_drivers: [],
      },
    ],
  };
  const history = {
    // Newest event first; the scored event for "111" is NOT the newest, so
    // this also exercises the as_of_date match (not just events[0]).
    111: [
      { date: "2026-06-10", type: "License", result: "Pass", headline: "", score: null },
      { date: "2026-05-01", type: "Canvass", result: "Fail",
        headline: "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT", score: 0.8 },
    ],
    222: [
      { date: "2026-04-01", type: "Canvass", result: "Pass", headline: "", score: 0.1 },
    ],
  };
  writeFileSync(path.join(dir, "scores.json"), JSON.stringify(scores));
  writeFileSync(path.join(dir, "history.json"), JSON.stringify(history));
  if (withComments) {
    const cdir = path.join(dir, "comments-by-license");
    mkdirSync(cdir);
    // Index-aligned with history["111"]: entry [1] is the scored event, whose
    // FULL text adds a temperature violation the headline alone doesn't carry.
    writeFileSync(
      path.join(cdir, "111.json"),
      JSON.stringify([
        "",
        "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT - Comments: rat droppings | 21. COLD HOLDING temperature above 41F",
      ]),
    );
  }
  return dir;
}

function run(dir, extraArgs) {
  const dest = path.join(dir, "search-index.json");
  execFileSync("node", [SCRIPT, path.join(dir, "scores.json"), dest, ...extraArgs]);
  return JSON.parse(readFileSync(dest, "utf-8")).rows;
}

describe("gen-search-index violation tagging", () => {
  it("tags from headlines when no comments dir is given (dev mode)", () => {
    const dir = writeFixtures(false);
    const rows = run(dir, [path.join(dir, "history.json")]);
    expect(rows[0].vc).toBe(0b1); // pests only: headline = first violation
    expect(rows[1].vc).toBeUndefined(); // clean latest inspection → omitted
  });

  it("tags from full comment text when the comments dir is given (deploy mode)", () => {
    const dir = writeFixtures(true);
    const rows = run(dir, [
      path.join(dir, "history.json"),
      path.join(dir, "comments-by-license"),
    ]);
    expect(rows[0].vc).toBe(0b11); // pests + temperature from the full text
    expect(rows[1].vc).toBeUndefined();
  });

  it("omits vc entirely without a history path (legacy invocation)", () => {
    const dir = writeFixtures(false);
    const rows = run(dir, []);
    expect(rows.every((r) => r.vc === undefined)).toBe(true);
  });
});
