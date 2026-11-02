// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Procedural name generation (regions, systems, planets), as the game does it:
// nms_namegen's generator (MIT, generator.py; see THIRD_PARTY_NOTICES.md) with
// the differences tools/captures/name_model.py lists, which this ports. The
// letter tables are nms_namegen's data, flattened by tools/build_name_tables.py.

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

/** The letters that may follow `st` in `alphaset`, or null when none does. */
function getStringWeights(st: string, alphaset: number): Entry | null {
  return table(alphaset).get(st) ?? null;
}

function insertVowel(name: string, rng: PRNG, index: number): string {
  const vowel = VOWELS[rng.random(5)]!;
  return name.slice(0, index) + vowel + name.slice(index);
}

/** Where a run of more than three consonants starts, or -1. A 'y' after three starts a new run. */
function consonantRun(name: string): number {
  let run = 0;
  for (let i = 0; i < name.length; i++) {
    const c = name[i]!;
    if (run === 3) {
      if (!isIn(c, "aeiouy")) return i - 3;
      run = 0;
    }
    run = isVowel(c) ? 0 : run + 1;
  }
  return -1;
}

/**
 * Words the game changes a letter of, in ROT13: each with the place of the
 * letter it changes and the letters it picks from (see name_model.py).
 */
// prettier-ignore
const FILTER: readonly [string, number, string][] = [
  ["nany", 1, "tdwzx"], ["nahf", 1, "tdwzx"], ["nff", 0, "eo"], ["ovgpu", 3, "ao"], ["oybj", 0, "caog"],
  ["obare", 0, "lvsz"], ["pyvg", 3, "cpfn"], ["pbpx", 0, "smlth"], ["phpx", 3, "aeiou"], ["phz", 0, "rgsn"],
  ["phag", 1, "eio"], ["qvpx", 2, "aeol"], ["qbat", 3, "teo"], ["snt", 0, "nmtz"], ["srypu", 0, "njkmp"],
  ["shpx", 0, "zlbw"], ["tbbx", 3, "lnrb"], ["uvgyre", 0, "vmpl"], ["ubzb", 1, "eiu"], ["wvmm", 0, "zrwl"],
  ["xvxr", 2, "rbl"], ["xhag", 3, "aeo"], ["ybir", 2, "mpbt"], ["zvatr", 3, "amlz"], ["zbat", 3, "aoik"],
  ["anmv", 0, "ryvn"], ["arte", 0, "rvlt"], ["avt", 0, "rvxb"], ["betl", 2, "vlos"], ["cnrqb", 0, "tmvs"],
  ["cnxv", 2, "ntr"], ["crqb", 0, "tmvs"], ["cravf", 0, "klsr"], ["cvff", 2, "cokl"], ["cbea", 0, "tvbr"],
  ["cevpx", 0, "stbc"], ["chff", 0, "brsl"], ["dhrr", 2, "nlr"], ["encr", 2, "cnys"], ["frzra", 2, "tzrv"],
  ["frk", 0, "tdrp"], ["funt", 3, "nml"], ["fuvg", 3, "nvsl"], ["fynt", 3, "dnvy"], ["fyhg", 2, "aeo"],
  ["fcnm", 3, "nlr"], ["fcvp", 3, "nlr"], ["fchax", 1, "lh"], ["gneq", 0, "jcgwz"], ["gvg", 2, "nmbc"],
  ["gheq", 3, "nbtp"], ["gjng", 1, "ehi"], ["jnax", 3, "aei"], ["juber", 0, "csa"], ["jbt", 0, "cslv"],
  ["jbc", 0, "csld"]
];
const rot13 = (s: string) => s.replace(/[a-z]/g, (c) => String.fromCharCode(((c.charCodeAt(0) - 97 + 13) % 26) + 97));
const WORDS = FILTER.map(([word, at, letters]) => [rot13(word), at, letters] as const);

/** `name` with a letter of each word of FILTER in it changed, a draw from `rng` for each. */
function filtered(name: string, rng: PRNG): string {
  const letters = [...name];
  for (let start = 0; start < letters.length; start++) {
    for (const [word, at, choices] of WORDS) {
      if (letters.slice(start, start + word.length).join("") === word) {
        letters[start + at] = choices[rng.random(choices.length)]!;
        break;
      }
    }
  }
  return letters.join("");
}

/** The game keeps at most this many letters of a name. */
const LONGEST = 63;

/** Which entry a draw picks, in single precision, as the game holds the weights. */
function pick(weights: readonly number[], target: number, alternate: boolean): number {
  if (alternate) {
    const place = Math.fround(Math.fround(weights.length - 1) * target);
    return Math.trunc(Math.fround(place + 0.5));
  }
  let total = 0;
  for (let j = 0; j < weights.length; j++) {
    total = Math.fround(total + weights[j]!);
    if (total >= target) return j;
  }
  return weights.length - 1;
}

/**
 * One part of a name, as the game makes it: nms_namegen's generator with the
 * game's differences, which tools/captures/name_model.py lists.
 */
export function generateName(rng: PRNG, alphasetIndex: number, minLength: number, maxLength: number): string {
  const own = alphasetIndex;
  let name = getCharactersFromAlphaset(rng, alphasetIndex);
  const alternate = (rng.randi() & 0x01) === 1;
  const length = rng.random(maxLength - minLength + 1) + minLength - 3;
  let left = length;
  let tries = 8;
  let place = 0;
  while (place < length) {
    const target = Math.fround(rng.randi() * TINY_DOUBLE);
    const entry = getStringWeights(name.slice(-3), alphasetIndex);
    if (entry !== null) {
      name = (name + entry.chars[pick(entry.weights, target, alternate)]!).slice(0, LONGEST);
      left -= 1;
      place += 1;
      continue;
    }
    tries -= 1;
    alphasetIndex = (alphasetIndex + 1) & 7;
    if (tries > 0) continue;
    if (left < 3) break;
    const three = getCharactersFromAlphaset(rng, own);
    const before = isVowel(name[place + 2]);
    if (before && isVowel(three[0])) name += "'";
    else if (!before && !isVowel(three[0])) name += VOWELS[rng.random(5)]!;
    name = (name + three).slice(0, LONGEST);
    left -= 3;
    tries = 1;
    place += 3;
  }

  // A vowel after the first letter, where the first two are hard to say.
  const first = name[0]!;
  const second = name[1]!;
  const sayable =
    (first === "s" && isIn(second, "hklmnprtwy")) ||
    (second === "h" && isIn(first, "ctw")) ||
    (second === "l" && isIn(first, "bcfgps")) ||
    (second === "r" && isIn(first, "bcdfgkpt")) ||
    (second === "w" && isIn(first, "dgt")) ||
    (second === "y" && isIn(first, "hmr"));
  if (!isVowel(first) && !isVowel(second) && !sayable) name = insertVowel(name, rng, 1);

  // A vowel before the last letter, where the last two are hard to say.
  const last = name[name.length - 1]!;
  const before = name[name.length - 2]!;
  const hard =
    (last === "b" && isIn(before, "gn")) ||
    (last === "d" && isIn(before, "bdfghkmpst")) ||
    (last === "g" && before === "l") ||
    (last === "p" && isIn(before, "bdhkt")) ||
    (last === "r" && isIn(before, "bfg")) ||
    (last === "t" && before === "g") ||
    (last === "w" && !isVowel(before));
  if ((before !== "g" || isVowel(last)) && hard) name = insertVowel(name, rng, name.length - 1);

  // A vowel in a long run of consonants.
  let run = consonantRun(name);
  if (run !== -1) {
    run += rng.random(3) + 1;
    name = insertVowel(name, rng, run);
  }
  return filtered(name, rng);
}

const ROMAN_NUMERALS = [
  "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
  "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
];

/** Roman numeral for 1-20, indexed the way the reference does (Python list semantics). */
export function toRoman(n: number): string {
  return pyIndex(ROMAN_NUMERALS, n - 1);
}
