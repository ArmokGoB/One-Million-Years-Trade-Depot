#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes tests/fixtures/ship-vectors.json: the ship model's output for a few addresses.

tools/captures/ship_model.py predicts a system's 50 ship seeds from its
address, and whether its exotic is a squid; tests/ships.test.ts replays
these vectors through the TypeScript port. The addresses are made up, picked by a fixed search so that between
them they cover every kind of body layout and every dominant race the model
treats differently. CI regenerates the file and fails if it changed.

Usage:
    python3 tools/crosscheck/ship_vectors.py --namegen /path/to/nms_namegen
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DEFAULT = ROOT / "tests" / "fixtures" / "ship-vectors.json"
MASK32 = 0xFFFFFFFF

# What each vector is there for, in the order the search fills them.
WANTED = [
    "Gek, no moons",
    "Korvax, a planet with one moon",
    "Vy'keen, a planet with two moons",
    "uncharted",
    "abandoned",
    "a prime planet with moons",
    "six bodies",
    "purple star",
    "gas giant layout",
    "another galaxy, with a planet digit",
    "two planets with two moons each",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--namegen", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    sys.path.insert(0, str(args.namegen.resolve()))
    sys.path.insert(0, str(ROOT / "tools" / "captures"))
    import ship_model  # noqa: E402
    from nms_namegen.system import systemAttributes  # noqa: E402

    def kinds(code: int, galaxy: int) -> set[str]:
        attributes = systemAttributes(code & 0x0FFFFFFFFFFF, galaxy)
        ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & MASK32)
        bodies = ship_model.bodies(ua)
        if attributes["star_type"] == 4:
            # Every body of a purple system is a prime body, so none has attractors.
            return {"gas giant layout" if bodies is None else "purple star"}
        found = set()
        moons = {k: [j for j, b in enumerate(bodies) if b.parent == k] for k in range(len(bodies))}
        inhabited = not attributes["abandoned"] and not attributes["uncharted"]
        if inhabited and attributes["dominant_race"] == 1 and not any(b.parent >= 0 for b in bodies):
            found.add("Gek, no moons")
        if (
            inhabited
            and attributes["dominant_race"] == 2
            and any(len(m) == 1 and not bodies[k].prime for k, m in moons.items())
        ):
            found.add("Korvax, a planet with one moon")
        if inhabited and attributes["dominant_race"] == 3 and ship_model.uncertainty(bodies):
            found.add("Vy'keen, a planet with two moons")
        if attributes["uncharted"]:
            found.add("uncharted")
        if attributes["abandoned"]:
            found.add("abandoned")
        if any(m and bodies[k].prime for k, m in moons.items()):
            found.add("a prime planet with moons")
        if len(bodies) == 6:
            found.add("six bodies")
        if len(ship_model.two_moon_planets(bodies)) == 2:
            found.add("two planets with two moons each")
        if galaxy != 0 and code >> 44:
            found.add("another galaxy, with a planet digit")
        return found

    rnd = random.Random(20261001)
    chosen: dict[str, tuple[int, int]] = {}
    while len(chosen) < len(WANTED):
        purple = rnd.random() < 0.3
        system = rnd.randrange(0x3E9, 0x42A) if purple else rnd.randrange(1, 0x300)
        galaxy = rnd.randrange(256) if rnd.random() < 0.5 else 0
        planet = rnd.randrange(1, 7) if rnd.random() < 0.2 else 0
        code = (planet << 44) | (system << 32) | (rnd.randrange(0x100) << 24) | (rnd.randrange(0x1000) << 12)
        code |= rnd.randrange(0x1000)
        for kind in sorted(kinds(code, galaxy) - chosen.keys(), key=WANTED.index):
            chosen[kind] = (code, galaxy)
            break

    vectors = []
    for kind in WANTED:
        code, galaxy = chosen[kind]
        ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & MASK32)
        bodies = ship_model.bodies(ua) or []
        prediction, *others = ship_model.predictions(ua)

        def squid(seed: int) -> dict[str, bool]:
            return ship_model.exotic_squid(seed)._asdict()

        vectors.append(
            {
                "what": kind,
                "code": f"{code:012X}",
                "galaxy": galaxy,
                "bodies": [[b.size, b.parent, b.prime] for b in bodies],
                "start": prediction.start,
                "uncertain": prediction.uncertain,
                "ships": [f"{s:016X}" for s in prediction.ships],
                "exoticSquid": squid(prediction.ships[20]),
                "crash": f"{prediction.crash:016X}",
                # the other ways a two-moon planet's moons can be arranged
                "others": [
                    {
                        "start": o.start,
                        "exotic": f"{o.ships[20]:016X}",
                        "exoticSquid": squid(o.ships[20]),
                        "crash": f"{o.crash:016X}",
                    }
                    for o in others
                ],
            }
        )

    payload = {
        "_source": "tools/captures/ship_model.py over made-up addresses, written by tools/crosscheck/ship_vectors.py.",
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
