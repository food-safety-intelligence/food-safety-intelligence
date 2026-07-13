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
