/**
 * Client for submitting user feedback.
 *
 * The app is a static export (no server, no API routes), so — exactly like the
 * agent client — the browser posts directly to an external endpoint. Here that
 * endpoint is a Google Apps Script Web App bound to a private Google Sheet: it
 * appends the submission as a row and emails the team. The URL is injected at
 * build time via NEXT_PUBLIC_FEEDBACK_ENDPOINT (unset in local dev unless you
 * export it), so an unconfigured build simply reports feedback as unavailable
 * rather than posting into the void.
 *
 * Two deliberate fetch choices, both forced by Apps Script:
 *  - Content-Type text/plain keeps this a CORS "simple request", so the browser
 *    sends no preflight — Apps Script Web Apps can't answer an OPTIONS preflight.
 *  - mode "no-cors" because the ContentService response carries no
 *    Access-Control-Allow-Origin header, so the browser refuses to read it.
 * The response is therefore opaque: a resolved fetch means the request was
 * delivered; we can't read a status or body, so server-side outcomes (e.g. a
 * honeypot-flagged row the script silently drops) are invisible here. That's
 * acceptable — real submissions always land, and spam is dropped server-side.
 */

const FEEDBACK_URL = process.env.NEXT_PUBLIC_FEEDBACK_ENDPOINT ?? "";

/**
 * Who is giving feedback. This is NOT chosen on the form. It is prefilled from a
 * site-entry role step (a future onboarding feature) and carried through; the
 * form only reads that value. Until the entry step ships, submissions carry
 * "unknown". The set is kept in sync with the roles that step will offer:
 * resident/diner, food-business operator, health inspector.
 */
export type FeedbackRole = "resident" | "operator" | "inspector" | "unknown";

export const FEEDBACK_ROLES: readonly FeedbackRole[] = [
  "resident",
  "operator",
  "inspector",
  "unknown",
] as const;

/** Upper bound on the free-text message, mirrored as the textarea maxLength. */
export const MAX_FEEDBACK_CHARS = 2000;

export interface FeedbackPayload {
  /** The user's free-text message (required, already trimmed and capped). */
  message: string;
  /** Prefilled role (see FeedbackRole); "unknown" until the entry step lands. */
  role: FeedbackRole;
  /** Where the feedback was sent from: "site" | "how-it-works" | "restaurant-detail". */
  source: string;
  /** License id of the establishment, when sent from a restaurant detail page. */
  venueId?: string;
  /** Establishment name, when sent from a restaurant detail page. */
  venueName?: string;
  /**
   * Honeypot — always empty for a real user (the field is hidden from humans).
   * Bots auto-fill every field, so the Apps Script drops any row where this is
   * non-empty. Sent so the drop happens server-side, where it can't be bypassed.
   */
  company?: string;
}

/** Whether this build has a submission endpoint configured. */
export function feedbackEnabled(): boolean {
  return FEEDBACK_URL.length > 0;
}

/**
 * Submit one feedback entry. Resolves once the request is delivered; rejects
 * only on a network failure or when no endpoint is configured. The opaque
 * no-cors response means server-side validation errors can't be surfaced.
 */
export async function submitFeedback(payload: FeedbackPayload): Promise<void> {
  if (!FEEDBACK_URL) {
    throw new Error("Feedback endpoint is not configured.");
  }
  await fetch(FEEDBACK_URL, {
    method: "POST",
    mode: "no-cors",
    headers: { "Content-Type": "text/plain;charset=utf-8" },
    body: JSON.stringify(payload),
  });
}
