// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A system's own multi-tools, from its address and the day: a port of
// tools/captures/multitool_model.py, which the capture report checks against
// every set of multi-tools the capture mod records. tests/multitools.test.ts
// holds this port to it.
//
// The game builds a system's set just before it generates the system. Its
// first run comes from the generator seeded with the address, mixed, as the
// stream of the planets' seeds is: its first draw, scaled to three, gives how
// many standard multi-tools there are, 2, 3 or 4; then each multi-tool's seed
// is the next two draws, mixed into 64 bits as a ship's seed is: the standard
// ones, then the royal, the Sentinel and the Atlas one. The rotation, three
// more standard ones, comes from a generator seeded with the address and the
// day hashed together; when the day changes, at midnight UTC, the game makes
// it again. Multi-tool terminals that restock after a while offer one of the
// three.
//
// The address is the player's as the game generates the system: the system's
// own after a warp, but a planet's when the player is at that planet then, as
// when a save loads there.

import type { PartModel } from "./parts";
import { seededPRNG, type PRNG } from "./prng";
import { MASK64, mix64 } from "./u64";

export type MultitoolKind = "Standard" | "Royal" | "Sentinel" | "Atlas";

/** The model each kind of multi-tool is built from, whose parts parts.ts picks. */
export const MULTITOOL_MODELS: Record<MultitoolKind, PartModel> = {
  Standard: "MULTITOOL",
  Royal: "ROYALMULTITOOL",
  Sentinel: "SENTINELMULTITOOL",
  Atlas: "ATLASMULTITOOL",
};

/** How many standard multi-tools the first run can have: its first draw picks one, each as likely. */
export const STANDARD_COUNTS = [2, 3, 4] as const;

/** How many standard multi-tools the rotation has. */
export const ROTATION = 3;

/** How long one day of the rotation lasts, in milliseconds. */
export const DAY_MS = 86_400_000;

/** The multiplier of the hash that seeds the rotation (CityHash's Hash128to64). */
const HASH_MUL = 0x9ddf_ea08_eb38_2d69n;

export interface Multitool {
  kind: MultitoolKind;
  seed: bigint;
}

/** The first run of the set made from universal address `ua`, in the order the game builds it. */
export function multitoolRun(ua: bigint): Multitool[] {
  const rng = seededPRNG(mix64(ua));
  const standard = STANDARD_COUNTS[rng.random(STANDARD_COUNTS.length)] as number;
  const kinds: MultitoolKind[] = [...Array<MultitoolKind>(standard).fill("Standard"), "Royal", "Sentinel", "Atlas"];
  return kinds.map((kind) => ({ kind, seed: nextSeed(rng) }));
}

/**
 * The day the rotation is made from at `ms` milliseconds since 1970 UTC, the
 * time `Date.now()` gives: how many whole days have passed since then.
 */
export function rotationDay(ms: number): number {
  return Math.floor(ms / DAY_MS);
}

/**
 * The seed of the rotation's generator: CityHash's Hash128to64 of a 128-bit
 * value whose low half is the address and whose high half is the day.
 */
export function dayHash(ua: bigint, day: number): bigint {
  const high = BigInt.asUintN(64, BigInt(day));
  let a = ((ua ^ high) * HASH_MUL) & MASK64;
  a ^= a >> 47n;
  let b = ((high ^ a) * HASH_MUL) & MASK64;
  b ^= b >> 47n;
  return (b * HASH_MUL) & MASK64;
}

/** The rotation of the set made from universal address `ua` on `day` (rotationDay), in the game's order. */
export function multitoolRotation(ua: bigint, day: number): Multitool[] {
  const rng = seededPRNG(dayHash(ua, day));
  return Array.from({ length: ROTATION }, () => ({ kind: "Standard" as const, seed: nextSeed(rng) }));
}

/** A multi-tool's seed: the generator's next two draws, mixed. */
function nextSeed(rng: PRNG): bigint {
  const low = BigInt(rng.randi());
  const high = BigInt(rng.randi());
  return mix64((high << 32n) | low);
}
