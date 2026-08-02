"use client";

import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { useChatScope } from "@/components/ChatScopeContext";

/**
 * Footer "Give feedback" link. On an establishment detail page the chat scope
 * holds the venue in view (set by RegisterChatEstablishment), so the link
 * defaults to feedback ABOUT that venue — the same as the "something look wrong?"
 * link, and the form still lets the user clear the venue. Everywhere else the
 * scope is empty and the link is generic. `source=footer` is kept either way so
 * the entry point is recorded.
 */
export function FeedbackFooterLink() {
  const { current } = useChatScope();
  const href = current
    ? `/feedback?source=footer&venue=${encodeURIComponent(
        current.licenseId,
      )}&name=${encodeURIComponent(current.name)}`
    : "/feedback?source=footer";
  return (
    <Link
      href={href}
      className="mt-3 inline-flex items-center gap-1.5 text-teal hover:underline"
    >
      <MessageSquarePlus className="w-4 h-4" strokeWidth={2} />
      Give feedback
    </Link>
  );
}
