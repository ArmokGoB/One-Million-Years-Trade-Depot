#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builds src/core/data/name-tables.json from nms_namegen's name data.

nms_namegen ships its name-generation data as a 5.4 MB nested search tree
(letter_map.json) plus eight "alphaset" strings. The browser only ever needs
the answer the tree gives for a 1-3 letter key, so this script asks the
reference implementation for every key that can occur in a name and stores
the answers flat:

    weights : distinct float32 weights, as their shortest decimal form
    tables  : one object per alphaset, key -> "<chars>:<weight indices, base 36>"

Every stored answer is checked against the reference lookup before writing,
so the output is exactly equivalent to nms_namegen's getStringWeights().

Usage:
    python3 tools/build_name_tables.py --namegen /path/to/nms_namegen

The data is derived from nms_namegen (MIT); see THIRD_PARTY_NOTICES.md.
"""

import argparse
import itertools
import json
import subprocess
import sys
from pathlib import Path

ALPHABET = "abcdefghijklmnopqrstuvwxyz'"  # every character a generated name can contain
OUT_DEFAULT = Path(__file__).resolve().parent.parent / "src" / "core" / "data" / "name-tables.json"


def base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--namegen", required=True, type=Path, help="path to a checkout of hadsh/nms_namegen")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    sys.path.insert(0, str(args.namegen.resolve()))
    import numpy as np  # noqa: E402  (nms_namegen depends on numpy too)
    from nms_namegen import generator as g  # noqa: E402

    commit = subprocess.run(
        ["git", "-C", str(args.namegen), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip() or "unknown"

    letter_map = g.LetterMap
    weight_index: dict[float, int] = {}
    weight_strings: list[str] = []
    tables: list[dict[str, str]] = []
    first_chars: list[str] = []

    def weight_id(x: float) -> int:
        if x not in weight_index:
            s = np.format_float_positional(np.float32(x), unique=True, trim="-")
            # The browser decodes with Math.fround(Number(s)); prove that round-trips.
            if float(np.float32(float(s))) != x:
                raise SystemExit(f"weight {x!r} does not round-trip through {s!r}")
            weight_index[x] = len(weight_strings)
            weight_strings.append(s)
        return weight_index[x]

    for alphaset in range(8):
        sub = letter_map[str(alphaset)]
        first_chars.append("".join(sorted(sub.keys())))
        table: dict[str, str] = {}
        for length in (1, 2, 3):
            for tup in itertools.product(ALPHABET, repeat=length):
                key = "".join(tup)
                if key[0] not in sub:
                    continue  # the reference raises KeyError here; the browser port does the same
                result = g.getStringWeights(key, alphaset)
                if result is None:
                    continue
                chars = "".join(w["Item1"] for w in result)
                if len(chars) != len(result):
                    raise SystemExit(f"multi-character entry under {key!r}")
                table[key] = chars + ":" + ".".join(base36(weight_id(w["Item2"])) for w in result)
        tables.append(table)

    # Round-trip check of the whole table against the reference lookup.
    decoded_weights = [float(np.float32(float(s))) for s in weight_strings]
    for alphaset in range(8):
        sub = letter_map[str(alphaset)]
        for length in (1, 2, 3):
            for tup in itertools.product(ALPHABET, repeat=length):
                key = "".join(tup)
                if key[0] not in sub:
                    continue
                expected = g.getStringWeights(key, alphaset)
                entry = tables[alphaset].get(key)
                if expected is None:
                    assert entry is None, key
                    continue
                chars, idx = entry.split(":")
                got = [(c, decoded_weights[int(i, 36)]) for c, i in zip(chars, idx.split("."))]
                want = [(w["Item1"], w["Item2"]) for w in expected]
                assert got == want, (alphaset, key, got, want)

    payload = {
        "_source": (
            "Derived from nms_namegen (https://github.com/hadsh/nms_namegen, commit "
            f"{commit}), MIT License. Regenerate with tools/build_name_tables.py. "
            "See THIRD_PARTY_NOTICES.md."
        ),
        "alphasets": g.ALPHASETS,
        "firstChars": first_chars,
        "weights": weight_strings,
        "tables": tables,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"), ensure_ascii=True)
        fh.write("\n")
    entries = sum(len(t) for t in tables)
    print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes, {entries:,} entries, {len(weight_strings):,} weights)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
