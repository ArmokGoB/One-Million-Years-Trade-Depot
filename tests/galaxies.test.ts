// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { GALAXY_COUNT, GALAXY_NAMES, galaxyLabel, galaxyName } from "../src/core";

describe("galaxy names", () => {
  it("names every galaxy once", () => {
    expect(GALAXY_NAMES).toHaveLength(GALAXY_COUNT);
    expect(new Set(GALAXY_NAMES).size).toBe(GALAXY_COUNT);
    for (const name of GALAXY_NAMES) expect(name).toMatch(/^[A-Z][A-Za-z' ]*[a-z]$/);
  });
  it("starts with Euclid and ends with Odyalutai", () => {
    expect(galaxyName(0)).toBe("Euclid");
    expect(galaxyName(1)).toBe("Hilbert Dimension");
    expect(galaxyName(9)).toBe("Eissentam");
    expect(galaxyName(254)).toBe("Iousongola");
    expect(galaxyName(255)).toBe("Odyalutai");
    expect(() => galaxyName(256)).toThrow(RangeError);
    expect(() => galaxyName(-1)).toThrow(RangeError);
  });
  it("labels galaxies as players number them", () => {
    expect(galaxyLabel(0)).toBe("Galaxy 1: Euclid");
    expect(galaxyLabel(1)).toBe("Galaxy 2: Hilbert Dimension");
    expect(galaxyLabel(2)).toBe("Galaxy 3: Calypso");
    expect(galaxyLabel(255)).toBe("Galaxy 256: Odyalutai");
  });
});
