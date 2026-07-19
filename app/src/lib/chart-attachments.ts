// Chart attachments carried in an agent message.
//
// The chat wire contract stays a single text string end to end (see
// `lib/agent-api.ts` and the agent runtime). A generated chart therefore travels
// inside the assistant's text as a fenced block the agent emits:
//
//   ```eatelligence-chart
//   {"id":"c1","title":"Risk tiers","img":"https://…/c1.png","script":"https://…/c1.py"}
//   ```
//
// The client parses those blocks out of the text (like it already parses
// markdown links), renders each as an inline chart card, and lists them in the
// attachments rail. Because attachments are DERIVED from the stored string, the
// persisted transcript and the replayed agent history stay plain strings — no
// storage-schema change, and the block never has to round-trip as structured data.

export interface ChartAttachment {
  /** Stable id, unique within a message. Used as the React key + download slug. */
  id: string;
  /** Human title shown above the chart and in the attachments rail. */
  title: string;
  /** URL of the rendered PNG (https presigned from the backend, or a data URL in the mock). */
  imageUrl: string;
  /** URL to fetch the generating script text lazily (the backend uploads it beside the PNG). */
  scriptUrl?: string;
  /** Inline script text. The mock uses this; the backend prefers `scriptUrl` to keep the block small. */
  scriptText?: string;
  /** Script language, for the label + (future) syntax handling. Defaults to python. */
  language?: string;
}

export interface ParsedAgentMessage {
  /** The message text with every chart block removed. */
  text: string;
  /** Charts parsed out of the message, in document order. */
  attachments: ChartAttachment[];
}

// Fenced block: ```eatelligence-chart\n<json>\n```  (info-string may carry trailing
// spaces). The trailing newline is part of the match so removing the block joins
// the surrounding prose with a single break instead of leaving a blank line.
const CHART_BLOCK = /```eatelligence-chart[ \t]*\r?\n([\s\S]*?)\r?\n?```[ \t]*\r?\n?/g;

// Only these schemes may become an <img src> or a fetched script URL. A model
// reply is untrusted text; a relative path (same-origin asset) and an inline
// image data URL are safe, http(s) is the real backend, everything else
// (javascript:, blob:, file:, …) is rejected so a reply can't smuggle a vector in.
function isSafeImageUrl(u: unknown): u is string {
  return (
    typeof u === "string" &&
    (/^https:\/\//i.test(u) ||
      /^\//.test(u) ||
      /^data:image\/(png|jpeg|svg\+xml|webp)[;,]/i.test(u))
  );
}

function isSafeScriptUrl(u: unknown): u is string {
  return typeof u === "string" && (/^https:\/\//i.test(u) || /^\//.test(u));
}

/**
 * Split an assistant message into its text and any chart attachments.
 * Malformed or unsafe blocks are dropped (never rendered as raw JSON).
 * A message with no chart block returns the text unchanged and an empty list.
 */
export function parseChartAttachments(content: string): ParsedAgentMessage {
  if (!content || content.indexOf("eatelligence-chart") === -1) {
    return { text: content ?? "", attachments: [] };
  }

  const attachments: ChartAttachment[] = [];
  const seenIds = new Set<string>();

  const text = content
    .replace(CHART_BLOCK, (_match, body: string) => {
      const att = toAttachment(body, seenIds);
      if (att) attachments.push(att);
      // Remove the block from the rendered text whether or not it parsed, so a
      // broken block never leaks raw JSON into the bubble.
      return "";
    })
    // Collapse the blank lines the removed block leaves behind.
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return { text, attachments };
}

function toAttachment(body: string, seenIds: Set<string>): ChartAttachment | null {
  let raw: unknown;
  try {
    raw = JSON.parse(body.trim());
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;

  const img = o.img ?? o.imageUrl;
  if (!isSafeImageUrl(img)) return null;

  // An id is required and must be unique within the message (React key + slug).
  // An explicit id can still collide with a later fallback, so loop until free —
  // this is untrusted model output.
  let id = typeof o.id === "string" && o.id.trim() ? o.id.trim() : "";
  let n = seenIds.size + 1;
  while (!id || seenIds.has(id)) {
    id = `chart-${n++}`;
  }
  seenIds.add(id);

  const scriptUrlCandidate = o.script ?? o.scriptUrl;
  const scriptText = typeof o.scriptText === "string" ? o.scriptText : undefined;

  return {
    id,
    title: typeof o.title === "string" && o.title.trim() ? o.title.trim() : "Chart",
    imageUrl: img,
    scriptUrl: isSafeScriptUrl(scriptUrlCandidate) ? scriptUrlCandidate : undefined,
    scriptText,
    language: typeof o.lang === "string" ? o.lang : "python",
  };
}

// ─── Dev-only mock ──────────────────────────────────────────────────────────
// A self-contained chart message for exercising the UI with no backend (see
// ChatInterface's `?demo=chart`). The image is an inline SVG data URL and the
// script is inlined, so it renders and downloads/copies without any network.

const MOCK_CHART_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400" font-family="ui-sans-serif, system-ui, sans-serif">
  <rect width="640" height="400" fill="#ffffff"/>
  <text x="32" y="40" font-size="18" font-weight="600" fill="#1f2421">Chicago establishments by risk tier</text>
  <g fill="#6b7f6e">
    <rect x="70" y="120" width="90" height="210"/>
    <rect x="200" y="135" width="90" height="195"/>
    <rect x="330" y="250" width="90" height="80"/>
    <rect x="460" y="300" width="90" height="30"/>
  </g>
  <g font-size="14" fill="#1f2421" text-anchor="middle">
    <text x="115" y="350">Low</text>
    <text x="245" y="350">Moderate</text>
    <text x="375" y="350">Elevated</text>
    <text x="505" y="350">High</text>
  </g>
  <g font-size="13" fill="#1f2421" text-anchor="middle">
    <text x="115" y="112">11,364</text>
    <text x="245" y="127">10,734</text>
    <text x="375" y="242">1,303</text>
    <text x="505" y="292">220</text>
  </g>
  <line x1="60" y1="330" x2="590" y2="330" stroke="#d8dcd6" stroke-width="1"/>
</svg>`;

const MOCK_CHART_SCRIPT = `import json
import pandas as pd
import matplotlib.pyplot as plt

# scores.json for the active city, already loaded into the sandbox
df = pd.DataFrame(json.load(open("/tmp/scores.json"))["scores"])

order = ["Low", "Moderate", "Elevated", "High"]
counts = df["risk_tier"].value_counts().reindex(order)

fig, ax = plt.subplots(figsize=(6.4, 4))
ax.bar(order, counts.values, color="#6b7f6e")
ax.set_title("Chicago establishments by risk tier")
for i, v in enumerate(counts.values):
    ax.text(i, v, f"{v:,}", ha="center", va="bottom")
fig.tight_layout()
fig.savefig("chart.png", dpi=144)
`;

const MOCK_CHART2_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400" font-family="ui-sans-serif, system-ui, sans-serif">
  <rect width="640" height="400" fill="#ffffff"/>
  <text x="32" y="40" font-size="18" font-weight="600" fill="#1f2421">Trend direction across Chicago</text>
  <g>
    <rect x="120" y="120" width="150" height="210" fill="#6b7f6e"/>
    <rect x="370" y="300" width="150" height="30" fill="#b4553f"/>
  </g>
  <g font-size="14" fill="#1f2421" text-anchor="middle">
    <text x="195" y="350">Improving</text>
    <text x="445" y="350">Worsening</text>
  </g>
  <g font-size="13" fill="#1f2421" text-anchor="middle">
    <text x="195" y="112">2,213</text>
    <text x="445" y="292">109</text>
  </g>
  <line x1="90" y1="330" x2="560" y2="330" stroke="#d8dcd6" stroke-width="1"/>
</svg>`;

const MOCK_CHART2_SCRIPT = `import json
import pandas as pd
import matplotlib.pyplot as plt

df = pd.DataFrame(json.load(open("/tmp/scores.json"))["scores"])

# trend_slope > 0 is worsening; the stable band is |slope| < 0.0003
improving = (df["trend_slope"] < -0.0003).sum()
worsening = (df["trend_slope"] > 0.0003).sum()

fig, ax = plt.subplots(figsize=(6.4, 4))
ax.bar(["Improving", "Worsening"], [improving, worsening], color=["#6b7f6e", "#b4553f"])
ax.set_title("Trend direction across Chicago")
fig.tight_layout()
fig.savefig("chart.png", dpi=144)
`;

function chartBlock(obj: Record<string, unknown>): string {
  return ["```eatelligence-chart", JSON.stringify(obj), "```"].join("\n");
}

/** Dev-only: the raw message content the mock seeds (text + two chart blocks). */
export function mockChartMessageContent(): string {
  return [
    "Here is the distribution of establishments across the four risk tiers in Chicago. Most sit in the Low and Moderate tiers, with a small High-risk tail.",
    chartBlock({
      id: "demo-tiers",
      title: "Chicago establishments by risk tier",
      img: `data:image/svg+xml;utf8,${encodeURIComponent(MOCK_CHART_SVG)}`,
      scriptText: MOCK_CHART_SCRIPT,
      lang: "python",
    }),
    "And here is how many are trending in each direction. Far more establishments are improving than worsening.",
    chartBlock({
      id: "demo-trend",
      title: "Trend direction across Chicago",
      img: `data:image/svg+xml;utf8,${encodeURIComponent(MOCK_CHART2_SVG)}`,
      scriptText: MOCK_CHART2_SCRIPT,
      lang: "python",
    }),
    "Open either script to see how it was computed, or download the images.",
  ].join("\n");
}
