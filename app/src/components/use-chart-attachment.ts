"use client";

import { useCallback, useState } from "react";
import type { ChartAttachment } from "@/lib/chart-attachments";

export type ChartView = "image" | "script";

function downloadSlug(title: string): string {
  const s = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || "chart";
}

/**
 * Shared state + actions for a chart attachment: the image/script view toggle,
 * lazy script fetch, download-as-PNG, and copy-to-clipboard. Used by both the
 * inline `ChartCard` and the enlarged `ChartImageModal` so the two never drift.
 */
export function useChartAttachment(attachment: ChartAttachment) {
  const { title, imageUrl, scriptUrl, scriptText: inlineScript } = attachment;

  const [view, setView] = useState<ChartView>("image");
  const [copied, setCopied] = useState(false);
  const [script, setScript] = useState<string | null>(inlineScript ?? null);
  const [scriptError, setScriptError] = useState(false);
  const [loadingScript, setLoadingScript] = useState(false);

  // Fetch the script text once, the first time it's needed (view flip or copy).
  const ensureScript = useCallback(async (): Promise<string | null> => {
    if (script !== null) return script;
    if (!scriptUrl) return null;
    setLoadingScript(true);
    try {
      const res = await fetch(scriptUrl);
      if (!res.ok) throw new Error(String(res.status));
      const text = await res.text();
      setScript(text);
      setScriptError(false);
      return text;
    } catch {
      setScriptError(true);
      return null;
    } finally {
      setLoadingScript(false);
    }
  }, [script, scriptUrl]);

  // Flip to the script view, fetching the text on first open (click-driven, no effect).
  const showScript = useCallback(() => {
    setView("script");
    void ensureScript();
  }, [ensureScript]);

  const showImage = useCallback(() => setView("image"), []);

  const handleDownload = useCallback(async () => {
    try {
      const res = await fetch(imageUrl);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${downloadSlug(title)}.png`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      // Cross-origin quirks can block a programmatic download; open it instead —
      // but only a real http(s) URL, never top-level-navigate a data: URL (an SVG
      // data document could run script).
      if (/^https?:\/\//i.test(imageUrl)) {
        window.open(imageUrl, "_blank", "noopener,noreferrer");
      }
    }
  }, [imageUrl, title]);

  const handleCopy = useCallback(async () => {
    const text = await ensureScript();
    if (text === null) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked (permissions / insecure context): leave state unchanged.
    }
  }, [ensureScript]);

  return {
    view,
    showImage,
    showScript,
    script,
    scriptError,
    loadingScript,
    copied,
    handleDownload,
    handleCopy,
  };
}
