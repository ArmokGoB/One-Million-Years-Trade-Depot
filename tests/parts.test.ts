// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Parts against tools/captures/parts_model.py, the Python model they port,
// over the made-up seeds in tests/fixtures/parts-vectors.json (written by
// tools/crosscheck/parts_vectors.py).

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { distinguishingParts, exoticSquid, PART_MODELS, partsFor, type PartModel } from "../src/core";

interface PartsVector {
  model: PartModel;
  seed: string;
  parts: string[];
}

const file = JSON.parse(readFileSync(new URL("./fixtures/parts-vectors.json", import.meta.url), "utf8")) as {
  vectors: PartsVector[];
};

describe("parts vectors from the Python model", () => {
  it("cover every model, four seeds each", () => {
    expect(file.vectors.map((v) => v.model)).toEqual(PART_MODELS.flatMap((model) => [model, model, model, model]));
  });

  for (const v of file.vectors) {
    it(`${v.model} with seed ${v.seed}`, () => {
      expect(partsFor(v.model, BigInt(`0x${v.seed}`))).toEqual(v.parts);
    });
  }
});

describe("parts", () => {
  it("of an exotic start with its body, a squid's where the squid rule says so", () => {
    const exotics = file.vectors.filter((v) => v.model === "S-CLASS_PROC");
    expect(exotics.some((v) => v.parts[0] === "_SCLASSSHIP_SQU")).toBe(true);
    for (const v of exotics) {
      expect(v.parts[0] === "_SCLASSSHIP_SQU").toBe(exoticSquid(BigInt(`0x${v.seed}`)));
    }
  });

  it("that tell a model apart are those picked from lists with more than one option", () => {
    for (const v of file.vectors) {
      // Some of the parts, in the same order.
      let at = 0;
      for (const part of distinguishingParts(v.model, BigInt(`0x${v.seed}`))) {
        at = v.parts.indexOf(part, at);
        expect(at, `${v.model} ${v.seed} ${part}`).toBeGreaterThanOrEqual(0);
        at += 1;
      }
    }
    // A royal multi-tool's lists have one option each, so royal multi-tools all have the same parts.
    expect(distinguishingParts("ROYALMULTITOOL", 1n)).toEqual([]);
    expect(partsFor("ROYALMULTITOOL", 1n)).toHaveLength(4);
    // An exotic's cockpit and landing gear are the only ones of their lists; its body and wings vary.
    const exotic = file.vectors.find((v) => v.model === "S-CLASS_PROC" && v.parts[0] === "_SCLASSSHIP_ROY")!;
    const parts = distinguishingParts("S-CLASS_PROC", BigInt(`0x${exotic.seed}`));
    expect(parts[0]).toBe("_SCLASSSHIP_ROY");
    expect(parts).not.toContain("_COCKPIT_A");
    expect(parts).not.toContain("_LANDINGGEAR_A");
  });

  it("are the same every time for the same seed", () => {
    const seed = 0x0123456789abcdefn;
    for (const model of PART_MODELS) expect(partsFor(model, seed)).toEqual(partsFor(model, seed));
  });
});
