"use client";

import { CheckCircle2, MessageSquare, Send, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import {
  FEEDBACK_ROLES,
  feedbackEnabled,
  type FeedbackRole,
  MAX_FEEDBACK_CHARS,
  submitFeedback,
  topicsForRole,
} from "@/lib/feedback";
import { cn } from "@/lib/utils";

type Status = "idle" | "submitting" | "success" | "error";

/**
 * Resolve the submitter's role WITHOUT asking on the form. The role is captured
 * once at site entry (a future onboarding step) and carried forward; this form
 * only reads the prefilled value. Order: an explicit `?role=` link param first
 * (lets a future entry step deep-link a role in), then a `fsi_role` value that
 * step will persist, else "unknown". Kept hidden so submissions are already
 * role-tagged the day the entry step lands — nothing here has to change then.
 */
function resolveRole(param: string | null): FeedbackRole {
  const candidate = param ?? readStoredRole();
  return FEEDBACK_ROLES.includes(candidate as FeedbackRole)
    ? (candidate as FeedbackRole)
    : "unknown";
}

function readStoredRole(): string | null {
  try {
    return window.localStorage.getItem("fsi_role");
  } catch {
    // localStorage can throw in private-mode / blocked-storage browsers.
    return null;
  }
}

export function FeedbackForm() {
  const params = useSearchParams();
  const venueId = params.get("venue") ?? undefined;
  const venueName = params.get("name") ?? undefined;
  // The entry point (footer / how-it-works / restaurant-detail / direct) is
  // recorded even if the user later clears the venue below.
  const source =
    params.get("source") ?? (venueId ? "restaurant-detail" : "site");
  const role = resolveRole(params.get("role"));
  const topics = topicsForRole(role);

  const [message, setMessage] = useState("");
  const [topic, setTopic] = useState<string>(topics[0]);
  // Whether the user detached this feedback from the establishment it opened
  // from (arrived via a listing's "tell us" link, but it's not about that venue).
  const [venueCleared, setVenueCleared] = useState(false);
  // Honeypot state. A real user never sees or fills this; a non-empty value on
  // submit means a bot, and the server (Apps Script) drops the row.
  const [company, setCompany] = useState("");
  const [status, setStatus] = useState<Status>("idle");

  const showVenue = Boolean(venueName) && !venueCleared;
  const enabled = feedbackEnabled();
  const trimmed = message.trim();
  const canSubmit = enabled && trimmed.length > 0 && status !== "submitting";

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setStatus("submitting");
    try {
      await submitFeedback({
        message: trimmed.slice(0, MAX_FEEDBACK_CHARS),
        topic,
        role,
        source,
        // Drop the venue if the user detached it.
        venueId: venueCleared ? undefined : venueId,
        venueName: venueCleared ? undefined : venueName,
        company,
      });
      setStatus("success");
    } catch {
      setStatus("error");
    }
  }

  if (status === "success") {
    return (
      <div
        className="rounded-3xl border border-line bg-card p-8 soft-shadow text-center"
        role="status"
      >
        <span className="inline-flex w-12 h-12 rounded-2xl bg-sage/15 items-center justify-center">
          <CheckCircle2 className="w-6 h-6 text-sage-strong" strokeWidth={1.8} />
        </span>
        <h2 className="text-2xl font-light tracking-tight mt-4">
          Thank you — we&apos;ve got it.
        </h2>
        <p className="text-muted leading-relaxed mt-2 max-w-[46ch] mx-auto">
          Your note has been sent to the team. We read every submission to help
          improve the data and the way it&apos;s shown.
        </p>
        <button
          type="button"
          onClick={() => {
            setMessage("");
            setStatus("idle");
          }}
          className="mt-6 inline-flex items-center gap-2 px-5 py-3 rounded-full bg-ink text-cream text-base font-medium hover:bg-teal transition-colors min-h-[44px]"
        >
          Send another
        </button>
      </div>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-3xl border border-line bg-card p-6 sm:p-8 soft-shadow"
      noValidate
    >
      {showVenue && (
        <div className="mb-5 rounded-2xl bg-tint border border-line px-4 py-3 text-sm flex items-start justify-between gap-3">
          <div>
            <span className="text-2xs tracking-widest uppercase text-muted block mb-0.5">
              About this establishment
            </span>
            <span className="text-ink font-medium">{venueName}</span>
          </div>
          <button
            type="button"
            onClick={() => setVenueCleared(true)}
            className="shrink-0 inline-flex items-center gap-1 text-xs text-muted hover:text-ink rounded-full px-2 py-1 min-h-[32px] hover:bg-card transition-colors"
          >
            <X className="w-3.5 h-3.5" strokeWidth={2} />
            Not about this
          </button>
        </div>
      )}

      <label htmlFor="feedback-topic" className="block">
        <span className="text-sm font-medium text-ink">Topic</span>
      </label>
      <select
        id="feedback-topic"
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        disabled={!enabled || status === "submitting"}
        className="mt-2 mb-5 w-full rounded-2xl border border-line bg-cream/40 px-4 py-3 text-md text-ink outline-none transition-colors focus:border-teal focus:bg-card disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {topics.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      <label htmlFor="feedback-message" className="block">
        <span className="text-sm font-medium text-ink">Your feedback</span>
        <span className="block text-sm text-muted mt-1 leading-relaxed">
          Tell us what&apos;s wrong, confusing, or missing — a data error, a
          listing that looks off, or something we could explain better.
        </span>
      </label>

      <textarea
        id="feedback-message"
        name="message"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        rows={6}
        maxLength={MAX_FEEDBACK_CHARS}
        disabled={!enabled || status === "submitting"}
        placeholder="Share your feedback…"
        aria-describedby="feedback-count feedback-privacy"
        className="mt-3 w-full rounded-2xl border border-line bg-cream/40 px-4 py-3 text-md text-ink leading-relaxed resize-y outline-none transition-colors focus:border-teal focus:bg-card disabled:opacity-60 disabled:cursor-not-allowed"
      />

      {/* Honeypot: hidden from humans (off-screen, not focusable, ignored by
          assistive tech and autofill), so anything typed here is a bot. */}
      <div aria-hidden="true" className="sr-only">
        <label htmlFor="feedback-company">Company (leave blank)</label>
        <input
          id="feedback-company"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        />
      </div>

      <div className="mt-2 flex items-center justify-between gap-3">
        <p id="feedback-privacy" className="text-xs text-muted leading-relaxed">
          Please don&apos;t include personal details — we don&apos;t collect your
          name or email.
        </p>
        <span
          id="feedback-count"
          className="num text-xs text-muted tabular-nums shrink-0"
        >
          {message.length}/{MAX_FEEDBACK_CHARS}
        </span>
      </div>

      {status === "error" && (
        <p
          role="alert"
          className="mt-4 rounded-xl bg-terra/10 border border-terra/30 px-4 py-3 text-sm text-terra-strong"
        >
          Something went wrong sending your feedback. Please check your
          connection and try again.
        </p>
      )}

      {!enabled && (
        <p className="mt-4 rounded-xl bg-tint px-4 py-3 text-sm text-muted">
          Feedback submission isn&apos;t set up in this environment yet.
        </p>
      )}

      <div className="mt-5">
        <button
          type="submit"
          disabled={!canSubmit}
          className={cn(
            "inline-flex items-center gap-2 px-6 py-3 rounded-full text-base font-medium min-h-[44px] transition-colors",
            canSubmit
              ? "bg-ink text-cream hover:bg-teal"
              : "bg-line text-muted cursor-not-allowed",
          )}
        >
          {status === "submitting" ? (
            <>
              <MessageSquare className="w-4 h-4 animate-pulse" strokeWidth={2} />
              Sending…
            </>
          ) : (
            <>
              <Send className="w-4 h-4" strokeWidth={2} />
              Send feedback
            </>
          )}
        </button>
      </div>
    </form>
  );
}
