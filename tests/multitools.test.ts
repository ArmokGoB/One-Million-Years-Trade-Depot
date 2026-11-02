// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A system's own multi-tools against tools/captures/multitool_model.py, the
// Python model it ports, over the made-up addresses in
// tests/fixtures/multitool-vectors.json (written by
// tools/crosscheck/multitool_vectors.py). tests/crosscheck.test.ts compares
// the two over thousands more when CROSSCHECK_FILE is set.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  colorName,
  DAY_MS,
  describeSystem,
  distinguishingParts,
  hex64,
  hexColor,
  legacyPalettes,
  MULTITOOL_MODELS,
  multitoolRotation,
  multitoolRun,
  paint,
  paintColors,
  parsePortalCode,
  partsFor,
  rotationDay,
  universalAddress,
  type Multitool,
} from "../src/core";

/** [model file, seed] of each multi-tool, in the game's order. */
type Listed = [string, string][];

interface MultitoolVector {
  code: string;
  galaxy: number;
  run: Listed;
  /** The rotation on this day, in whole days since 1970 UTC. */
  day: number;
  rotation: Listed;
  /** Both made from the planet's address, for an address with a planet digit. */
  planet?: { run: Listed; rotation: Listed };
}

const file = JSON.parse(readFileSync(new URL("./fixtures/multitool-vectors.json", import.meta.url), "utf8")) as {
  vectors: MultitoolVector[];
};

const listed = (tools: Multitool[]): Listed => tools.map((tool) => [MULTITOOL_MODELS[tool.kind], hex64(tool.seed)]);

/** What describeSystem says of each multi-tool. */
const described = (tools: Multitool[]) =>
  tools.map((tool) => {
    const model = MULTITOOL_MODELS[tool.kind];
    // A multi-tool's colors come from its own seed, the older way.
    const passes = paint(model, partsFor(model, tool.seed), tool.seed, legacyPalettes(tool.seed));
    return {
      kind: tool.kind,
      seed: `0x${hex64(tool.seed)}`,
      parts: distinguishingParts(model, tool.seed),
      colors: paintColors(passes).map((color) => ({ hex: hexColor(color), name: colorName(color) })),
    };
  });

/** The universal address of a portal code's planet: the system's, with the planet digit. */
const planetAddress = (code: bigint, galaxy: number) => universalAddress(code, galaxy) | ((code >> 44n) << 52n);

describe("multi-tool vectors from the Python model", () => {
  it("has three systems with each number of standard multi-tools", () => {
    const standard = file.vectors.map((v) => v.run.filter(([name]) => name === "MULTITOOL").length);
    expect(standard).toEqual([2, 2, 2, 3, 3, 3, 4, 4, 4]);
  });

  it("has addresses with planet digits", () => {
    expect(file.vectors.filter((v) => v.planet).length).toBeGreaterThan(0);
  });

  for (const v of file.vectors) {
    it(`${v.code} in galaxy ${v.galaxy}: ${v.run.length} multi-tools, and day ${v.day}'s rotation`, () => {
      const code = parsePortalCode(v.code);
      const ua = universalAddress(code, v.galaxy);
      const run = multitoolRun(ua);
      const rotation = multitoolRotation(ua, v.day);
      expect(listed(run)).toEqual(v.run);
      expect(listed(rotation)).toEqual(v.rotation);
      const description = describeSystem(code, v.galaxy, v.day);
      expect(description.multitools).toEqual(described(run));
      expect(description.rotation).toEqual({ day: v.day, multitools: described(rotation) });
      if (v.planet) {
        const at = planetAddress(code, v.galaxy);
        expect(listed(multitoolRun(at))).toEqual(v.planet.run);
        expect(listed(multitoolRotation(at, v.day))).toEqual(v.planet.rotation);
      }
    });
  }
});

describe("a system's own multi-tools", () => {
  it("end their first run with the royal, the Sentinel and the Atlas one", () => {
    for (const v of file.vectors) {
      const kinds = multitoolRun(universalAddress(parsePortalCode(v.code), v.galaxy)).map((tool) => tool.kind);
      expect(kinds.slice(-3)).toEqual(["Royal", "Sentinel", "Atlas"]);
      expect(new Set(kinds.slice(0, -3))).toEqual(new Set(["Standard"]));
    }
  });

  it("are the system's in the description, whatever the planet digit", () => {
    const at = (code: string) => describeSystem(parsePortalCode(code), 0, 20_000);
    const [planet, system] = [at("509A039BAE4B"), at("009A039BAE4B")];
    expect(planet.multitools).toEqual(system.multitools);
    expect(planet.rotation).toEqual(system.rotation);
  });

  it("are another set when made from a planet's address", () => {
    const code = parsePortalCode("509A039BAE4B");
    expect(multitoolRun(planetAddress(code, 0))).not.toEqual(multitoolRun(universalAddress(code, 0)));
  });

  it("have a rotation that changes with the day", () => {
    const ua = universalAddress(parsePortalCode("009A039BAE4B"), 0);
    expect(multitoolRotation(ua, 20_718)).not.toEqual(multitoolRotation(ua, 20_717));
    expect(multitoolRotation(ua, 20_717).map((tool) => tool.kind)).toEqual(["Standard", "Standard", "Standard"]);
  });
});

describe("the rotation's day", () => {
  it("counts whole days since 1970 UTC", () => {
    expect(rotationDay(0)).toBe(0);
    expect(rotationDay(DAY_MS - 1)).toBe(0);
    expect(rotationDay(DAY_MS)).toBe(1);
    expect(rotationDay(Date.UTC(2026, 10, 2))).toBe(20_759);
    expect(rotationDay(Date.UTC(2026, 10, 2, 23, 59, 59, 999))).toBe(20_759);
  });
});
