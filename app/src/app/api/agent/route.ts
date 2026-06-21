/**
 * Chatbot endpoint — STUB.
 *
 * Mirrors the SageMaker-stub idiom (agents/tools/get_safety_score): a
 * deterministic, data-backed placeholder behind an env flag, with the real
 * path present as the documented swap. The web app otherwise reads only static
 * JSON; this route is the single live seam, kept inert (no model call) for now.
 *
 *   AGENT_USE_STUB=true  (default) → answer from precomputed scores.json by
 *                                    keyword match. No network, no model.
 *   AGENT_USE_STUB=false           → proxy to the agent sidecar at AGENT_URL
 *                                    (inactive until that service exists).
 */

import { loadScores } from "@/lib/scores-server";
import type { RestaurantScore } from "@/lib/scores";

const STUB_NOTE =
  "Preliminary — answers come from precomputed risk scores by keyword match, not the live AI agent.";

export async function POST(request: Request): Promise<Response> {
  let message = "";
  try {
    const body = (await request.json()) as { message?: unknown };
    if (typeof body.message === "string") message = body.message;
  } catch {
    // Malformed/empty body falls through to the empty-message reply below.
  }

  if (!message.trim()) {
    return Response.json({
      reply:
        'Ask about food-safety risk for Chicago restaurants — try "safest tacos" or "is Subway risky?".',
      stub: true,
      stub_note: STUB_NOTE,
    });
  }

  const useStub =
    (process.env.AGENT_USE_STUB ?? "true").toLowerCase() !== "false";

  if (!useStub) {
    // Real path (inactive by default): proxy to the agent sidecar. Parallels
    // sagemaker_stub._invoke_real — present as the swap point, not wired for
    // the demo.
    const url = process.env.AGENT_URL;
    if (!url) {
      return Response.json(
        { reply: "The agent service is not configured.", stub: false },
        { status: 503 },
      );
    }
    const res = await fetch(`${url}/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = (await res.json()) as { reply?: string };
    return Response.json(
      { reply: data.reply ?? "No answer.", stub: false },
      { status: res.status },
    );
  }

  const { scores } = await loadScores();
  return Response.json({
    reply: buildStubReply(message, scores),
    stub: true,
    stub_note: STUB_NOTE,
  });
}

// ---------------------------------------------------------------------------
// Stub answer builder — deterministic, sourced entirely from scores.json.
// ---------------------------------------------------------------------------

// Words that carry intent or filler, not a restaurant name. Stripped before
// substring-matching the message against dba_name + address.
const STOPWORDS = new Set([
  "safe", "safest", "safer", "risk", "risks", "risky", "riskiest", "unsafe",
  "dangerous", "worst", "best", "good", "bad", "top", "lowest", "highest",
  "score", "scores", "rating", "restaurant", "restaurants", "place", "places",
  "spot", "spots", "food", "near", "me", "my", "show", "find", "tell", "about",
  "please", "the", "a", "an", "is", "are", "in", "on", "at", "around", "of",
  "for", "which", "what", "where", "how", "any",
]);

function riskiestIntent(msg: string): boolean {
  return /\b(risk|risks|risky|riskiest|worst|highest|dangerous|unsafe|avoid|bad)\b/.test(
    msg,
  );
}

function extractTerm(msg: string): string {
  return msg
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 0 && !STOPWORDS.has(w))
    .join(" ")
    .trim();
}

function titleCase(s: string): string {
  return s.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

function buildStubReply(message: string, scores: RestaurantScore[]): string {
  if (scores.length === 0) {
    return "I don't have any scored Chicago restaurants loaded right now.";
  }

  const riskiest = riskiestIntent(message.toLowerCase());
  const term = extractTerm(message);

  let pool = scores;
  let matchedTerm = false;
  if (term) {
    const filtered = scores.filter((r) =>
      `${r.dba_name} ${r.address}`.toLowerCase().includes(term),
    );
    if (filtered.length > 0) {
      pool = filtered;
      matchedTerm = true;
    }
  }

  const ranked = [...pool].sort((a, b) =>
    riskiest ? b.risk_score - a.risk_score : a.risk_score - b.risk_score,
  );
  const top = ranked.slice(0, 3);

  const lines = top.map((r, i) => {
    const addr = r.address.trim();
    return `${i + 1}. ${titleCase(r.dba_name)} — ${r.risk_tier} risk (score ${r.risk_score.toFixed(2)})${addr ? `, ${addr}` : ""}`;
  });

  const adj = riskiest ? "highest-risk" : "lowest-risk";
  let intro: string;
  if (term && matchedTerm) {
    intro = `Here are the ${adj} Chicago spots matching "${term}" in our data:`;
  } else if (term) {
    intro = `I couldn't find a Chicago restaurant matching "${term}", so here are the ${adj} spots overall:`;
  } else {
    intro = `Here are the ${adj} Chicago restaurants in our data:`;
  }

  return `${intro}\n${lines.join("\n")}`;
}
