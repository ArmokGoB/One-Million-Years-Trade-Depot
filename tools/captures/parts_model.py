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
2. Otherwise one draw picks one of its options, as the game's code does it:
   each option weighs 20, one whose name has xRARE in it 1 and one with
   xNEVER 0 (case matters), and the draw times the total weight, over 2^32,
   falls on one of them in turn. So a rare option is exactly a twentieth as
   likely as another. A list of xNEVER options only is skipped, without a
   draw.
3. The part goes on the model's list under its ID less any LOD suffix (a
   level of detail: _HULL_BLOD0 is listed as _HULL_B), unless it's on it
   already.
4. If the option has child lists, two more draws make a seed, mixed as a
   ship's seed is (game_rng.mix), and the child lists are picked from in the
   same way with the generator seeded with that, their parts following the
   option; but where every child list offers xNEVER options only, the game
   neither draws nor goes through them.
5. Then two more draws make a seed for each scene the option brings in; that
   scene's descriptor, if it has one, is picked from with the generator
   seeded with it, and its parts follow. A scene whose descriptor offers
   xNEVER options only takes no draws.

The parts come out in that order, as the game lists them. Worked out from the
parts the capture mod records with each seed, and then read in the game's
code; tools/captures/report.py checks every recorded model against this, and
src/core/parts.ts is the site's port.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from game_rng import Stream, mix

TABLES = Path(__file__).resolve().parents[2] / "src" / "core" / "data" / "part-tables.json"

# How much an option weighs in a pick, by the weight class the table gives it: normal, xRARE, xNEVER.
WEIGHTS = (20, 1, 0)
NEVER = 2
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
    """The option one draw picks, by weight; none, without a draw, from options that all weigh nothing."""
    unpacked = [unpack(o) for o in options]
    total = sum(WEIGHTS[cls] for _, cls, _, _ in unpacked)
    if total == 0:
        return None
    r = stream.below(total)
    for option in unpacked:
        weight = WEIGHTS[option[1]]
        if r < weight:
            return option
        r -= weight
    raise AssertionError("a draw below the total weight falls on an option")


def never_only(lists: list) -> bool:
    """Whether every one of these lists offers options, and only xNEVER ones: the game goes through no such
    child lists or scene descriptor, nor draws a seed for them."""
    return bool(lists) and all(options and all(unpack(o)[1] == NEVER for o in options) for _, options in lists)


def _offer(lists: list, reached: set[str] | None) -> None:
    """Note the options of these lists as offered, less any LOD suffix."""
    if reached is not None:
        for _type_id, options in lists:
            reached.update(LOD_SUFFIX.sub("", unpack(option)[0]) for option in options)


def _walk(lists: list, stream: Stream, out: list[str], reached: set[str] | None = None) -> None:
    trees = tables()["trees"]
    for type_id, options in lists:
        _offer([(type_id, options)], reached)
        if any(unpack(option)[0] in out for option in options):
            continue  # decided already
        picked = _pick(stream, options)
        if picked is None:
            continue
        part, _, refs, children = picked
        listed = LOD_SUFFIX.sub("", part)
        if listed not in out:
            out.append(listed)
        # Lists of xNEVER options only, which the game doesn't go through, still count as offering them.
        if children and never_only(children):
            _offer(children, reached)
        elif children:
            low, high = stream.word(), stream.word()
            _walk(children, Stream(mix((high << 32) | low)), out, reached)
        for ref in refs:
            if ref >= 0 and never_only(trees[ref]):
                _offer(trees[ref], reached)
                continue
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
    through on the way, picked or not, less any LOD suffix: the parts it could have picked instead. The
    options of the xNEVER-only lists a picked part brings, which the game passes over, count too."""
    t = tables()
    out: list[str] = []
    reached: set[str] = set()
    _walk(t["trees"][t["models"][model]], Stream(seed), out, reached)
    return out, reached
