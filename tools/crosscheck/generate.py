#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Differential test data: runs nms_namegen over many addresses, one JSON per line.

tests/crosscheck.test.ts replays the file against the TypeScript port when
CROSSCHECK_FILE points at it. Unlike the 443 golden vectors, this covers
every planet digit, all 256 galaxies, and the system indices where the
generator branches (guide stars, black hole, Atlas Interface, the purple
window, the ends of the range).

Usage:
    python3 tools/crosscheck/generate.py --namegen /path/to/nms_namegen --count 20000 > crosscheck.jsonl
"""

import argparse
import json
import random
import sys
from pathlib import Path

EDGE_SYSTEM_IDS = [
    0x000, 0x001, 0x002, 0x008, 0x009, 0x00A, 0x010, 0x077, 0x078, 0x079, 0x07A, 0x07B, 0x07C,
    0x0FF, 0x100, 0x2FF, 0x3E7, 0x3E8, 0x3E9, 0x3EA, 0x428, 0x429, 0x42A, 0x7FF, 0xFFE, 0xFFF,
]
EDGE_COORDS = [0x000, 0x001, 0x7FE, 0x7FF, 0x800, 0x801, 0xFFE, 0xFFF]
EDGE_Y = [0x00, 0x01, 0x7E, 0x7F, 0x80, 0x81, 0xFE, 0xFF]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--namegen", required=True, type=Path)
    parser.add_argument("--count", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()

    sys.path.insert(0, str(args.namegen.resolve()))
    from nms_namegen.planet import planetName  # noqa: E402
    from nms_namegen.region import regionName, voxelAttributes  # noqa: E402
    from nms_namegen.system import planetSeeds, systemAttributes, systemName  # noqa: E402

    rnd = random.Random(args.seed)

    def random_case():
        roll = rnd.random()
        planet = rnd.randrange(16)
        galaxy = rnd.randrange(256)
        x, z, y = rnd.randrange(0x1000), rnd.randrange(0x1000), rnd.randrange(0x100)
        system = rnd.randrange(0x1000)
        if roll < 0.25:
            system = rnd.choice(EDGE_SYSTEM_IDS)
        elif roll < 0.35:
            x, z, y = rnd.choice(EDGE_COORDS), rnd.choice(EDGE_COORDS), rnd.choice(EDGE_Y)
        elif roll < 0.45:
            # near the galactic centre, where voxel attributes change shape
            x = (rnd.randrange(-12, 13)) & 0xFFF
            z = (rnd.randrange(-12, 13)) & 0xFFF
            y = (rnd.randrange(-12, 13)) & 0xFF
        elif roll < 0.6:
            system = rnd.randrange(1, 0x2FF)  # the range real systems mostly occupy
        code = (planet << 44) | (system << 32) | (y << 24) | (z << 12) | x
        return code, galaxy

    def guarded(fn, *a):
        try:
            return fn(*a)
        except Exception as exc:  # the port must fail on exactly the same inputs
            return f"ERR:{type(exc).__name__}"

    out = sys.stdout
    for _ in range(args.count):
        code, galaxy = random_case()
        seeds = guarded(planetSeeds, code, galaxy)
        rec = {
            "code": f"{code:012X}",
            "galaxy": galaxy,
            "region": guarded(regionName, code, galaxy),
            "system": guarded(systemName, code, galaxy),
            "planet": guarded(planetName, code, galaxy),
            "sysattr": guarded(systemAttributes, code, galaxy),
            "voxel": guarded(voxelAttributes, code),
        }
        if isinstance(seeds, dict):
            rec["seeds"] = [f"{s & 0xFFFFFFFFFFFFFFFF:016X}" for s in seeds["planet_seeds"]]
            rec["planet_count"] = seeds["planet_count"]
            rec["moon_count"] = seeds["moon_count"]
            rec["sizes"] = seeds["sizes"]
            # names of every body, in generation order
            rec["body_names"] = [guarded(planetName, s) for s in seeds["planet_seeds"]]
        else:
            rec["seeds"] = seeds
        out.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
