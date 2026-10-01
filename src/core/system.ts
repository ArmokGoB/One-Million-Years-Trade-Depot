// SPDX-License-Identifier: AGPL-3.0-or-later
//
// System generation: name, attributes and body seeds from a portal code.
// Ported line for line from nms_namegen (MIT) system.py; see THIRD_PARTY_NOTICES.md.
// The comments explaining *why* each draw is read the way it is live in the
// reference implementation; they are summarised here.

import { indexPrimedPRNG } from "./iprng";
import { capitalize, generateName, toRoman } from "./namegen";
import { MULTIPLIER, PRNG, primeFromWord } from "./prng";
import { MASK32, MASK64, MIX_A, MIX_B, swap16 } from "./u64";
import { voxelAttributes } from "./voxel";

/** Read a 32-bit draw as the game does: a float32 in [0, 1). */
function probability(word: bigint): number {
  return Math.fround(Number(word & MASK32) / 4294967296);
}

// Per-star-type probability tables, as the exact float32 values the game holds.
// Index: 0 yellow, 1 green, 2 blue, 3 red, 4 purple.
const ABANDONED_SYSTEM_THRESHOLD = [0.0, 0.10000000149011612, 0.10000000149011612, 0.0, 0.3499999940395355];
const EMPTY_SYSTEM_THRESHOLD = [0.0, 0.4000000059604645, 0.4000000059604645, 0.949999988079071, 0.20000000298023224];
const PIRATE_SYSTEM_THRESHOLD = [0.25, 0.15000000596046448, 0.15000000596046448, 0.5, 0.05000000074505806];

// Draw value -> category (this project's 1-based numbering, as in nms_namegen).
const ECONOMY_FROM_DRAW = [4, 6, 1, 5, 2, 3, 7];
const WEALTH_FROM_BUCKET = [3, 1, 2];
const CONFLICT_FROM_DRAW = [1, 2, 3];
const RACE_FROM_DRAW = [1, 3, 2];

export interface SystemAttributes {
  planet_count: number;
  prime_planet_count: number;
  safe_start_planet: number;
  gas_giant: boolean;
  /** 0 yellow, 1 green, 2 blue, 3 red, 4 purple */
  star_type: number;
  /** 1 trading, 2 advanced materials, 3 scientific, 4 mining, 5 manufacturing, 6 technology, 7 power generation */
  economy_type: number;
  /** 1 low, 2 medium, 3 high */
  wealth: number;
  /** 1 low, 2 medium, 3 high */
  conflict_level: number;
  /** 0 none (uncharted), 1 Gek, 2 Korvax, 3 Vy'keen */
  dominant_race: number;
  uncharted: boolean;
  abandoned: boolean;
  pirate: boolean;
}

export interface PlanetSeeds {
  planet_seeds: bigint[];
  planet_count: number;
  moon_count: number;
  /** Experimental in the reference: per-slot size class, not validated per slot. */
  sizes: number[];
}

/** The system's procedural name, e.g. "Abarof-Dulin". */
export function systemName(code: bigint, galaxy: number): string {
  const galacticCoords = code & MASK32;
  const systemIndex = ((code & 0x0fff_0000_0000n) >> 24n) | BigInt(galaxy);

  let rolCoords = swap16(galacticCoords);
  rolCoords = (rolCoords ^ galacticCoords ^ systemIndex) & MASK32;
  const seed = primeFromWord(galacticCoords, rolCoords);

  const rng = new PRNG(seed);

  let alphasetIndex = 0x00;
  let alphasetReg = Number(((seed & MASK32) * 0x5n) >> 32n);
  if (alphasetReg === 0) {
    alphasetIndex = 0x02;
  } else if ((alphasetReg & 0xff) < 0x04) {
    alphasetIndex = (alphasetReg & 0xff) + 0x02;
  } else {
    alphasetIndex = 0x07;
  }

  let maxLength = rng.random(4) + 0x06;
  let name = capitalize(generateName(rng, alphasetIndex, 6, maxLength));

  // Short names may get a hyphenated second part.
  if (name.length < 8) {
    const r = rng.random(4);
    if (r < 2) {
      alphasetReg = rng.random(5);
      const minLength = 3;
      maxLength = 5;
      if (alphasetReg === 0) alphasetIndex = 0x02;
      else if (alphasetReg < 4) alphasetIndex = alphasetReg + 2;
      else alphasetIndex = 0x07;
      const name2 = generateName(rng, alphasetIndex, minLength, maxLength);
      name = `${name}-${capitalize(name2)}`;
    }
  }

  if (rng.random(0x0a) < 0x03) {
    let n = rng.random(19) + 1;
    if (n > 19) n = 19;
    name = `${name} ${toRoman(n)}`;
  }
  return name;
}

/** Attributes plus the internal anomaly flag (black hole / Atlas Interface system). */
export interface SystemAttributesDetailed {
  attributes: SystemAttributes;
  /** 0 none, 1 Atlas Interface, 2 black hole */
  anomaly: number;
}

export function systemAttributes(code: bigint, galaxy: number): SystemAttributes {
  return systemAttributesDetailed(code, galaxy).attributes;
}

export function systemAttributesDetailed(code: bigint, galaxy: number): SystemAttributesDetailed {
  code = code & 0xfff_ffff_ffffn;
  let systemId = Number((code & 0xfff_0000_0000n) >> 32n);
  const universalAddress = (((BigInt(systemId) << 8n) | (BigInt(galaxy) & 0xffn)) << 32n) | (code & MASK32);
  const va = voxelAttributes(code);
  // The generator decrements the system id before every branch below.
  systemId = systemId - 1;
  const systemSeed = indexPrimedPRNG(universalAddress) & MASK32;
  const rol16 = (swap16(systemSeed) ^ systemSeed) & MASK32;
  const seed = systemSeed === 0n ? (systemSeed + 1n) * MULTIPLIER + rol16 : systemSeed * MULTIPLIER + rol16;

  const rng = new PRNG(seed);
  let starType = 0;
  let safeStart = 0;
  let primePlanetCount = 2;
  let planetCount = 1;
  let anomaly = 0;

  if (systemId < va.guide_star_count) {
    planetCount = Number(((seed & MASK32) * 4n) >> 0x20n) + 3;
    safeStart = rng.random(planetCount) + 1;
  } else {
    starType = 0;
    if (Number(((seed & MASK32) * 0x64n) >> 0x20n) < 0x1e) {
      starType = rng.random(3) + 1;
    }

    // Black-hole and Atlas-station system ids are anomalies: base star type, no safe-start draw.
    const anomalyDiff = systemId - va.guide_star_count;
    if (va.black_hole_count > 0 && anomalyDiff >= 0 && anomalyDiff < va.black_hole_count) {
      anomaly = 2;
      starType = 0;
    }
    if (
      va.atlas_station_count > 0 &&
      anomalyDiff - va.black_hole_count >= 0 &&
      anomalyDiff - va.black_hole_count < va.atlas_station_count
    ) {
      anomaly = 1;
      starType = 0;
    }

    planetCount = rng.random(6) + 1;

    if (va.guide_star_renegade_count >= 10 || starType !== 0 || anomaly !== 0) {
      safeStart = 0;
    } else {
      safeStart = rng.random(planetCount + 1);
    }
  }

  // Economy, wealth, conflict and race draws.
  rng.updateSeed();
  const economyWord = rng.seed & MASK32;
  const economyType = ECONOMY_FROM_DRAW[Number((economyWord * 7n) >> 32n)]!;

  rng.updateSeed();
  const wealthWord = rng.seed & MASK32;
  const wealthPct = Number((wealthWord * 100n) >> 32n);
  const wealthBucket = wealthPct < 10 ? 0 : wealthPct < 30 ? 1 : 2;
  let wealth = WEALTH_FROM_BUCKET[wealthBucket]!;

  rng.updateSeed();
  const conflictWord = rng.seed & MASK32;
  let conflictLevel = CONFLICT_FROM_DRAW[Number((conflictWord * 3n) >> 32n)]!;

  rng.updateSeed();
  const raceWord = rng.seed & MASK32;
  let dominantRace = RACE_FROM_DRAW[Number((raceWord * 3n) >> 32n)]!;

  if (systemId < va.guide_star_renegade_count) {
    starType = rng.random(3) + 1;
  }

  // Purple window: raw SSI 0x3E9-0x429 inclusive (systemId is already decremented).
  if (systemId > 0x3e7 && systemId < 0x429) {
    starType = 4;
  }

  // Abandoned check; when abandoned, the empty-system draw is skipped.
  rng.updateSeed();
  const abandoned = probability(rng.seed) < ABANDONED_SYSTEM_THRESHOLD[starType]!;

  let uncharted = false;
  if (!abandoned) {
    rng.updateSeed();
    uncharted = probability(rng.seed) < EMPTY_SYSTEM_THRESHOLD[starType]!;
  }

  if (uncharted) dominantRace = 0;
  if (abandoned) {
    wealth = 1;
    conflictLevel = 1;
  }

  const diff = 6 - planetCount;
  if (diff < 1) {
    primePlanetCount = 0;
  } else if (rng.random(100) >= 33 || diff < 2) {
    primePlanetCount = 1;
  }

  // Purple systems: every body becomes an extra body; 15% use the gas-giant layout.
  let gasGiant = false;
  if (starType === 4) {
    primePlanetCount += planetCount;
    planetCount = 0;
    if (rng.random(100) < 15) {
      gasGiant = true;
      if (rng.random(100) < 66) {
        planetCount = 0;
        primePlanetCount = 6;
      }
    }
  }

  // Pirate check peeks at the next word without consuming it.
  let pirate = false;
  if (!abandoned && !uncharted && (starType !== 0 || safeStart <= 0)) {
    const peek = new PRNG(rng.seed);
    peek.updateSeed();
    pirate = probability(peek.seed) < PIRATE_SYSTEM_THRESHOLD[starType]!;
  }

  return {
    attributes: {
      planet_count: planetCount,
      prime_planet_count: primePlanetCount,
      safe_start_planet: safeStart,
      gas_giant: gasGiant,
      star_type: starType,
      economy_type: economyType,
      wealth,
      conflict_level: conflictLevel,
      dominant_race: dominantRace,
      uncharted,
      abandoned,
      pirate,
    },
    anomaly,
  };
}

/** Mixes the next two PRNG words into one body seed. */
function bodySeed(rng: PRNG): bigint {
  const low = BigInt(rng.randi()) & MASK32;
  const high = BigInt(rng.randi()) & MASK32;
  let register = (high << 0x20n) | low;
  register = (((register >> 33n) ^ register) * MIX_A) & MASK64;
  register = (((register >> 33n) ^ register) * MIX_B) & MASK64;
  return (register >> 33n) ^ register;
}

/** Per-body seeds in generation order, plus the rendered planet/moon split. */
export function planetSeeds(code: bigint, galaxy: number): PlanetSeeds {
  const attrs = systemAttributes(code, galaxy);
  const gasGiant = attrs.gas_giant;

  const seeds: bigint[] = [];
  const galacticCoords = code & MASK32;
  const systemIndex = ((code & 0x0fff_0000_0000n) >> 24n) | BigInt(galaxy);
  let moonCount = 0;

  let register = (systemIndex << 0x20n) | galacticCoords;
  register = (((register >> 33n) ^ register) * MIX_A) & MASK64;
  register = (((register >> 33n) ^ register) * MIX_B) & MASK64;
  register = (register >> 33n) ^ register;

  let seedH = (swap16(register & MASK32) ^ (register & MASK32) ^ (register >> 32n));
  const seedL = register & MASK32;
  if (seedH === 0n) seedH = 1n;

  const rng = new PRNG((seedH << 32n) | seedL);

  const primaryCount = attrs.planet_count;
  const totalCount = primaryCount + attrs.prime_planet_count;
  const stop = attrs.safe_start_planet - 1;
  const sizes: number[] = [];

  if (gasGiant) {
    for (let k = 0; k < totalCount; k++) seeds.push(bodySeed(rng));
    return { planet_seeds: seeds, planet_count: 1, moon_count: totalCount - 1, sizes };
  }

  // Primary bodies: all size classes first, then all seeds.
  let i = 0;
  while (i < primaryCount) {
    i += 1;
    const size = rng.random(3);
    sizes.push(size);
    if (size === 0) {
      let m = primaryCount - i;
      if (m < 0) m = 0;
      if (m > 2) m = 2;
      let nMoons = rng.random(m + 1);
      if (nMoons > 0) {
        while (i !== stop) {
          i += 1;
          nMoons -= 1;
          moonCount += 1;
          if (nMoons <= 0) break;
        }
      }
    }
  }

  i = 0;
  while (i < primaryCount) {
    seeds.push(bodySeed(rng));
    i += 1;
  }

  // Extra bodies interleave size class and seed, and can pull moons in.
  while (i < totalCount) {
    const size = rng.random(3);
    sizes.push(size);
    seeds.push(bodySeed(rng));
    i += 1;
    if (size === 0) {
      let m = totalCount - i;
      if (m < 0) m = 0;
      if (m > 2) m = 2;
      let nMoons = rng.random(m + 1);
      while (nMoons > 0 && i !== stop) {
        seeds.push(bodySeed(rng));
        moonCount += 1;
        nMoons -= 1;
        i += 1;
      }
    }
  }

  return { planet_seeds: seeds, planet_count: totalCount - moonCount, moon_count: moonCount, sizes };
}
