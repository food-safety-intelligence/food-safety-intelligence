"use client";

import { useEffect } from "react";
import { useChatScope } from "@/components/ChatScopeContext";

/**
 * Registers the establishment whose detail page is mounted into the chat scope,
 * so the floating chat can scope questions to it ("this restaurant"). Clears the
 * scope on unmount, so navigating away returns the chat to general mode and
 * navigating between two detail pages swaps the scope to the new one. Renders
 * nothing — it's a side-effect-only bridge from the server page to the client
 * chat context.
 */
export function RegisterChatEstablishment({
  licenseId,
  name,
}: {
  licenseId: string;
  name: string;
}) {
  const { setCurrent } = useChatScope();
  useEffect(() => {
    setCurrent({ licenseId, name });
    return () => setCurrent(null);
  }, [licenseId, name, setCurrent]);
  return null;
}
