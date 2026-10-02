// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One call that gathers everything the site shows about a system.

import { formatPortalCode, portalParts, toGalacticCoordinates, withPlanet } from "./address";
import { planetNameFromSeed } from "./planet";
import { regionName } from "./region";
import { shipPool, type ShipGroup, type SquidCall } from "./ships";
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
export const CAPTURE_CHECKS = { systems: 66, outlawSystems: 9, planetNames: { matched: 2417, checked: 2497 } } as const;

/**
 * How the ship prediction fares against the systems recorded in game with
 * the capture mod: every ship seed and the Sentinel crash-site seed right in
 * `matched` of `recorded` with the model's first guess, and in all the rest
 * with a planet's two moons the other way round. The model was worked out
 * from these same systems. `twoMoons` counts those with a planet that has two
 * moons, which ShipsInfo.uncertain flags, and how many the first guess got.
 */
export const SHIP_ACCURACY = { matched: 62, recorded: 66, twoMoons: { firstGuess: 3, recorded: 7 } } as const;

/**
 * How the squid prediction fares against the exotics whose parts the capture
 * mod recorded as the game built them: every one of the `recorded` exotics,
 * `squids` of them squids, on the side of the line the prediction puts it.
 */
export const SQUID_CHECKS = { recorded: 12, squids: 6 } as const;

/**
 * How often the civilian slots held a solar ship in the systems recorded:
 * [solar, slots] for the shuttle slots outside and inside outlaw systems,
 * and for the other civilian slots inside them. Outside outlaw systems
 * those never did.
 */
export const SOLAR_COUNTS = {
  shuttle: [42, 375],
  outlawShuttle: [54, 63],
  outlawOther: [11, 117],
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
  faction: string;
  economy: string;
  wealth: string;
  conflict: string;
  pirate: boolean;
  abandoned: boolean;
  uncharted: boolean;
  blackHole: boolean;
  atlasInterface: boolean;
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
