// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One call that gathers everything the site shows about a system.

import { formatPortalCode, portalParts, toGalacticCoordinates, universalAddress, withPlanet } from "./address";
import { colorName, hexColor } from "./colornames";
import { guildFor, type Guild } from "./guild";
import { MULTITOOL_MODELS, multitoolRun, type MultitoolKind } from "./multitools";
import {
  basePalettes,
  legacyPalettes,
  paint,
  paintColors,
  paletteSource,
  type PaintModel,
  type Palettes,
} from "./paint";
import { namedParts, type Side } from "./partnames";
import { distinguishingParts, PART_MODELS, partsFor, type PartModel } from "./parts";
import { planetNameFromSeed } from "./planet";
import { regionName } from "./region";
import { CRASH_SITE_MODEL, shipPool, type ShipGroup } from "./ships";
import { STAR_COLORS, starColors, starCount, type StarColor } from "./stars";
import { planetSeeds, systemAttributesDetailed, systemName, type SystemAttributes } from "./system";
import { hex64 } from "./u64";

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

/** What each model with parts or paint is, as a type of ship or multi-tool. */
export const MODEL_NAMES: Record<PaintModel, string> = {
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
  FREIGHTERSMALL_PROC: "Small freighter",
  FREIGHTERTINY_PROC: "Tiny freighter",
  POLICEFREIGHTER: "Sentinel freighter",
  PIRATEFREIGHTER: "Pirate capital freighter",
  COMBATFRIGATELOD0: "Combat frigate",
  SCIENCEFRIGATELOD0: "Exploration frigate",
  INDUSTRIALFRIGATELOD0: "Industrial frigate",
  DIPLOMATICFRIGATELOD0: "Trade frigate",
  SUPPORTFRIGATELOD0: "Support frigate",
  GHOSTSHIPFRIGATELOD0: "Cursed frigate",
  PIRATECRUISERLOD0: "Pirate frigate",
  SWARMFRIGATE: "Swarm frigate",
  SWARM: "Swarm drone",
};

/** A color the game paints with, and its name. */
export interface ColorInfo {
  /** As CSS: "#rrggbb". */
  hex: string;
  /** In words (see colorName), e.g. "dark teal". */
  name: string;
}

/** A part of a ship as the game names it (see namedParts). */
export interface PartNameInfo {
  /** As the game names it, in its English, e.g. "Omega Fuselage". */
  name: string;
  /** Which of an explorer's wings it is, "left" or "right"; "" for any other part. */
  side: Side;
  /** The part IDs it's made of that tell ships apart (see BuildInfo.parts); possibly none. */
  parts: string[];
}

/** A model a ship or multi-tool is built from: the parts that tell it apart, and the colors of its paint. */
export interface BuildInfo {
  /** The model's name (see MODEL_NAMES), e.g. "Shuttle". */
  model: string;
  /** Part IDs as the game lists them, e.g. "_COCKPIT_E" (see distinguishingParts); none for a frigate. */
  parts: string[];
  /**
   * The parts the game names, for a fighter, hauler, explorer or solar: one
   * for each slot the Starship Fabricator fills, but for the few the game
   * leaves unnamed. Part IDs in `parts` that none of them is made of have no
   * name.
   */
  names: PartNameInfo[];
  /** Its paint's colors, each once, the hull's before the decals' (see paintColors); none if the game paints none. */
  colors: ColorInfo[];
}

export interface ShipInfo {
  /** Position in the game's list, 0-49. */
  slot: number;
  type: string;
  group: ShipGroup;
  seed: string;
  /**
   * Its parts and colors, for each model the ship could be built from (two
   * where it's one or the other); none where the site works out neither.
   */
  builds: BuildInfo[];
  /** What a player should know about this slot, if anything. */
  note: string | null;
}

export interface ShipsInfo {
  exotic: string;
  /** Whether the exotic is a squid. */
  exoticSquid: boolean;
  exoticParts: string[];
  exoticColors: ColorInfo[];
  crashSite: string;
  crashSiteParts: string[];
  crashSiteColors: ColorInfo[];
  /** All 50, in the game's order. */
  ships: ShipInfo[];
  /** Why the prediction may be wrong for this system, if a known gap in the model applies. */
  uncertain: string | null;
  /** The exotic and crash-site ship for each other way a two-moon planet's moons can be arranged. */
  alternatives: {
    exotic: string;
    exoticSquid: boolean;
    exoticParts: string[];
    exoticColors: ColorInfo[];
    crashSite: string;
    crashSiteParts: string[];
    crashSiteColors: ColorInfo[];
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
  starColor: StarColor;
  /** How many stars the system has: 1, or 2 in a binary system and 3 in a trinary one. */
  stars: 1 | 2 | 3;
  /** The color of each of its stars, the main one's first (see starColors). */
  starColors: StarColor[];
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
  multitools: { kind: MultitoolKind; seed: string; parts: string[]; colors: ColorInfo[] }[];
  raw: SystemAttributes;
}

const seedText = (seed: bigint) => `0x${hex64(seed)}`;

const isPartModel = (model: PaintModel): model is PartModel => (PART_MODELS as string[]).includes(model);

/** A model's parts that tell it apart, and the names the game gives its parts, each with the IDs it's made of. */
function partsAndNames(model: PaintModel, seed: bigint): Pick<BuildInfo, "parts" | "names"> {
  if (!isPartModel(model)) return { parts: [], names: [] };
  const parts = distinguishingParts(model, seed);
  const names = namedParts(model, seed).map(({ name, side, parts: made }) => ({
    name,
    side,
    parts: parts.filter((part) => made.includes(part)),
  }));
  return { parts, names };
}

/**
 * The colors of a system's ships and multi-tools, each model's palettes made
 * once: a ship's from its own seed, the fleet's from the system's address and
 * a multi-tool's from its own seed the older way (see paletteSource).
 */
class Painter {
  private readonly made = new Map<string, Palettes>();

  constructor(private readonly ua: bigint) {}

  private palettes(model: PaintModel, seed: bigint): Palettes {
    const source = paletteSource(model);
    const from = source === "system" ? this.ua : seed;
    const key = `${source === "legacy" ? "legacy" : "base"} ${from}`;
    let palettes = this.made.get(key);
    if (!palettes) {
      palettes = source === "legacy" ? legacyPalettes(from) : basePalettes(from);
      this.made.set(key, palettes);
    }
    return palettes;
  }

  colors(model: PaintModel, seed: bigint, hint = ""): ColorInfo[] {
    const parts = isPartModel(model) ? partsFor(model, seed) : [];
    const passes = paint(model, parts, seed, this.palettes(model, seed), hint);
    return paintColors(passes).map((color) => ({ hex: hexColor(color), name: colorName(color) }));
  }
}

function describeShips(code: bigint, galaxy: number, painter: Painter): ShipsInfo {
  const pool = shipPool(code, galaxy);
  return {
    exotic: seedText(pool.exotic),
    exoticSquid: pool.exoticSquid,
    exoticParts: distinguishingParts("S-CLASS_PROC", pool.exotic),
    exoticColors: painter.colors("S-CLASS_PROC", pool.exotic),
    crashSite: seedText(pool.crashSite),
    crashSiteParts: distinguishingParts(CRASH_SITE_MODEL, pool.crashSite),
    crashSiteColors: painter.colors(CRASH_SITE_MODEL, pool.crashSite),
    ships: pool.ships.map(({ slot, type, group, seed, paints, hint, note }) => ({
      slot,
      type,
      group,
      seed: seedText(seed),
      builds: paints.map((model) => ({
        model: MODEL_NAMES[model],
        ...partsAndNames(model, seed),
        colors: painter.colors(model, seed, hint),
      })),
      note,
    })),
    uncertain: pool.uncertain,
    alternatives: pool.alternatives.map((a) => ({
      exotic: seedText(a.exotic),
      exoticSquid: a.exoticSquid,
      exoticParts: distinguishingParts("S-CLASS_PROC", a.exotic),
      exoticColors: painter.colors("S-CLASS_PROC", a.exotic),
      crashSite: seedText(a.crashSite),
      crashSiteParts: distinguishingParts(CRASH_SITE_MODEL, a.crashSite),
      crashSiteColors: painter.colors(CRASH_SITE_MODEL, a.crashSite),
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
  const painter = new Painter(ua);
  const stars = starCount(ua);
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
    stars,
    starColors: starColors(a.star_type, stars),
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
    ships: describeShips(systemCode, galaxy, painter),
    guild: guildFor(ua),
    multitools: multitoolRun(ua).map(({ kind, seed }) => ({
      kind,
      seed: seedText(seed),
      parts: distinguishingParts(MULTITOOL_MODELS[kind], seed),
      colors: painter.colors(MULTITOOL_MODELS[kind], seed),
    })),
    raw: a,
  };
}
