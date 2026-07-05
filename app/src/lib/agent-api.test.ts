import { describe, expect, it } from "vitest";

import {
  buildWireQuery,
  scopedInputBudget,
  taggedWireQuery,
  type AgentEstablishment,
} from "@/lib/agent-api";

const AMARIT: AgentEstablishment = {
  licenseId: "1234567",
  name: "AMARIT RESTAURANT",
};

describe("buildWireQuery", () => {
  it("returns the query unchanged when no establishment is in scope", () => {
    expect(buildWireQuery("how common is food poisoning?")).toBe(
      "how common is food poisoning?",
    );
  });

  it("prepends a context tag naming the establishment and its license_id", () => {
    const wire = buildWireQuery("tell me about this restaurant", AMARIT);
    expect(wire).toContain("AMARIT RESTAURANT");
    expect(wire).toContain("license_id 1234567");
    // The user's own text is preserved, after the tag.
    expect(wire.endsWith("tell me about this restaurant")).toBe(true);
    expect(wire.indexOf("AMARIT")).toBeLessThan(wire.indexOf("this restaurant"));
  });

  it("tells the model that deictic references resolve to the establishment", () => {
    const wire = buildWireQuery("is it safe?", AMARIT);
    expect(wire).toContain('"this restaurant"');
    expect(wire).toContain('"it"');
  });

  it("caps a very long establishment name so the tag can't blow the budget", () => {
    const longName = "X".repeat(500);
    const wire = buildWireQuery("hi", { licenseId: "9", name: longName });
    // Name is truncated to 80 chars inside the tag.
    expect(wire).toContain("X".repeat(80));
    expect(wire).not.toContain("X".repeat(81));
  });
});

describe("scopedInputBudget", () => {
  it("leaves room for the user's text within the 500-char wire limit", () => {
    const budget = scopedInputBudget(AMARIT);
    expect(budget).toBeGreaterThan(0);
    // A user message exactly at the budget must keep the whole wire query <= 500.
    const wire = buildWireQuery("y".repeat(budget), AMARIT);
    expect(wire.length).toBeLessThanOrEqual(500);
  });

  it("never returns a negative budget, even for an absurd name", () => {
    expect(scopedInputBudget({ licenseId: "9", name: "Z".repeat(10_000) })).toBeGreaterThanOrEqual(0);
  });
});

describe("taggedWireQuery", () => {
  it("returns the plain query for Chicago with no persona or establishment", () => {
    expect(taggedWireQuery("safe sushi near Wicker Park", "chicago")).toBe(
      "safe sushi near Wicker Park",
    );
  });

  it("prepends a city marker for a non-Chicago city", () => {
    const wire = taggedWireQuery("safe sushi", "nyc");
    expect(wire).toBe("[[city:nyc]]safe sushi");
  });

  it("prepends a persona marker after the city marker", () => {
    const wire = taggedWireQuery("worklist for Logan Square", "chicago", "inspector");
    expect(wire).toBe("[[persona:inspector]]worklist for Logan Square");
  });

  it("orders city marker before persona marker before the establishment tag", () => {
    const wire = taggedWireQuery("is it safe?", "nyc", "caregiver", AMARIT);
    const cityIdx = wire.indexOf("[[city:nyc]]");
    const personaIdx = wire.indexOf("[[persona:caregiver]]");
    const tagIdx = wire.indexOf("AMARIT RESTAURANT");
    expect(cityIdx).toBe(0);
    expect(cityIdx).toBeLessThan(personaIdx);
    expect(personaIdx).toBeLessThan(tagIdx);
    expect(wire.endsWith("is it safe?")).toBe(true);
  });

  it("omits both markers for the default chicago, no-persona case even with an establishment", () => {
    const wire = taggedWireQuery("tell me about this restaurant", "chicago", undefined, AMARIT);
    expect(wire).not.toContain("[[city:");
    expect(wire).not.toContain("[[persona:");
    expect(wire.startsWith('(The user is viewing')).toBe(true);
  });
});
