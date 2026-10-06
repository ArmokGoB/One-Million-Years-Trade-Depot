// SPDX-License-Identifier: AGPL-3.0-or-later
//
// How many stars a system has, from its address alone: a port of
// tools/captures/star_model.py, which the capture report checks against every
// capture. tests/stars.test.ts holds this port to it.
//
// The game counts a system's stars from its NebulaSeed, a number between 0
// and 1: a second star when it's above 1 minus the binary star chance, and a
// third when it's also above 1 minus the ternary star chance. NebulaSeed is
// the 9th draw of the generator seeded with the system's universal address,
// as a fraction of the largest draw, in single precision. In two game modes,
// Seasonal (expeditions) and Unspecified, with a setting on, the game also
// gives three stars to one system whose address it holds; this covers the
// normal game.

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
