// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Replays nms_namegen's 443 golden vectors (MIT; see THIRD_PARTY_NOTICES.md)
// through the TypeScript port. Every field must match bit for bit.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  hex64,
  parsePortalCode,
  planetName,
  planetSeeds,
  regionName,
  systemAttributes,
  systemName,
  voxelAttributes,
} from "../src/core";

interface GoldenVector {
  code: string;
  galaxy: number;
  region: string;
  system: string;
  planet: string;
  sysattr: Record<string, number | boolean>;
  seeds: string[];
  planet_count: number;
  moon_count: number;
  sizes: number[];
  voxel: Record<string, number>;
}

const file = JSON.parse(readFileSync(new URL("./fixtures/golden-vectors.json", import.meta.url), "utf8")) as {
  vectors: GoldenVector[];
};

describe("golden vectors from nms_namegen", () => {
  it("has all 443 vectors", () => {
    expect(file.vectors).toHaveLength(443);
  });

  for (const v of file.vectors) {
    it(`${v.code} in galaxy ${v.galaxy}`, () => {
      const code = parsePortalCode(v.code);
      expect(regionName(code, v.galaxy)).toBe(v.region);
      expect(systemName(code, v.galaxy)).toBe(v.system);
      if (v.planet.startsWith("ERR:")) {
        expect(() => planetName(code, v.galaxy)).toThrow();
      } else {
        expect(planetName(code, v.galaxy)).toBe(v.planet);
      }
      expect(systemAttributes(code, v.galaxy)).toEqual(v.sysattr);

      const seeds = planetSeeds(code, v.galaxy);
      expect(seeds.planet_seeds.map(hex64)).toEqual(v.seeds);
      expect(seeds.planet_count).toBe(v.planet_count);
      expect(seeds.moon_count).toBe(v.moon_count);
      expect(seeds.sizes).toEqual(v.sizes);

      expect(voxelAttributes(code)).toEqual(v.voxel);
    });
  }
});
