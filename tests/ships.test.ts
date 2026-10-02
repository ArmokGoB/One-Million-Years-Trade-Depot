// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The ship pool against tools/captures/ship_model.py, the Python model it
// ports, over the made-up addresses in tests/fixtures/ship-vectors.json
// (written by tools/crosscheck/ship_vectors.py). tests/crosscheck.test.ts
// compares the two over thousands more when CROSSCHECK_FILE is set.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  describeSystem,
  hex64,
  parsePortalCode,
  planetSeeds,
  shipPool,
  slotTypes,
  systemAttributes,
  withPlanet,
  type ShipGroup,
} from "../src/core";

interface ShipVector {
  what: string;
  code: string;
  galaxy: number;
  bodies?: [number, number, boolean][];
  start?: number;
  uncertain?: string | null;
  ships: string[] | null;
  crash?: string;
}

const file = JSON.parse(readFileSync(new URL("./fixtures/ship-vectors.json", import.meta.url), "utf8")) as {
  vectors: ShipVector[];
};

describe("ship pool vectors from the Python model", () => {
  it("covers every layout the model treats differently", () => {
    expect(file.vectors.map((v) => v.what)).toEqual([
      "Gek, no moons",
      "Korvax, a planet with one moon",
      "Vy'keen, a planet with two moons",
      "uncharted",
      "abandoned",
      "a prime planet with moons",
      "six bodies",
      "purple star",
      "gas giant layout",
      "another galaxy, with a planet digit",
    ]);
  });

  for (const v of file.vectors) {
    it(`${v.what}: ${v.code} in galaxy ${v.galaxy}`, () => {
      const code = parsePortalCode(v.code);
      const pool = shipPool(code, v.galaxy);
      if (v.ships === null) {
        expect(pool).toBeNull();
        return;
      }
      if (!pool) throw new Error("expected a ship pool");
      const { bodies } = planetSeeds(withPlanet(code, 0), v.galaxy);
      expect(bodies.map((b) => [b.size, b.parent, b.prime])).toEqual(v.bodies);
      expect(pool.drawsBeforeShips).toBe(v.start);
      expect(pool.uncertain).toBe(v.uncertain);
      expect(pool.ships.map((s) => hex64(s.seed))).toEqual(v.ships);
      expect(pool.ships.map((s) => s.slot)).toEqual([...Array(50).keys()]);
      expect(hex64(pool.crashSite)).toBe(v.crash);
      expect(hex64(pool.exotic)).toBe(v.ships[20]);
    });
  }
});

describe("slot types", () => {
  const civilian = (race: number) => slotTypes(race).slice(0, 20).map(([type]) => type);
  const runs = (types: string[]) =>
    types.reduce<[string, number][]>((out, type) => {
      const last = out[out.length - 1];
      if (last && last[0] === type) last[1] += 1;
      else out.push([type, 1]);
      return out;
    }, []);

  it("gives the civilian slots by dominant race", () => {
    expect(runs(civilian(1))).toEqual([["Hauler", 7], ["Fighter", 3], ["Explorer", 3], ["Shuttle or solar", 7]]);
    expect(runs(civilian(2))).toEqual([["Hauler", 3], ["Fighter", 3], ["Explorer", 7], ["Shuttle or solar", 7]]);
    expect(runs(civilian(3))).toEqual([["Hauler", 3], ["Fighter", 7], ["Explorer", 3], ["Shuttle or solar", 7]]);
    expect(runs(civilian(0))).toEqual([["Hauler", 5], ["Fighter", 5], ["Explorer", 5], ["Shuttle or solar", 5]]);
  });

  it("puts the same ships in slots 20 to 49 whatever the race", () => {
    const fixed = (race: number) => slotTypes(race).slice(20);
    expect(fixed(0)).toEqual(fixed(1));
    expect(fixed(2)).toEqual(fixed(3));
    expect(fixed(0)).toEqual(fixed(3));
    const types = slotTypes(1);
    expect(types[20]).toEqual(["Exotic", "exotic"]);
    expect(types[27]).toEqual(["Frigate (Combat)", "frigate"]);
    expect(types[35]).toEqual(["Police interceptor", "police"]);
    expect(types[49]).toEqual(["Corvette", "corvette"]);
    const counts = new Map<ShipGroup, number>();
    for (const [, group] of types) counts.set(group, (counts.get(group) ?? 0) + 1);
    expect(Object.fromEntries(counts)).toEqual({
      civilian: 20,
      exotic: 1,
      freighter: 6,
      frigate: 10,
      police: 2,
      pirate: 7,
      swarm: 3,
      corvette: 1,
    });
  });

  it("uses the system's dominant race", () => {
    for (const v of file.vectors.filter((v) => v.ships)) {
      const code = parsePortalCode(v.code);
      const race = systemAttributes(withPlanet(code, 0), v.galaxy).dominant_race;
      expect(shipPool(code, v.galaxy)!.ships.map((s) => s.type)).toEqual(slotTypes(race).map(([type]) => type));
    }
  });

  it("says the Normandy's slot isn't a ship found in systems", () => {
    const v = file.vectors.find((v) => v.ships)!;
    const ships = shipPool(parsePortalCode(v.code), v.galaxy)!.ships;
    expect(ships[32]!.type).toBe("Frigate (Normandy)");
    expect(ships[32]!.note).toMatch(/Beachhead expedition/);
    expect(ships.filter((s) => s.note).map((s) => s.slot)).toEqual([32]);
  });
});

describe("describeSystem", () => {
  it("includes the ships, with seeds written as on the rest of the page", () => {
    const v = file.vectors.find((v) => v.what === "Korvax, a planet with one moon")!;
    const d = describeSystem(parsePortalCode(v.code), v.galaxy);
    expect(d.ships).not.toBeNull();
    expect(d.ships!.exotic).toBe(`0x${v.ships![20]}`);
    expect(d.ships!.crashSite).toBe(`0x${v.crash}`);
    expect(d.ships!.ships).toHaveLength(50);
    expect(d.ships!.ships[0]).toEqual({
      slot: 0,
      type: "Hauler",
      group: "civilian",
      seed: `0x${v.ships![0]}`,
      note: null,
    });
    expect(d.ships!.ships[32]!.note).toMatch(/Beachhead expedition/);
    expect(d.ships!.uncertain).toBeNull();
  });

  it("says why a prediction may be wrong", () => {
    const v = file.vectors.find((v) => v.what === "Vy'keen, a planet with two moons")!;
    expect(describeSystem(parsePortalCode(v.code), v.galaxy).ships!.uncertain).toBe(v.uncertain);
  });

  it("has no ships for a gas giant layout", () => {
    const v = file.vectors.find((v) => v.what === "gas giant layout")!;
    const d = describeSystem(parsePortalCode(v.code), v.galaxy);
    expect(d.gasGiant).toBe(true);
    expect(d.ships).toBeNull();
  });
});
