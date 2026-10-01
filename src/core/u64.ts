// SPDX-License-Identifier: AGPL-3.0-or-later
//
// 64-bit helpers. All seed arithmetic in this project uses BigInt so that it
// matches the game's fixed-width integer maths exactly, the same way the
// Python reference (nms_namegen) relies on unbounded ints plus explicit masks.

export const MASK32 = 0xffff_ffffn;
export const MASK64 = 0xffff_ffff_ffff_ffffn;

/**
 * Rotate a 64-bit value right by `r` bits. `r` is reduced modulo 64 first,
 * exactly like Python's `r & 63`, so negative amounts become left rotations.
 */
export function ror64(x: bigint, r: number): bigint {
  const s = BigInt(((r % 64) + 64) % 64);
  return ((x >> s) | (x << (64n - s))) & MASK64;
}

/** Swap the two 16-bit halves of a 32-bit value. */
export function swap16(x: bigint): bigint {
  return ((x & 0xffffn) << 16n) | ((x & 0xffff_0000n) >> 16n);
}

/**
 * The 64-bit finaliser the generator uses to turn a pair of words into a
 * seed: xor-shift by 33, multiply, twice, then a final xor-shift.
 */
export const MIX_A = 0x64dd81482cbd31d7n;
export const MIX_B = 0xe36aa5c613612997n;

/** Index into an array with Python semantics: negative indices count from the end. */
export function pyIndex<T>(arr: readonly T[], i: number): T {
  const j = i < 0 ? arr.length + i : i;
  if (j < 0 || j >= arr.length) {
    throw new RangeError(`IndexError: index ${i} out of range for length ${arr.length}`);
  }
  return arr[j] as T;
}

/** Format an unsigned 64-bit value as 16 uppercase hex digits. */
export function hex64(x: bigint): string {
  return (x & MASK64).toString(16).toUpperCase().padStart(16, "0");
}
