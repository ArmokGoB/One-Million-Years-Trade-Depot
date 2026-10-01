// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Procedural name generation (regions, systems, planets).
// Ported from nms_namegen (MIT) generator.py; see THIRD_PARTY_NOTICES.md.
// The letter tables are nms_namegen's data, flattened by tools/build_name_tables.py.

import rawTables from "./data/name-tables.json";
import type { PRNG } from "./prng";
import { pyIndex } from "./u64";

interface NameTablesFile {
  alphasets: string[];
  firstChars: string[];
  weights: string[];
  tables: Record<string, string>[];
}

interface Entry {
  chars: string;
  weights: number[];
}

const DATA = rawTables as NameTablesFile;
const ALPHASETS: readonly string[] = DATA.alphasets;
const WEIGHTS: readonly number[] = DATA.weights.map((s) => Math.fround(Number(s)));
const FIRST_CHARS: readonly Set<string>[] = DATA.firstChars.map((s) => new Set(s));
const decoded: (Map<string, Entry> | undefined)[] = [];

function table(alphaset: number): Map<string, Entry> {
  let map = decoded[alphaset];
  if (!map) {
    map = new Map();
    for (const [key, value] of Object.entries(DATA.tables[alphaset] ?? {})) {
      const [chars = "", idx = ""] = value.split(":");
      map.set(key, { chars, weights: idx.split(".").map((i) => WEIGHTS[parseInt(i, 36)]!) });
    }
    decoded[alphaset] = map;
  }
  return map;
}

/** The game's float scale for turning a 32-bit word into [0, 1). */
export const TINY_DOUBLE = 2.3283064370807974e-10;

const VOWELS = "aeiou";
const isVowel = (c: string | undefined): boolean => c !== undefined && VOWELS.includes(c);
const isIn = (c: string, set: string): boolean => set.includes(c);

/** Python's str.capitalize(): first character upper case, the rest lower case. */
export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

function getCharactersFromAlphaset(rng: PRNG, cache1: number): string {
  const alphaset = ALPHASETS[cache1 & 0x07]!;
  const r = rng.random(Math.floor(alphaset.length / 3)) * 3;
  return alphaset.slice(r, r + 3);
}

function getStringWeights(st: string, alphaset: number): Entry | null {
  const first = st[0];
  if (first === undefined) throw new RangeError("IndexError: string index out of range");
  if (!FIRST_CHARS[alphaset]?.has(first)) throw new Error(`KeyError: '${first}'`);
  return table(alphaset).get(st) ?? null;
}

function insertVowel(name: string, rng: PRNG, index: number): string {
  const vowel = VOWELS[rng.random(5)]!;
  return name.slice(0, index) + vowel + name.slice(index);
}

function getConsecutiveConsonants(name: string): number {
  let consonance = 0;
  for (let i = 0; i < name.length; i++) {
    const c = name[i]!;
    if (consonance < 3) {
      if (!isIn(c, "aeiou")) consonance += 1;
      else consonance = 0;
    } else {
      if (!isIn(c, "aeiouy")) return i - 3;
      consonance = 0;
    }
  }
  return -1;
}

export function generateName(rng: PRNG, alphasetIndex: number, minLength: number, maxLength: number): string {
  let alternateCharGetter = false;
  let name = getCharactersFromAlphaset(rng, alphasetIndex);
  if (rng.randi() & 0x01) alternateCharGetter = true;

  let register = rng.random(maxLength - minLength + 0x01);
  register = register + minLength - 0x03;
  let add = register;

  if (register > 0) {
    let target = 0;
    let index = 0;
    let tries = 8;
    let i = 0;
    while (i < register) {
      const charWeights = getStringWeights(name.slice(i, i + 3), alphasetIndex);
      target = rng.randi() * TINY_DOUBLE;
      if (charWeights === null) {
        tries -= 1;
        i -= 1;
        alphasetIndex = (alphasetIndex + 1) & 0x08000007;
        if (alphasetIndex < 0) alphasetIndex = -alphasetIndex;

        if (tries === 0) {
          if (add < 3) break;
          const temp = getCharactersFromAlphaset(rng, alphasetIndex);
          if (isVowel(name[i + 2]) && isVowel(temp[0])) {
            name += "'";
          } else if (!isVowel(temp[0])) {
            name += VOWELS[rng.random(5) & 0xff]!;
          }
          name += temp;
          tries = 1;
          i += 2;
          add -= 3;
        }
      } else {
        if (alternateCharGetter) {
          target *= charWeights.weights.length - 1;
          index = Math.trunc(Math.sign(target) * 0.5 + target);
        } else {
          let weight = 0.0;
          let j = 0;
          for (; j < charWeights.weights.length; j++) {
            weight += charWeights.weights[j]!;
            if (weight >= target) break;
          }
          // Python's loop variable stays on the last index when nothing breaks.
          if (j === charWeights.weights.length) j -= 1;
          index = j;
        }
        name += charWeights.chars[index]!;
        add -= 1;
      }

      if (name.length > 63) name = name.slice(0, 64);
      i += 1;
    }
  }

  const first = name[0]!;
  const second = name[1]!;

  // Insert a vowel at the start where needed.
  if (!isIn(first, "aeiou") && !isIn(second, "aeiou")) {
    if (first !== "s" || !isIn(second, "hklmnprtwy")) {
      const allowedCluster =
        (second === "h" && isIn(first, "ctw")) ||
        (second === "l" && isIn(first, "bcfgps")) ||
        (second === "r" && isIn(first, "bcdfgkpt")) ||
        (second === "w" && isIn(first, "dgt")) ||
        (second === "y" && isIn(first, "hmr"));
      if (!allowedCluster) name = insertVowel(name, rng, 1);
    }
  }

  // Insert a vowel at the end where needed.
  if (name.length > 1) {
    const ult = name[name.length - 1]!;
    const penult = name[name.length - 2]!;
    if (penult !== "g" || isIn(ult, "aeiou")) {
      if (
        (ult === "b" && isIn(penult, "gn")) ||
        (ult === "d" && isIn(penult, "bdfghkmpst")) ||
        (ult === "g" && penult === "l") ||
        (ult === "p" && isIn(penult, "bdhkt")) ||
        (ult === "r" && isIn(penult, "bfg")) ||
        (ult === "t" && penult === "g") ||
        (ult === "w" && !isIn(penult, "aeiou"))
      ) {
        name = insertVowel(name, rng, name.length - 1);
      }
    }
  }

  // Break up long consonant runs.
  let consonanceIndex = getConsecutiveConsonants(name);
  if (consonanceIndex !== -1) {
    consonanceIndex += rng.random(3) + 1;
    name = insertVowel(name, rng, consonanceIndex);
  }

  return name;
}

const ROMAN_NUMERALS = [
  "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
  "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
];

/** Roman numeral for 1-20, indexed the way the reference does (Python list semantics). */
export function toRoman(n: number): string {
  return pyIndex(ROMAN_NUMERALS, n - 1);
}
