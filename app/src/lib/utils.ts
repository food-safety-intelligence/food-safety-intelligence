import clsx, { type ClassValue } from "clsx";

/**
 * Tiny className combiner. Keeps JSX readable when conditionally combining
 * Tailwind utility classes. We avoid `tailwind-merge` for now because the
 * theme is small and we don't have conflicting utility overrides.
 */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}

export function formatScore(score: number): string {
  return score.toFixed(2);
}

export function formatDelta(delta: number): string {
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  return `${sign}${Math.abs(delta).toFixed(4)}`;
}

/**
 * Human-readable inspection date. Static format chosen to be unambiguous
 * across locales: "22 May 2026".
 */
export function formatInspectionDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const monthNames = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${String(d).padStart(2, "0")} ${monthNames[m - 1]} ${y}`;
}
