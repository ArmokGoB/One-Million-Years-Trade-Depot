#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes tests/fixtures/paint-vectors.json: palettes and paint of every model the site paints, with made-up
seeds.

tools/captures/paint_model.py makes palettes from a seed and paints a model; tests/paint.test.ts replays these
vectors through the TypeScript port. The seeds are made up, by a fixed search: two palette seeds, whose base
and older palettes are kept whole, and two seeds for each model, with its own palettes or a made-up system's
as paint_model.palette_source() says, and the Sentinel ship once more with the texture hint POLICE. CI
regenerates the file and fails if it changed.

Usage:
    python3 tools/crosscheck/paint_vectors.py
"""

import argparse
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DEFAULT = ROOT / "tests" / "fixtures" / "paint-vectors.json"
EACH = 2

sys.path.insert(0, str(ROOT / "tools" / "captures"))
import paint_model  # noqa: E402
import parts_model  # noqa: E402


def short(value: float) -> float:
    """The shortest decimal that is the same single-precision number."""
    for digits in range(1, 10):
        text = f"{value:.{digits}g}"
        if struct.unpack("<f", struct.pack("<f", float(text)))[0] == value:
            return float(text)
    raise ValueError(value)


def colors(palette) -> list | None:
    return None if palette is None else [[short(x) for x in color] for color in palette]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    rnd = random.Random(20261021)
    palettes = []
    for _ in range(2):
        seed = rnd.getrandbits(64)
        palettes.append(
            {
                "seed": f"{seed:016X}",
                "base": [colors(p) for p in paint_model.palettes(seed)],
                "legacy": [colors(p) for p in paint_model.legacy_palettes(seed)],
            }
        )

    part_models = set(parts_model.models())
    paints = []
    for model in paint_model.models():
        hints = [""] * EACH + (["POLICE"] if model == "SENTINELSHIP_PROC" else [])
        for hint in hints:
            seed = rnd.getrandbits(64)
            source = paint_model.palette_source(model)
            palette_seed = seed if source != paint_model.SYSTEM else rnd.getrandbits(64)
            pals = (paint_model.legacy_palettes if source == paint_model.LEGACY else paint_model.palettes)(palette_seed)
            parts = parts_model.parts(model, seed) if model in part_models else []
            passes = paint_model.paint(model, parts, seed, pals, hint)
            paints.append(
                {
                    "model": model,
                    "seed": f"{seed:016X}",
                    "palettes": f"{palette_seed:016X}",
                    "hint": hint,
                    "passes": [
                        [
                            [
                                p.group,
                                p.layer,
                                p.option,
                                p.palette,
                                p.alt,
                                colors([p.color])[0] if p.color else None,
                                int(p.painted),
                            ]
                            for p in passes[k]
                        ]
                        for k in sorted(passes)
                    ],
                }
            )

    def compact(value) -> str:
        return json.dumps(value, separators=(",", ":"))

    source = json.dumps(
        "tools/captures/paint_model.py over made-up seeds, written by tools/crosscheck/paint_vectors.py. A palette "
        "seed's palettes: each one's five colors (null where the tables have none); a paint: each pass's layers, "
        "[group, layer, option, palette, color alternative, color (null for none), painted]."
    )
    text = (
        f'{{\n "_source": {source},\n "palettes": [\n'
        + ",\n".join("  " + compact(p) for p in palettes)
        + '\n ],\n "paints": [\n'
        + ",\n".join("  " + compact(p) for p in paints)
        + "\n ]\n}\n"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    json.loads(args.out.read_text(encoding="utf-8"))
    print(f"wrote {args.out} ({len(palettes)} palette seeds, {len(paints)} paints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
