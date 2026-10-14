#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes tests/fixtures/parts-vectors.json: the parts of a few models with made-up seeds.

tools/captures/parts_model.py picks a model's parts from its seed;
tests/parts.test.ts replays these vectors through the TypeScript port. The
seeds are made up, picked by a fixed search: for each model, a few seeds,
the first of them, for a model with rare options, one that picks one, and
for the exotic, one squid. CI regenerates the file and fails if it changed.

Usage:
    python3 tools/crosscheck/parts_vectors.py
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DEFAULT = ROOT / "tests" / "fixtures" / "parts-vectors.json"
EACH = 4
SQUID = "_SCLASSSHIP_SQU"

sys.path.insert(0, str(ROOT / "tools" / "captures"))
import parts_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    rnd = random.Random(20261013)
    vectors = []
    for model in parts_model.models():
        rare = {part for part, cls in parts_model.reachable(model).items() if cls == 1}
        found: list[tuple[int, list[str]]] = []
        while len(found) < EACH:
            seed = rnd.getrandbits(64)
            parts = parts_model.parts(model, seed)
            if not found and rare and not rare.intersection(parts):
                continue  # the first of a model with rare options picks one
            if model == "S-CLASS_PROC" and len(found) == 1 and parts[0] != SQUID:
                continue  # and the exotic's second is a squid
            found.append((seed, parts))
        vectors += [{"model": model, "seed": f"{seed:016X}", "parts": parts} for seed, parts in found]

    lines = ",\n".join("  " + json.dumps(v, separators=(",", ":")) for v in vectors)
    source = json.dumps(
        "tools/captures/parts_model.py over made-up seeds, written by tools/crosscheck/parts_vectors.py."
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(f'{{\n "_source": {source},\n "vectors": [\n{lines}\n ]\n}}\n', encoding="utf-8")
    json.loads(args.out.read_text(encoding="utf-8"))
    print(f"wrote {args.out} ({len(vectors)} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
