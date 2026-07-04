# 0014. User feedback collection via a hosted form endpoint

## Status
Accepted (2026-07-04). Implemented in the `bella/app-user-feedback` PR.

## Context
We want visitors to report problems — a wrong listing, a confusing score, a
data error. The web app is a **static export** (`output: "export"`, decision
[0013]) served from CloudFront: it has **no server, no API routes, and no write
surface** — it only ever reads precomputed JSON. So it cannot receive or persist
a form submission on its own. Standing up our own write-backend (an API route +
datastore) would mean provisioning in the **agent AWS account**, which this
workstream can't administer, plus owning spam handling and secrets — heavy for a
capstone feedback box.

## Decision
Let a **hosted form service own persistence, spam, delivery, and storage**; the
app only renders a form and POSTs to it.

- **Endpoint**: a **Google Apps Script Web App** bound to a private Google Sheet.
  On each POST it appends a row and emails the team (`MailApp`). Deployed with
  access "Anyone" (visitors are not logged in) and `@OnlyCurrentDoc` (Sheets
  scope limited to the one bound Sheet). Script committed at
  `feedback-apps-script.gs` (paste-source + backend contract).
- **App → endpoint**: a client-side `fetch` with `mode: "no-cors"` and
  `Content-Type: text/plain` — the same client-posts-to-an-external-endpoint
  pattern as the chat agent (`agent-api.ts`). `text/plain` keeps it a CORS-simple
  request (Apps Script can't answer a preflight); `no-cors` because the response
  carries no CORS header, so it's opaque (we can't read success — acceptable).
- **Endpoint URL** lives in the committed `app/.env.production`
  (`NEXT_PUBLIC_FEEDBACK_ENDPOINT`), baked in at build time like
  `NEXT_PUBLIC_ALB_URL`. It's append-only and public, so committing it is fine.
- **Payload / Sheet schema**: `timestamp | role | source | venue_id |
  venue_name | message`. Only `message` is user-entered. `venue_id`/`venue_name`
  are present only when the form is opened from a restaurant page.
- **No personal data**: we deliberately **do not collect an email** (or name),
  so there is no PII to handle; the Sheet stays a private team log.
- **Spam**: a hidden **honeypot** field (`company`) — invisible to humans, filled
  by bots; the script drops any row where it is non-empty, server-side.
- **Role is prefilled, not asked.** The form carries a hidden `role`
  (resident / operator / inspector) that a future **site-entry role step** will
  set; until then it submits `unknown`. Kept in the schema now so submissions are
  role-tagged the day that step lands.
- **Entry points**: a site-wide footer link, a call-to-action at the end of the
  how-it-works page, and a contextual "something look wrong with this listing?"
  link on the restaurant detail page (which passes the venue).

## Consequences
- No backend, no AWS, no new npm dependency, no secrets in the app; nothing new
  to operate. Verified end-to-end: real browser POSTs land as Sheet rows + team
  emails, venue columns populate, and the honeypot drops a company-filled POST.
- The endpoint is an open, unauthenticated URL — someone who finds it could spam
  it. Mitigated by the honeypot and Gmail's send quota; if abused, redeploy for a
  new URL and update the env var.
- Preserves the app's read-only-JSON shape: the only outbound write is this
  feedback POST to an external service — it is **not** model inference, so it does
  not breach the permanent batch-score-to-JSON contract.

## Alternatives considered
- **Own AWS API route → DynamoDB/S3** — matches the Phase-2 AWS direction but
  needs provisioning in the agent account (out of this workstream's control) and
  we'd own spam + secrets. Too heavy for a feedback box.
- **Plain Google Form (iframe or raw POST)** — Sheet-native, but the form is
  either off-brand (iframe) or a hacky no-cors POST, and email is coarser.
- **`mailto:` link** — trivial, but no aggregation, no spreadsheet, and depends
  on a configured mail client.
- **Collect an email for replies** — rejected to avoid holding any PII.
- **Summarize / cluster feedback with an agent now** — deferred. At capstone
  volume the Sheet is readable by eye; the schema is left clustering-ready so a
  later batch job (reusing the Bedrock setup) can add topic clusters when there's
  feedback to cluster.

[0013]: 0013-client-render-detail-page.md
