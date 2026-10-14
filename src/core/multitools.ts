// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A system's own multi-tools, from its address alone: a port of
// tools/captures/multitool_model.py, which the capture report checks against
// every set of multi-tools the capture mod records. tests/multitools.test.ts
// holds this port to it.
//
// The game builds a system's set just before it generates the system, in two
// runs. The first comes from the generator seeded with the system's
// universal address, mixed, as the stream of the planets' seeds is: its
// first draw, scaled to three, gives how many standard multi-tools there are,
// 2, 3 or 4; then each multi-tool's seed is the next two draws, mixed into 64
// bits as a ship's seed is: the standard ones, then the royal, the Sentinel
// and the Atlas one. The second run, three more standard multi-tools, comes
// from a seed not worked out yet.

import type { PartModel } from "./parts";
import { seededPRNG } from "./prng";
import { mix64 } from "./u64";

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

/** How many standard multi-tools follow the first run, from a seed not worked out. */
export const SECOND_RUN = 3;

export interface Multitool {
  kind: MultitoolKind;
  seed: bigint;
}

/** The first run of the set of the system at universal address `ua`, in the order the game builds it. */
export function multitoolRun(ua: bigint): Multitool[] {
  const rng = seededPRNG(mix64(ua));
  const standard = STANDARD_COUNTS[rng.random(STANDARD_COUNTS.length)] as number;
  const kinds: MultitoolKind[] = [...Array<MultitoolKind>(standard).fill("Standard"), "Royal", "Sentinel", "Atlas"];
  return kinds.map((kind) => {
    const low = BigInt(rng.randi());
    const high = BigInt(rng.randi());
    return { kind, seed: mix64((high << 32n) | low) };
  });
}
