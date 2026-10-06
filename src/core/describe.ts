// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One call that gathers everything the site shows about a system.

import { formatPortalCode, portalParts, toGalacticCoordinates, universalAddress, withPlanet } from "./address";
import { planetNameFromSeed } from "./planet";
import { regionName } from "./region";
import { shipPool, type ShipGroup, type SquidCall } from "./ships";
import { starCount } from "./stars";
import { planetSeeds, systemAttributesDetailed, systemName, type SystemAttributes } from "./system";
import { hex64 } from "./u64";

export const STAR_COLOURS = ["Yellow", "Green", "Blue", "Red", "Purple"] as const;
export const ECONOMIES = [
  "",
  "Trading",
  "Advanced Materials",
  "Scientific",
  "Mining",
  "Manufacturing",
  "Technology",
  "Power Generation",
] as const;
export const TIERS = ["", "Low", "Medium", "High"] as const;
export const RACES = ["None", "Gek", "Korvax", "Vy'keen"] as const;

/**
 * How often each field matches what players recorded in game, measured by
 * nms_namegen against 1,000 hand-recorded post-Origins systems (2026-08-23).
 */
export const MEASURED_ACCURACY = {
  starColour: 0.991,
  uncharted: 0.998,
  dominantRace: 0.991,
  conflict: 0.9903,
  economy: 0.9902,
  wealth: 0.989,
  planetCount: 0.988,
  planetAndMoonCounts: 0.984,
} as const;

/**
 * What the measurement above doesn't cover, checked against the capture mod's
 * records instead: the order of bodies and the outlaw flag matched the game
 * in all `systems` recorded, `outlawSystems` of them outlaw systems, and so
 * did `planetNames.matched` of the `planetNames.checked` planet names the
 * game generated while they were recorded.
 */
export const CAPTURE_CHECKS = { systems: 99, outlawSystems: 11, planetNames: { matched: 5755, checked: 5971 } } as const;

/**
 * How the ship prediction fares against the systems recorded in game with
 * the capture mod: every ship seed and the Sentinel crash-site seed right in
 * `matched` of `recorded` with the model's first guess, and in all the rest
 * with a planet's two moons the other way round. The model was worked out
 * from the first `workedOutFrom` of them; the rest were recorded after.
 * `twoMoons` counts those with a planet that has two moons, which
 * ShipsInfo.uncertain flags, and how many the first guess got.
 */
export const SHIP_ACCURACY = {
  matched: 94,
  recorded: 99,
  workedOutFrom: 66,
  twoMoons: { firstGuess: 5, recorded: 10 },
} as const;

/**
 * How the squid prediction fares against the exotics whose parts the capture
 * mod recorded as the game built them: every one of the `recorded` exotics,
 * `squids` of them squids, on the side of the line the prediction puts it.
 */
export const SQUID_CHECKS = { recorded: 40, squids: 9 } as const;

/**
 * How the star count fares against the game's own: the same in every one of
 * the `counted` systems whose stars the capture mod counted as the game does,
 * `several` of them with more than one star.
 */
export const STAR_CHECKS = { counted: 19, several: 2 } as const;

/**
 * The giant planets the capture mod has recorded (the game flags their systems
 * IsGiantSystem): `recorded` of them, `gas` gas giants (also IsGasGiantSystem)
 * and `lush` lush ones. Players have found giants of other biomes too; what
 * decides a giant's biome isn't known.
 */
export const GIANT_CHECKS = { recorded: 7, gas: 6, lush: 1 } as const;

/**
 * How often the civilian slots held a solar ship in the systems recorded:
 * [solar, slots] for the shuttle slots outside and inside outlaw systems,
 * and for the other civilian slots inside them. Outside outlaw systems
 * those never did.
 */
export const SOLAR_COUNTS = {
  shuttle: [66, 588],
  outlawShuttle: [66, 77],
  outlawOther: [13, 143],
} as const;

export interface ShipInfo {
  /** Position in the game's list, 0-49. */
  slot: number;
  type: string;
  group: ShipGroup;
  seed: string;
  /** What a player should know about this slot, if anything. */
  note: string | null;
}

export interface ShipsInfo {
  exotic: string;
  /** Whether the exotic is a squid. */
  exoticSquid: SquidCall;
  crashSite: string;
  /** All 50, in the game's order. */
  ships: ShipInfo[];
  /** Why the prediction may be wrong for this system, if a known gap in the model applies. */
  uncertain: string | null;
  /** The exotic and crash-site seeds for each other way a two-moon planet's moons can be arranged. */
  alternatives: { exotic: string; exoticSquid: SquidCall; crashSite: string }[];
}

export interface BodyInfo {
  /** 1-based position in generation order. The reference maps portal planet digit N to slot N (not yet verified in game). */
  index: number;
  seed: string;
  name: string;
  portalCode: string;
}

export interface SystemDescription {
  portalCode: string;
  galacticCoordinates: string;
  galaxy: number;
  systemIndex: number;
  name: string;
  region: string;
  starColour: (typeof STAR_COLOURS)[number];
  /** How many stars the system has: 1, or 2 in a binary system and 3 in a trinary one. */
  stars: 1 | 2 | 3;
  faction: string;
  economy: string;
  wealth: string;
  conflict: string;
  pirate: boolean;
  abandoned: boolean;
  uncharted: boolean;
  blackHole: boolean;
  atlasInterface: boolean;
  /**
   * One giant planet, every other body its moon: what nms_namegen calls the
   * gas-giant layout. Most such giants are gas giants, not all (see GIANT_CHECKS).
   */
  gasGiant: boolean;
  planetCount: number;
  moonCount: number;
  bodies: BodyInfo[];
  /** The ships predicted from the address. */
  ships: ShipsInfo;
  raw: SystemAttributes;
}

const seedText = (seed: bigint) => `0x${hex64(seed)}`;

function describeShips(code: bigint, galaxy: number): ShipsInfo {
  const pool = shipPool(code, galaxy);
  return {
    exotic: seedText(pool.exotic),
    exoticSquid: pool.exoticSquid,
    crashSite: seedText(pool.crashSite),
    ships: pool.ships.map(({ slot, type, group, seed, note }) => ({ slot, type, group, seed: seedText(seed), note })),
    uncertain: pool.uncertain,
    alternatives: pool.alternatives.map((a) => ({
      exotic: seedText(a.exotic),
      exoticSquid: a.exoticSquid,
      crashSite: seedText(a.crashSite),
    })),
  };
}

export function describeSystem(code: bigint, galaxy: number): SystemDescription {
  const systemCode = withPlanet(code, 0);
  const { attributes: a, anomaly } = systemAttributesDetailed(systemCode, galaxy);
  const seeds = planetSeeds(systemCode, galaxy);

  const race = RACES[a.dominant_race] ?? "Unknown";
  let faction: string;
  if (a.uncharted) faction = "Uncharted";
  else if (a.abandoned) faction = `Abandoned (${race})`;
  else faction = race;

  const bodies: BodyInfo[] = seeds.planet_seeds.map((seed, i) => ({
    index: i + 1,
    seed: seedText(seed),
    name: planetNameFromSeed(seed),
    portalCode: formatPortalCode(withPlanet(systemCode, i + 1)),
  }));

  return {
    portalCode: formatPortalCode(systemCode),
    galacticCoordinates: toGalacticCoordinates(systemCode),
    galaxy,
    systemIndex: portalParts(systemCode).system,
    name: systemName(systemCode, galaxy),
    region: regionName(systemCode, galaxy),
    starColour: STAR_COLOURS[a.star_type] ?? "Yellow",
    stars: starCount(universalAddress(systemCode, galaxy)),
    faction,
    economy: a.uncharted ? "None" : ECONOMIES[a.economy_type] ?? "Unknown",
    wealth: a.uncharted ? "None" : TIERS[a.wealth] ?? "Unknown",
    conflict: a.uncharted ? "None" : TIERS[a.conflict_level] ?? "Unknown",
    pirate: a.pirate,
    abandoned: a.abandoned,
    uncharted: a.uncharted,
    blackHole: anomaly === 2,
    atlasInterface: anomaly === 1,
    gasGiant: a.gas_giant,
    planetCount: seeds.planet_count,
    moonCount: seeds.moon_count,
    bodies,
    ships: describeShips(systemCode, galaxy),
    raw: a,
  };
}
