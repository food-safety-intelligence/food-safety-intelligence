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

interface ChatScopeValue {
  current: ChatEstablishment | null;
  setCurrent: (establishment: ChatEstablishment | null) => void;
}

const ChatScopeContext = createContext<ChatScopeValue | null>(null);

/**
 * Shares "the establishment the user is currently looking at" between the
 * restaurant detail page (which sets it) and the site-wide floating chat (which
 * scopes questions to it). Wraps both the page tree and the FloatingChat in the
 * root layout so they read the same value.
 */
export function ChatScopeProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<ChatEstablishment | null>(null);
  return (
    <ChatScopeContext.Provider value={{ current, setCurrent }}>
      {children}
    </ChatScopeContext.Provider>
  );
}

export function useChatScope(): ChatScopeValue {
  const ctx = useContext(ChatScopeContext);
  // Consumers always render inside the provider (it wraps the whole layout), but
  // fall back to a no-op rather than throw so an out-of-tree mount degrades to
  // "no scope" instead of crashing the page.
  return ctx ?? { current: null, setCurrent: () => {} };
}
