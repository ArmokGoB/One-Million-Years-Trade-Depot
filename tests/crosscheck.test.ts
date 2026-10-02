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
  hex64,
  parsePortalCode,
  planetName,
  planetNameFromSeed,
  planetSeeds,
  regionName,
  shipPool,
  systemAttributes,
  systemName,
  voxelAttributes,
  withPlanet,
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
}
interface ShipCase {
  bodies: [number, number, boolean][];
  start: number;
  uncertain: string | null;
  first: string;
  exotic: string;
  /** [squid, close]: whether the exotic is a squid, and whether its seed is too close to the line to be sure. */
  squid: [boolean, boolean];
  crash: string;
  last: string;
  /** [start, exotic, crash] for each other arrangement of a two-moon planet's moons. */
  others: [number, string, string][];
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
    squid: [pool.exoticSquid.squid, pool.exoticSquid.close],
    crash: hex64(pool.crashSite),
    last: hex64(pool.ships[49]!.seed),
    others: pool.alternatives.map((a) => [a.drawsBeforeShips, hex64(a.exotic), hex64(a.crashSite)]),
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
          if (c.ships.squid[0]) squids += 1;
        }
      }
    }
    expect(lines.length).toBeGreaterThan(0);
    expect(shipPools, "cases with a predicted ship pool").toBeGreaterThan(lines.length / 2);
    expect(squids, "cases whose exotic is a squid").toBeGreaterThan(0);
    expect(mismatches.slice(0, 20)).toEqual([]);
  }, 300_000); // 20,000 cases take seconds, mostly the ship pools
});
