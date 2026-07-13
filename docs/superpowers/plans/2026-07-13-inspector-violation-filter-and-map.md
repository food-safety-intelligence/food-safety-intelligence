# Inspector Tab Violation Filter + Map View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a violation-category filter and a List/Map toggle to the "For inspectors" page, driven by a new compact `vc` bitmask tagged into each city's `search-index.json` at app build time.

**Architecture:** A shared 6-category taxonomy JSON (slugs, labels, regex patterns) is read by both the app UI and `gen-search-index.mjs`. The generator tags each establishment's latest scored inspection (full S3 comment text in deploy builds, committed headlines in dev) into an optional per-row bitmask `vc`. `InspectorWorklist` adds URL-driven chips (`?viol=`) and a view toggle (`?view=map`) whose map pane reuses the Search tab's `MapView` unmodified.

**Tech Stack:** Next.js 16 (App Router) + React 19 + TypeScript strict, Tailwind, vitest, plain-Node build scripts (`.mjs`), react-map-gl/maplibre (already installed).

**Spec:** `docs/superpowers/specs/2026-07-13-inspector-violation-filter-and-map-design.md` (approved). Work happens on branch `jun/app-inspector-violation-map`, in `app/` only.

## Global Constraints

- TypeScript `strict: true`, no `any`. Plain functions, no classes.
- No new npm dependencies. No Python pipeline, `scores.json` contract, or S3 changes.
- No em dashes and no emoji in user-facing UI copy.
- Font sizes only from the named type-scale rungs (`text-2xs` … `text-6xl`); no new arbitrary `text-[Npx]` values (other arbitrary values like `h-[70vh]` are fine).
- Accessibility: `aria-pressed` on toggle chips, keyboard reachable, no color-only signals.
- All commands below run from `app/` unless the path says otherwise. Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- The Chicago `search-index.json` must stay under 10 MB (CloudFront compression ceiling; it is 7.1 MB today).
- Do not modify `MapView.tsx` or `MapExplorer.tsx`.

---

### Task 1: Shared taxonomy + app-side violations lib

**Files:**
- Create: `app/src/lib/violation-categories.json`
- Create: `app/src/lib/violations.ts`
- Test: `app/src/lib/violations.test.ts`

**Interfaces:**
- Consumes: nothing (leaf task).
- Produces:
  - `violation-categories.json`: array of `{ slug: string, label: string, patterns: string[] }`; array index = category id = bit position.
  - `VIOLATION_CATEGORIES: { id: number; slug: string; label: string }[]`
  - `parseViol(raw: string | null | undefined): string[]` (canonical-order valid slugs)
  - `bitsForSlugs(slugs: string[]): number`
  - `matchesViolations(vc: number | undefined, bits: number): boolean`

- [ ] **Step 1: Write the taxonomy JSON**

Create `app/src/lib/violation-categories.json`. Array order defines the bit position (`pests` = bit 0). `patterns` are case-insensitively OR-joined into one RegExp per category by consumers. These are the spec's initial keyword lists; Task 3 tunes them against real data.

```json
[
  {
    "slug": "pests",
    "label": "Pests and rodents",
    "patterns": ["rodent", "\\bmice\\b", "\\bmouse\\b", "\\brats?\\b", "roach", "insect", "\\bpests?\\b", "vermin", "\\bfl(y|ies)\\b"]
  },
  {
    "slug": "temp",
    "label": "Temperature control",
    "patterns": ["temperature", "cold holding", "hot holding", "\\bcool", "refrigerat", "thermometer", "reheat"]
  },
  {
    "slug": "contamination",
    "label": "Contamination and food source",
    "patterns": ["contaminat", "adulterat", "approved source", "unapproved", "sewage", "\\bprotected\\b"]
  },
  {
    "slug": "hygiene",
    "label": "Hygiene and handwashing",
    "patterns": ["handwash", "hand wash", "hand sink", "handsink", "hygien", "\\bsoap\\b", "towel", "bare hand"]
  },
  {
    "slug": "sanitizing",
    "label": "Cleaning and sanitizing",
    "patterns": ["saniti", "\\bclean"]
  },
  {
    "slug": "facility",
    "label": "Facility and equipment",
    "patterns": ["\\bfloors?\\b", "\\bwalls?\\b", "ceiling", "plumbing", "\\brepair", "garbage", "refuse", "toilet", "restroom", "ventilat", "lighting", "\\bleak"]
  }
]
```

- [ ] **Step 2: Write the failing tests**

Create `app/src/lib/violations.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  bitsForSlugs,
  matchesViolations,
  parseViol,
  VIOLATION_CATEGORIES,
} from "./violations";

describe("VIOLATION_CATEGORIES", () => {
  it("has six categories with unique slugs and ids matching array order", () => {
    expect(VIOLATION_CATEGORIES).toHaveLength(6);
    const slugs = VIOLATION_CATEGORIES.map((c) => c.slug);
    expect(new Set(slugs).size).toBe(6);
    VIOLATION_CATEGORIES.forEach((c, i) => expect(c.id).toBe(i));
  });
});

describe("parseViol", () => {
  it("returns [] for absent or empty input", () => {
    expect(parseViol(null)).toEqual([]);
    expect(parseViol(undefined)).toEqual([]);
    expect(parseViol("")).toEqual([]);
  });

  it("keeps only known slugs, in canonical taxonomy order", () => {
    expect(parseViol("temp,pests")).toEqual(["pests", "temp"]);
    expect(parseViol("bogus,temp")).toEqual(["temp"]);
    expect(parseViol("bogus")).toEqual([]);
  });

  it("dedupes repeated slugs", () => {
    expect(parseViol("pests,pests")).toEqual(["pests"]);
  });
});

describe("bitsForSlugs / matchesViolations", () => {
  it("round-trips slugs to a bitmask", () => {
    expect(bitsForSlugs([])).toBe(0);
    expect(bitsForSlugs(["pests"])).toBe(0b1);
    expect(bitsForSlugs(["pests", "temp"])).toBe(0b11);
  });

  it("matches everything when no filter is active", () => {
    expect(matchesViolations(undefined, 0)).toBe(true);
    expect(matchesViolations(0, 0)).toBe(true);
    expect(matchesViolations(0b100, 0)).toBe(true);
  });

  it("never matches rows without vc when a filter is active", () => {
    expect(matchesViolations(undefined, 0b1)).toBe(false);
    expect(matchesViolations(0, 0b1)).toBe(false);
  });

  it("ORs across selected categories", () => {
    expect(matchesViolations(0b100, 0b101)).toBe(true);
    expect(matchesViolations(0b010, 0b101)).toBe(false);
  });

  it("all six selected still excludes clean rows (spec: not a no-op)", () => {
    const all = bitsForSlugs(VIOLATION_CATEGORIES.map((c) => c.slug));
    expect(matchesViolations(0, all)).toBe(false);
    expect(matchesViolations(undefined, all)).toBe(false);
    expect(matchesViolations(1 << 5, all)).toBe(true);
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pnpm test -- src/lib/violations.test.ts`
Expected: FAIL — cannot resolve `./violations`.

- [ ] **Step 4: Write the implementation**

Create `app/src/lib/violations.ts`:

```ts
/**
 * Violation-category taxonomy helpers for the inspector worklist's
 * `?viol=` filter. The taxonomy itself lives in violation-categories.json —
 * shared with scripts/gen-search-index.mjs (which does the keyword matching
 * at build time) so chips and tagging can't drift. The app only ever reads
 * slugs + labels; the regex patterns are generator-only.
 */

import rawCategories from "./violation-categories.json";

export interface ViolationCategory {
  /** Bit position in a SearchIndexRow's `vc` bitmask (= JSON array index). */
  id: number;
  slug: string;
  label: string;
}

export const VIOLATION_CATEGORIES: ViolationCategory[] = rawCategories.map(
  (c, i) => ({ id: i, slug: c.slug, label: c.label }),
);

const BY_SLUG = new Map(VIOLATION_CATEGORIES.map((c) => [c.slug, c]));

/**
 * Parse the `?viol=` URL value (comma-separated slugs) into valid slugs in
 * canonical taxonomy order. Unknown slugs are dropped; absent/empty → []
 * (no violation filter — unlike tiers, there is no "all selected = no-op").
 */
export function parseViol(raw: string | null | undefined): string[] {
  if (!raw) return [];
  const wanted = new Set(raw.split(","));
  return VIOLATION_CATEGORIES.filter((c) => wanted.has(c.slug)).map(
    (c) => c.slug,
  );
}

/** OR-bitmask over the given category slugs. [] → 0 (no filter). */
export function bitsForSlugs(slugs: string[]): number {
  let bits = 0;
  for (const s of slugs) {
    const c = BY_SLUG.get(s);
    if (c) bits |= 1 << c.id;
  }
  return bits;
}

/**
 * True when the row passes the violation filter. bits=0 means no filter is
 * active and everything matches. With a filter active, rows without `vc`
 * (clean latest inspection, or an index built before tagging existed) never
 * match.
 */
export function matchesViolations(
  vc: number | undefined,
  bits: number,
): boolean {
  if (bits === 0) return true;
  return ((vc ?? 0) & bits) !== 0;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pnpm test -- src/lib/violations.test.ts`
Expected: PASS (all tests green).

- [ ] **Step 6: Lint + typecheck, then commit**

Run: `pnpm lint && pnpm exec tsc --noEmit`
Expected: clean.

```bash
git add src/lib/violation-categories.json src/lib/violations.ts src/lib/violations.test.ts
git commit -m "feat(app): violation-category taxonomy + ?viol= filter helpers

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Build-time tagging module

**Files:**
- Create: `app/scripts/lib/violation-tagging.mjs`
- Test: `app/scripts/lib/violation-tagging.test.mjs`
- Modify: `app/vitest.config.ts` (extend `include`)

**Interfaces:**
- Consumes: `app/src/lib/violation-categories.json` (Task 1).
- Produces (plain JS with JSDoc, imported by Task 3):
  - `tagViolations(text: string | null | undefined): number` — bitmask
  - `latestScoredEvent(events: {date: string}[] | undefined, asOfDate: string | null): { event, index } | null`
  - `CATEGORY_SLUGS: string[]`

- [ ] **Step 1: Extend the vitest include glob**

In `app/vitest.config.ts`, change:

```ts
    include: ["src/**/*.test.{ts,tsx}"],
```

to:

```ts
    // scripts/ are plain-Node build helpers (.mjs) — their pure logic
    // (violation tagging, index generation) is tested here too.
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs"],
```

- [ ] **Step 2: Write the failing tests**

Create `app/scripts/lib/violation-tagging.test.mjs`:

```js
import { describe, expect, it } from "vitest";
import { latestScoredEvent, tagViolations } from "./violation-tagging.mjs";

describe("tagViolations", () => {
  it("returns 0 for empty or violation-free text", () => {
    expect(tagViolations("")).toBe(0);
    expect(tagViolations(null)).toBe(0);
    expect(tagViolations(undefined)).toBe(0);
    expect(tagViolations("license renewal paperwork on file")).toBe(0);
  });

  // Real headline shapes from the three cities (bit 0 = pests, 1 = temp,
  // 2 = contamination, 3 = hygiene, 4 = sanitizing, 5 = facility).
  it("tags Chicago violation names", () => {
    expect(tagViolations("38. INSECTS, RODENTS, & ANIMALS NOT PRESENT")).toBe(0b1);
    expect(
      tagViolations("5. PROCEDURES FOR RESPONDING TO VOMITING AND DIARRHEAL EVENTS"),
    ).toBe(0);
  });

  it("tags NYC free-text violations", () => {
    expect(
      tagViolations(
        "Evidence of mice or live mice in establishment's food or non-food areas.",
      ),
    ).toBe(0b1);
    expect(tagViolations("Food not cooled by an approved method.")).toBe(0b10);
  });

  it("tags LA requirement-style headlines", () => {
    expect(tagViolations("# 44. FLOORS, WALLS AND CEILINGS: PROPERLY BUILT")).toBe(1 << 5);
    expect(tagViolations("FOOD CONTACT SURFACES: CLEAN AND SANITIZED")).toBe(1 << 4);
  });

  it("sets multiple bits for multi-violation text", () => {
    const text = [
      "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT",
      "21. COLD HOLDING temperature above 41F",
    ].join("\n");
    expect(tagViolations(text)).toBe(0b11);
  });
});

describe("latestScoredEvent", () => {
  const events = [
    { date: "2026-05-01", headline: "newest" },
    { date: "2026-01-15", headline: "scored" },
    { date: "2025-11-02", headline: "old" },
  ];

  it("prefers the event matching as_of_date", () => {
    expect(latestScoredEvent(events, "2026-01-15")).toEqual({
      event: events[1],
      index: 1,
    });
  });

  it("falls back to the newest event when no date matches", () => {
    expect(latestScoredEvent(events, "2020-01-01")).toEqual({
      event: events[0],
      index: 0,
    });
    expect(latestScoredEvent(events, null)).toEqual({
      event: events[0],
      index: 0,
    });
  });

  it("returns null for missing or empty history", () => {
    expect(latestScoredEvent(undefined, "2026-01-01")).toBeNull();
    expect(latestScoredEvent([], null)).toBeNull();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pnpm test -- scripts/lib/violation-tagging.test.mjs`
Expected: FAIL — cannot resolve `./violation-tagging.mjs`.

- [ ] **Step 4: Write the implementation**

Create `app/scripts/lib/violation-tagging.mjs`:

```js
/**
 * Violation-category keyword tagging for gen-search-index.mjs.
 *
 * The taxonomy (slugs, labels, regex patterns) is the SAME JSON the app UI
 * imports for its filter chips (src/lib/violation-categories.json) — one
 * source of truth, so a chip can never exist without matching tagger logic.
 * Array index = category id = bit position in the emitted `vc` bitmask.
 */

import { readFileSync } from "node:fs";

const categories = JSON.parse(
  readFileSync(
    new URL("../../src/lib/violation-categories.json", import.meta.url),
    "utf-8",
  ),
);

const matchers = categories.map((c, i) => ({
  bit: 1 << i,
  slug: c.slug,
  re: new RegExp(c.patterns.join("|"), "i"),
}));

export const CATEGORY_SLUGS = matchers.map((m) => m.slug);

/**
 * Bitmask of violation categories mentioned in `text` (bit i = category i).
 * @param {string | null | undefined} text
 * @returns {number}
 */
export function tagViolations(text) {
  if (!text) return 0;
  let bits = 0;
  for (const m of matchers) if (m.re.test(text)) bits |= m.bit;
  return bits;
}

/**
 * Pick the history event the row's score describes: exact `as_of_date` match,
 * else the newest event (history arrays are pre-sorted newest-first by the
 * exporter). The returned `index` lines up with the license's comments array,
 * which the exporter builds from the same sorted/capped slice.
 * @param {{date: string}[] | undefined} events
 * @param {string | null} asOfDate
 * @returns {{event: object, index: number} | null}
 */
export function latestScoredEvent(events, asOfDate) {
  if (!events || events.length === 0) return null;
  if (asOfDate) {
    const i = events.findIndex((e) => e.date === asOfDate);
    if (i !== -1) return { event: events[i], index: i };
  }
  return { event: events[0], index: 0 };
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pnpm test -- scripts/lib/violation-tagging.test.mjs`
Expected: PASS. Also run the full suite once (`pnpm test`) to confirm the include-glob change broke nothing.

- [ ] **Step 6: Lint, then commit**

Run: `pnpm lint`
Expected: clean.

```bash
git add scripts/lib/violation-tagging.mjs scripts/lib/violation-tagging.test.mjs vitest.config.ts
git commit -m "feat(app): build-time violation keyword tagger (shared taxonomy)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Wire tagging into gen-search-index.mjs + regenerate dev indexes

**Files:**
- Modify: `app/scripts/gen-search-index.mjs`
- Modify: `app/package.json` (scripts: `predev`, `gen-nyc:dev`, `gen-la:dev`, `prebuild`)
- Modify: `app/src/lib/scores.ts` (add `vc` to `SearchIndexRow`, ~line 473)
- Test: `app/scripts/gen-search-index.test.mjs`
- Regenerates (gitignored/untracked artifacts, not committed): `app/public/data/{,nyc/,la/}search-index.json`

**Interfaces:**
- Consumes: `tagViolations`, `latestScoredEvent`, `CATEGORY_SLUGS` from `./lib/violation-tagging.mjs` (Task 2).
- Produces:
  - `search-index.json` rows gain optional `vc: number` (omitted when 0).
  - New CLI shape: `node scripts/gen-search-index.mjs <scores.json> [dest.json] [inspection_history.json] [comments-by-license-dir]` — both new args optional; omitting history skips tagging entirely (legacy behavior).
  - `SearchIndexRow.vc?: number` in `src/lib/scores.ts`.

- [ ] **Step 1: Write the failing integration test**

Create `app/scripts/gen-search-index.test.mjs`. It runs the real script on tmp-dir fixtures and asserts the emitted `vc`:

```js
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test -- scripts/gen-search-index.test.mjs`
Expected: FAIL — `rows[0].vc` is `undefined` in the first two tests (the script ignores the extra args today). The legacy test may already pass.

- [ ] **Step 3: Modify gen-search-index.mjs**

Four edits to `app/scripts/gen-search-index.mjs`:

(a) Extend the header comment's usage line:

```js
 * Usage: node scripts/gen-search-index.mjs <source-scores.json> [dest.json] \
 *          [inspection_history.json] [comments-by-license-dir]
 *
 * The two optional inputs enable violation-category tagging (`vc` bitmask per
 * row, taxonomy in src/lib/violation-categories.json): deploy builds pass the
 * S3-synced comments dir (full violation text); dev builds pass history only,
 * so tagging falls back to the first-violation headline. No history path →
 * no vc fields at all (the UI then hides the violation filter).
```

(b) Replace the imports + arg block:

```js
import { readFileSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  CATEGORY_SLUGS,
  latestScoredEvent,
  tagViolations,
} from "./lib/violation-tagging.mjs";

const src = process.argv[2] ?? "public/data/scores.json";
const dest = process.argv[3] ?? "public/data/search-index.json";
const historyPath = process.argv[4] ?? null;
const commentsDir = process.argv[5] ?? null;
```

(c) Inside `main()`, before the `rows` mapping, add:

```js
  const history = historyPath
    ? JSON.parse(await readFile(historyPath, "utf-8"))
    : null;

  // Full violation text for one license, when the deploy build synced it.
  // comments[i] is index-aligned with history[license][i] (both come from the
  // same sorted/capped slice in export_inspection_history.py).
  const commentsFor = (licenseId) => {
    if (!commentsDir) return null;
    try {
      return JSON.parse(
        readFileSync(path.join(commentsDir, `${licenseId}.json`), "utf-8"),
      );
    } catch {
      return null; // license has no synced comments — headline fallback
    }
  };

  let taggedFromComments = 0;
  const categoryCounts = CATEGORY_SLUGS.map(() => 0);

  // Violation categories at the latest scored inspection (spec 2026-07-13).
  const vcFor = (r) => {
    if (!history) return 0;
    const hit = latestScoredEvent(history[r.license_id], r.as_of_date ?? null);
    if (!hit) return 0;
    let text = hit.event.headline ?? "";
    const comments = commentsFor(r.license_id);
    if (comments && typeof comments[hit.index] === "string") {
      text = comments[hit.index]; // "" = clean inspection, use verbatim
      taggedFromComments += 1;
    }
    const vc = tagViolations(text);
    for (let i = 0; i < categoryCounts.length; i += 1) {
      if (vc & (1 << i)) categoryCounts[i] += 1;
    }
    return vc;
  };
```

(d) In the `rows` mapping, compute and serialize `vc` (omitted when 0, same pattern as `is_out_of_business`). Change the map callback's opening to compute it, and add the spread line right after the `is_out_of_business` spread:

```js
  const rows = scores.map((r) => {
    const d = r.top_drivers?.[0];
    const vc = vcFor(r);
    return {
      // ... existing fields unchanged ...
      // Serialized only when true (~27% of rows) — absent means active.
      ...(r.is_out_of_business ? { is_out_of_business: true } : {}),
      // Violation-category bitmask at the latest scored inspection; omitted
      // when clean/unknown so the field costs nothing on most rows.
      ...(vc ? { vc } : {}),
    };
  });
```

(e) After the existing `console.log(\`[search-index] ${rows.length} rows ...\`)` line, add the mode + sanity-count logging:

```js
  if (history) {
    const mode =
      commentsDir && taggedFromComments > 0
        ? `full text (${taggedFromComments.toLocaleString()} licenses with comments)`
        : "headlines only (first violation per inspection; dev fallback)";
    console.log(`[search-index] violation tagging: ${mode}`);
    console.log(
      "[search-index] category counts: " +
        CATEGORY_SLUGS.map((s, i) => `${s}=${categoryCounts[i]}`).join(" "),
    );
  } else {
    console.log(
      "[search-index] violation tagging: skipped (no history path) — rows carry no vc",
    );
  }
```

- [ ] **Step 4: Run the integration test to verify it passes**

Run: `pnpm test -- scripts/gen-search-index.test.mjs`
Expected: PASS (all three tests).

- [ ] **Step 5: Add `vc` to SearchIndexRow**

In `app/src/lib/scores.ts`, inside `interface SearchIndexRow` (after the `is_out_of_business` member, ~line 491), add:

```ts
  /**
   * Bitmask of violation categories observed at the latest scored inspection
   * (bit i = VIOLATION_CATEGORIES[i] in lib/violations.ts). Omitted when the
   * inspection was clean or the index was built without violation tagging —
   * an index with NO vc on any row predates the feature, and the worklist
   * hides the violation filter entirely.
   */
  vc?: number;
```

Run: `pnpm exec tsc --noEmit`
Expected: clean.

- [ ] **Step 6: Update the four package.json scripts**

In `app/package.json`, replace these script values (only the `gen-search-index.mjs` invocations change; the `build-detail-data.mjs` parts stay exactly as they are):

```json
"predev": "node scripts/gen-search-index.mjs public/data/scores.json public/data/search-index.json public/data/inspection_history.json && node scripts/build-detail-data.mjs public/data/scores.json public/data/inspection_history.json && npm run gen-nyc:dev && npm run gen-la:dev",
"gen-nyc:dev": "node scripts/gen-search-index.mjs public/data/nyc/scores.json public/data/nyc/search-index.json public/data/nyc/inspection_history.json && node scripts/build-detail-data.mjs public/data/nyc/scores.json public/data/nyc/inspection_history.json \"\" public/data/nyc",
"gen-la:dev": "node scripts/gen-search-index.mjs public/data/la/scores.json public/data/la/search-index.json public/data/la/inspection_history.json && node scripts/build-detail-data.mjs public/data/la/scores.json public/data/la/inspection_history.json \"\" public/data/la",
"prebuild": "node scripts/prebuild-sync-s3.mjs && node scripts/gen-search-index.mjs /tmp/fsi-build-cache/scores.json public/data/search-index.json /tmp/fsi-build-cache/inspection_history.json /tmp/fsi-build-cache/comments-by-license && node scripts/gen-search-index.mjs /tmp/fsi-build-cache/nyc/scores.json public/data/nyc/search-index.json /tmp/fsi-build-cache/nyc/inspection_history.json /tmp/fsi-build-cache/nyc/comments-by-license && node scripts/gen-search-index.mjs /tmp/fsi-build-cache/la/scores.json public/data/la/search-index.json /tmp/fsi-build-cache/la/inspection_history.json /tmp/fsi-build-cache/la/comments-by-license"
```

(Note: a deploy build without S3 creds leaves `comments-by-license/` empty; `commentsFor` then returns null per license and tagging falls back to headlines — same graceful path the detail pages already use.)

- [ ] **Step 7: Regenerate the dev indexes and sanity-check keyword match rates**

Run the generator for all three cities (skip the slow `build-detail-data` part of `predev`):

```bash
node scripts/gen-search-index.mjs public/data/scores.json public/data/search-index.json public/data/inspection_history.json
node scripts/gen-search-index.mjs public/data/nyc/scores.json public/data/nyc/search-index.json public/data/nyc/inspection_history.json
node scripts/gen-search-index.mjs public/data/la/scores.json public/data/la/search-index.json public/data/la/inspection_history.json
```

Expected: each prints `violation tagging: headlines only ...` plus per-category counts.

Sanity-check the logged counts per city (spec requirement): every category should match more than 0 rows and no category should match nearly all rows (>90%). Dev counts are DEPRESSED by the headline-only fallback (first violation per inspection) — that is expected; what you are catching here is a category at 0 in every city (dead keyword) or one absurdly high (over-broad keyword, e.g. if `\bclean` swallowed a city). If a pattern is clearly broken, adjust `src/lib/violation-categories.json`, re-run Task 1/2 tests (`pnpm test`) — updating any test expectation that legitimately changed — and regenerate.

Then verify the size budget:

```bash
ls -l public/data/search-index.json
```

Expected: file size under 10,000,000 bytes (it was ~7.1 MB before; `vc` adds well under 0.5 MB).

- [ ] **Step 8: Full test run, lint, commit**

Run: `pnpm lint && pnpm exec tsc --noEmit && pnpm test`
Expected: all clean.

```bash
git add scripts/gen-search-index.mjs scripts/gen-search-index.test.mjs src/lib/scores.ts package.json
git commit -m "feat(app): tag violation categories into search-index rows (vc bitmask)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(Do NOT stage `public/data/**/search-index.json` — generated artifacts, already untracked.)

---

### Task 4: Violation filter chips on the Inspector worklist

**Files:**
- Modify: `app/src/components/InspectorWorklist.tsx`

**Interfaces:**
- Consumes: `parseViol`, `bitsForSlugs`, `matchesViolations`, `VIOLATION_CATEGORIES` (Task 1); `SearchIndexRow.vc` (Task 3).
- Produces: URL contract `?viol=<slug,slug>` on `/inspectors` (used by Task 5's map mode and by shareable links); a queue empty-state.

No new unit tests: the filter logic is already covered by Task 1's tests, and this repo does not unit-test render output (verification is Task 6's `/verify`). Steps below are edit → static checks → dev-server smoke → commit.

- [ ] **Step 1: Imports and URL state**

In `app/src/components/InspectorWorklist.tsx`:

Add to the imports (after the `@/lib/utils` import):

```ts
import {
  bitsForSlugs,
  matchesViolations,
  parseViol,
  VIOLATION_CATEGORIES,
} from "@/lib/violations";
```

Below the existing `tierParam`/`activeTiers`/`sort` block (~line 85), add:

```ts
  // Violation-category filter, URL-driven like tier/sort. Memoized on the raw
  // param (same React Compiler pattern as activeTiers). bits=0 → no filter.
  const violParam = searchParams.get("viol") ?? undefined;
  const activeViol = useMemo(() => parseViol(violParam), [violParam]);
  const violBits = bitsForSlugs(activeViol);
```

- [ ] **Step 2: Extend setParams and add toggleViol**

Change the `setParams` signature and body (~line 148) to also handle `viol`:

```ts
  const setParams = (next: {
    tiers?: RiskTier[];
    sort?: InspectorSort;
    viol?: string[];
  }) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next.tiers) {
      if (isAllTiers(next.tiers)) params.delete("tier");
      else params.set("tier", next.tiers.join(","));
    }
    if (next.sort) {
      if (next.sort === "risk") params.delete("sort");
      else params.set("sort", next.sort);
    }
    if (next.viol) {
      // Unlike tiers, all-six-selected is NOT a no-op (it still excludes
      // establishments whose latest inspection was clean), so the param
      // only clears when the selection is empty.
      if (next.viol.length === 0) params.delete("viol");
      else params.set("viol", next.viol.join(","));
    }
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
```

After `toggleTier` (~line 171), add:

```ts
  const toggleViol = (slug: string) => {
    const set = new Set(activeViol);
    if (set.has(slug)) set.delete(slug);
    else set.add(slug);
    setParams({
      viol: VIOLATION_CATEGORIES.filter((c) => set.has(c.slug)).map(
        (c) => c.slug,
      ),
    });
    setVisibleCount(QUEUE_PAGE);
  };
```

- [ ] **Step 3: Filter the rows and compute chip data**

In the `rows` useMemo (~line 183), add the violation predicate and dependency:

```ts
  const rows = useMemo(() => {
    const tierSet = new Set(activeTiers);
    const tierActive = !isAllTiers(activeTiers);
    const matched = activeRows.filter(
      (r) =>
        (!tierActive || tierSet.has(r.risk_tier)) &&
        matchesViolations(r.vc, violBits),
    );
    const days = (r: SearchIndexRow) => daysSince(r.as_of_date, now) ?? -1;
    return matched.slice().sort((a, b) => {
      if (sort === "overdue") return days(b) - days(a);
      if (sort === "trend")
        return (b.trend_slope ?? -9) - (a.trend_slope ?? -9);
      return b.risk_score - a.risk_score;
    });
  }, [activeRows, activeTiers, violBits, sort, now]);
```

After the `tierCounts` memo (~line 235), add:

```ts
  // An index built before violation tagging has no vc on ANY row — hide the
  // violation chips rather than render controls that can never match.
  const indexHasVc = useMemo(
    () => activeRows.some((r) => r.vc !== undefined),
    [activeRows],
  );

  // Chip counts over ACTIVE venues, like tierCounts (population-level; they
  // don't shrink when other filters are applied).
  const violCounts = useMemo(() => {
    const counts = VIOLATION_CATEGORIES.map(() => 0);
    for (const r of activeRows) {
      const vc = r.vc ?? 0;
      for (const c of VIOLATION_CATEGORIES) {
        if (vc & (1 << c.id)) counts[c.id] += 1;
      }
    }
    return counts;
  }, [activeRows]);
```

- [ ] **Step 4: Render the chip row**

Directly AFTER the closing `</div>` of the `{/* ---- Controls ---- */}` block (the div containing the Tier and Sort rows, ~line 364) and BEFORE the `{/* ---- Main grid ---- */}` div, insert:

```tsx
      {/* ---- Violation filter ---- */}
      {indexHasVc && (
        <div
          role="group"
          aria-label="Filter by violations at last inspection"
          className="mt-3 flex flex-wrap items-center gap-1.5"
        >
          <span className="text-2xs tracking-[0.14em] uppercase text-muted mr-1.5">
            Violations at last inspection
          </span>
          {VIOLATION_CATEGORIES.map((c) => {
            const on = activeViol.includes(c.slug);
            return (
              <button
                key={c.slug}
                type="button"
                onClick={() => toggleViol(c.slug)}
                aria-pressed={on}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-xs font-medium cursor-pointer transition-colors",
                  on
                    ? "bg-ink text-cream border border-ink"
                    : "bg-transparent text-ink border border-line hover:bg-tint",
                )}
              >
                {c.label}
                <span
                  className={cn("num ml-1.5", on ? "text-cream/70" : "text-muted")}
                >
                  {violCounts[c.id].toLocaleString()}
                </span>
              </button>
            );
          })}
        </div>
      )}
```

- [ ] **Step 5: Add the queue empty state**

In the queue section, after the `{!failed && !index && (...)}` loading paragraph (~line 391), add:

```tsx
          {index && !failed && rows.length === 0 && (
            <p className="px-6 py-10 text-sm text-muted text-center">
              No establishments match these filters.
            </p>
          )}
```

- [ ] **Step 6: Static checks + dev-server smoke**

Run: `pnpm lint && pnpm exec tsc --noEmit && pnpm test`
Expected: clean.

Run `pnpm dev` (predev regenerates the indexes with `vc`), open `http://localhost:3000/inspectors`, and confirm by hand:
- The chip row renders with six labeled chips and non-zero counts.
- Clicking "Pests and rodents" sets `?viol=pests`, shrinks the queue count, and every visible row makes sense; clicking again clears it.
- Combining a tier chip + a violation chip narrows further (AND).
- Selecting two categories widens vs one (OR).
- A selection that matches nothing (e.g. Low tier + an unlikely category) shows "No establishments match these filters."
- Switching city (header toggle) keeps the filter param working (NYC/LA indexes also carry `vc`).

Stop the dev server when done.

- [ ] **Step 7: Commit**

```bash
git add src/components/InspectorWorklist.tsx
git commit -m "feat(app): violation-category filter chips on the inspector worklist

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: List | Map toggle on the queue panel

**Files:**
- Modify: `app/src/lib/scores.ts` (export `hasCoords`, ~line 505)
- Modify: `app/src/components/InspectorWorklist.tsx`

**Interfaces:**
- Consumes: `MapView` from `@/components/MapView` (existing, unmodified); `hasCoords`, `PinSummary` from `@/lib/scores`; `CITY_CONFIG` (already imported); the filtered+sorted `rows` from Task 4.
- Produces: URL contract `?view=map` on `/inspectors`.

- [ ] **Step 1: Export hasCoords**

In `app/src/lib/scores.ts` (~line 505), change:

```ts
function hasCoords(r: SearchIndexRow): boolean {
```

to:

```ts
/** Row has renderable map coordinates. Shared by the home + inspector maps. */
export function hasCoords(r: SearchIndexRow): boolean {
```

Run: `pnpm exec tsc --noEmit` — expected clean (`computeHomeView`'s internal use is unaffected).

- [ ] **Step 2: View state + map pins in InspectorWorklist**

Add imports:

```ts
import { MapView } from "@/components/MapView";
```

and extend the existing `@/lib/scores` type/value imports with `PinSummary` (type) and `hasCoords` (value):

```ts
import type {
  DetailBundle,
  PinSummary,
  RiskTier,
  SearchIndex,
  SearchIndexRow,
} from "@/lib/scores";
import {
  ALL_TIERS,
  hasCoords,
  isAllTiers,
  parseTiers,
  TIER_HEX,
} from "@/lib/scores";
```

Below the `parseInspectorSort` helper (~line 46), add:

```ts
type WorklistView = "list" | "map";

function parseWorklistView(raw: string | null): WorklistView {
  return raw === "map" ? "map" : "list";
}
```

Next to the other URL params (Task 4's `violParam` block), add:

```ts
  const view = parseWorklistView(searchParams.get("view"));
```

Extend `setParams`'s parameter type and body with:

```ts
    view?: WorklistView;
```

```ts
    if (next.view) {
      if (next.view === "list") params.delete("view");
      else params.set("view", next.view);
    }
```

After the `visible` slice (~line 262), add the pin projection:

```ts
  // Pins in active-sort order: MapView's zoom-density cap draws the FIRST N
  // pins, so the map surfaces the same establishments as the top of the list
  // (e.g. "Worsening fastest" puts trending pins on first). activeRows already
  // excludes closed venues, so no is_out_of_business handling here.
  const mapPins = useMemo<PinSummary[]>(
    () =>
      view === "map"
        ? rows.filter(hasCoords).map((r) => ({
            license_id: r.license_id,
            dba_name: r.dba_name,
            address: r.address,
            lat: r.lat as number,
            lon: r.lon as number,
            risk_score: r.risk_score,
            risk_tier: r.risk_tier,
            top_driver: r.top_driver ?? undefined,
          }))
        : [],
    [rows, view],
  );
```

- [ ] **Step 3: Toggle in the queue panel header**

Replace the queue panel header (the `div` with `flex items-baseline justify-between px-6 pt-5 pb-3.5 border-b border-line`, ~line 373) with:

```tsx
          <div className="flex flex-wrap items-center justify-between gap-2 px-6 pt-5 pb-3.5 border-b border-line">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <h2 className="text-md font-bold">Priority queue</h2>
              <p className="text-xs text-muted">
                <span className="num">{rows.length.toLocaleString()}</span>{" "}
                establishments · highest expected yield first
              </p>
            </div>
            {/* List | Map toggle — same segmented pattern as the home page's
                mobile Map/List switch. URL-driven (?view=map). */}
            <div
              role="group"
              aria-label="Queue view"
              className="inline-flex rounded-lg border border-line overflow-hidden text-xs"
            >
              {(["list", "map"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setParams({ view: v })}
                  aria-pressed={view === v}
                  className={cn(
                    "px-3 py-1 capitalize transition-colors cursor-pointer",
                    v === "map" && "border-l border-line",
                    view === v
                      ? "bg-ink text-cream"
                      : "text-muted hover:bg-cream/60",
                  )}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
```

- [ ] **Step 4: Render the map pane in map mode**

Restructure the queue section body so loading/failure states render in both modes, the map pane renders in map mode, and the rows/empty-state/show-more render in list mode. Replace everything between the header `div` (Step 3) and the section's closing `</section>` with:

```tsx
          {failed && (
            <p className="px-6 py-10 text-sm text-muted text-center">
              The worklist index couldn&apos;t load. Reload the page to try
              again.
            </p>
          )}
          {!failed && !index && (
            <p className="px-6 py-10 text-sm text-muted text-center">
              Loading the worklist…
            </p>
          )}

          {index && !failed && view === "map" && (
            <div className="relative h-[70vh] min-h-[480px]">
              <MapView
                pins={mapPins}
                className="absolute inset-0"
                center={{
                  lat: CITY_CONFIG[city].center.lat,
                  lon: CITY_CONFIG[city].center.lon,
                  zoom: CITY_CONFIG[city].zoom,
                }}
              />
            </div>
          )}

          {index && !failed && view === "list" && (
            <>
              {rows.length === 0 && (
                <p className="px-6 py-10 text-sm text-muted text-center">
                  No establishments match these filters.
                </p>
              )}
              {visible.map((r, i) => (
                <QueueRow
                  key={r.license_id}
                  row={r}
                  city={city}
                  rank={i + 1}
                  days={daysSince(r.as_of_date, now)}
                  expanded={!!expanded[r.license_id]}
                  onToggle={() =>
                    setExpanded((e) => ({
                      ...e,
                      [r.license_id]: !e[r.license_id],
                    }))
                  }
                  onAddToRoute={() =>
                    setRoute((ids) =>
                      ids.includes(r.license_id) ? ids : [...ids, r.license_id],
                    )
                  }
                />
              ))}
              {rows.length > visibleCount && (
                <div className="p-3">
                  <button
                    type="button"
                    onClick={() => setVisibleCount((c) => c + QUEUE_PAGE)}
                    className="w-full rounded-xl border border-line py-2 text-sm text-teal hover:bg-cream/50 transition-colors cursor-pointer"
                  >
                    Show {Math.min(QUEUE_PAGE, rows.length - visibleCount)} more
                  </button>
                </div>
              )}
            </>
          )}
```

(The `QueueRow`/show-more JSX is byte-identical to what was there; it only moved inside the `view === "list"` branch. Task 4's separately-added empty state is subsumed by this block — ensure it isn't duplicated.)

- [ ] **Step 5: Static checks + dev-server smoke**

Run: `pnpm lint && pnpm exec tsc --noEmit && pnpm test`
Expected: clean.

Run `pnpm dev`, open `http://localhost:3000/inspectors`, and confirm by hand:
- The List | Map toggle renders in the panel header; clicking Map sets `?view=map` and swaps the queue rows for a Chicago map with tier-colored pins; the sidebar stays.
- Tier + violation chips filter the pins live; sorts reorder which pins appear at city zoom.
- Clicking a pin opens the popup (tier, score, name, address, top driver) and "Open full record" navigates to the detail page.
- Switching city (header toggle) recenters the map (NYC/LA).
- Back in List view, expand/collapse and "Add to today's route" still work.

Stop the dev server when done.

- [ ] **Step 6: Commit**

```bash
git add src/lib/scores.ts src/components/InspectorWorklist.tsx
git commit -m "feat(app): List | Map toggle on the inspector priority queue

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Full verification + PR

**Files:**
- No source changes expected (fixes only if verification finds problems).

**Interfaces:**
- Consumes: everything above, running as a whole app.

- [ ] **Step 1: Run the repo's CI-equivalent checks**

From `app/`: `pnpm lint && pnpm exec tsc --noEmit && pnpm test`
From the repo root: `make lint` (ruff over Python — should be untouched/clean; the pre-commit hook enforces it anyway).
Expected: all clean.

- [ ] **Step 2: Run /verify for the visual change**

Invoke the `/verify` skill (it auto-discovers `verifier-app`) and capture REAL screenshots per the repo's checklist, at desktop AND ~390px mobile:
- Inspector page default state: chip row visible with counts.
- One violation chip active (`?viol=pests`): queue narrowed, chip visually distinct, URL correct.
- Combined filters (`?tier=High&viol=pests,temp`): AND/OR behavior visible.
- Zero-result state: "No establishments match these filters."
- Map view (`?view=map`): pins render, sidebar intact, no horizontal overflow.
- Map popup open (hover/click interaction), plus keyboard focus states on chips and the toggle.
- NYC or LA city switch in map view (recenter works).
- Contrast: chip text and toggle text at WCAG AA; confirm selected-state has a non-color cue (`aria-pressed` + the filled/outline treatment).

Report honestly which states were observed and which could not be exercised. Save all screenshots to a known path in the session scratchpad and list the paths.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin jun/app-inspector-violation-map
gh pr create --title "feat(app): inspector worklist violation filter + map view" --body "$(cat <<'EOF'
## Summary
- Violation-category filter chips on /inspectors (six categories, `?viol=` URL param, OR within the filter, AND with tiers), tagged at build time into search-index.json as a per-row `vc` bitmask from each establishment's latest scored inspection (full S3 comment text on deploys, committed headlines in dev).
- List | Map toggle on the priority queue (`?view=map`) reusing the Search tab's MapView: tier-colored pins in active-sort order, per-city centers, existing popups.
- Spec: docs/superpowers/specs/2026-07-13-inspector-violation-filter-and-map-design.md

## Verification
- vitest: taxonomy/param/bitmask units, tagger units (real per-city samples), gen-search-index integration (dev + deploy + legacy modes)
- /verify screenshots: [drag the captured screenshots in here — agent lists paths below]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Then ask Jun to drag the listed screenshot files into the PR description in the GitHub web UI (repo is private; committed PNGs won't render inline). Default reviewer: Arun (web-app backup owner). Squash-merge only, and note that merging to `main` deploys to production.

---

## Self-review (done at plan-writing time)

- **Spec coverage:** taxonomy + tagging rule (Tasks 1–3), dev/deploy text sources + logging + size budget (Task 3), chips/URL/AND-OR/counts/hidden-when-no-vc/empty state (Task 4), map toggle/pins-in-sort-order/per-city center/non-goal respected (Task 5), tests + /verify + PR screenshots (Tasks 1–3, 6). All-six-selected semantics encoded in Task 1 test + Task 4 setParams comment.
- **Placeholder scan:** none; every code step carries full code.
- **Type consistency:** `parseViol/bitsForSlugs/matchesViolations/VIOLATION_CATEGORIES` (Task 1) match Task 4 usage; `tagViolations/latestScoredEvent/CATEGORY_SLUGS` (Task 2) match Task 3 usage; `hasCoords/PinSummary` exports (Task 5 Step 1) match Step 2 usage; `vc?: number` consistent across Tasks 3–5.
