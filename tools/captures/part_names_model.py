# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ship's parts by the names the game gives them, from its seed.

The game names the parts of the ships it lets a player build at a space station's outfitting: fighters,
haulers, explorers and solars. Each slot of such a ship (fuselage or cockpit, wings, thrusters, sail) takes
components, each named, and each made of descriptor groups, sets of the part IDs a ship's descriptor lists
(see tools/build_part_names.py, which keeps what naming needs in src/core/data/part-names.json). A ship's
slot is named for the component that fits the parts parts_model.py picks for it:

1. A group fits when the descriptor went through a list that offers at least one of its parts, and the
   ship has every one of its parts that such a list offers. Parts of the group in lists the descriptor
   never goes through for this ship don't count: the outfitting's explorer components list the parts of
   both of the explorer's cockpits, for one, where a ship has one cockpit.
2. A component fits when all its groups fit, or, if its rule is 1, any one of them.
3. A slot is named when exactly one component fits and that component has a name.
4. An explorer with a matched pair of wings (the first part of one of the tables' pairs) is named as the
   outfitting's explorer with the same wing on both sides: as if it had the pair's second part, its right
   wing its left one.

Every fighter, hauler and solar has exactly one component fit each of its slots, but for one hauler wing
the game has no name for, and its slots are named the same whether parts in lists the descriptor never goes
through count or not. src/core/partnames.ts is the site's port.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import parts_model

TABLES = Path(__file__).resolve().parents[2] / "src" / "core" / "data" / "part-names.json"


@lru_cache(maxsize=1)
def tables() -> dict:
    with open(TABLES, encoding="utf-8") as f:
        return json.load(f)


def models() -> list[str]:
    """The models the tables name parts of, by the key of the parts tables (FIGHTER_PROC, ...)."""
    return list(tables()["models"])


@dataclass(frozen=True)
class Named:
    """A slot of a ship named: its side ('left', 'right' or none), the name, and the ship's parts that make
    it, in the order the ship has them."""

    side: str
    name: str
    parts: tuple[str, ...]


def names(model: str, seed: int) -> list[Named]:
    """The named slots of ``model`` with ``seed``, in the outfitting's order; none for a model the tables
    don't name."""
    t = tables()
    slots = t["models"].get(model)
    if slots is None:
        return []
    parts, reached = parts_model.parts_and_options(model, seed)
    have = set(parts)
    paired = False
    for first, second in t["pairs"].get(model, []):
        if first in have:
            have = (have - {first}) | {second}
            paired = True

    def fits(group: list[str]) -> bool:
        offered = [part for part in group if part in reached]
        return bool(offered) and all(part in have for part in offered)

    found: list[Named | None] = []
    for side, components in slots:
        fitting = []
        for name, rule, groups in components:
            fit = [group for group in groups if fits(group)]
            if fit and (rule == 1 or len(fit) == len(groups)):
                fitting.append((name, fit))
        named = None
        if len(fitting) == 1 and fitting[0][0]:
            name, fit = fitting[0]
            made = {part for group in fit for part in group}
            named = Named(side, name, tuple(part for part in parts if part in made))
        found.append(named)
    sides = [side for side, _ in slots]
    if paired and "left" in sides and "right" in sides:
        left = found[sides.index("left")]
        found[sides.index("right")] = left and Named("right", left.name, left.parts)
    return [n for n in found if n]
