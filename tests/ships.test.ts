// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The ship pool against tools/captures/ship_model.py, the Python model it
// ports, over the made-up addresses in tests/fixtures/ship-vectors.json
// (written by tools/crosscheck/ship_vectors.py). tests/crosscheck.test.ts
// compares the two over thousands more when CROSSCHECK_FILE is set.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  basePalettes,
  civilianType,
  colorName,
  describeSystem,
  distinguishingParts,
  exoticSquid,
  firstDraw,
  hex64,
  hexColor,
  MULTIPLIER,
  namedParts,
  paint,
  paintColors,
  parsePortalCode,
  planetSeeds,
  partsFor,
  shipPool,
  slotTypes,
  solarRoll,
  SQUID_PART,
  systemAttributes,
  typeModels,
  typePaints,
  universalAddress,
  withPlanet,
  type Palettes,
  type PartModel,
  type ShipGroup,
} from "../src/core";

/** The names the game gives a starship's parts, each with the parts that tell ships apart it's made of. */
function namesOf(model: PartModel, seed: bigint) {
  const parts = distinguishingParts(model, seed);
  return namedParts(model, seed).map(({ name, side, parts: made }) => ({
    name,
    side,
    parts: parts.filter((part) => made.includes(part)),
  }));
}

/** A starship's colors as the site works them out: its paint, with palettes from `palettes`. */
function colorsOf(model: PartModel, seed: bigint, palettes: Palettes, hint = "") {
  const passes = paint(model, partsFor(model, seed), seed, palettes, hint);
  return paintColors(passes).map((color) => ({ hex: hexColor(color), name: colorName(color) }));
}

interface ShipVector {
  what: string;
  code: string;
  galaxy: number;
  bodies: [number, number, boolean][];
  start: number;
  uncertain: string | null;
  ships: string[];
  exoticSquid: boolean;
  crash: string;
  /** What each of the first 20 ships is: Hauler, Fighter, Explorer, Shuttle or Solar. */
  civilian: string[];
  /** The other ways a two-moon planet's moons can be arranged. */
  others: { start: number; exotic: string; exoticSquid: boolean; crash: string }[];
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
      "an outlaw system",
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
      expect(pool.ships.slice(0, 20).map((s) => s.type)).toEqual(v.civilian);
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
    expect(runs(civilian(1))).toEqual([["Hauler", 7], ["Fighter", 3], ["Explorer", 3], ["Shuttle", 7]]);
    expect(runs(civilian(2))).toEqual([["Hauler", 3], ["Fighter", 3], ["Explorer", 7], ["Shuttle", 7]]);
    expect(runs(civilian(3))).toEqual([["Hauler", 3], ["Fighter", 7], ["Explorer", 3], ["Shuttle", 7]]);
    expect(runs(civilian(0))).toEqual([["Hauler", 5], ["Fighter", 5], ["Explorer", 5], ["Shuttle", 5]]);
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

  it("uses the system's dominant race, and makes some civilian ships solar", () => {
    for (const v of file.vectors) {
      const code = parsePortalCode(v.code);
      const attributes = systemAttributes(withPlanet(code, 0), v.galaxy);
      const slots = slotTypes(attributes.dominant_race);
      shipPool(code, v.galaxy).ships.forEach((s, slot) => {
        expect(s.type === slots[slot]![0] || (slot < 20 && s.type === "Solar"), `${v.what} ${slot}`).toBe(true);
        expect(s.group).toBe(slots[slot]![1]);
      });
    }
  });
});

describe("solar ships", () => {
  const ua = universalAddress(withPlanet(parsePortalCode("009A039BAE4B"), 0), 0);
  // Seeds whose roll falls under 0.1, between 0.1 and 0.85, and over 0.85.
  const seeds = Array.from({ length: 200 }, (_, k) => BigInt(k) * 0x9e3779b97f4a7c15n);
  const low = seeds.find((seed) => solarRoll(seed, ua) < 0.1)!;
  const middle = seeds.find((seed) => solarRoll(seed, ua) > 0.2 && solarRoll(seed, ua) < 0.8)!;
  const high = seeds.find((seed) => solarRoll(seed, ua) > 0.9)!;

  it("come from a roll that's a fraction, the same every time for the same ship and system", () => {
    for (const seed of seeds) {
      const roll = solarRoll(seed, ua);
      expect(roll).toBeGreaterThanOrEqual(0);
      expect(roll).toBeLessThanOrEqual(1);
      expect(roll).toBe(Math.fround(roll));
      expect(solarRoll(seed, ua)).toBe(roll);
    }
    expect(solarRoll(low, ua + 1n)).not.toBe(solarRoll(low, ua));
  });

  it("are shuttles that roll under 0.1, and in an outlaw system under 0.85", () => {
    expect(civilianType("Shuttle", low, ua, false)).toBe("Solar");
    expect(civilianType("Shuttle", middle, ua, false)).toBe("Shuttle");
    expect(civilianType("Shuttle", middle, ua, true)).toBe("Solar");
    expect(civilianType("Shuttle", high, ua, true)).toBe("Shuttle");
  });

  it("are other civilian ships that roll under 0.1 only in an outlaw system", () => {
    for (const type of ["Hauler", "Fighter", "Explorer"]) {
      expect(civilianType(type, low, ua, false)).toBe(type);
      expect(civilianType(type, low, ua, true)).toBe("Solar");
      expect(civilianType(type, middle, ua, true)).toBe(type);
    }
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

describe("slot models", () => {
  it("are the models each type of ship is built from", () => {
    expect(typeModels("Hauler")).toEqual(["DROPSHIP_PROC"]);
    expect(typeModels("Shuttle")).toEqual(["SHUTTLE_PROC"]);
    expect(typeModels("Solar")).toEqual(["SAILSHIP_PROC"]);
    expect(typeModels("Pirate fighter")).toEqual(["FIGHTER_PROC"]);
    expect(typeModels("Sentinel freighter")).toEqual(["POLICEFREIGHTER"]);
    expect(typeModels("Pirate capital freighter")).toEqual(["PIRATEFREIGHTER"]);
    expect(typeModels("Combat frigate")).toEqual([]);
  });

  it("give parts to the civilian ships, the exotic, the freighters, the Sentinels' and the pirates' ships", () => {
    const v = file.vectors.find((v) => v.what === "Gek, no moons")!;
    const ships = shipPool(parsePortalCode(v.code), v.galaxy).ships;
    const withParts = ships.filter((s) => s.models.length).map((s) => s.slot);
    expect(withParts).toEqual([...Array(27).keys(), 35, 36, 37, 38, 39, 40, 41, 43]);
    expect(ships[20]!.models).toEqual(["S-CLASS_PROC"]);
    expect(ships[24]!.models).toEqual(["CAPITALFREIGHTER_PROC"]);
    expect(ships[25]!.models).toEqual(["FREIGHTERSMALL_PROC"]);
    expect(ships[35]!.models).toEqual(["SENTINELSHIP_PROC"]);
  });

  it("paint those and the frigates and the swarm's frigate and drone, the Sentinel ship with the hint POLICE", () => {
    const v = file.vectors.find((v) => v.what === "Gek, no moons")!;
    const ships = shipPool(parsePortalCode(v.code), v.galaxy).ships;
    const painted = ships.filter((s) => s.paints.length).map((s) => s.slot);
    // Not the recon frigate, the organic frigates, the swarm's capital freighter or the corvette.
    expect(painted).toEqual([...Array(50).keys()].filter((slot) => ![32, 33, 34, 46, 49].includes(slot)));
    expect(ships[27]!.paints).toEqual(["COMBATFRIGATELOD0"]);
    expect(ships[42]!.paints).toEqual(["PIRATECRUISERLOD0"]);
    expect(ships[44]!.paints).toEqual(["PIRATECRUISERLOD0"]);
    expect(ships[48]!.paints).toEqual(["SWARM"]);
    expect(typePaints("Solar")).toEqual(["SAILSHIP_PROC"]);
    expect(ships.filter((s) => s.hint).map((s) => [s.slot, s.hint])).toEqual([[35, "POLICE"]]);
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
  const squid = (draw: number) => exoticSquid(seedWithFirstDraw(draw));

  it("takes the first draw from the seed as the Python model does", () => {
    expect(firstDraw(0x0123456789abcdefn)).toBe(4005469434);
    expect(firstDraw(0xfedcba9876543210n)).toBe(3066718828);
    expect(firstDraw(1n)).toBe(1517811866);
    for (const draw of [0, 1, Math.floor(line), Math.ceil(line), 2 ** 32 - 1]) {
      expect(firstDraw(seedWithFirstDraw(draw))).toBe(draw);
    }
  });

  it("are the exotics whose first draw is at least 20/21 of its range: the squid's body weighs 0.05 to 1", () => {
    for (const draw of [0, 1, Math.floor(line) - 1, Math.floor(line)]) expect(squid(draw), String(draw)).toBe(false);
    for (const draw of [Math.ceil(line), Math.ceil(line) + 1, 2 ** 32 - 1]) expect(squid(draw), String(draw)).toBe(true);
  });

  it("have the squid's body as their first part", () => {
    expect(partsFor("S-CLASS_PROC", seedWithFirstDraw(Math.ceil(line)))[0]).toBe(SQUID_PART);
    expect(partsFor("S-CLASS_PROC", seedWithFirstDraw(Math.floor(line)))[0]).not.toBe(SQUID_PART);
  });
});

describe("describeSystem", () => {
  it("includes the ships, with seeds written as on the rest of the page", () => {
    const v = file.vectors.find((v) => v.what === "Korvax, a planet with one moon")!;
    const d = describeSystem(parsePortalCode(v.code), v.galaxy);
    const seed = (k: number) => BigInt(`0x${v.ships[k]}`);
    const crash = BigInt(`0x${v.crash}`);
    expect(d.ships.exotic).toBe(`0x${v.ships[20]}`);
    expect(d.ships.exoticSquid).toEqual(v.exoticSquid);
    expect(d.ships.crashSite).toBe(`0x${v.crash}`);
    expect(d.ships.ships).toHaveLength(50);
    expect(d.ships.ships[0]).toEqual({
      slot: 0,
      type: "Hauler",
      group: "civilian",
      seed: `0x${v.ships[0]}`,
      builds: [
        {
          model: "Hauler",
          parts: distinguishingParts("DROPSHIP_PROC", seed(0)),
          names: namesOf("DROPSHIP_PROC", seed(0)),
          colors: colorsOf("DROPSHIP_PROC", seed(0), basePalettes(seed(0))),
        },
      ],
      note: null,
    });
    // A hauler's cockpit, thrusters and wings, each by name; nothing else of its parts is named.
    expect(d.ships.ships[0]!.builds[0]!.names.map((n) => n.side)).toEqual(["", "", ""]);
    // The exotic's aren't named: the game's Starship Fabricator doesn't build exotics.
    expect(d.ships.ships[20]!.builds[0]!.names).toEqual([]);
    expect(d.ships.exoticParts).toEqual(distinguishingParts("S-CLASS_PROC", seed(20)));
    expect(d.ships.exoticColors).toEqual(colorsOf("S-CLASS_PROC", seed(20), basePalettes(seed(20))));
    expect(d.ships.crashSiteParts).toEqual(distinguishingParts("SENTINELSHIP_PROC", crash));
    // The crash-site ship has no texture hint; the system's Sentinel ship has POLICE.
    expect(d.ships.crashSiteColors).toEqual(colorsOf("SENTINELSHIP_PROC", crash, basePalettes(crash)));
    expect(d.ships.ships[35]!.builds[0]!.colors).toEqual(
      colorsOf("SENTINELSHIP_PROC", seed(35), basePalettes(seed(35)), "POLICE"),
    );
    // A freighter takes its colors from its system's palettes.
    const system = basePalettes(universalAddress(withPlanet(parsePortalCode(v.code), 0), v.galaxy));
    expect(d.ships.ships[24]!.builds[0]!.colors).toEqual(colorsOf("CAPITALFREIGHTER_PROC", seed(24), system));
    // A frigate's, from its closest level of detail, which has no parts.
    expect(d.ships.ships[27]!.builds).toEqual([
      {
        model: "Combat frigate",
        parts: [],
        names: [],
        colors: paintColors(paint("COMBATFRIGATELOD0", [], seed(27), system)).map((color) => ({
          hex: hexColor(color),
          name: colorName(color),
        })),
      },
    ]);
    expect(d.ships.ships[27]!.builds[0]!.colors.length).toBeGreaterThan(0);
    expect(d.ships.ships[32]!.builds).toEqual([]);
    expect(d.ships.ships[32]!.note).toMatch(/Beachhead expedition/);
    expect(d.ships.uncertain).toBeNull();
    expect(d.ships.alternatives).toEqual([]);
  });

  it("gives the other moon arrangement's exotic and crash-site seeds", () => {
    const v = file.vectors.find((v) => v.what === "Vy'keen, a planet with two moons")!;
    const ships = describeSystem(parsePortalCode(v.code), v.galaxy).ships;
    expect(ships.uncertain).toBe(v.uncertain);
    expect(ships.alternatives).toEqual(
      v.others.map((o) => {
        const exotic = BigInt(`0x${o.exotic}`);
        const crash = BigInt(`0x${o.crash}`);
        return {
          exotic: `0x${o.exotic}`,
          exoticSquid: o.exoticSquid,
          exoticParts: distinguishingParts("S-CLASS_PROC", exotic),
          exoticColors: colorsOf("S-CLASS_PROC", exotic, basePalettes(exotic)),
          crashSite: `0x${o.crash}`,
          crashSiteParts: distinguishingParts("SENTINELSHIP_PROC", crash),
          crashSiteColors: colorsOf("SENTINELSHIP_PROC", crash, basePalettes(crash)),
        };
      }),
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
