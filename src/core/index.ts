// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Public API of the generation core. Pure functions, no DOM: usable from the
// website, from Node, or from any other project.

export * from "./address";
export { colorName, hexColor, oklch } from "./colornames";
export * from "./describe";
export { GALAXY_NAMES, galaxyLabel, galaxyName } from "./galaxies";
export { GUILDS, guildFor, type Guild } from "./guild";
export { indexPrimedPRNG } from "./iprng";
export {
  MULTITOOL_MODELS,
  multitoolRun,
  SECOND_RUN,
  STANDARD_COUNTS,
  type Multitool,
  type MultitoolKind,
} from "./multitools";
export { generateName } from "./namegen";
export {
  basePalettes,
  legacyPalettes,
  PAINT_MODELS,
  paint,
  paintColors,
  paletteSource,
  type PaintedLayer,
  type PaintModel,
  type Palettes,
  type PaletteSource,
  type RGB,
} from "./paint";
export { NAMED_MODELS, namedParts, type NamedPart, type Side } from "./partnames";
export { distinguishingParts, PART_MODELS, partsAndOptions, partsFor, type PartModel } from "./parts";
export { planetName, planetNameFromSeed, planetSeedForCode } from "./planet";
export { MULTIPLIER, PRNG, seededPRNG } from "./prng";
export { regionName } from "./region";
export {
  civilianType,
  CRASH_SITE_MODEL,
  drawsBeforeShips,
  exoticSquid,
  firstDraw,
  shipPool,
  shipSeeds,
  slotTypes,
  solarRoll,
  SQUID_PART,
  swappedMoons,
  typeModels,
  typePaints,
  type Ship,
  type ShipGroup,
  type ShipPool,
} from "./ships";
export {
  nebulaSeed,
  STAR_CHANCES,
  STAR_COLORS,
  starColors,
  starCount,
  starsFromNebula,
  type StarColor,
} from "./stars";
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
