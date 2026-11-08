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
  it("name every slot of a Fabricator ship", () => {
    for (const v of fabricator) expect(v.names.length, `${v.model} ${v.seed}`).toBe(3);
  });

  it("give the hauler wing the product tables leave out the name the game's text has for it", () => {
    const heavy = fabricator.filter((v) => v.names.some(([, , made]) => made.includes("_SUBWINGS_D27")));
    expect(heavy.length).toBeGreaterThan(0);
    for (const v of heavy) {
      const [, name, made] = v.names.find(([, , made]) => made.includes("_SUBWINGS_D27"))!;
      expect(name).toBe("Heavy-22 D-Wing");
      expect(made).toEqual(expect.arrayContaining(["_WINGS_C", "_THRUSTERS_D2", "_SUBWINGS_D27"]));
    }
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

  it("name a slot by what it holds on each kind of freighter", () => {
    const slots = community.filter(
      (v) => v.model === "FREIGHTER_PROC" && v.names.some(([, , made]) => made.includes("_CARGOB_A")),
    );
    const kinds = slots.map((v) => {
      const hull = partsFor(v.model, BigInt(`0x${v.seed}`)).find((p) => p === "_HULL_A" || p === "_HULL_B");
      const holds = v.names.filter(([, , made]) => made.includes("_CARGOB_A")).map(([, name]) => name);
      return [hull, holds];
    });
    expect(kinds).toContainEqual(["_HULL_A", ["Tokamak Cargo"]]);
    expect(kinds).toContainEqual(["_HULL_B", ["Dewar Cargo"]]);
    for (const [hull, holds] of kinds) expect(holds).toEqual([hull === "_HULL_A" ? "Tokamak Cargo" : "Dewar Cargo"]);
  });

  it("name a shuttle's chin only on a cockpit with a place for it", () => {
    const withId = community
      .filter((v) => v.model === "SHUTTLE_PROC")
      .map((v) => ({ parts: partsFor(v.model, BigInt(`0x${v.seed}`)), names: v.names.map(([, name]) => name) }))
      .filter((v) => v.parts.includes("_ACC_B"));
    const on = (cockpit: string) => withId.filter((v) => v.parts.includes(cockpit));
    expect(on("_DCOCKPIT_A").length).toBeGreaterThan(0);
    expect(on("_SCOCKPIT_C").length).toBeGreaterThan(0);
    for (const v of on("_DCOCKPIT_A")) expect(v.names).toContain("Angled Chin");
    for (const v of on("_SCOCKPIT_C")) expect(v.names).not.toContain("Angled Chin");
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
