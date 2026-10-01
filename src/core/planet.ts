// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Planet and moon names from a body seed.
// Ported from nms_namegen (MIT) planet.py; see THIRD_PARTY_NOTICES.md.

import { capitalize, generateName, TINY_DOUBLE, toRoman } from "./namegen";
import { MULTIPLIER, PRNG } from "./prng";
import { MASK32, pyIndex, swap16 } from "./u64";
import { planetSeeds } from "./system";

const ADORNMENTS = ["Prime", "Major", "Minor", "Alpha", "Beta", "Gamma", "Delta", "Omega", "Sigma", "Tau"];

const STYLES = [
  "%PROCNORM%",
  "%PROCNORM% %ADORNMENT%",
  "%PROCNORM% %NUMERAL%",
  "%PROCNORM% %SHORTCODE%",
  "%PROCLONG% %PROCSHORT%",
  "%PROCSHORT% %LONGCODE%",
  "%PROCNORM%",
  "%PROCNORM% %ADORNMENT%",
  "%PROCNORM% %NUMERAL%",
  "Style 9",
  "New %PROCNORM%",
];

/**
 * The seed of the body the portal code's planet digit points at.
 * Mirrors the reference exactly, including its Python indexing: digit 0
 * (a system-level code) resolves to the *last* body, and a digit past the
 * number of bodies throws.
 */
export function planetSeedForCode(code: bigint, galaxy: number): bigint {
  const planetId = Number((code & 0xf000_0000_0000n) >> 44n);
  return pyIndex(planetSeeds(code, galaxy).planet_seeds, planetId - 1);
}

const replaceAll = (s: string, token: string, value: string): string => s.split(token).join(value);

/** Procedural name of the body with this seed. */
export function planetNameFromSeed(planetSeed: bigint): string {
  const lowword = planetSeed & MASK32;
  const highword = planetSeed >> 32n;

  const rol16 = (swap16(lowword) ^ lowword ^ highword) & MASK32;
  const seed = lowword === 0n ? (lowword + 1n) * MULTIPLIER + rol16 : lowword * MULTIPLIER + rol16;

  const rng = new PRNG(seed);
  const adornment = Number(((rng.seed & MASK32) * 10n) >> 0x20n);
  const code = rng.random(50) + 1;
  const shortcode = rng.random(0x1a) + 0x41;
  const numeral = rng.random(0x12) + 2;
  const digit = rng.random(0x09) + 1;
  const alpha = rng.random(0x1a) + 0x41;
  const longcode = rng.random(0x59) + 0xb;

  const procnorm = generateName(rng, 7, 4, 8);
  const procshort = generateName(rng, 5, 4, 5);
  const proclong = generateName(rng, 7, 6, 10);

  let namegenStyle = rng.random(9);
  const target = rng.randi() * TINY_DOUBLE;
  if (!(0.0350000001 <= target)) namegenStyle = 10;

  let name = STYLES[namegenStyle]!;
  name = replaceAll(name, "%PROCNORM%", capitalize(procnorm));
  name = replaceAll(name, "%PROCSHORT%", capitalize(procshort));
  name = replaceAll(name, "%PROCLONG%", capitalize(proclong));
  name = replaceAll(name, "%ADORNMENT%", ADORNMENTS[adornment]!);
  name = replaceAll(name, "%SHORTCODE%", `${String.fromCharCode(shortcode)}${code % 0x50}`);
  name = replaceAll(name, "%NUMERAL%", toRoman(numeral));
  name = replaceAll(name, "%LONGCODE%", `${longcode}/${String.fromCharCode(alpha)}${digit}`);
  return name;
}

/** Name of the body selected by the portal code's planet digit (reference semantics). */
export function planetName(code: bigint, galaxy: number): string {
  return planetNameFromSeed(planetSeedForCode(code, galaxy));
}
