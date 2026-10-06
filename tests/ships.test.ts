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
  exoticSquid,
  firstDraw,
  hex64,
  MULTIPLIER,
  parsePortalCode,
  planetSeeds,
  shipPool,
  slotTypes,
  SQUID_EDGES,
  systemAttributes,
  withPlanet,
  type ShipGroup,
  type SquidCall,
} from "../src/core";

interface ShipVector {
  what: string;
  code: string;
  galaxy: number;
  bodies: [number, number, boolean][];
  start: number;
  uncertain: string | null;
  ships: string[];
  exoticSquid: SquidCall;
  crash: string;
  /** The other ways a two-moon planet's moons can be arranged. */
  others: { start: number; exotic: string; exoticSquid: SquidCall; crash: string }[];
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
      "giant planet layout",
      "another galaxy, with a planet digit",
      "two planets with two moons each",
    ]);
  });

  for (const v of file.vectors) {
    it(`${v.what}: ${v.code} in galaxy ${v.galaxy}`, () => {
      const code = parsePortalCode(v.code);
      const pool = shipPool(code, v.galaxy);
      const { bodies } = planetSeeds(withPlanet(code, 0), v.galaxy);
      expect(bodies.map((b) => [b.size, b.parent, b.prime])).toEqual(v.bodies);
      expect(pool.drawsBeforeShips).toBe(v.start);
      expect(pool.uncertain).toBe(v.uncertain);
      expect(pool.ships.map((s) => hex64(s.seed))).toEqual(v.ships);
      expect(pool.ships.map((s) => s.slot)).toEqual([...Array(50).keys()]);
      expect(hex64(pool.crashSite)).toBe(v.crash);
      expect(hex64(pool.exotic)).toBe(v.ships[20]);
      expect(pool.exoticSquid).toEqual(v.exoticSquid);
      expect(
        pool.alternatives.map((a) => ({
          start: a.drawsBeforeShips,
          exotic: hex64(a.exotic),
          exoticSquid: a.exoticSquid,
          crash: hex64(a.crashSite),
        })),
      ).toEqual(v.others);
      for (const a of pool.alternatives) {
        expect(a.ships).toHaveLength(50);
        expect(a.ships[20]).toBe(a.exotic);
      }
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
    expect(types[27]).toEqual(["Combat frigate", "frigate"]);
    expect(types.slice(27, 35).map(([type]) => type)).toEqual([
      "Combat frigate",
      "Exploration frigate",
      "Industrial frigate",
      "Trade frigate",
      "Support frigate",
      "Recon frigate",
      "Organic frigate (DeepSpace)",
      "Organic frigate (DeepSpaceCommon)",
    ]);
    expect(types[35]).toEqual(["Sentinel ship", "sentinel"]);
    expect(types[42]).toEqual(["Raider frigate", "frigate"]);
    expect(types[45]).toEqual(["Cursed frigate", "frigate"]);
    expect(types[49]).toEqual(["Corvette", "corvette"]);
    const counts = new Map<ShipGroup, number>();
    for (const [, group] of types) counts.set(group, (counts.get(group) ?? 0) + 1);
    expect(Object.fromEntries(counts)).toEqual({
      civilian: 20,
      exotic: 1,
      freighter: 6,
      frigate: 10,
      sentinel: 2,
      pirate: 7,
      swarm: 3,
      corvette: 1,
    });
  });

  it("uses the system's dominant race and outlaw flag", () => {
    for (const v of file.vectors) {
      const code = parsePortalCode(v.code);
      const attributes = systemAttributes(withPlanet(code, 0), v.galaxy);
      expect(shipPool(code, v.galaxy).ships.map((s) => s.type)).toEqual(
        slotTypes(attributes.dominant_race, attributes.pirate).map(([type]) => type),
      );
    }
  });

  it("says which civilian ships an outlaw system may make solar", () => {
    const outlaw = (race: number) => slotTypes(race, true).slice(0, 20).map(([type]) => type);
    expect(runs(outlaw(1))).toEqual([
      ["Hauler or solar", 7],
      ["Fighter or solar", 3],
      ["Explorer or solar", 3],
      ["Solar or shuttle", 7],
    ]);
    expect(slotTypes(2, true).slice(20)).toEqual(slotTypes(2).slice(20));
  });

  it("notes the frigate types that don't come from ordinary systems", () => {
    const v = file.vectors[0]!;
    const ships = shipPool(parsePortalCode(v.code), v.galaxy).ships;
    expect(ships[32]!.type).toBe("Recon frigate");
    expect(ships[32]!.note).toMatch(/SSV Normandy SR1, the Beachhead expedition's reward/);
    expect(ships[45]!.note).toMatch(/Ship of the Damned, the Adrift expedition's reward/);
    expect(ships[42]!.note).toMatch(/Pirate Dreadnought/);
    expect(ships[33]!.note).toMatch(/Dream Aerial/);
    expect(ships[34]!.note).toBe(ships[33]!.note);
    expect(ships.filter((s) => s.note).map((s) => s.slot)).toEqual([32, 33, 34, 42, 45]);
  });
});

describe("squid exotics", () => {
  const M32 = 0xffffffffn;
  const swap16 = (x: bigint) => ((x >> 16n) | (x << 16n)) & M32;
  /** A made-up seed whose first draw is `draw`: the game's seeding, run backwards. */
  function seedWithFirstDraw(draw: number, low = 0x2468ace1n): bigint {
    const high = (BigInt(draw) - low * MULTIPLIER) & M32;
    if (high === 0n) throw new Error("the game would make this high word 1; pick another low word");
    return ((high ^ swap16(low) ^ low) << 32n) | low;
  }
  const line = (20 * 2 ** 32) / 21;
  const call = (draw: number) => exoticSquid(seedWithFirstDraw(draw));

  it("takes the first draw from the seed as the Python model does", () => {
    expect(firstDraw(0x0123456789abcdefn)).toBe(4005469434);
    expect(firstDraw(0xfedcba9876543210n)).toBe(3066718828);
    expect(firstDraw(1n)).toBe(1517811866);
    for (const draw of [0, 1, SQUID_EDGES.notSquid, Math.floor(line), Math.ceil(line), 2 ** 32 - 1]) {
      expect(firstDraw(seedWithFirstDraw(draw))).toBe(draw);
    }
  });

  it("draws the line at 20/21 of the range, between the closest exotics recorded", () => {
    expect(SQUID_EDGES.notSquid).toBeLessThan(line);
    expect(SQUID_EDGES.squid).toBeGreaterThan(line);
    expect(call(0)).toEqual({ squid: false, close: false });
    expect(call(SQUID_EDGES.notSquid)).toEqual({ squid: false, close: false });
    expect(call(SQUID_EDGES.notSquid + 1)).toEqual({ squid: false, close: true });
    expect(call(Math.floor(line))).toEqual({ squid: false, close: true });
    expect(call(Math.ceil(line))).toEqual({ squid: true, close: true });
    expect(call(SQUID_EDGES.squid - 1)).toEqual({ squid: true, close: true });
    expect(call(SQUID_EDGES.squid)).toEqual({ squid: true, close: false });
    expect(call(2 ** 32 - 1)).toEqual({ squid: true, close: false });
  });
});

describe("describeSystem", () => {
  it("includes the ships, with seeds written as on the rest of the page", () => {
    const v = file.vectors.find((v) => v.what === "Korvax, a planet with one moon")!;
    const d = describeSystem(parsePortalCode(v.code), v.galaxy);
    expect(d.ships.exotic).toBe(`0x${v.ships[20]}`);
    expect(d.ships.exoticSquid).toEqual(v.exoticSquid);
    expect(d.ships.crashSite).toBe(`0x${v.crash}`);
    expect(d.ships.ships).toHaveLength(50);
    expect(d.ships.ships[0]).toEqual({
      slot: 0,
      type: "Hauler",
      group: "civilian",
      seed: `0x${v.ships[0]}`,
      note: null,
    });
    expect(d.ships.ships[32]!.note).toMatch(/Beachhead expedition/);
    expect(d.ships.uncertain).toBeNull();
    expect(d.ships.alternatives).toEqual([]);
  });

  it("gives the other moon arrangement's exotic and crash-site seeds", () => {
    const v = file.vectors.find((v) => v.what === "Vy'keen, a planet with two moons")!;
    const ships = describeSystem(parsePortalCode(v.code), v.galaxy).ships;
    expect(ships.uncertain).toBe(v.uncertain);
    expect(ships.alternatives).toEqual(
      v.others.map((o) => ({ exotic: `0x${o.exotic}`, exoticSquid: o.exoticSquid, crashSite: `0x${o.crash}` })),
    );
    expect(ships.alternatives).toHaveLength(1);
  });

  it("predicts a giant planet system, whose bodies are all prime", () => {
    const v = file.vectors.find((v) => v.what === "giant planet layout")!;
    const d = describeSystem(parsePortalCode(v.code), v.galaxy);
    expect(d.gasGiant).toBe(true);
    expect(d.ships.exotic).toBe(`0x${v.ships[20]}`);
    expect(v.start).toBe(41);
  });
});
