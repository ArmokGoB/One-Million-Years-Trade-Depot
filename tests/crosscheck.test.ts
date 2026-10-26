// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Differential test against the Python reference over many random addresses.
// Generate the input with:
//   python3 tools/crosscheck/generate.py --namegen <path> --count 20000 > crosscheck.jsonl
// then run:
//   CROSSCHECK_FILE=crosscheck.jsonl npm test
// Skipped when CROSSCHECK_FILE is not set.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  basePalettes,
  guildFor,
  hex64,
  hexColor,
  legacyPalettes,
  MULTITOOL_MODELS,
  multitoolRun,
  NAMED_MODELS,
  namedParts,
  PAINT_MODELS,
  paint,
  paletteSource,
  parsePortalCode,
  PART_MODELS,
  partsFor,
  planetName,
  planetNameFromSeed,
  planetSeeds,
  regionName,
  shipPool,
  starColors,
  starCount,
  systemAttributes,
  systemName,
  universalAddress,
  voxelAttributes,
  withPlanet,
  type PaintModel,
  type PartModel,
} from "../src/core";

const path = process.env.CROSSCHECK_FILE;

type Maybe<T> = T | string;
interface Case {
  code: string;
  galaxy: number;
  region: Maybe<string>;
  system: Maybe<string>;
  planet: Maybe<string>;
  sysattr: Maybe<Record<string, number | boolean>>;
  voxel: Maybe<Record<string, number>>;
  seeds: Maybe<string[]>;
  planet_count?: number;
  moon_count?: number;
  sizes?: number[];
  body_names?: string[];
  /** tools/captures/ship_model.py's prediction. */
  ships?: Maybe<ShipCase>;
  /** tools/captures/star_model.py's count. */
  stars?: number;
  /** tools/captures/star_model.py's color of each star, from nms_namegen's star type. */
  suns?: string[];
  /** tools/captures/guild_model.py's guild. */
  guild?: string;
  /** tools/captures/multitool_model.py's first run: [model file, seed]. */
  multitools?: [string, string][];
  /** tools/captures/parts_model.py's parts for one model with the system's first ship seed: [model, parts]. */
  parts?: [PartModel, string[]];
  /**
   * tools/captures/paint_model.py's paint of one model with that seed: [model, texture hint, each pass's
   * layers as "option:palette:alternative:color"], the color as hex, empty for none and for a layer not painted.
   */
  paint?: [PaintModel, string, string[][]];
  /**
   * tools/captures/part_names_model.py's names of one fighter's, hauler's, explorer's or solar's parts with
   * that seed: [model, each named slot as [side, name, the parts it's made of]].
   */
  names?: [PartModel, [string, string, string[]][]];
}

/** The port's paint in the shape generate.py writes. */
function paintCase(model: PaintModel, hint: string, seed: bigint, ua: bigint): string[][] {
  const source = paletteSource(model);
  const palettes = source === "legacy" ? legacyPalettes(seed) : basePalettes(source === "system" ? ua : seed);
  const parts = (PART_MODELS as string[]).includes(model) ? partsFor(model as PartModel, seed) : [];
  return paint(model, parts, seed, palettes, hint).map((layers) =>
    layers.map((l) => `${l.option}:${l.palette}:${l.alt}:${l.painted && l.color ? hexColor(l.color).slice(1) : ""}`),
  );
}

interface ShipCase {
  bodies: [number, number, boolean][];
  start: number;
  uncertain: string | null;
  first: string;
  exotic: string;
  /** Whether the exotic is a squid. */
  squid: boolean;
  crash: string;
  last: string;
  /** [start, exotic, crash] for each other arrangement of a two-moon planet's moons. */
  others: [number, string, string][];
  /** The slots of the civilian ships the game makes solar. */
  solar: number[];
}

/** The port's ship pool in the shape generate.py writes, key order included. */
function shipCase(code: bigint, galaxy: number): ShipCase {
  const pool = shipPool(code, galaxy);
  return {
    bodies: planetSeeds(withPlanet(code, 0), galaxy).bodies.map((b) => [b.size, b.parent, b.prime]),
    start: pool.drawsBeforeShips,
    uncertain: pool.uncertain,
    first: hex64(pool.ships[0]!.seed),
    exotic: hex64(pool.exotic),
    squid: pool.exoticSquid,
    crash: hex64(pool.crashSite),
    last: hex64(pool.ships[49]!.seed),
    others: pool.alternatives.map((a) => [a.drawsBeforeShips, hex64(a.exotic), hex64(a.crashSite)]),
    solar: pool.ships.flatMap((s, slot) => (s.type === "Solar" ? [slot] : [])),
  };
}

const isErr = (v: unknown): v is string => typeof v === "string" && v.startsWith("ERR:");

function same(expected: unknown, actual: () => unknown, label: string, mismatches: string[]): void {
  let got: unknown;
  try {
    got = actual();
  } catch (e) {
    got = `ERR:${(e as Error).message.split(":")[0]}`;
  }
  const ok = isErr(expected) ? isErr(got) : JSON.stringify(got) === JSON.stringify(expected);
  if (!ok) mismatches.push(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(got)}`);
}

describe.skipIf(!path)("crosscheck against the Python reference", () => {
  it("matches on every case", () => {
    const lines = readFileSync(path!, "utf8").split("\n").filter(Boolean);
    const mismatches: string[] = [];
    let shipPools = 0;
    let squids = 0;
    let solars = 0;
    const starCounts = [0, 0, 0, 0];
    const sunsSeen = new Set<string>();
    const guilds = new Map<string, number>();
    const standardCounts = new Map<number, number>();
    const partModels = new Set<string>();
    const paintModels = new Set<string>();
    const namedModels = new Set<string>();
    for (const line of lines) {
      const c = JSON.parse(line) as Case;
      const code = parsePortalCode(c.code);
      const tag = `${c.code}/g${c.galaxy}`;
      same(c.region, () => regionName(code, c.galaxy), `${tag} region`, mismatches);
      same(c.system, () => systemName(code, c.galaxy), `${tag} system`, mismatches);
      same(c.planet, () => planetName(code, c.galaxy), `${tag} planet`, mismatches);
      same(c.sysattr, () => systemAttributes(code, c.galaxy), `${tag} sysattr`, mismatches);
      same(c.voxel, () => voxelAttributes(code), `${tag} voxel`, mismatches);
      same(c.seeds, () => planetSeeds(code, c.galaxy).planet_seeds.map(hex64), `${tag} seeds`, mismatches);
      if (!isErr(c.seeds)) {
        const s = planetSeeds(code, c.galaxy);
        same(c.planet_count!, () => s.planet_count, `${tag} planet_count`, mismatches);
        same(c.moon_count!, () => s.moon_count, `${tag} moon_count`, mismatches);
        same(c.sizes!, () => s.sizes, `${tag} sizes`, mismatches);
        same(c.body_names!, () => s.planet_seeds.map(planetNameFromSeed), `${tag} body names`, mismatches);
      }
      if (c.ships !== undefined) {
        same(c.ships, () => shipCase(code, c.galaxy), `${tag} ships`, mismatches);
        if (!isErr(c.ships)) {
          shipPools += 1;
          if (c.ships.squid) squids += 1;
          solars += c.ships.solar.length;
        }
      }
      if (c.stars !== undefined) {
        same(c.stars, () => starCount(universalAddress(code, c.galaxy)), `${tag} stars`, mismatches);
        starCounts[c.stars] = (starCounts[c.stars] ?? 0) + 1;
      }
      if (c.suns !== undefined) {
        const ua = universalAddress(code, c.galaxy);
        const sunColors = () => starColors(systemAttributes(code, c.galaxy).star_type, starCount(ua));
        same(c.suns, sunColors, `${tag} suns`, mismatches);
        for (const sun of c.suns) sunsSeen.add(sun);
      }
      if (c.guild !== undefined) {
        same(c.guild, () => guildFor(universalAddress(code, c.galaxy)), `${tag} guild`, mismatches);
        guilds.set(c.guild, (guilds.get(c.guild) ?? 0) + 1);
      }
      if (c.multitools !== undefined) {
        const run = () =>
          multitoolRun(universalAddress(code, c.galaxy)).map((t) => [MULTITOOL_MODELS[t.kind], hex64(t.seed)]);
        same(c.multitools, run, `${tag} multitools`, mismatches);
        const standard = c.multitools.filter(([file]) => file === "MULTITOOL").length;
        standardCounts.set(standard, (standardCounts.get(standard) ?? 0) + 1);
      }
      if (c.parts !== undefined && !isErr(c.ships)) {
        const [model, parts] = c.parts;
        const seed = BigInt(`0x${(c.ships as ShipCase).first}`);
        same(parts, () => partsFor(model, seed), `${tag} ${model} parts`, mismatches);
        partModels.add(model);
      }
      if (c.paint !== undefined && !isErr(c.ships)) {
        const [model, hint, layers] = c.paint;
        const seed = BigInt(`0x${(c.ships as ShipCase).first}`);
        const ua = universalAddress(withPlanet(code, 0), c.galaxy);
        same(layers, () => paintCase(model, hint, seed, ua), `${tag} ${model} paint`, mismatches);
        paintModels.add(model);
      }
      if (c.names !== undefined && !isErr(c.ships)) {
        const [model, names] = c.names;
        const seed = BigInt(`0x${(c.ships as ShipCase).first}`);
        const port = () => namedParts(model, seed).map((n) => [n.side, n.name, n.parts]);
        same(names, port, `${tag} ${model} names`, mismatches);
        namedModels.add(model);
      }
    }
    expect(lines.length).toBeGreaterThan(0);
    expect(shipPools, "cases with a predicted ship pool").toBeGreaterThan(lines.length / 2);
    expect(squids, "cases whose exotic is a squid").toBeGreaterThan(0);
    expect(solars, "civilian ships made solar").toBeGreaterThan(shipPools);
    expect(starCounts.slice(1), "cases with one, two and three stars").not.toContain(0);
    expect([...sunsSeen].sort(), "star colors seen").toEqual(["Blue", "Green", "Purple", "Red", "Yellow"]);
    expect([...guilds.keys()].sort(), "cases with each guild").toEqual(["Explorers", "Mercenaries", "Merchants"]);
    expect([...standardCounts.keys()].sort(), "cases with 2, 3 and 4 standard multi-tools").toEqual([2, 3, 4]);
    expect([...partModels].sort(), "models whose parts were compared").toEqual([...PART_MODELS].sort());
    expect([...paintModels].sort(), "models whose paint was compared").toEqual([...PAINT_MODELS].sort());
    expect([...namedModels].sort(), "models whose names were compared").toEqual([...NAMED_MODELS].sort());
    expect(mismatches.slice(0, 20)).toEqual([]);
  }, 300_000); // 20,000 cases take seconds, mostly the ship pools
});
