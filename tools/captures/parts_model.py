# SPDX-License-Identifier: AGPL-3.0-or-later
"""A model's parts from its seed: which parts the game picks for a ship or a multi-tool.

The game picks the parts of a procedural model from its descriptor (see
tools/build_part_tables.py, which keeps what picking needs in
src/core/data/part-tables.json) with the generator seeded with the model's
seed, a ship's or multi-tool's seed as the capture mod records it. It goes
through the descriptor's lists in order:

1. A list one of whose options is already among the model's parts, by its
   ID as the descriptor has it, is skipped, without a draw. That way a part
   two scenes share, such as a wing and its mirror image, is picked once.
2. Otherwise one draw picks one of its options. Each option is as likely as
   the next, except that one whose name has xRARE in it weighs 0.05 against
   the others' 1, and one with xNEVER weighs nothing (case matters). A list
   of such options only is skipped.
3. The part goes on the model's list under its ID less any LOD suffix (a
   level of detail: _HULL_BLOD0 is listed as _HULL_B), unless it's on it
   already.
4. If the option has child lists, two more draws make a seed, mixed as a
   ship's seed is (game_rng.mix), and the child lists are picked from in the
   same way with the generator seeded with that, their parts following the
   option.
5. Then two more draws make a seed for each scene the option brings in; that
   scene's descriptor, if it has one, is picked from with the generator
   seeded with it, and its parts follow.

The parts come out in that order, as the game lists them. Worked out from the
parts the capture mod records with each seed; tools/captures/report.py checks
every recorded model against this, and src/core/parts.ts is the site's port.
Whether skipping a list of xNEVER options takes a draw doesn't show: in the
game's descriptors, no such list has another after it in the same stream.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from game_rng import Stream, mix

TABLES = Path(__file__).resolve().parents[2] / "src" / "core" / "data" / "part-tables.json"

# How much an option weighs in a pick, by the weight class the table gives it: normal, xRARE, xNEVER.
WEIGHTS = (1.0, 0.05, 0.0)
# A level-of-detail suffix, which the game drops from the IDs it lists.
LOD_SUFFIX = re.compile(r"LOD\d+$")


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


def _walk(lists: list, stream: Stream, out: list[str], reached: set[str] | None = None) -> None:
    trees = tables()["trees"]
    for _type_id, options in lists:
        if reached is not None:
            reached.update(LOD_SUFFIX.sub("", unpack(option)[0]) for option in options)
        if any(unpack(option)[0] in out for option in options):
            continue  # decided already
        picked = _pick(stream, options)
        if picked is None:
            continue
        part, _, refs, children = picked
        listed = LOD_SUFFIX.sub("", part)
        if listed not in out:
            out.append(listed)
        if children:
            low, high = stream.word(), stream.word()
            _walk(children, Stream(mix((high << 32) | low)), out, reached)
        for ref in refs:
            low, high = stream.word(), stream.word()
            if ref >= 0:
                _walk(trees[ref], Stream(mix((high << 32) | low)), out, reached)


def reachable(model: str) -> dict[str, int]:
    """Every option ``model``'s tables can pick, by its ID as the descriptor has it, with its weight class
    (0 normal, 1 rare, 2 never)."""
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
    return parts_and_options(model, seed)[0]


def parts_and_options(model: str, seed: int) -> tuple[list[str], set[str]]:
    """The parts the game picks for ``model`` with ``seed``, in order, and every option of every list it goes
    through on the way, picked or not, less any LOD suffix: the parts it could have picked instead."""
    t = tables()
    out: list[str] = []
    reached: set[str] = set()
    _walk(t["trees"][t["models"][model]], Stream(seed), out, reached)
    return out, reached
