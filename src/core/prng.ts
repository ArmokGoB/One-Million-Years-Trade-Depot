// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The game's personal RNG: a 32-bit multiply-with-carry generator.
// Ported from nms_namegen (MIT) prng.py; see THIRD_PARTY_NOTICES.md.

import { MASK32, MASK64, swap16 } from "./u64";

export const MULTIPLIER = 0x5a76f899n;

export class PRNG {
  seed: bigint;

  constructor(seed: bigint) {
    this.seed = seed;
  }

  /** Advance the state: low word times the multiplier, plus the carry (high word). */
  updateSeed(): void {
    this.seed = (this.seed & MASK32) * MULTIPLIER + (this.seed >> 32n);
  }

  /** An integer in [0, range). */
  random(range: number): number {
    this.updateSeed();
    return Number(((this.seed & MASK32) * BigInt(range)) >> 32n);
  }

  /** The next 32-bit word. */
  randi(): number {
    this.updateSeed();
    return Number(this.seed & MASK32);
  }

  /** The next full 64-bit state. */
  randl(): bigint {
    this.updateSeed();
    return this.seed & MASK64;
  }
}

/**
 * The generator the game starts from a 64-bit seed: the seed's low word, and
 * a carry from that word with its halves swapped, the word itself and the
 * seed's high word (never zero).
 */
export function seededPRNG(seed: bigint): PRNG {
  const low = seed & MASK32;
  let high = (swap16(low) ^ low ^ (seed >> 32n)) & MASK32;
  if (high === 0n) high = 1n;
  return new PRNG((high << 32n) | low);
}

/**
 * How the generator primes its RNG from a 32-bit word: the word times the
 * multiplier, plus a 32-bit "carry" built from the same word. A zero word is
 * treated as one so the stream never collapses.
 */
export function primeFromWord(word: bigint, carry: bigint): bigint {
  return (word === 0n ? 1n : word) * MULTIPLIER + carry;
}
