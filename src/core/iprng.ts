// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Index-primed PRNG: how the game turns a universal address into a system
// seed, using Threefish/Skein-style 64-bit mixing.
// Ported line for line from nms_namegen (MIT) iprng.py; see THIRD_PARTY_NOTICES.md.

import { MASK64, pyIndex, ror64 } from "./u64";

type Quad = [bigint, bigint, bigint, bigint];

function hashRound(a: bigint, b: bigint, c: bigint, d: bigint, rota: number, rotb: number): Quad {
  const a1 = (ror64(b, rota) ^ c) & MASK64;
  const b1 = (ror64(a, rotb) ^ d) & MASK64;
  const c1 = (b1 + c) & MASK64;
  const d1 = (a1 + d) & MASK64;
  return [a1, b1, c1, d1];
}

function doHash(a: bigint, b: bigint, c: bigint, d: bigint, key: bigint, seed: bigint): Quad {
  [a, b, c, d] = hashRound(a, b, c, d, -0x17, 0x18);
  [a, b, c, d] = hashRound(a, b, c, d, -0x5, 0x1b);
  a = (a + key + 1n) & MASK64;
  d = (d + key + 1n) & MASK64;
  [a, b, c, d] = hashRound(a, b, c, d, -0x19, 0x1f);
  [a, b, c, d] = hashRound(a, b, c, d, 0x12, -0xc);
  [a, b, c, d] = hashRound(a, b, c, d, 0x6, -0x16);
  [a, b, c, d] = hashRound(a, b, c, d, -0x20, -0x20);
  a = (a + seed + 2n) & MASK64;
  d = (d + key + seed + 2n) & MASK64;
  [a, b, c, d] = hashRound(a, b, c, d, -0xe, -0x10);
  [a, b, c, d] = hashRound(b, a, d, c, 0x7, 0xc);
  [a, b, c, d] = hashRound(b, a, d, c, -0x17, 0x18);
  [a, b, c, d] = hashRound(a, b, c, d, -0x5, 0x1b);
  a = (a + 3n) & MASK64;
  b = (b + key) & MASK64;
  c = (c + key) & MASK64;
  d = (d + 3n + seed) & MASK64;
  [a, b, c, d] = hashRound(a, b, c, d, -0x19, 0x1f);
  [a, b, c, d] = hashRound(a, b, c, d, 0x12, -0xc);
  [a, b, c, d] = hashRound(a, b, c, d, 0x6, -0x16);
  [a, b, c, d] = hashRound(a, b, c, d, -0x20, -0x20);
  a = (a + 4n) & MASK64;
  b = (b + seed) & MASK64;
  c = (c + seed + key) & MASK64;
  d = (d + 4n) & MASK64;
  [a, b, c, d] = hashRound(a, b, c, d, -0xe, -0x10);
  [a, b, c, d] = hashRound(a, b, c, d, 0xc, 0x7);
  [a, b, c, d] = hashRound(a, b, c, d, -0x17, 0x18);
  return [
    (c + seed) & MASK64,
    ror64(a, 0x1b) ^ d,
    d,
    ((ror64(b, -0x5) ^ c) + 5n) & MASK64,
  ];
}

/** The 64-bit value the game derives from a universal address (UA). */
export function indexPrimedPRNG(ua: bigint): bigint {
  const seed = ua & 0xff_ffff_ffffn;
  const systemId = Number(((ua >> 0x20n) >> 8n) & 0xfffn);
  const key = (seed ^ 0x1bd11bdaa9fc1a22n) & MASK64;

  let a = seed;
  let b = ror64(seed, 7) ^ seed;
  let c = b + a;
  let d = seed + seed;
  let o = doHash(a, b, c, d, key, seed);

  let counter: number;
  if (systemId >= 9) {
    const systemIndex = systemId - 1;
    const sysHigh = (systemIndex - 8) >> 3;
    counter = (systemIndex - 8) & 7;

    a = BigInt(sysHigh + 1) + seed;
    b = ror64(a, 7) ^ a;
    c = b + a;
    d = a + a;
    o = doHash(a, b, c, d, key, seed);
  } else {
    counter = systemId - 1;
  }

  // Python's `>>` floors and its indexing wraps negatives; system id 0 relies on both.
  const index = Math.floor(counter / 2);
  counter += 1;
  const word = pyIndex(o, index);
  return (1 & counter) === 0 ? (word >> 0x20n) & MASK64 : word & MASK64;
}
