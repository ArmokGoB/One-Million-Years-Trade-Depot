// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Public API of the generation core. Pure functions, no DOM: usable from the
// website, from Node, or from any other project.

export * from "./address";
export * from "./describe";
export { indexPrimedPRNG } from "./iprng";
export { generateName } from "./namegen";
export { planetName, planetNameFromSeed, planetSeedForCode } from "./planet";
export { MULTIPLIER, PRNG, seededPRNG } from "./prng";
export { regionName } from "./region";
export {
  drawsBeforeShips,
  exoticSquid,
  firstDraw,
  shipPool,
  shipSeeds,
  shipUncertainty,
  slotTypes,
  SQUID_EDGES,
  twoMoonPlanets,
  type Alternative,
  type Ship,
  type ShipGroup,
  type ShipPool,
  type SquidCall,
} from "./ships";
export { nebulaSeed, STAR_CHANCES, starCount, starsFromNebula } from "./stars";
export {
  planetSeeds,
  systemAttributes,
  systemAttributesDetailed,
  systemName,
  type Body,
  type PlanetSeeds,
  type SystemAttributes,
  type SystemAttributesDetailed,
} from "./system";
export { hex64 } from "./u64";
export { voxelAttributes, type VoxelAttributes } from "./voxel";
