/**
 * Food Safety Intelligence — feedback endpoint (Google Apps Script).
 *
 * @OnlyCurrentDoc
 * Limits the Sheets permission to THIS spreadsheet only (not "all your Google
 * Sheets"). Apps Script reads this annotation and requests the narrower scope,
 * so the authorisation screen asks for access to the current spreadsheet alone.
 *
 * This is the server side of the /feedback form. The web app is a static export
 * with no backend, so the browser posts submissions straight to this script,
 * which appends each one as a row in the bound Google Sheet and emails the team.
 *
 * ── One-time setup ────────────────────────────────────────────────────────────
 * 1. Create a Google Sheet. In the first tab, add this header row (row 1):
 *
 *        timestamp | role | source | venue_id | venue_name | message
 *
 * 2. In that Sheet: Extensions → Apps Script. Delete the default code, paste
 *    this whole file, and Save.
 * 3. Deploy → New deployment → type "Web app":
 *        Execute as:      Me
 *        Who has access:  Anyone
 *    Deploy, authorise when prompted, and copy the Web app URL (ends in /exec).
 * 4. Set that URL as the app's NEXT_PUBLIC_FEEDBACK_ENDPOINT (build-time env
 *    var — it gets baked into the static bundle, so it must be present when the
 *    site is built/deployed).
 * 5. Share the Sheet with the team: Restricted → add each person as Editor.
 *    Keep it Restricted (never "anyone with the link") — the public only ever
 *    touches this script URL, never the Sheet.
 *
 * Redeploying after an edit: Deploy → Manage deployments → edit the existing
 * one → Version: New version. Re-using the same deployment keeps the /exec URL
 * stable, so the app's env var doesn't change.
 *
 * ── Payload contract (must match app/src/lib/feedback.ts) ─────────────────────
 *   message    string   required — the user's free text
 *   role       string   "resident" | "operator" | "inspector" | "unknown"
 *                        (prefilled by the app; "unknown" until the site-entry
 *                        role step ships)
 *   source     string   where it came from: "site" | "how-it-works" |
 *                        "restaurant-detail"
 *   venueId    string   optional — license id, only when sent from a listing
 *   venueName  string   optional — establishment name, only when sent from a listing
 *   company    string   honeypot — always empty for real users; bots fill it
 */

// Where new-feedback notifications are sent.
const NOTIFY_EMAIL = "bella_davies@berkeley.edu";

function doPost(e) {
  const data = JSON.parse(e.postData.contents);

  // Honeypot: the form's `company` field is hidden from humans, so a non-empty
  // value means a bot. Drop the row silently — return "ok" so the bot still sees
  // success — without recording it or emailing anyone.
  if (data.company) {
    return ContentService.createTextOutput("ok");
  }

  // venue_id / venue_name are optional (only sent from a restaurant page), so
  // fall back to "" — those two columns stay blank for general feedback.
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  sheet.appendRow([
    new Date(),
    data.role || "unknown",
    data.source || "",
    data.venueId || "",
    data.venueName || "",
    data.message || "",
  ]);

  MailApp.sendEmail(
    NOTIFY_EMAIL,
    "New Food Safety feedback (" + (data.role || "unknown") + ")",
    "Role: " + (data.role || "unknown") +
      "\nSource: " + (data.source || "") +
      "\nVenue: " + (data.venueName || "") +
      (data.venueId ? " (#" + data.venueId + ")" : "") +
      "\n\n" + (data.message || "")
  );

  return ContentService.createTextOutput("ok");
}
