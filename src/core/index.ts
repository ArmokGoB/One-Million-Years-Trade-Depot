// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Public API of the generation core. Pure functions, no DOM: usable from the
// website, from Node, or from any other project.

export * from "./address";
export * from "./describe";
export { indexPrimedPRNG } from "./iprng";
export { generateName } from "./namegen";
export { planetName, planetNameFromSeed, planetSeedForCode } from "./planet";
export { MULTIPLIER, PRNG } from "./prng";
export { regionName } from "./region";
export {
  planetSeeds,
  systemAttributes,
  systemAttributesDetailed,
  systemName,
  type PlanetSeeds,
  type SystemAttributes,
  type SystemAttributesDetailed,
} from "./system";
export { hex64 } from "./u64";
export { voxelAttributes, type VoxelAttributes } from "./voxel";
