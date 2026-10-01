// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Address formats. Everything internal uses the 12-digit portal code
// PSSSYYZZZXXX as a bigint: planet digit, system index, then the region's
// Y, Z and X voxel coordinates in portal frame (centre-origin, wrapped).

export const GALAXY_COUNT = 256;

export interface PortalParts {
  planet: number;
  system: number;
  y: number;
  z: number;
  x: number;
}

export class AddressError extends Error {}

/** Parse 12 hex digits, ignoring spaces, dashes, colons and an optional 0x. */
export function parsePortalCode(input: string): bigint {
  const cleaned = input.trim().replace(/^0x/i, "").replace(/[\s:_-]/g, "");
  if (!/^[0-9a-fA-F]{12}$/.test(cleaned)) {
    throw new AddressError("A portal address is exactly 12 hexadecimal digits (0-9, A-F).");
  }
  return BigInt(`0x${cleaned}`);
}

export function formatPortalCode(code: bigint): string {
  return code.toString(16).toUpperCase().padStart(12, "0");
}

export function portalParts(code: bigint): PortalParts {
  return {
    planet: Number((code >> 44n) & 0xfn),
    system: Number((code >> 32n) & 0xfffn),
    y: Number((code >> 24n) & 0xffn),
    z: Number((code >> 12n) & 0xfffn),
    x: Number(code & 0xfffn),
  };
}

export function fromParts(p: PortalParts): bigint {
  return (
    (BigInt(p.planet & 0xf) << 44n) |
    (BigInt(p.system & 0xfff) << 32n) |
    (BigInt(p.y & 0xff) << 24n) |
    (BigInt(p.z & 0xfff) << 12n) |
    BigInt(p.x & 0xfff)
  );
}

/** Same address with a different planet digit (0 = the system itself). */
export function withPlanet(code: bigint, planet: number): bigint {
  return (code & 0x0fff_ffff_ffffn) | (BigInt(planet & 0xf) << 44n);
}

/**
 * Signal-booster "galactic coordinates", e.g. `HUKYA:046A:0081:0D6D:0038`
 * (the leading letters are optional). Booster X/Y/Z are corner-origin, so
 * they are shifted into portal frame: X and Z by 0x801, Y by 0x81, wrapped.
 * Example: 025B:0082:03FF:004A <-> portal 004A03C00A5C.
 */
export function parseGalacticCoordinates(input: string): bigint {
  const parts = input.trim().split(":").map((s) => s.trim());
  if (parts.length === 5) parts.shift();
  if (parts.length !== 4 || parts.some((s) => !/^[0-9a-fA-F]{1,4}$/.test(s))) {
    throw new AddressError("Galactic coordinates look like 046A:0081:0D6D:0038 (X:Y:Z:system).");
  }
  const [x, y, z, system] = parts.map((s) => parseInt(s, 16)) as [number, number, number, number];
  if (x > 0xfff || z > 0xfff || y > 0xff || system > 0xfff) {
    throw new AddressError("Galactic coordinates are out of range (X, Z ≤ 0FFF, Y ≤ 00FF, system ≤ 0FFF).");
  }
  return fromParts({ planet: 0, system, y: (y + 0x81) & 0xff, z: (z + 0x801) & 0xfff, x: (x + 0x801) & 0xfff });
}

export function toGalacticCoordinates(code: bigint): string {
  const p = portalParts(code);
  const h4 = (n: number) => n.toString(16).toUpperCase().padStart(4, "0");
  return [h4((p.x + 0x7ff) & 0xfff), h4((p.y + 0x7f) & 0xff), h4((p.z + 0x7ff) & 0xfff), h4(p.system)].join(":");
}

/** Accept either format. */
export function parseAnyAddress(input: string): bigint {
  return input.includes(":") ? parseGalacticCoordinates(input) : parsePortalCode(input);
}

export function parseGalaxy(input: string | number): number {
  const n = typeof input === "number" ? input : Number(String(input).trim());
  if (!Number.isInteger(n) || n < 0 || n >= GALAXY_COUNT) {
    throw new AddressError("Galaxy is a number from 0 (Euclid) to 255.");
  }
  return n;
}
