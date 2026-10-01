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
  systemAttributes,
  systemName,
  voxelAttributes,
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
    }
    expect(lines.length).toBeGreaterThan(0);
    expect(mismatches.slice(0, 20)).toEqual([]);
  });
});
