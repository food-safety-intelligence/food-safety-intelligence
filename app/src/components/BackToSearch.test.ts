import { describe, expect, it } from "vitest";

import { backToSearchHref } from "@/components/BackToSearch";

describe("backToSearchHref", () => {
  it("returns the bare home for Chicago (the default city)", () => {
    expect(backToSearchHref("chicago")).toBe("/");
  });

  it("carries the city param for NYC so a back-link stays in NYC", () => {
    expect(backToSearchHref("nyc")).toBe("/?city=nyc");
  });

  it("carries the city param for LA so a back-link stays in LA", () => {
    expect(backToSearchHref("la")).toBe("/?city=la");
  });
});
