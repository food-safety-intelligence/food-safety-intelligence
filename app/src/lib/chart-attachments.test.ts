import { describe, it, expect } from "vitest";
import {
  parseChartAttachments,
  mockChartMessageContent,
} from "./chart-attachments";

function block(obj: Record<string, unknown>): string {
  return ["```eatelligence-chart", JSON.stringify(obj), "```"].join("\n");
}

describe("parseChartAttachments", () => {
  it("returns text unchanged and no attachments when there is no block", () => {
    const { text, attachments } = parseChartAttachments("just a normal answer");
    expect(text).toBe("just a normal answer");
    expect(attachments).toEqual([]);
  });

  it("extracts a valid chart block and strips it from the text", () => {
    const content = [
      "Here is the chart.",
      block({ id: "c1", title: "Tiers", img: "https://cdn.example/c1.png", script: "https://cdn.example/c1.py" }),
      "Open the script to see how.",
    ].join("\n");

    const { text, attachments } = parseChartAttachments(content);
    expect(text).toBe("Here is the chart.\nOpen the script to see how.");
    expect(attachments).toHaveLength(1);
    expect(attachments[0]).toMatchObject({
      id: "c1",
      title: "Tiers",
      imageUrl: "https://cdn.example/c1.png",
      scriptUrl: "https://cdn.example/c1.py",
      language: "python",
    });
  });

  it("accepts an inline data-URL image and inline script text", () => {
    const content = block({
      id: "c2",
      title: "Inline",
      img: "data:image/svg+xml;utf8,<svg/>",
      scriptText: "print('hi')",
    });
    const { attachments } = parseChartAttachments(content);
    expect(attachments).toHaveLength(1);
    expect(attachments[0].imageUrl).toContain("data:image/svg+xml");
    expect(attachments[0].scriptText).toBe("print('hi')");
    expect(attachments[0].scriptUrl).toBeUndefined();
  });

  it("drops a block with malformed JSON without leaking raw JSON into the text", () => {
    const content = ["Before", "```eatelligence-chart", "{ not json ", "```", "After"].join("\n");
    const { text, attachments } = parseChartAttachments(content);
    expect(attachments).toEqual([]);
    expect(text).toBe("Before\nAfter");
    expect(text).not.toContain("not json");
  });

  it("rejects an unsafe image scheme", () => {
    const content = block({ id: "x", title: "bad", img: "javascript:alert(1)" });
    const { attachments } = parseChartAttachments(content);
    expect(attachments).toEqual([]);
  });

  it("rejects an unsafe (non-https, non-relative) script url but keeps the chart", () => {
    const content = block({
      id: "x",
      title: "ok",
      img: "https://cdn.example/x.png",
      script: "http://insecure.example/x.py",
    });
    const { attachments } = parseChartAttachments(content);
    expect(attachments).toHaveLength(1);
    expect(attachments[0].scriptUrl).toBeUndefined();
  });

  it("assigns a fallback id when missing or duplicated", () => {
    const content = [
      block({ img: "https://cdn.example/a.png" }),
      block({ id: "dup", img: "https://cdn.example/b.png" }),
      block({ id: "dup", img: "https://cdn.example/c.png" }),
    ].join("\n\n");
    const { attachments } = parseChartAttachments(content);
    expect(attachments).toHaveLength(3);
    const ids = attachments.map((a) => a.id);
    expect(new Set(ids).size).toBe(3);
    expect(attachments[0].title).toBe("Chart"); // default title
  });

  it("keeps ids unique when an explicit id collides with a fallback", () => {
    const content = [
      block({ id: "chart-2", img: "https://cdn.example/a.png" }),
      block({ img: "https://cdn.example/b.png" }), // no id → fallback would be chart-2 without the loop
    ].join("\n\n");
    const { attachments } = parseChartAttachments(content);
    expect(attachments).toHaveLength(2);
    expect(new Set(attachments.map((a) => a.id)).size).toBe(2);
  });

  it("parses the dev mock into two distinct attachments", () => {
    const { text, attachments } = parseChartAttachments(mockChartMessageContent());
    expect(attachments).toHaveLength(2);
    expect(attachments.map((a) => a.id)).toEqual(["demo-tiers", "demo-trend"]);
    expect(attachments.every((a) => a.imageUrl.includes("data:image/svg+xml"))).toBe(true);
    expect(attachments.every((a) => (a.scriptText ?? "").includes("matplotlib"))).toBe(true);
    expect(text).not.toContain("eatelligence-chart");
  });
});
