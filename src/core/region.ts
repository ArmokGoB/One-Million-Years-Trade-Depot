// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Region (voxel) names, e.g. "Yihelli Quadrant".
// Ported from nms_namegen (MIT) region.py regionName(); see THIRD_PARTY_NOTICES.md.

import { capitalize, generateName } from "./namegen";
import { PRNG } from "./prng";
import { MASK32, MASK64, MIX_A, MIX_B, swap16 } from "./u64";

const REGION_NAME_ADORNMENTS = [
  "{} Adjunct", "{} Void", "{} Expanse", "{} Terminus", "{} Boundary",
  "{} Fringe", "{} Cluster", "{} Mass", "{} Band", "{} Cloud",
  "{} Nebula", "{} Quadrant", "{} Sector", "{} Anomaly", "{} Conflux",
  "{} Instability", "Sea of {}", "The Arm of {}", "{} Spur", "{} Shallows",
];

export function regionName(code: bigint, galaxy: number): string {
  const g = BigInt(galaxy);
  let register = g >> 1n;
  register ^= (g << 32n) | (code & MASK32);
  register = (register * MIX_A) & MASK64;
  register = (((register >> 33n) ^ register) * MIX_B) & MASK64;
  register = (register >> 33n) ^ register;

  let seedH = swap16(register & MASK32) ^ (register & MASK32) ^ (register >> 32n);
  let seed = register & MASK32;
  if (seedH === 0n) seedH = 1n;
  seed |= seedH << 32n;

  const rng = new PRNG(seed);
  const minLength = 6;
  const maxLength = rng.random(4) + 6;
  const alphasetIndex = 0;
  let name = capitalize(generateName(rng, alphasetIndex, minLength, maxLength));
  if (rng.random(0x64) < 0x50) {
    const adornment = REGION_NAME_ADORNMENTS[rng.random(0x14)]!;
    name = adornment.replace("{}", () => name);
  }
  return name;
}
