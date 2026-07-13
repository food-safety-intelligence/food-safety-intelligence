import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Pure-logic unit tests (geometry, score/tier helpers). No DOM is needed — the
// components' rendering is exercised by hand in dev; what we lock down here is
// the math that silently regressed (the gauge arc-flag bug) or could go NaN.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  // Match the app's automatic JSX runtime so importing a .tsx module (for its
  // exported pure helpers) transforms the same way Next builds it.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "node",
    // Match both .test.ts and .test.tsx so a .tsx test is actually picked up —
    // the .ts-only glob silently skipped them. (A test that renders a component
    // into the DOM would also need environment: "jsdom"; the node env here still
    // runs .tsx files that only exercise pure logic.)
    // scripts/ are plain-Node build helpers (.mjs) — their pure logic
    // (violation tagging, index generation) is tested here too.
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs"],
  },
});
