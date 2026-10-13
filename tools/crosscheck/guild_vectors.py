#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes tests/fixtures/guild-vectors.json: the guild for a few addresses.

tools/captures/guild_model.py works out which guild's envoy a system's space
station has from its address; tests/guild.test.ts replays these vectors
through the TypeScript port. The addresses are made up, picked by a fixed
search: four systems with each guild, from several galaxies, purple systems
and planet digits among them. Each vector holds the first draw the guild
comes from, so the port has to match it exactly. CI regenerates the file and
fails if it changed.

Usage:
    python3 tools/crosscheck/guild_vectors.py
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DEFAULT = ROOT / "tests" / "fixtures" / "guild-vectors.json"
EACH = 4

sys.path.insert(0, str(ROOT / "tools" / "captures"))
import guild_model  # noqa: E402
from game_rng import MASK32, stream_states  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    rnd = random.Random(20261013)
    chosen: dict[str, list[tuple[int, int]]] = {guild: [] for guild in guild_model.GUILDS}
    while any(len(found) < EACH for found in chosen.values()):
        purple = rnd.random() < 0.25
        system = rnd.randrange(0x3E9, 0x42A) if purple else rnd.randrange(1, 0x300)
        galaxy = rnd.randrange(256) if rnd.random() < 0.5 else 0
        planet = rnd.randrange(1, 7) if rnd.random() < 0.3 else 0
        code = (planet << 44) | (system << 32) | (rnd.randrange(0x100) << 24) | (rnd.randrange(0x1000) << 12)
        code |= rnd.randrange(0x1000)
        ua = (system << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)  # the system's: no planet digit
        guild = guild_model.guild(ua)
        if len(chosen[guild]) < EACH:
            chosen[guild].append((code, galaxy))

    vectors = []
    for guild, found in chosen.items():
        for code, galaxy in found:
            ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)
            first = stream_states(ua, 1)[0] & MASK32
            vectors.append({"code": f"{code:012X}", "galaxy": galaxy, "firstDraw": f"{first:08X}", "guild": guild})

    payload = {
        "_source": "tools/captures/guild_model.py over made-up addresses, written by tools/crosscheck/guild_vectors.py.",
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
