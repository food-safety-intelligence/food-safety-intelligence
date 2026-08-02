import { describe, expect, it } from "vitest";

import { formatLocationLine } from "./city";

describe("formatLocationLine", () => {
  it("shows a NYC borough beside the city, because it is inside it", () => {
    expect(
      formatLocationLine(
        { address: "1307 Avenue Z", neighborhood: "Brooklyn", zip: "11235" },
        "nyc",
      ),
    ).toBe("1307 Avenue Z · Brooklyn · New York, NY 11235");
  });

  it("uses an LA locality INSTEAD of the city", () => {
    // West Hollywood is a separate incorporated city. Appending it to the fixed
    // "Los Angeles, CA" claimed the venue was somewhere it is not.
    expect(
      formatLocationLine(
        { address: "8500 W Sunset Blvd", neighborhood: "West Hollywood", zip: "90069" },
        "la",
      ),
    ).toBe("8500 W Sunset Blvd · West Hollywood, CA 90069");
  });

  it("does not repeat Los Angeles when the locality IS Los Angeles", () => {
    expect(
      formatLocationLine(
        { address: "7717 Compton Ave", neighborhood: "Los Angeles", zip: "90001" },
        "la",
      ),
    ).toBe("7717 Compton Ave · Los Angeles, CA 90001");
  });

  it("leaves no orphaned separator when a city publishes no neighborhood", () => {
    // Chicago's feed has no usable area column, so neighborhood is always empty.
    expect(
      formatLocationLine(
        { address: "1152 S Wabash Ave", neighborhood: "", zip: "60605" },
        "chicago",
      ),
    ).toBe("1152 S Wabash Ave · Chicago, IL 60605");
  });

  it("falls back to the city name when the locality is missing", () => {
    expect(
      formatLocationLine({ address: "1 Main St", neighborhood: "", zip: "90001" }, "la"),
    ).toBe("1 Main St · Los Angeles, CA 90001");
  });

  it("omits a missing zip without leaving a trailing space", () => {
    expect(
      formatLocationLine({ address: "1 Main St", neighborhood: "", zip: "" }, "chicago"),
    ).toBe("1 Main St · Chicago, IL");
  });

  it("tolerates padded values", () => {
    expect(
      formatLocationLine(
        { address: "  1 Main St  ", neighborhood: "  Queens ", zip: " 11354 " },
        "nyc",
      ),
    ).toBe("1 Main St · Queens · New York, NY 11354");
  });

  it("drops the address when it is missing", () => {
    expect(
      formatLocationLine({ address: "", neighborhood: "Bronx", zip: "10451" }, "nyc"),
    ).toBe("Bronx · New York, NY 10451");
  });
});
