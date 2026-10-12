// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import {
  AddressError,
  formatPortalCode,
  parseAnyAddress,
  parseGalacticCoordinates,
  parseGalaxyNumber,
  parsePortalCode,
  portalParts,
  toGalacticCoordinates,
  withPlanet,
} from "../src/core";

describe("portal codes", () => {
  it("parses and formats 12 hex digits", () => {
    const code = parsePortalCode("004a 03c0 0a5c");
    expect(formatPortalCode(code)).toBe("004A03C00A5C");
    expect(portalParts(code)).toEqual({ planet: 0, system: 0x04a, y: 0x03, z: 0xc00, x: 0xa5c });
  });

  it("rejects anything that is not 12 hex digits", () => {
    expect(() => parsePortalCode("004A03C00A5")).toThrow(AddressError);
    expect(() => parsePortalCode("004A03C00A5G")).toThrow(AddressError);
  });

  it("swaps the planet digit", () => {
    expect(formatPortalCode(withPlanet(parsePortalCode("004A03C00A5C"), 3))).toBe("304A03C00A5C");
    expect(formatPortalCode(withPlanet(parsePortalCode("304A03C00A5C"), 0))).toBe("004A03C00A5C");
  });
});

describe("signal-booster galactic coordinates", () => {
  // Known pair: a ship location posted as 025B:0082:03FF:004A, whose portal
  // address is 004A03C00A5C.
  it("converts to the portal frame", () => {
    expect(formatPortalCode(parseGalacticCoordinates("025B:0082:03FF:004A"))).toBe("004A03C00A5C");
    expect(formatPortalCode(parseGalacticCoordinates("HUKYA:025B:0082:03FF:004A"))).toBe("004A03C00A5C");
  });

  it("converts back", () => {
    expect(toGalacticCoordinates(parsePortalCode("004A03C00A5C"))).toBe("025B:0082:03FF:004A");
  });

  it("round-trips every corner of the range", () => {
    for (const s of ["0000:0000:0000:0000", "0FFF:00FF:0FFF:0FFF", "07FF:007F:07FF:0079", "0800:0080:0800:0001"]) {
      expect(toGalacticCoordinates(parseGalacticCoordinates(s))).toBe(s);
    }
  });

  // The Pilgrim Star, which the site shows until a visitor looks up another system.
  it("agrees on the Pilgrim Star", () => {
    expect(formatPortalCode(parseGalacticCoordinates("064A:0082:01B9:009A"))).toBe("009A039BAE4B");
    expect(toGalacticCoordinates(parsePortalCode("009A039BAE4B"))).toBe("064A:0082:01B9:009A");
  });

  it("is picked automatically by parseAnyAddress", () => {
    expect(formatPortalCode(parseAnyAddress("025B:0082:03FF:004A"))).toBe("004A03C00A5C");
    expect(formatPortalCode(parseAnyAddress("004A03C00A5C"))).toBe("004A03C00A5C");
  });
});

describe("galaxy numbers", () => {
  it("numbers galaxies from 1 to 256, as players do, and gives the game's index, from 0", () => {
    expect(parseGalaxyNumber("1")).toBe(0);
    expect(parseGalaxyNumber(" 2 ")).toBe(1);
    expect(parseGalaxyNumber(256)).toBe(255);
  });
  it("says there are only 256 galaxies of a number past the last", () => {
    expect(() => parseGalaxyNumber("257")).toThrow(/only 256 galaxies/);
    expect(() => parseGalaxyNumber("100000")).toThrow(AddressError);
  });
  it("turns down anything else", () => {
    for (const input of ["0", "-1", "1.5", "", "two", "0x10", "1e2"]) {
      expect(() => parseGalaxyNumber(input), input).toThrow(/^Galaxy is a number from 1 \(Euclid\) to 256\.$/);
    }
  });
});
