// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Per-region (voxel) attributes that steer system generation.
// Ported from nms_namegen (MIT) region.py voxelAttributes(); see THIRD_PARTY_NOTICES.md.

export interface VoxelAttributes {
  guide_star_count: number;
  black_hole_count: number;
  atlas_station_count: number;
  inside_gap: number;
  guide_star_renegade_count: number;
}

/** Galaxy-independent: depends only on the region coordinates in the portal code. */
export function voxelAttributes(code: bigint): VoxelAttributes {
  let x = Number(code & 0xfffn);
  let y = Number((code & 0xff00_0000n) >> 24n);
  let z = Number((code & 0xff_f000n) >> 12n);

  // Fold to signed offsets from the galactic centre.
  if (x > 0x7ff) x -= 0x1000;
  if (z > 0x7ff) z -= 0x1000;
  if (y > 0x7f) y -= 0x100;

  const out: VoxelAttributes = {
    guide_star_count: 0x78,
    black_hole_count: 1,
    atlas_station_count: 1,
    inside_gap: 0,
    guide_star_renegade_count: 0,
  };

  // Truncated to an integer before both tests, as the reference does.
  const distance = Math.trunc(Math.sqrt(x * x + y * y + z * z));
  if (distance < 8) {
    out.guide_star_count = 0;
    out.black_hole_count = 0;
    out.atlas_station_count = 0;
    out.inside_gap = 1;
  }
  if (distance > 8 && distance < 1440) {
    let diff = Math.trunc(((distance - 8) * 120) / 1440);
    if (diff < 0) diff = 0;
    if (diff > 0x78) diff = 0x78;
    out.guide_star_renegade_count = 0x78 - diff;
  }
  return out;
}
