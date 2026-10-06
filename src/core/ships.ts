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
// Whether the exotic is a squid comes from the exotic's own seed: see
// exoticSquid().

import { universalAddress, withPlanet } from "./address";
import { seededPRNG } from "./prng";
import { planetSeeds, systemAttributes, type Body } from "./system";
import { mix64 } from "./u64";

/** Base radius of a planet's attractor shell, by size (0 large, 1 medium, 2 small, 3 moon). */
const BASE_RADIUS: readonly number[] = [195072, 147456, 96768, 23040];
const SHELL = 40000;
const CLEARANCE = 500;
const STATION_DRAWS = 38;
const TAIL_DRAWS = 3;
const SHIP_COUNT = 50;
const CRASH_BEFORE = 42;

type Vec3 = readonly [number, number, number];

/**
 * Where a moon sits relative to its parent: 225,792 away, a lone moon along
 * +x. A planet's two moons sit at +30 and -30 degrees of elevation, the first
 * above, at azimuths 0 and the golden angle (137.5 degrees); which of the two
 * gets which azimuth varies in a way not worked out yet. Written out exactly
 * as the Python model computes them.
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
  /** What a player should know about this slot, if anything, e.g. that it never turns up in systems. */
  note: string | null;
}

export interface ShipPool {
  /** All 50, in the game's order. */
  ships: Ship[];
  /** The exotic's seed (always slot 20). */
  exotic: bigint;
  /** Whether the exotic is a squid. */
  exoticSquid: SquidCall;
  /** The seed the game holds for the ship at this system's Sentinel crash sites. */
  crashSite: bigint;
  /** Draws the generator makes before the first ship's. */
  drawsBeforeShips: number;
  /** Why the prediction may be wrong, if a known gap in the model applies. */
  uncertain: string | null;
  /**
   * The ship seeds for each other way the system's two-moon planets can have
   * their moons arranged. Empty unless a planet that isn't prime has two moons.
   */
  alternatives: Alternative[];
}

export interface Alternative {
  /** The planets whose two moons are the other way round. */
  swapped: number[];
  ships: bigint[];
  exotic: bigint;
  exoticSquid: SquidCall;
  crashSite: bigint;
  drawsBeforeShips: number;
}

export interface SquidCall {
  /** Whether the game makes the exotic with this seed a squid. */
  squid: boolean;
  /**
   * The seed's first draw lies in the narrow stretch where the line between
   * squids and other exotics could still be, so `squid` rests on where it
   * most likely is rather than on exotics recorded on both sides.
   */
  close: boolean;
}

function distance(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** Each moon's position relative to its parent; the planets in `swapped` have their two moons the other way round. */
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

/** The planets that aren't prime and have two moons, whose arrangement the model can't tell. */
export function twoMoonPlanets(bodies: readonly Body[]): number[] {
  return bodies.flatMap((body, k) =>
    !body.prime && bodies.filter((other) => other.parent === k).length === 2 ? [k] : [],
  );
}

/** Why a prediction for these bodies may be wrong, if a known gap in the model applies. */
export function shipUncertainty(bodies: readonly Body[]): string | null {
  const planets = twoMoonPlanets(bodies).length; // at most two: a system has six bodies at most
  if (planets === 1) return "a planet with two moons, which the game arranges in one of two ways";
  if (planets) return "two planets with two moons each, which the game arranges in one of two ways";
  return null;
}

/**
 * How many draws the generator makes before the first ship's, with the two
 * moons of the planets in `swapped` the other way round.
 */
export function drawsBeforeShips(ua: bigint, bodies: readonly Body[], swapped: ReadonlySet<number> = new Set()): number {
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

/**
 * Among the exotics recorded in game so far, the highest first draw (see
 * firstDraw) of one that isn't a squid, and the lowest of a squid. Where
 * exactly the line lies between the two isn't known yet.
 */
export const SQUID_EDGES = { notSquid: 4088215205, squid: 4093481076 } as const;

/** The first draw the game makes from a ship's seed, which picks the first part of the ship's model. */
export function firstDraw(seed: bigint): number {
  return seededPRNG(seed).randi();
}

/**
 * Whether the exotic with this seed is a squid. The game picks the first part
 * of a ship's model with the first draw from the ship's seed, each option
 * taking its own stretch of the draw's range: for an exotic, the squid's body
 * near the top of the range and the other exotics' body below it. The line is
 * drawn at 20/21 of the range, the squid weighted 0.05 against the other's 1,
 * the likeliest place for it between SQUID_EDGES.
 */
export function exoticSquid(seed: bigint): SquidCall {
  const draw = firstDraw(seed);
  return {
    squid: 21 * draw >= 20 * 2 ** 32,
    close: draw > SQUID_EDGES.notSquid && draw < SQUID_EDGES.squid,
  };
}

// --- What each slot holds, as seen in every system recorded so far ---

/** Haulers, fighters and explorers from slot 0 on, by dominant race; shuttles or solars fill up to slot 19. */
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

/**
 * The type the game puts in each of the 50 slots. Only the first 20, the
 * civilian ships, vary: with the dominant race (0 for an uncharted system),
 * and with whether outlaws control the system. The game makes some of them
 * solar ships, in a way not worked out yet: about 1 in 10 shuttles, and in
 * outlaw systems most shuttles and about 1 in 10 of the other civilian ships.
 */
export function slotTypes(dominantRace: number, outlaw = false): (readonly [string, ShipGroup])[] {
  const [haulers, fighters, explorers] = CIVILIAN_BY_RACE[dominantRace] ?? CIVILIAN_BY_RACE[0]!;
  const maybeSolar = (type: string) => (outlaw ? `${type} or solar` : type);
  const civilian = [
    ...Array<string>(haulers).fill(maybeSolar("Hauler")),
    ...Array<string>(fighters).fill(maybeSolar("Fighter")),
    ...Array<string>(explorers).fill(maybeSolar("Explorer")),
  ];
  while (civilian.length < 20) civilian.push(outlaw ? "Solar or shuttle" : "Shuttle or solar");
  return Array.from({ length: SHIP_COUNT }, (_, slot) =>
    slot < 20 ? ([civilian[slot]!, "civilian"] as const) : FIXED_SLOTS[slot]!,
  );
}

/**
 * The system's 50 ships. Where a planet has two moons, the model's first
 * guess at their arrangement, with the ships for the others as alternatives.
 * A giant planet layout's bodies aren't modelled, but it only occurs in purple
 * systems, whose bodies are all prime planets and moons and have no attractors.
 */
export function shipPool(code: bigint, galaxy: number): ShipPool {
  const systemCode = withPlanet(code, 0);
  const attributes = systemAttributes(systemCode, galaxy);
  const { bodies } = planetSeeds(systemCode, galaxy);
  const ua = universalAddress(systemCode, galaxy);
  const planets = twoMoonPlanets(bodies);
  // In the Python model's order: the last planet's moons flip first.
  const arrangements = Array.from({ length: 2 ** planets.length }, (_, n) =>
    planets.filter((_, i) => (n >> (planets.length - 1 - i)) & 1),
  );
  const [first, ...others] = arrangements.map((swapped) => {
    const start = drawsBeforeShips(ua, bodies, new Set(swapped));
    const { ships, crashSite } = shipSeeds(ua, start);
    const exotic = ships[20]!;
    return { swapped, ships, exotic, exoticSquid: exoticSquid(exotic), crashSite, drawsBeforeShips: start };
  });
  const types = slotTypes(attributes.dominant_race, attributes.pirate);
  return {
    ships: first!.ships.map((seed, slot) => ({
      slot,
      seed,
      type: types[slot]![0],
      group: types[slot]![1],
      note: SLOT_NOTES[slot] ?? null,
    })),
    exotic: first!.exotic,
    exoticSquid: first!.exoticSquid,
    crashSite: first!.crashSite,
    drawsBeforeShips: first!.drawsBeforeShips,
    uncertain: shipUncertainty(bodies),
    alternatives: others,
  };
}
