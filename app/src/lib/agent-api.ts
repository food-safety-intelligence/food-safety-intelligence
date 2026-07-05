/**
 * Client for the Food Safety Agent.
 *
 * In production the CloudFront distribution proxies /api/agent → ALB,
 * so the browser always talks HTTPS to CloudFront and never directly to
 * the HTTP ALB (which would be blocked as mixed content).
 *
 * In local dev, NEXT_PUBLIC_ALB_URL overrides to the direct ALB address.
 * That's fine for localhost because there's no mixed-content restriction
 * on HTTP origins.
 *
 * Auth upgrade path for production:
 *   1. Add a Cognito User Pool to the ALB listener rule.
 *   2. Obtain a Cognito JWT from the browser via `amazon-cognito-identity-js`.
 *   3. Pass it as `Authorization: Bearer <jwt>` below.
 */

import type { City } from "@/lib/city";

// Relative /api/agent hits CloudFront which proxies to ALB (avoids mixed-content).
// Override with NEXT_PUBLIC_ALB_URL for local dev.
const AGENT_URL =
  process.env.NEXT_PUBLIC_ALB_URL ?? "/api/agent";

export interface AgentResponse {
  result: string;
}

/** One prior turn replayed to the agent for multi-turn context. */
export interface AgentHistoryTurn {
  role: "user" | "agent";
  content: string;
}

/** The establishment the user is viewing, used to scope "this restaurant". */
export interface AgentEstablishment {
  licenseId: string;
  name: string;
}

/**
 * Audience the chat was opened for — set when the user clicks the chat
 * launcher from the For Inspectors or For Caregivers page (see
 * ChatScopeContext's ChatPersona, the UI-facing twin of this type). Shapes the
 * agent's system prompt (see agents/entrypoint.py's ACTIVE PERSONA prefix) and
 * the starter-chip pools in ChatInterface. Undefined/omitted is the default,
 * unscoped chat.
 */
export type AgentPersona = "inspector" | "caregiver";

// The deployed agent receives only the `query` string reliably (the proxy
// forwards just that field), so establishment context rides inside the query
// rather than as a separate field. The whole wire query must stay within the
// proxy's 500-char cap; we keep the tag compact and cap the user's text against
// the remaining budget (see scopedInputBudget) so a scoped send is never
// rejected for length.
const WIRE_QUERY_LIMIT = 500;
// Defensive cap on the establishment name inside the tag so one very long
// dba_name can't swallow the whole budget.
const MAX_TAG_NAME_CHARS = 80;

function scopeTag(establishment: AgentEstablishment): string {
  const name = establishment.name.slice(0, MAX_TAG_NAME_CHARS);
  // Tells the model which establishment "this restaurant / this place / it /
  // here" refers to, and gives it the license_id so it can call
  // explain_restaurant directly instead of re-searching by name.
  return `(The user is viewing the detail page for "${name}" (license_id ${establishment.licenseId}); "this restaurant", "this place", "it", and "here" refer to it.)`;
}

/**
 * Characters left for the user's own text once the establishment tag is
 * prepended, so the input can be capped and a scoped send never trips the
 * proxy's length limit. Floored at 0.
 */
export function scopedInputBudget(establishment: AgentEstablishment): number {
  // tag + "\n\n" + userText must fit WIRE_QUERY_LIMIT.
  return Math.max(0, WIRE_QUERY_LIMIT - scopeTag(establishment).length - 2);
}

/**
 * The text actually sent to the agent: the user's message, prefixed with a
 * compact establishment-context tag when one is in scope. The displayed message
 * bubble and the stored transcript keep the user's clean text — only the wire
 * payload carries the tag.
 */
export function buildWireQuery(
  query: string,
  establishment?: AgentEstablishment,
): string {
  if (!establishment) return query;
  return `${scopeTag(establishment)}\n\n${query}`;
}

/**
 * The text actually sent over the wire: city marker, then persona marker,
 * then the establishment-scoped query (see buildWireQuery) — in that fixed
 * order so the backend's anchored regexes (agents/entrypoint.py's
 * _extract_city / _extract_persona) can strip them one at a time regardless
 * of which are present. Markers are the robust path — the deployed Lambda
 * proxy forwards only the `query` string — so this is what actually reaches
 * the agent in production; the explicit `city`/`persona` body fields (added
 * below in queryAgent) are for the local test server / a future proxy that
 * passes the full body.
 */
export function taggedWireQuery(
  query: string,
  city: City,
  persona?: AgentPersona,
  establishment?: AgentEstablishment,
): string {
  let wire = buildWireQuery(query, establishment);
  if (persona) wire = `[[persona:${persona}]]${wire}`;
  if (city !== "chicago") wire = `[[city:${city}]]${wire}`;
  return wire;
}

/**
 * Send a conversational query to the Food Safety Agent.
 *
 * The deployed agent is stateless (a fresh, isolated agent per request), so
 * multi-turn context is replayed by the caller: pass the prior turns as
 * `history` and the agent answers follow-ups ("is the second one safe too?")
 * with that context. The backend validates and length-caps the history.
 *
 * @param query     Natural-language query (max 500 chars).
 * @param sessionId Caller-managed UUID that scopes the conversation. Must be
 *                  ≥33 chars.
 * @param history   Prior turns of THIS conversation (oldest first), excluding
 *                  the current query. Empty/omitted for the first turn.
 * @param establishment  The establishment the user is viewing, if any. When set,
 *                  a compact context tag is prepended to the wire query so the
 *                  agent resolves "this restaurant" to it. Does not affect the
 *                  displayed message or stored history (the caller keeps those
 *                  clean).
 * @param city      The active city (multi-city, DR 0016). Defaults to Chicago.
 * @param persona   The audience the chat was opened for (For Inspectors / For
 *                  Caregivers), if any. Shapes the agent's framing — see
 *                  AgentPersona.
 * @returns         The agent's plain-text response.
 */
export async function queryAgent(
  query: string,
  sessionId: string,
  history: AgentHistoryTurn[] = [],
  establishment?: AgentEstablishment,
  city: City = "chicago",
  persona?: AgentPersona,
): Promise<string> {
  const wire = taggedWireQuery(query, city, persona, establishment);
  const res = await fetch(AGENT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: wire,
      session_id: sessionId,
      history,
      city,
      persona,
    }),
  });

  let data: Record<string, string> = {};
  try {
    data = (await res.json()) as Record<string, string>;
  } catch {
    // body might be empty on network errors
  }

  if (!res.ok) {
    throw new Error(data.error ?? `Server error (HTTP ${res.status})`);
  }
  if (data.error) throw new Error(data.error);
  return data.result ?? "";
}
