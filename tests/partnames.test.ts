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

/** The ship types whose parts the game names: those its Starship Fabricator builds. */
const FABRICATOR = ["FIGHTER_PROC", "DROPSHIP_PROC", "SCIENTIFIC_PROC", "SAILSHIP_PROC"];
const fabricator = file.vectors.filter((v) => FABRICATOR.includes(v.model));
const community = file.vectors.filter((v) => !FABRICATOR.includes(v.model));

describe("part name vectors from the Python model", () => {
  it("cover every model whose parts have names", () => {
    expect([...new Set(file.vectors.map((v) => v.model))]).toEqual(NAMED_MODELS);
    expect(NAMED_MODELS).toEqual([
      ...FABRICATOR,
      "SHUTTLE_PROC",
      "S-CLASS_PROC",
      "SENTINELSHIP_PROC",
      "FREIGHTER_PROC",
      "CAPITALFREIGHTER_PROC",
    ]);
  });

  for (const v of file.vectors) {
    it(`${v.model} with seed ${v.seed}`, () => {
      const got = namedParts(v.model, BigInt(`0x${v.seed}`)).map((n) => [n.side, n.name, n.parts]);
      expect(got).toEqual(v.names);
    });
  }
});

describe("named parts", () => {
  it("name every slot of a Fabricator ship but for one hauler wing the game leaves unnamed", () => {
    for (const v of fabricator) {
      expect(v.names.length, `${v.model} ${v.seed}`).toBe(v.model === "DROPSHIP_PROC" ? v.names.length : 3);
    }
    const haulers = fabricator.filter((v) => v.model === "DROPSHIP_PROC");
    expect(haulers.filter((v) => v.names.length === 2)).toHaveLength(1);
    expect(haulers.filter((v) => v.names.length === 3)).toHaveLength(haulers.length - 1);
  });

  it("are made of the ship's own parts, in its order", () => {
    for (const v of file.vectors) {
      const parts = partsFor(v.model, BigInt(`0x${v.seed}`));
      for (const [, name, made] of v.names) {
        if (FABRICATOR.includes(v.model)) expect(made.length, `${v.model} ${v.seed} ${name}`).toBeGreaterThan(0);
        expect(made, `${v.model} ${v.seed} ${name}`).toEqual(parts.filter((part) => made.includes(part)));
      }
    }
  });

  it("come, for the ships players name the parts of, in the order of their first parts", () => {
    for (const v of community) {
      const parts = partsFor(v.model, BigInt(`0x${v.seed}`));
      const firsts = v.names.map(([, , made]) => (made.length ? parts.indexOf(made[0]!) : -1));
      expect(firsts, `${v.model} ${v.seed}`).toEqual([...firsts].sort((a, b) => a - b));
    }
  });

  it("give every Sentinel ship its body, which has no ID of its own, first", () => {
    const sentinels = community.filter((v) => v.model === "SENTINELSHIP_PROC");
    expect(sentinels.length).toBeGreaterThan(0);
    for (const v of sentinels) expect(v.names[0], v.seed).toEqual(["", "Body", []]);
  });

  it("can name one part twice, as a forward X-wing's two open halves in one model", () => {
    const xwing = community.find((v) => partsFor(v.model, BigInt(`0x${v.seed}`)).includes("_WINGS1_O"))!;
    const names = xwing.names.filter(([, , made]) => made.includes("_WINGS1_O")).map(([, name]) => name);
    expect(names).toEqual(["X-Wing Front Top", "X-Wing Front Bottom"]);
  });

  it("give an explorer with a matched pair of wings the same wing on both sides", () => {
    const paired = file.vectors.filter(
      (v) =>
        v.model === "SCIENTIFIC_PROC" && partsFor(v.model, BigInt(`0x${v.seed}`)).some((p) => /^_WINGS_SYM1?$/.test(p)),
    );
    expect(paired.length).toBeGreaterThanOrEqual(2);
    for (const v of paired) {
      const [, left, right] = v.names;
      expect(left![0]).toBe("left");
      expect(right![0]).toBe("right");
      expect(right![1]).toBe(left![1]);
    }
  });

  it("are none for a model whose parts have no names", () => {
    for (const model of ["MULTITOOL", "POLICEFREIGHTER", "FREIGHTERSMALL_PROC"] as const) {
      expect(namedParts(model, 0x0123456789abcdefn)).toEqual([]);
    }
  });
});
