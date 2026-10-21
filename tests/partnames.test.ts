// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Named parts against tools/captures/part_names_model.py, the Python model
// they port, over the made-up seeds in tests/fixtures/part-names-vectors.json
// (written by tools/crosscheck/part_names_vectors.py).

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { NAMED_MODELS, namedParts, partsFor, type PartModel, type Side } from "../src/core";

interface NamesVector {
  model: PartModel;
  seed: string;
  names: [Side, string, string[]][];
}

const file = JSON.parse(readFileSync(new URL("./fixtures/part-names-vectors.json", import.meta.url), "utf8")) as {
  vectors: NamesVector[];
};

describe("part name vectors from the Python model", () => {
  it("cover every ship type the game names parts of", () => {
    expect([...new Set(file.vectors.map((v) => v.model))]).toEqual(NAMED_MODELS);
    expect(NAMED_MODELS).toEqual(["FIGHTER_PROC", "DROPSHIP_PROC", "SCIENTIFIC_PROC", "SAILSHIP_PROC"]);
  });

  for (const v of file.vectors) {
    it(`${v.model} with seed ${v.seed}`, () => {
      const got = namedParts(v.model, BigInt(`0x${v.seed}`)).map((n) => [n.side, n.name, n.parts]);
      expect(got).toEqual(v.names);
    });
  }
});

describe("named parts", () => {
  it("name every slot of a fighter, explorer and solar, and of a hauler but for one wing the game leaves unnamed", () => {
    for (const v of file.vectors) {
      expect(v.names.length, `${v.model} ${v.seed}`).toBe(v.model === "DROPSHIP_PROC" ? v.names.length : 3);
    }
    const haulers = file.vectors.filter((v) => v.model === "DROPSHIP_PROC");
    expect(haulers.filter((v) => v.names.length === 2)).toHaveLength(1);
    expect(haulers.filter((v) => v.names.length === 3)).toHaveLength(haulers.length - 1);
  });

  it("are made of the ship's own parts", () => {
    for (const v of file.vectors) {
      const parts = partsFor(v.model, BigInt(`0x${v.seed}`));
      for (const [, name, made] of v.names) {
        expect(made.length, `${v.model} ${v.seed} ${name}`).toBeGreaterThan(0);
        for (const part of made) expect(parts, `${v.model} ${v.seed} ${name}`).toContain(part);
      }
    }
  });

  it("give an explorer with a matched pair of wings the same wing on both sides", () => {
    const paired = file.vectors.filter(
      (v) => v.model === "SCIENTIFIC_PROC" && partsFor(v.model, BigInt(`0x${v.seed}`)).some((p) => /^_WINGS_SYM1?$/.test(p)),
    );
    expect(paired.length).toBeGreaterThanOrEqual(2);
    for (const v of paired) {
      const [, left, right] = v.names;
      expect(left![0]).toBe("left");
      expect(right![0]).toBe("right");
      expect(right![1]).toBe(left![1]);
    }
  });

  it("are none for a model the game doesn't name parts of", () => {
    for (const model of ["SHUTTLE_PROC", "S-CLASS_PROC", "SENTINELSHIP_PROC", "FREIGHTER_PROC", "MULTITOOL"] as const) {
      expect(namedParts(model, 0x0123456789abcdefn)).toEqual([]);
    }
  });
});
