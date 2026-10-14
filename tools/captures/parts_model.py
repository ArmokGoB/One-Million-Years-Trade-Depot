# SPDX-License-Identifier: AGPL-3.0-or-later
"""A model's parts from its seed: which parts the game picks for a ship or a multi-tool.

The game picks the parts of a procedural model from its descriptor (see
tools/build_part_tables.py, which keeps what picking needs in
src/core/data/part-tables.json) with the generator seeded with the model's
seed, a ship's or multi-tool's seed as the capture mod records it:

1. It goes through the descriptor's lists in order and picks one option from
   each with one draw. Each option is as likely as the next, except that an
   option whose name says xRARE weighs 0.05 against the others' 1, and one
   whose name says xNEVER weighs nothing. A list of such options only is
   skipped.
2. If the option it picked has child lists, two more draws make a seed,
   mixed as a ship's seed is (game_rng.mix), and the child lists are picked
   from in the same way with the generator seeded with that, and their parts
   follow the option.
3. Then two more draws make a seed for each scene the option brings in; that
   scene's descriptor, if it has one, is picked from with the generator seeded
   with it, and its parts follow.

The parts come out in that order, as the game lists them. Worked out from the
parts the capture mod records with each seed; tools/captures/report.py checks
every recorded model against this, and src/core/parts.ts is the site's port.
Whether skipping a list of xNEVER options takes a draw doesn't show in the
records yet: no such list is followed by another in the same stream.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from game_rng import Stream, mix

TABLES = Path(__file__).resolve().parents[2] / "src" / "core" / "data" / "part-tables.json"

# How much an option weighs in a pick, by the weight class the table gives it: normal, xRARE, xNEVER.
WEIGHTS = (1.0, 0.05, 0.0)


@lru_cache(maxsize=1)
def tables() -> dict:
    with open(TABLES, encoding="utf-8") as f:
        return json.load(f)


def models() -> list[str]:
    """The models the table has, by key (FIGHTER_PROC, MULTITOOL, ...)."""
    return list(tables()["models"])


def unpack(option) -> tuple[str, int, list[int], list]:
    """An option of the tables as (ID, weight class, referenced scenes, child lists)."""
    if isinstance(option, str):
        return option, 0, [], []
    part, cls, refs, children = [*option, *(None, 0, [], [])[len(option) :]]
    return part, cls, refs, children


def _pick(stream: Stream, options: list) -> tuple | None:
    unpacked = [unpack(o) for o in options]
    weights = [WEIGHTS[cls] for _, cls, _, _ in unpacked]
    if all(w == 1.0 for w in weights):
        return unpacked[stream.below(len(unpacked))]
    total = sum(weights)
    if total == 0.0:
        return None
    r = stream.unit() * total
    acc = 0.0
    last = None
    for option, w in zip(unpacked, weights):
        if w == 0.0:
            continue
        acc += w
        last = option
        if r < acc:
            return option
    return last  # only if rounding put r at the very top


def _walk(lists: list, stream: Stream, out: list[str]) -> None:
    trees = tables()["trees"]
    for _type_id, options in lists:
        picked = _pick(stream, options)
        if picked is None:
            continue
        part, _, refs, children = picked
        out.append(part)
        if children:
            low, high = stream.word(), stream.word()
            _walk(children, Stream(mix((high << 32) | low)), out)
        for ref in refs:
            low, high = stream.word(), stream.word()
            if ref >= 0:
                _walk(trees[ref], Stream(mix((high << 32) | low)), out)


def reachable(model: str) -> dict[str, int]:
    """Every option ``model``'s tables can pick, by ID, with its weight class (0 normal, 1 rare, 2 never)."""
    t = tables()
    found: dict[str, int] = {}
    seen: set[int] = set()

    def walk(lists: list) -> None:
        for _type_id, options in lists:
            for option in options:
                part, cls, refs, children = unpack(option)
                found[part] = cls
                walk(children)
                for ref in refs:
                    if ref >= 0 and ref not in seen:
                        seen.add(ref)
                        walk(t["trees"][ref])

    walk(t["trees"][t["models"][model]])
    return found


def parts(model: str, seed: int) -> list[str]:
    """The parts the game picks for ``model`` (a key of the table, such as FIGHTER_PROC) with ``seed``, in order."""
    t = tables()
    out: list[str] = []
    _walk(t["trees"][t["models"][model]], Stream(seed), out)
    return out
