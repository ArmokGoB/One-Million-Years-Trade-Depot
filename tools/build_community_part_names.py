#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builds src/core/data/community-part-names.json from tools/community_part_names.tsv.

The game names the parts of the ships its Starship Fabricator builds (see build_part_names.py). Players name
the parts of the others: shuttles, exotics, Sentinel ships, freighters and capital freighters.
tools/community_part_names.tsv has their names, the No Man's Sky Coordinate Exchange's (NMSCE) and this
project's own for parts NMSCE has no name for, each with the part IDs that make it; its first lines say how
they're written.

This script checks the file against the parts tables (src/core/data/part-tables.json): each line's model has
parts, and every part ID it names is one that model's descriptors can pick. It writes each model's names in
the file's order, each [name, groups], a group being the part IDs that must all be on a ship for it to have
the part; a name whose only group is empty is on every ship of the model. tools/captures/part_names_model.py
and src/core/partnames.ts name a ship's parts from the result.

Usage:
    python3 tools/build_community_part_names.py
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DEFAULT = ROOT / "tools" / "community_part_names.tsv"
OUT_DEFAULT = ROOT / "src" / "core" / "data" / "community-part-names.json"

sys.path.insert(0, str(ROOT / "tools" / "captures"))
import parts_model  # noqa: E402

PART_ID = re.compile(r"_[A-Z0-9_]+")
ALWAYS = "always"


class SourceError(Exception):
    pass


def split_top(text: str, sep: str) -> list[str]:
    """``text`` split at each ``sep`` outside parentheses."""
    out, depth, start = [], 0, 0
    for k, c in enumerate(text):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                raise SourceError(f"unmatched ')' in {text!r}")
        elif c == sep and depth == 0:
            out.append(text[start:k])
            start = k + 1
    if depth:
        raise SourceError(f"unmatched '(' in {text!r}")
    out.append(text[start:])
    return [part.strip() for part in out]


def part_ids(term: str) -> list[str]:
    """A term's part IDs: one ID, or several in parentheses, any one of which will do."""
    if term.startswith("(") and term.endswith(")"):
        ids = [part.strip() for part in term[1:-1].split(",")]
    else:
        ids = [term]
    for part in ids:
        if not PART_ID.fullmatch(part):
            raise SourceError(f"not a part ID: {part!r}")
    return ids


def groups(parts: str) -> list[list[str]]:
    """The groups a line's parts stand for: each alternative's terms, one ID of each, in every combination."""
    if parts == ALWAYS:
        return [[]]
    out: list[list[str]] = []
    for alternative in split_top(parts, ","):
        terms = [part_ids(term) for term in split_top(alternative, "+")]
        for group in itertools.product(*terms):
            if len(set(group)) < len(group):
                raise SourceError(f"a part twice in one group: {alternative!r}")
            if list(group) not in out:
                out.append(list(group))
    return out


def options(model: str) -> set[str]:
    """The part IDs ``model``'s descriptors can pick, as a ship's parts list them."""
    return {
        parts_model.LOD_SUFFIX.sub("", part).upper()
        for part, weight_class in parts_model.reachable(model).items()
        if weight_class != parts_model.NEVER
    }


def read(source: Path) -> dict[str, list[list]]:
    models: dict[str, list[list]] = {}
    known = parts_model.models()
    pickable: dict[str, set[str]] = {}
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        try:
            if len(fields) != 3:
                raise SourceError(f"{len(fields)} fields, not 3 (model, name, parts)")
            model, name, parts = (field.strip() for field in fields)
            if model not in known:
                raise SourceError(f"no parts tables for {model!r}")
            if not name:
                raise SourceError("no name")
            found = groups(parts)
            pickable.setdefault(model, options(model))
            for group in found:
                for part in group:
                    if part not in pickable[model]:
                        raise SourceError(f"{model} never has {part}")
        except SourceError as exc:
            raise SourceError(f"{source.name}:{number}: {exc}") from None
        models.setdefault(model, []).append([name, found])
    return models


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    try:
        models = read(args.source)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    about = (
        "Derived from tools/community_part_names.tsv by tools/build_community_part_names.py. For each model, "
        "the names players use for its parts, NMSCE's and this project's own, in the file's order, each "
        "[name, groups]: a ship has the part when it has every part ID of one of its groups, and the part is "
        "made of the IDs of every such group. A name whose only group is empty is on every ship of the model."
    )

    def compact(value) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    # One name per line, so that a change to one shows as a change to its line.
    lines = ["{", f'"about":{compact(about)},', '"models":{']
    for k, (model, names) in enumerate(models.items()):
        lines.append(f'"{model}":[')
        lines.append(",\n".join(compact(entry) for entry in names))
        lines.append("]" + ("," if k + 1 < len(models) else ""))
    lines.append("}}")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.loads(args.out.read_text(encoding="utf-8"))  # still valid JSON
    count = sum(len(names) for names in models.values())
    print(f"Wrote {args.out}: {count} names of {len(models)} models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
