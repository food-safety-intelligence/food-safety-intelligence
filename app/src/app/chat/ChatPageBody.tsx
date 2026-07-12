"use client";

import { useSearchParams } from "next/navigation";
import { ChatInterface } from "@/components/ChatInterface";
import type { ChatPersona } from "@/components/ChatScopeContext";

// The persona (inspector / caregiver) rides in on `?persona=` when the user
// maximizes the floating chat from the For Inspectors / Caregivers page — see
// FloatingChat. Read it here rather than from ChatScopeContext, whose persona is
// cleared once those pages unmount on navigation. Anything unexpected falls back
// to the generic, unscoped chat.
function toPersona(value: string | null): ChatPersona | undefined {
  return value === "inspector" || value === "caregiver" ? value : undefined;
}

export function ChatPageBody() {
  const persona = toPersona(useSearchParams().get("persona"));
  return <ChatInterface persona={persona} />;
}
