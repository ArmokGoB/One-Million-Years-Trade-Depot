// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One call that gathers everything the site shows about a system.

import { formatPortalCode, portalParts, toGalacticCoordinates, universalAddress, withPlanet } from "./address";
import { guildFor, type Guild } from "./guild";
import { MULTITOOL_MODELS, multitoolRun, type MultitoolKind } from "./multitools";
import { distinguishingParts, type PartModel } from "./parts";
import { planetNameFromSeed } from "./planet";
import { regionName } from "./region";
import { CRASH_SITE_MODEL, shipPool, type ShipGroup } from "./ships";
import { starCount } from "./stars";
import { planetSeeds, systemAttributesDetailed, systemName, type SystemAttributes } from "./system";
import { hex64 } from "./u64";

export const STAR_COLORS = ["Yellow", "Green", "Blue", "Red", "Purple"] as const;
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

/** What each model with parts is, as a type of ship or multi-tool. */
export const MODEL_NAMES: Record<PartModel, string> = {
  FIGHTER_PROC: "Fighter",
  DROPSHIP_PROC: "Hauler",
  SCIENTIFIC_PROC: "Explorer",
  SHUTTLE_PROC: "Shuttle",
  SAILSHIP_PROC: "Solar",
  "S-CLASS_PROC": "Exotic",
  SENTINELSHIP_PROC: "Sentinel ship",
  FREIGHTER_PROC: "Freighter",
  CAPITALFREIGHTER_PROC: "Capital freighter",
  MULTITOOL: "Standard multi-tool",
  ROYALMULTITOOL: "Royal multi-tool",
  SENTINELMULTITOOL: "Sentinel multi-tool",
  ATLASMULTITOOL: "Atlas multi-tool",
};

/** The parts that tell a ship or multi-tool apart from others built from the same model (see distinguishingParts). */
export interface PartsInfo {
  /** The model's name (see MODEL_NAMES), e.g. "Shuttle". */
  model: string;
  /** Part IDs as the game lists them, e.g. "_COCKPIT_E". */
  parts: string[];
}

export interface ShipInfo {
  /** Position in the game's list, 0-49. */
  slot: number;
  type: string;
  group: ShipGroup;
  seed: string;
  /** Its parts, for each model the ship could be built from (two where it's one or the other); none for frigates. */
  parts: PartsInfo[];
  /** What a player should know about this slot, if anything. */
  note: string | null;
}

export interface ShipsInfo {
  exotic: string;
  /** Whether the exotic is a squid. */
  exoticSquid: boolean;
  exoticParts: string[];
  crashSite: string;
  crashSiteParts: string[];
  /** All 50, in the game's order. */
  ships: ShipInfo[];
  /** Why the prediction may be wrong for this system, if a known gap in the model applies. */
  uncertain: string | null;
  /** The exotic and crash-site ship for each other way a two-moon planet's moons can be arranged. */
  alternatives: {
    exotic: string;
    exoticSquid: boolean;
    exoticParts: string[];
    crashSite: string;
    crashSiteParts: string[];
  }[];
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
  starColor: (typeof STAR_COLORS)[number];
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
   * gas-giant layout. Most such giants are gas giants, not all.
   */
  gasGiant: boolean;
  planetCount: number;
  moonCount: number;
  bodies: BodyInfo[];
  /** The ships predicted from the address. */
  ships: ShipsInfo;
  /** The guild whose envoy the system's space station has (the same throughout a region). */
  guild: Guild;
  /**
   * The first run of the system's own multi-tools, in the game's order: 2 to 4
   * standard ones, then the royal, the Sentinel and the Atlas one. Three more
   * standard ones follow, from a seed not worked out (see multitools.ts).
   */
  multitools: { kind: MultitoolKind; seed: string; parts: string[] }[];
  raw: SystemAttributes;
}

const seedText = (seed: bigint) => `0x${hex64(seed)}`;

function describeShips(code: bigint, galaxy: number): ShipsInfo {
  const pool = shipPool(code, galaxy);
  return {
    exotic: seedText(pool.exotic),
    exoticSquid: pool.exoticSquid,
    exoticParts: distinguishingParts("S-CLASS_PROC", pool.exotic),
    crashSite: seedText(pool.crashSite),
    crashSiteParts: distinguishingParts(CRASH_SITE_MODEL, pool.crashSite),
    ships: pool.ships.map(({ slot, type, group, seed, models, note }) => ({
      slot,
      type,
      group,
      seed: seedText(seed),
      parts: models.map((model) => ({ model: MODEL_NAMES[model], parts: distinguishingParts(model, seed) })),
      note,
    })),
    uncertain: pool.uncertain,
    alternatives: pool.alternatives.map((a) => ({
      exotic: seedText(a.exotic),
      exoticSquid: a.exoticSquid,
      exoticParts: distinguishingParts("S-CLASS_PROC", a.exotic),
      crashSite: seedText(a.crashSite),
      crashSiteParts: distinguishingParts(CRASH_SITE_MODEL, a.crashSite),
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

  const ua = universalAddress(systemCode, galaxy);
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
    starColor: STAR_COLORS[a.star_type] ?? "Yellow",
    stars: starCount(ua),
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
    guild: guildFor(ua),
    multitools: multitoolRun(ua).map(({ kind, seed }) => ({
      kind,
      seed: seedText(seed),
      parts: distinguishingParts(MULTITOOL_MODELS[kind], seed),
    })),
    raw: a,
  };
}
