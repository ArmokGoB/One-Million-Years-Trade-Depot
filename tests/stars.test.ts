// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The star count against tools/captures/star_model.py, the Python model it
// ports, over the made-up addresses in tests/fixtures/star-vectors.json
// (written by tools/crosscheck/star_vectors.py). tests/crosscheck.test.ts
// compares the two over thousands more when CROSSCHECK_FILE is set.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  describeSystem,
  nebulaSeed,
  parsePortalCode,
  STAR_CHANCES,
  starCount,
  starsFromNebula,
  universalAddress,
  withPlanet,
} from "../src/core";

interface StarVector {
  code: string;
  galaxy: number;
  /** The bits of the system's NebulaSeed in single precision, in hex. */
  nebulaSeed: string;
  stars: number;
}

const file = JSON.parse(readFileSync(new URL("./fixtures/star-vectors.json", import.meta.url), "utf8")) as {
  vectors: StarVector[];
};

/** The bits of a number held in single precision. */
function float32Bits(value: number): string {
  const view = new DataView(new ArrayBuffer(4));
  view.setFloat32(0, value);
  return view.getUint32(0).toString(16).toUpperCase().padStart(8, "0");
}

/** The next number up that single precision can hold. */
function nextFloat32(value: number): number {
  const view = new DataView(new ArrayBuffer(4));
  view.setFloat32(0, value);
  view.setUint32(0, view.getUint32(0) + 1);
  return view.getFloat32(0);
}

describe("star count vectors from the Python model", () => {
  it("has four systems with each count", () => {
    expect(file.vectors.map((v) => v.stars)).toEqual([1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3]);
  });

  for (const v of file.vectors) {
    it(`${v.code} in galaxy ${v.galaxy}: ${v.stars}`, () => {
      const code = parsePortalCode(v.code);
      const ua = universalAddress(code, v.galaxy);
      expect(float32Bits(nebulaSeed(ua))).toBe(v.nebulaSeed);
      expect(starCount(ua)).toBe(v.stars);
      expect(describeSystem(code, v.galaxy).stars).toBe(v.stars);
    });
  }
});

describe("star count", () => {
  it("uses the game's chances, in single precision", () => {
    expect(STAR_CHANCES.binary).toBe(Math.fround(0.2));
    expect(STAR_CHANCES.ternary).toBe(Math.fround(0.05));
  });

  it("counts a star only when NebulaSeed is strictly above 1 minus its chance, worked out in single precision", () => {
    const second = Math.fround(1 - STAR_CHANCES.binary);
    const third = Math.fround(1 - STAR_CHANCES.ternary);
    expect([second, third]).toEqual([0.800000011920929, 0.949999988079071]);
    expect(starsFromNebula(0)).toBe(1);
    expect(starsFromNebula(second)).toBe(1);
    expect(starsFromNebula(nextFloat32(second))).toBe(2);
    expect(starsFromNebula(third)).toBe(2);
    expect(starsFromNebula(nextFloat32(third))).toBe(3);
    expect(starsFromNebula(1)).toBe(3);
  });

  it("is the system's, whatever the planet digit", () => {
    const v = file.vectors.find((v) => v.stars === 3)!;
    const code = parsePortalCode(v.code);
    for (const planet of [0, 1, 6, 15]) {
      expect(describeSystem(withPlanet(code, planet), v.galaxy).stars).toBe(3);
    }
  });
});
