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

// Relative /api/agent hits CloudFront which proxies to ALB (avoids mixed-content).
// Override with NEXT_PUBLIC_ALB_URL for local dev.
const AGENT_URL =
  process.env.NEXT_PUBLIC_ALB_URL ?? "/api/agent";

export interface AgentResponse {
  result: string;
}

/**
 * Send a conversational query to the Food Safety Agent.
 *
 * @param query     Natural-language query (max 500 chars).
 * @param sessionId Caller-managed UUID that preserves conversation state
 *                  across multiple turns. Must be ≥33 chars.
 * @returns         The agent's plain-text response.
 */
export async function queryAgent(
  query: string,
  sessionId: string,
): Promise<string> {
  const res = await fetch(AGENT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, session_id: sessionId }),
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
