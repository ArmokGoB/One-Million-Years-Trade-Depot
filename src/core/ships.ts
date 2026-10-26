// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A system's ships from its address alone: a port of
// tools/captures/ship_model.py, which was worked out from capture-mod records
// and is checked against every capture. tests/crosscheck.test.ts holds this
// port to the Python model over thousands of random addresses.
//
// After the planets, the game starts its generator again from the system's
// universal address for the space station, the locators and the ships:
//   1. 38 draws: the space station and the 9 locators around it.
//   2. For each planet that isn't a prime planet, in order, its "attractor"
//      locators: 30 + (a draw below 36) attempts, each drawing an elevation,
//      an azimuth, a distance (the planet's base radius plus up to 40,000)
//      and one more number. An attempt whose point lies within 500 of the
//      planet's base radius, or of its moon's or parent's, is dropped; any
//      other draws one more number.
//   3. 3 draws.
//   4. The ships: each seed mixes the next two draws; 50 ships, with the seed
//      for Sentinel crash sites drawn between ships 41 and 42.
//
// Where a planet's two moons sit, which decides which attractors they block,
// comes from the generator the game seeds with the address to place the
// planets: see swappedMoons().
//
// Whether the exotic is a squid comes from the exotic's own seed: see
// exoticSquid(). What each ship is built from, and so which parts it can
// have, comes from its slot, and for a civilian ship from whether the game
// makes it solar: see slotTypes(), civilianType() and parts.ts.

import { universalAddress, withPlanet } from "./address";
import type { PaintModel } from "./paint";
import { partsFor, type PartModel } from "./parts";
import { seededPRNG } from "./prng";
import { planetSeeds, systemAttributes, type Body } from "./system";
import { mix64 } from "./u64";

/** Base radius of a planet's attractor shell, by size (0 large, 1 medium, 2 small, 3 moon). */
const BASE_RADIUS: readonly number[] = [195072, 147456, 96768, 23040];
const SHELL = 40000;
const CLEARANCE = 500;
const STATION_DRAWS = 38;
const TAIL_DRAWS = 3;
/** The draws for each planet that isn't prime, as the game places them, before their moons'. */
const PLANET_DRAWS = 3;
const SHIP_COUNT = 50;
const CRASH_BEFORE = 42;

type Vec3 = readonly [number, number, number];

/**
 * Where a moon sits relative to its parent: 225,792 away, at a point the game
 * spreads over a sphere in a golden spiral. A lone moon sits along +x; a
 * planet's two moons at +30 and -30 degrees of elevation, the first above, one
 * at azimuth 0 and the other at the golden angle (137.5 degrees), which one
 * as swappedMoons() says. Written out exactly as the Python model computes them.
 */
const LONE_MOON: Vec3 = [225792, 0, 0];
const ABOVE_AT_0: Vec3 = [195541.60797129598, 112895.99999999999, 0];
const BELOW_AT_GOLDEN: Vec3 = [-144186.29608742514, -112895.99999999999, 132086.45830890225];
const ABOVE_AT_GOLDEN: Vec3 = [-144186.29608742514, 112895.99999999999, 132086.45830890225];
const BELOW_AT_0: Vec3 = [195541.60797129598, -112895.99999999999, 0];

export type ShipGroup = "civilian" | "exotic" | "freighter" | "frigate" | "sentinel" | "pirate" | "swarm" | "corvette";

export interface Ship {
  /** Position in the game's list, 0-49. */
  slot: number;
  seed: bigint;
  /** What the game puts in this slot, e.g. "Hauler" or "Combat frigate". */
  type: string;
  group: ShipGroup;
  /**
   * The model the ship in this slot is built from, whose parts parts.ts
   * picks; none for ships without picked parts, such as frigates.
   */
  models: readonly PartModel[];
  /**
   * The models whose paint paint.ts works out for this slot: its models, and
   * a frigate's closest level of detail; none for a ship the game doesn't
   * paint, such as the corvette.
   */
  paints: readonly PaintModel[];
  /** The texture hint the game paints the ship with: POLICE for the Sentinel ship, "" for the rest. */
  hint: string;
  /** What a player should know about this slot, if anything, e.g. that it never turns up in systems. */
  note: string | null;
}

export interface ShipPool {
  /** All 50, in the game's order. */
  ships: Ship[];
  /** The exotic's seed (always slot 20). */
  exotic: bigint;
  /** Whether the exotic is a squid. */
  exoticSquid: boolean;
  /** The seed the game holds for the ship at this system's Sentinel crash sites. */
  crashSite: bigint;
  /** Draws the generator makes before the first ship's. */
  drawsBeforeShips: number;
}

function distance(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/**
 * Each moon's position relative to its parent; the planets in `swapped` have
 * their two moons the other way round (see swappedMoons).
 */
function moonOffsets(bodies: readonly Body[], swapped: ReadonlySet<number>): Map<number, Vec3> {
  const moons = new Map<number, number[]>();
  bodies.forEach((body, k) => {
    if (body.parent >= 0) moons.set(body.parent, [...(moons.get(body.parent) ?? []), k]);
  });
  const offsets = new Map<number, Vec3>();
  for (const [parent, siblings] of moons) {
    if (siblings.length === 1) {
      offsets.set(siblings[0]!, LONE_MOON);
      continue;
    }
    const [first, second] = swapped.has(parent) ? [ABOVE_AT_GOLDEN, BELOW_AT_0] : [ABOVE_AT_0, BELOW_AT_GOLDEN];
    siblings.forEach((k, j) => offsets.set(k, j % 2 === 0 ? first : second));
  }
  return offsets;
}

/**
 * The planets that aren't prime and whose two moons the game puts the other
 * way round from moonOffsets' default: the first at the golden angle, the
 * second at azimuth 0. The game places a planet's moons at the points of a
 * golden spiral, the first moon at the top point, and turns point k of n to
 * azimuth (k + draw) mod n times the golden angle, with a draw of the planet's
 * own; so with two moons, an even draw puts the first at the golden angle. The
 * draws come after one draw and PLANET_DRAWS for each planet that isn't prime,
 * one for each such planet with moons, in order. Prime planets' moons come
 * from draws after those, but no prime planet has attractors.
 */
export function swappedMoons(ua: bigint, bodies: readonly Body[]): Set<number> {
  const moons = (k: number) => bodies.filter((body) => body.parent === k).length;
  const planets = bodies.flatMap((body, k) => (!body.prime && body.parent < 0 ? [k] : []));
  const rng = seededPRNG(ua);
  for (let k = 0; k < 1 + PLANET_DRAWS * planets.length; k++) rng.updateSeed();
  const swapped = new Set<number>();
  for (const planet of planets) {
    if (!moons(planet)) continue;
    const draw = rng.randi();
    if (moons(planet) === 2 && draw % 2 === 0) swapped.add(planet);
  }
  return swapped;
}

/**
 * How many draws the generator makes before the first ship's, with the moons
 * where the game puts them, or with the two moons of the planets in `swapped`
 * the other way round.
 */
export function drawsBeforeShips(
  ua: bigint,
  bodies: readonly Body[],
  swapped: ReadonlySet<number> = swappedMoons(ua, bodies),
): number {
  const offsets = moonOffsets(bodies, swapped);
  const rng = seededPRNG(ua);
  let draws = 0;
  const word = () => {
    draws += 1;
    return rng.randi();
  };
  const unit = () => word() / 4294967296;

  for (let k = 0; k < STATION_DRAWS; k++) word();
  bodies.forEach((body, k) => {
    if (body.prime) return;
    // Bodies near enough to block this planet's attractors: its parent and its moons.
    const near: [Vec3, number][] = [];
    const own = offsets.get(k);
    if (body.parent >= 0 && own) {
      near.push([[-own[0], -own[1], -own[2]], BASE_RADIUS[bodies[body.parent]!.size]! + CLEARANCE]);
    }
    bodies.forEach((other, j) => {
      const offset = offsets.get(j);
      if (other.parent === k && offset) near.push([offset, BASE_RADIUS[other.size]! + CLEARANCE]);
    });
    const base = BASE_RADIUS[body.size]!;

    draws += 1;
    const attempts = 30 + rng.random(36);
    for (let a = 0; a < attempts; a++) {
      const y = 1.0 - 2.0 * unit();
      const azimuth = 2.0 * Math.PI * unit();
      const reach = base + SHELL * unit();
      word();
      if (reach < base + CLEARANCE) continue;
      const ring = Math.sqrt(Math.max(0.0, 1.0 - y * y));
      const point: Vec3 = [reach * ring * Math.cos(azimuth), reach * y, reach * ring * Math.sin(azimuth)];
      if (near.some(([center, clearance]) => distance(point, center) < clearance)) continue;
      word();
    }
  });
  return draws + TAIL_DRAWS;
}

/** The 50 ship seeds and the crash-site seed, drawn after `start` draws. */
export function shipSeeds(ua: bigint, start: number): { ships: bigint[]; crashSite: bigint } {
  const rng = seededPRNG(ua);
  for (let k = 0; k < start; k++) rng.updateSeed();
  const seeds: bigint[] = [];
  for (let k = 0; k <= SHIP_COUNT; k++) {
    const low = BigInt(rng.randi());
    const high = BigInt(rng.randi());
    seeds.push(mix64((high << 32n) | low));
  }
  const crashSite = seeds.splice(CRASH_BEFORE, 1)[0]!;
  return { ships: seeds, crashSite };
}

// --- Whether the exotic is a squid ---

/** The first part of an exotic's model when it's a squid: the squid's body. */
export const SQUID_PART = "_SCLASSSHIP_SQU";

/** The first draw the game makes from a ship's seed, which picks the first part of the ship's model. */
export function firstDraw(seed: bigint): number {
  return seededPRNG(seed).randi();
}

/**
 * Whether the exotic with this seed is a squid: whether its first part, its
 * body, is the squid's. The squid's body is a rare option, weighing 1
 * against the other exotics' body's 20, so the first draw from the seed picks
 * it in the top 1/21 of its range.
 */
export function exoticSquid(seed: bigint): boolean {
  return partsFor("S-CLASS_PROC", seed)[0] === SQUID_PART;
}

// --- What each slot holds, as seen in every system recorded so far ---

/** Haulers, fighters and explorers from slot 0 on, by dominant race; shuttles fill up to slot 19. */
const CIVILIAN_BY_RACE: Record<number, readonly [number, number, number]> = {
  0: [5, 5, 5], // uncharted: no dominant race
  1: [7, 3, 3], // Gek
  2: [3, 3, 7], // Korvax
  3: [3, 7, 3], // Vy'keen
};

/**
 * Frigate types as the game shows them, for its frigate classes 0-7 (Combat,
 * Exploration, Mining, Diplomacy, Support, Normandy, DeepSpace,
 * DeepSpaceCommon). The two organic classes keep their internal names apart.
 */
const FRIGATE_TYPES = [
  "Combat frigate",
  "Exploration frigate",
  "Industrial frigate",
  "Trade frigate",
  "Support frigate",
  "Recon frigate",
  "Organic frigate (DeepSpace)",
  "Organic frigate (DeepSpaceCommon)",
] as const;

const ORGANIC = "Organic frigates come through the Dream Aerial, built from plans a fleet expedition can bring back.";

/**
 * The game's list is a set of templates, not a list of ships that turn up:
 * every system has a frigate of every type, for one, including types whose
 * only known frigates are expedition rewards. Those slots say so.
 */
const SLOT_NOTES: Record<number, string> = {
  32: "The only known Recon frigate is the SSV Normandy SR1, the Beachhead expedition's reward.",
  33: ORGANIC,
  34: ORGANIC,
  42: "Raider frigates are the ones you can hire after defeating a Pirate Dreadnought.",
  45: "The only known Cursed frigate is the Ship of the Damned, the Adrift expedition's reward.",
};

const FIXED_SLOTS: Record<number, readonly [string, ShipGroup]> = {
  20: ["Exotic", "exotic"],
  21: ["Freighter", "freighter"],
  22: ["Freighter", "freighter"],
  23: ["Freighter", "freighter"],
  24: ["Capital freighter", "freighter"],
  25: ["Small freighter", "freighter"],
  26: ["Tiny freighter", "freighter"],
  ...Object.fromEntries(FRIGATE_TYPES.map((name, i) => [27 + i, [name, "frigate"] as const])),
  // The game's Police faction, which is the Sentinels: a ship of class Robot (texture hint POLICE) and a freighter.
  35: ["Sentinel ship", "sentinel"],
  36: ["Sentinel freighter", "sentinel"],
  37: ["Pirate fighter", "pirate"],
  38: ["Pirate fighter", "pirate"],
  39: ["Pirate fighter", "pirate"],
  40: ["Pirate fighter", "pirate"],
  41: ["Pirate fighter", "pirate"],
  42: ["Raider frigate", "frigate"],
  43: ["Pirate capital freighter", "pirate"],
  44: ["Pirate frigate", "pirate"],
  45: ["Cursed frigate", "frigate"],
  46: ["Swarm capital freighter", "swarm"],
  47: ["Swarm frigate", "swarm"],
  48: ["Swarm drone", "swarm"],
  49: ["Corvette", "corvette"],
};

/** The model of the ship at a system's Sentinel crash sites: a Sentinel ship's. */
export const CRASH_SITE_MODEL: PartModel = "SENTINELSHIP_PROC";

/** The models each type of ship is built from, as every capture shows. */
const TYPE_MODELS: Record<string, PartModel> = {
  Hauler: "DROPSHIP_PROC",
  Fighter: "FIGHTER_PROC",
  Explorer: "SCIENTIFIC_PROC",
  Shuttle: "SHUTTLE_PROC",
  Solar: "SAILSHIP_PROC",
  Exotic: "S-CLASS_PROC",
  Freighter: "FREIGHTER_PROC",
  "Capital freighter": "CAPITALFREIGHTER_PROC",
  "Small freighter": "FREIGHTERSMALL_PROC",
  "Tiny freighter": "FREIGHTERTINY_PROC",
  "Sentinel ship": "SENTINELSHIP_PROC",
  "Sentinel freighter": "POLICEFREIGHTER",
  "Pirate fighter": "FIGHTER_PROC",
  "Pirate capital freighter": "PIRATEFREIGHTER",
};

/**
 * The models whose paint the site works out for the types without picked
 * parts: each frigate's closest level of detail, the swarm's frigate and
 * drone. The game paints no layer of the recon frigate, the DeepSpace organic
 * frigate, the swarm's capital freighter or the corvette; the DeepSpaceCommon
 * organic frigate's paint needs parts the site doesn't pick.
 */
const PAINT_ONLY_MODELS: Record<string, PaintModel> = {
  "Combat frigate": "COMBATFRIGATELOD0",
  "Exploration frigate": "SCIENCEFRIGATELOD0",
  "Industrial frigate": "INDUSTRIALFRIGATELOD0",
  "Trade frigate": "DIPLOMATICFRIGATELOD0",
  "Support frigate": "SUPPORTFRIGATELOD0",
  "Raider frigate": "PIRATECRUISERLOD0",
  "Pirate frigate": "PIRATECRUISERLOD0",
  "Cursed frigate": "GHOSTSHIPFRIGATELOD0",
  "Swarm frigate": "SWARMFRIGATE",
  "Swarm drone": "SWARM",
};

/** The model a ship of this type ("Fighter", "Solar", ...) is built from, if it has picked parts. */
export function typeModels(type: string): PartModel[] {
  const model = TYPE_MODELS[type];
  return model ? [model] : [];
}

/** The model whose paint the site works out for a ship of this type: its model, or a frigate's closest detail. */
export function typePaints(type: string): PaintModel[] {
  const model = TYPE_MODELS[type] ?? PAINT_ONLY_MODELS[type];
  return model ? [model] : [];
}

/** The slot of the Sentinel ship, which the game paints with the texture hint POLICE. */
const SENTINEL_SLOT = 35;

/**
 * The type the game puts in each of the 50 slots, before it makes some of the
 * civilian ships solar (see civilianType). Only the first 20, the civilian
 * ships, vary, with the dominant race (0 for an uncharted system): as many
 * haulers, fighters and explorers as the race's weights in the game's solar
 * generation globals give, then shuttles.
 */
export function slotTypes(dominantRace: number): (readonly [string, ShipGroup])[] {
  const [haulers, fighters, explorers] = CIVILIAN_BY_RACE[dominantRace] ?? CIVILIAN_BY_RACE[0]!;
  const civilian = [
    ...Array<string>(haulers).fill("Hauler"),
    ...Array<string>(fighters).fill("Fighter"),
    ...Array<string>(explorers).fill("Explorer"),
  ];
  while (civilian.length < 20) civilian.push("Shuttle");
  return Array.from({ length: SHIP_COUNT }, (_, slot) =>
    slot < 20 ? ([civilian[slot]!, "civilian"] as const) : FIXED_SLOTS[slot]!,
  );
}

// --- Which civilian ships the game makes solar ---

/**
 * How likely the game is to make a civilian ship solar, its pirates' class,
 * from its solar generation globals, in single precision:
 * PirateClassShipOverrideProbability for a shuttle, and in an outlaw system
 * for any other civilian ship; PirateClassShipOverrideProbabilityPirateSystem
 * for a shuttle in an outlaw system. Outside outlaw systems the game never
 * makes a hauler, fighter or explorer solar.
 */
const SOLAR_CHANCE = Math.fround(0.1);
const SOLAR_CHANCE_OUTLAW_SHUTTLE = Math.fround(0.85);
/** What the game hashes a ship's seed and its system's address with. */
const HASH_MULTIPLIER = 0x9ddfea08eb382d69n;
const MASK64 = 0xffffffffffffffffn;
/** What the game multiplies a draw by to make a fraction of it: 1 / (2^32 - 1). */
const DRAW_SCALE = 1 / 4294967295;

/**
 * The number the game compares with a chance to decide whether the civilian
 * ship with `seed`, in the system at universal address `ua`, is solar: the
 * first draw of a generator seeded with the two hashed together, as a
 * single-precision fraction.
 */
export function solarRoll(seed: bigint, ua: bigint): number {
  const a = ((ua ^ seed) * HASH_MULTIPLIER) & MASK64;
  const b = (((a >> 47n) ^ ua ^ a) * HASH_MULTIPLIER) & MASK64;
  const hashed = (((b >> 47n) ^ b) * HASH_MULTIPLIER) & MASK64;
  return Math.fround(seededPRNG(hashed).randi() * DRAW_SCALE);
}

/**
 * What the game makes the civilian ship with `seed` whose slot holds `type`
 * (see slotTypes): that type, or "Solar" if its roll (see solarRoll) comes in
 * under its chance.
 */
export function civilianType(type: string, seed: bigint, ua: bigint, outlaw: boolean): string {
  let chance = 0;
  if (type === "Shuttle") chance = outlaw ? SOLAR_CHANCE_OUTLAW_SHUTTLE : SOLAR_CHANCE;
  else if (outlaw) chance = SOLAR_CHANCE;
  return chance > 0 && solarRoll(seed, ua) < chance ? "Solar" : type;
}

/**
 * The system's 50 ships. A giant planet layout's bodies aren't modeled, but it
 * only occurs in purple systems, whose bodies are all prime planets and moons
 * and have no attractors.
 */
export function shipPool(code: bigint, galaxy: number): ShipPool {
  const systemCode = withPlanet(code, 0);
  const attributes = systemAttributes(systemCode, galaxy);
  const { bodies } = planetSeeds(systemCode, galaxy);
  const ua = universalAddress(systemCode, galaxy);
  const start = drawsBeforeShips(ua, bodies);
  const { ships, crashSite } = shipSeeds(ua, start);
  const exotic = ships[20]!;
  const slots = slotTypes(attributes.dominant_race);
  return {
    ships: ships.map((seed, slot) => {
      const [base, group] = slots[slot]!;
      const type = group === "civilian" ? civilianType(base, seed, ua, attributes.pirate) : base;
      return {
        slot,
        seed,
        type,
        group,
        models: typeModels(type),
        paints: typePaints(type),
        hint: slot === SENTINEL_SLOT ? "POLICE" : "",
        note: SLOT_NOTES[slot] ?? null,
      };
    }),
    exotic,
    exoticSquid: exoticSquid(exotic),
    crashSite,
    drawsBeforeShips: start,
  };
}
