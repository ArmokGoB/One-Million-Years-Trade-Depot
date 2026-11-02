#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes tests/fixtures/multitool-vectors.json: a few systems' own multi-tools.

tools/captures/multitool_model.py works out a system's own multi-tools from
its address and the day; tests/multitools.test.ts replays these vectors
through the TypeScript port. The addresses are made up, picked by a fixed
search: three systems with each number of standard multi-tools, from
several galaxies, purple systems and planet digits among them. Each vector
has the first run and a day's rotation made from the system's address, on
a day of its own, and, for an address with a planet digit, both made from
the planet's address too. CI regenerates the file and fails if it changed.

Usage:
    python3 tools/crosscheck/multitool_vectors.py
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DEFAULT = ROOT / "tests" / "fixtures" / "multitool-vectors.json"
EACH = 3
# Days for the rotations, in whole days since 1970 UTC, from the epoch to far ahead.
DAYS = (0, 1, 20_000, 20_717, 20_718, 20_759, 40_000, 99_999, 2**20 + 3)

sys.path.insert(0, str(ROOT / "tools" / "captures"))
import multitool_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    rnd = random.Random(20261013)
    chosen: dict[int, list[tuple[int, int]]] = {count: [] for count in multitool_model.STANDARD_COUNTS}
    while any(len(found) < EACH for found in chosen.values()):
        purple = rnd.random() < 0.25
        system = rnd.randrange(0x3E9, 0x42A) if purple else rnd.randrange(1, 0x300)
        galaxy = rnd.randrange(256) if rnd.random() < 0.5 else 0
        planet = rnd.randrange(1, 7) if rnd.random() < 0.3 else 0
        code = (planet << 44) | (system << 32) | (rnd.randrange(0x100) << 24) | (rnd.randrange(0x1000) << 12)
        code |= rnd.randrange(0x1000)
        ua = (system << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)  # the system's: no planet digit
        standard = sum(1 for name, _ in multitool_model.first_run(ua) if name == multitool_model.STANDARD)
        if len(chosen[standard]) < EACH:
            chosen[standard].append((code, galaxy))

    def listed(made: list[tuple[str, int]]) -> list[list[str]]:
        return [[name, f"{seed:016X}"] for name, seed in made]

    vectors = []
    for found in chosen.values():
        for code, galaxy in found:
            ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)
            day = DAYS[len(vectors) % len(DAYS)]
            vector = {"code": f"{code:012X}", "galaxy": galaxy, "run": listed(multitool_model.first_run(ua))}
            vector.update(day=day, rotation=listed(multitool_model.rotation(ua, day)))
            if planet := code >> 44:
                at = ua | (planet << 52)  # the planet's address, as the game makes a set with the player there
                vector["planet"] = {
                    "run": listed(multitool_model.first_run(at)),
                    "rotation": listed(multitool_model.rotation(at, day)),
                }
            vectors.append(vector)

    payload = {
        "_source": "tools/captures/multitool_model.py over made-up addresses, written by "
        "tools/crosscheck/multitool_vectors.py.",
        "vectors": vectors,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
        fh.write("\n")
    print(f"wrote {args.out} ({len(vectors)} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
