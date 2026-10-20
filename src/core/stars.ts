// SPDX-License-Identifier: AGPL-3.0-or-later
//
// How many stars a system has, and what color each is, from its address alone:
// a port of tools/captures/star_model.py, which the capture report checks
// against every capture. tests/stars.test.ts holds this port to it.
//
// The game counts a system's stars from its NebulaSeed, a number between 0
// and 1: a second star when it's above 1 minus the binary star chance, and a
// third when it's also above 1 minus the ternary star chance. NebulaSeed is
// the 9th draw of the generator seeded with the system's universal address,
// as a fraction of the largest draw, in single precision. In two game modes,
// Seasonal (expeditions) and Unspecified, with a setting on, the game also
// gives three stars to one system whose address it holds; this covers the
// normal game.
//
// Each star has a color of its own. The game names five color variants for
// suns, one for each of its star types, in their order; the main star has the
// system's star color, and each other star the color after the one before,
// going round.

import { seededPRNG } from "./prng";

/** The game's chances of a second and a third star (its sky globals), in single precision. */
export const STAR_CHANCES = { binary: Math.fround(0.2), ternary: Math.fround(0.05) } as const;

/** NebulaSeed of the system at universal address `ua`: its 9th draw, as a fraction, in single precision. */
export function nebulaSeed(ua: bigint): number {
  const rng = seededPRNG(ua);
  for (let k = 0; k < 8; k++) rng.updateSeed();
  return Math.fround(rng.randi() / 4294967295);
}

/**
 * How many stars the game counts for a system with this NebulaSeed. It
 * subtracts each chance from 1 in single precision, and counts a star only
 * when NebulaSeed is strictly above the difference.
 */
export function starsFromNebula(nebula: number): 1 | 2 | 3 {
  const ternary = nebula > Math.fround(1 - STAR_CHANCES.ternary);
  const binary = nebula > Math.fround(1 - STAR_CHANCES.binary);
  return (1 + Number(ternary) + Number(binary)) as 1 | 2 | 3;
}

/** How many stars the system at universal address `ua` has. */
export function starCount(ua: bigint): 1 | 2 | 3 {
  return starsFromNebula(nebulaSeed(ua));
}

/** The game's star colors, in the order of its star types and of its color variants for suns. */
export const STAR_COLORS = ["Yellow", "Green", "Blue", "Red", "Purple"] as const;

export type StarColor = (typeof STAR_COLORS)[number];

/**
 * The color of each of the `count` stars of a system whose star type is
 * `starType` (its place in STAR_COLORS), the main star first: each the color
 * after the one before, going round.
 */
export function starColors(starType: number, count: number): StarColor[] {
  return Array.from({ length: count }, (_, k) => STAR_COLORS[(starType + k) % STAR_COLORS.length]!);
}
