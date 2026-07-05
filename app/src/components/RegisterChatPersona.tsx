"use client";

import { useEffect } from "react";
import { useChatScope, type ChatPersona } from "@/components/ChatScopeContext";

/**
 * Registers the audience the chat was opened for into the chat scope, so the
 * floating chat can default to that audience's framing and starter chips
 * (see ChatInterface) without the user having to say "I'm an inspector" or
 * "this is for someone immunocompromised". Clears the persona on unmount, so
 * navigating away returns the chat to the default, unscoped mode. Mirrors
 * RegisterChatEstablishment; renders nothing.
 */
export function RegisterChatPersona({ persona }: { persona: ChatPersona }) {
  const { setPersona } = useChatScope();
  useEffect(() => {
    setPersona(persona);
    return () => setPersona(null);
  }, [persona, setPersona]);
  return null;
}
