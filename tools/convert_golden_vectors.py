#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Copies nms_namegen's golden vectors into a form JavaScript can read exactly.

The reference file stores 64-bit planet seeds as JSON numbers (some of them
negative, two's-complement). JavaScript's JSON.parse rounds anything above
2**53, so seeds and portal codes are rewritten as hex strings. Nothing else
changes: these vectors are nms_namegen's own output (MIT), replayed by
tests/golden-vectors.test.ts to prove the TypeScript port is bit-for-bit
identical.

Usage:
    python3 tools/convert_golden_vectors.py --namegen /path/to/nms_namegen
"""

import argparse
import json
import subprocess
from pathlib import Path

OUT_DEFAULT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden-vectors.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--namegen", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    src = args.namegen / "test" / "fixtures" / "golden_vectors.json"
    commit = subprocess.run(
        ["git", "-C", str(args.namegen), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip() or "unknown"

    with open(src, encoding="utf-8") as fh:
        records = json.load(fh)

    vectors = []
    for rec in records:
        vectors.append(
            {
                "code": f"{rec['code']:012X}",
                "galaxy": rec["galaxy"],
                "region": rec["region"],
                "system": rec["system"],
                "planet": rec["planet"],
                "sysattr": rec["sysattr"],
                "seeds": [f"{s & 0xFFFFFFFFFFFFFFFF:016X}" for s in rec["seeds"]],
                "planet_count": rec["planet_count"],
                "moon_count": rec["moon_count"],
                "sizes": rec["sizes"],
                "voxel": rec["voxel"],
            }
        )

    payload = {
        "_source": (
            "nms_namegen test/fixtures/golden_vectors.json "
            f"(https://github.com/hadsh/nms_namegen, commit {commit}), MIT License; "
            "codes and seeds rewritten as hex strings by tools/convert_golden_vectors.py."
        ),
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
