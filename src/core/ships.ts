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

import { withPlanet } from "./address";
import { PRNG } from "./prng";
import { planetSeeds, systemAttributes, type Body } from "./system";
import { MASK32, mix64, swap16 } from "./u64";

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
 * +x. A pair of moons gets the one layout seen so far, at +30 and -30 degrees
 * of elevation and azimuths 0 and the golden angle, written out exactly as
 * the Python model computes it. Another system's two moons were laid out
 * differently, so predictions that depend on a pair are flagged.
 */
const LONE_MOON: Vec3 = [225792, 0, 0];
const MOON_PAIR: readonly Vec3[] = [
  [195541.60797129598, 112895.99999999999, 0],
  [-144186.29608742514, -112895.99999999999, 132086.45830890225],
];

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
  /** The seed the game holds for the ship at this system's Sentinel crash sites. */
  crashSite: bigint;
  /** Draws the generator makes before the first ship's. */
  drawsBeforeShips: number;
  /** Why the prediction may be wrong, if a known gap in the model applies. */
  uncertain: string | null;
}

/** The generator state the game builds from a 64-bit seed. */
function seeded(seed: bigint): PRNG {
  const low = seed & MASK32;
  let high = (swap16(low) ^ low ^ (seed >> 32n)) & MASK32;
  if (high === 0n) high = 1n;
  return new PRNG((high << 32n) | low);
}

function distance(a: Vec3, b: Vec3): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function moonOffsets(bodies: readonly Body[]): Map<number, Vec3> {
  const moons = new Map<number, number[]>();
  bodies.forEach((body, k) => {
    if (body.parent >= 0) moons.set(body.parent, [...(moons.get(body.parent) ?? []), k]);
  });
  const offsets = new Map<number, Vec3>();
  for (const siblings of moons.values()) {
    if (siblings.length === 1) offsets.set(siblings[0]!, LONE_MOON);
    else siblings.forEach((k, j) => offsets.set(k, MOON_PAIR[j % MOON_PAIR.length]!));
  }
  return offsets;
}

/** Why a prediction for these bodies may be wrong, if a known gap in the model applies. */
export function shipUncertainty(bodies: readonly Body[]): string | null {
  for (let k = 0; k < bodies.length; k++) {
    const family = [k, ...bodies.flatMap((other, j) => (other.parent === k ? [j] : []))];
    if (family.length > 2 && !family.every((j) => bodies[j]!.prime)) {
      return "a planet with two moons, whose layout isn't known yet";
    }
  }
  return null;
}

/** How many draws the generator makes before the first ship's. */
export function drawsBeforeShips(ua: bigint, bodies: readonly Body[]): number {
  const offsets = moonOffsets(bodies);
  const rng = seeded(ua);
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
  const rng = seeded(ua);
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
 * civilian ships, vary: with the dominant race (0 for an uncharted system).
 * The game picks between a shuttle and a solar ship in a way not known yet.
 */
export function slotTypes(dominantRace: number): (readonly [string, ShipGroup])[] {
  const [haulers, fighters, explorers] = CIVILIAN_BY_RACE[dominantRace] ?? CIVILIAN_BY_RACE[0]!;
  const civilian = [
    ...Array<string>(haulers).fill("Hauler"),
    ...Array<string>(fighters).fill("Fighter"),
    ...Array<string>(explorers).fill("Explorer"),
  ];
  while (civilian.length < 20) civilian.push("Shuttle or solar");
  return Array.from({ length: SHIP_COUNT }, (_, slot) =>
    slot < 20 ? ([civilian[slot]!, "civilian"] as const) : FIXED_SLOTS[slot]!,
  );
}

/** The system's 50 ships, or null for a gas-giant layout, which isn't modelled yet. */
export function shipPool(code: bigint, galaxy: number): ShipPool | null {
  const systemCode = withPlanet(code, 0);
  const attributes = systemAttributes(systemCode, galaxy);
  if (attributes.gas_giant) return null;
  const { bodies } = planetSeeds(systemCode, galaxy);
  const ua = (((systemCode >> 32n) & 0xfffn) << 40n) | (BigInt(galaxy & 0xff) << 32n) | (systemCode & MASK32);
  const start = drawsBeforeShips(ua, bodies);
  const { ships, crashSite } = shipSeeds(ua, start);
  const types = slotTypes(attributes.dominant_race);
  return {
    ships: ships.map((seed, slot) => ({
      slot,
      seed,
      type: types[slot]![0],
      group: types[slot]![1],
      note: SLOT_NOTES[slot] ?? null,
    })),
    exotic: ships[20]!,
    crashSite,
    drawsBeforeShips: start,
    uncertain: shipUncertainty(bodies),
  };
}
