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
