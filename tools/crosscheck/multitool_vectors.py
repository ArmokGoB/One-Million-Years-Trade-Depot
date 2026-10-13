#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes tests/fixtures/multitool-vectors.json: the first run of a few systems' multi-tools.

tools/captures/multitool_model.py works out the first run of a system's own
multi-tools from its address; tests/multitools.test.ts replays these vectors
through the TypeScript port. The addresses are made up, picked by a fixed
search: three systems with each number of standard multi-tools, from
several galaxies, purple systems and planet digits among them. CI
regenerates the file and fails if it changed.

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

    vectors = []
    for found in chosen.values():
        for code, galaxy in found:
            ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)
            run = [[name, f"{seed:016X}"] for name, seed in multitool_model.first_run(ua)]
            vectors.append({"code": f"{code:012X}", "galaxy": galaxy, "run": run})

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
