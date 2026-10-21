#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes tests/fixtures/part-names-vectors.json: the named parts of ships with made-up seeds.

tools/captures/part_names_model.py names a fighter's, hauler's, explorer's or solar's parts from its seed;
tests/partnames.test.ts replays these vectors through the TypeScript port. The seeds are made up, picked by
a fixed search: for each ship type, the first few seeds, and then one for each case the naming treats
apart: a hauler wing with no name in the game and one whose component fits by any one of its groups; and
explorers with a matched pair of wings on each of their two cockpits, with a right wing named by a
lookalike, and with wings whose accessory lists the generator never picks from. CI regenerates the file
and fails if it changed.

Usage:
    python3 tools/crosscheck/part_names_vectors.py
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DEFAULT = ROOT / "tests" / "fixtures" / "part-names-vectors.json"
EACH = 3

sys.path.insert(0, str(ROOT / "tools" / "captures"))
import part_names_model  # noqa: E402
import parts_model  # noqa: E402


def wing_rule_any(seed: int) -> bool:
    """A hauler whose wings are a component that fits by any one of its groups."""
    t = part_names_model.tables()
    any_names = {c[0] for _, comps in t["models"]["DROPSHIP_PROC"] for c in comps if c[1] == 1}
    return any(n.name in any_names for n in part_names_model.names("DROPSHIP_PROC", seed))


# The cases each ship type needs beyond its first few seeds: a description and a test of the seed.
CASES = {
    "DROPSHIP_PROC": [
        ("a wing with no name", lambda seed: len(part_names_model.names("DROPSHIP_PROC", seed)) == 2),
        ("wings that fit by any one group", wing_rule_any),
    ],
    "SCIENTIFIC_PROC": [
        ("a matched pair of wings", lambda seed: "_WINGS_SYM" in parts_model.parts("SCIENTIFIC_PROC", seed)),
        ("a matched pair on the other cockpit", lambda seed: "_WINGS_SYM1" in parts_model.parts("SCIENTIFIC_PROC", seed)),
        ("a right wing named by a lookalike", lambda seed: "_WINGSR_B4" in parts_model.parts("SCIENTIFIC_PROC", seed)),
        (
            "a right wing named by a lookalike on the other cockpit",
            lambda seed: "_WINGSRIGHT_K4" in parts_model.parts("SCIENTIFIC_PROC", seed),
        ),
        ("a left wing with an empty accessory list", lambda seed: "_WINGSL_G" in parts_model.parts("SCIENTIFIC_PROC", seed)),
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    rnd = random.Random(20261021)
    vectors = []
    for model in part_names_model.models():
        seeds = [rnd.getrandbits(64) for _ in range(EACH)]
        for _what, test in CASES.get(model, []):
            seed = rnd.getrandbits(64)
            while not test(seed):
                seed = rnd.getrandbits(64)
            seeds.append(seed)
        for seed in seeds:
            names = [[n.side, n.name, list(n.parts)] for n in part_names_model.names(model, seed)]
            vectors.append({"model": model, "seed": f"{seed:016X}", "names": names})

    lines = ",\n".join("  " + json.dumps(v, separators=(",", ":"), ensure_ascii=False) for v in vectors)
    source = json.dumps(
        "tools/captures/part_names_model.py over made-up seeds, written by tools/crosscheck/part_names_vectors.py."
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(f'{{\n "_source": {source},\n "vectors": [\n{lines}\n ]\n}}\n', encoding="utf-8")
    json.loads(args.out.read_text(encoding="utf-8"))
    print(f"wrote {args.out} ({len(vectors)} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
