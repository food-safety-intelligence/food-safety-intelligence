"use client";

import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";

/** The establishment whose detail page is currently in view, if any. */
export interface ChatEstablishment {
  /** license_id — also the detail-page route param and the explain_restaurant key. */
  licenseId: string;
  /** dba_name, for the scope chip and the context tag sent to the agent. */
  name: string;
}

/**
 * Audience the chat was opened for — set by the For Inspectors / For
 * Caregivers pages (see RegisterChatPersona) while they're in view. The
 * UI-facing twin of agent-api's AgentPersona; kept separate so agent-api.ts
 * doesn't need to import UI context types (same split as ChatEstablishment /
 * AgentEstablishment).
 */
export type ChatPersona = "inspector" | "caregiver";

interface ChatScopeValue {
  current: ChatEstablishment | null;
  setCurrent: (establishment: ChatEstablishment | null) => void;
  persona: ChatPersona | null;
  setPersona: (persona: ChatPersona | null) => void;
}

const ChatScopeContext = createContext<ChatScopeValue | null>(null);

/**
 * Shares "the establishment the user is currently looking at" and "the
 * audience the chat was opened for" between the pages that set them (the
 * restaurant detail page; the For Inspectors / For Caregivers pages) and the
 * site-wide floating chat, which reads both to scope questions and pick
 * starter chips. Wraps both the page tree and the FloatingChat in the root
 * layout so they read the same value.
 */
export function ChatScopeProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<ChatEstablishment | null>(null);
  const [persona, setPersona] = useState<ChatPersona | null>(null);
  return (
    <ChatScopeContext.Provider value={{ current, setCurrent, persona, setPersona }}>
      {children}
    </ChatScopeContext.Provider>
  );
}

export function useChatScope(): ChatScopeValue {
  const ctx = useContext(ChatScopeContext);
  // Consumers always render inside the provider (it wraps the whole layout), but
  // fall back to a no-op rather than throw so an out-of-tree mount degrades to
  // "no scope" instead of crashing the page.
  return ctx ?? { current: null, setCurrent: () => {}, persona: null, setPersona: () => {} };
}
