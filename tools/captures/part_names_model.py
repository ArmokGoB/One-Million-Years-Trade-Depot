# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ship's parts by name, from its seed: the game's names, or for ships it doesn't name, the names players use.

The game names the parts of the ships a player can build at a space station's Starship Fabricator:
fighters, haulers, explorers and solars. Each slot of such a ship (fuselage or cockpit, wings, thruster,
sail) takes components, each named, and each made of descriptor groups, sets of the part IDs a ship's
descriptor lists (see tools/build_part_names.py, which keeps what naming needs in
src/core/data/part-names.json). A ship's slot is named for the component that fits the parts
parts_model.py picks for it:

1. A group fits when the descriptor went through a list that offers at least one of its parts, and the
   ship has every one of its parts that such a list offers. Parts of the group in lists the descriptor
   never goes through for this ship don't count: the Fabricator's explorer components list the parts of
   both of the explorer's cockpits, for one, where a ship has one cockpit.
2. A component fits when all its groups fit, or, if its rule is 1, any one of them.
3. A slot is named when exactly one component fits and that component has a name.
4. An explorer with a matched pair of wings (the first part of one of the tables' pairs) is named as the
   Fabricator's explorer with the same wing on both sides: as if it had the pair's second part, its right
   wing its left one. A part named for having the second is made of the first.

Exactly one component fits each slot of every fighter, hauler, explorer and solar the capture mod has
recorded, and of 20,000 made-up seeds of each, and every one has a name: the hauler wing whose item the
product tables leave out, on about 1 hauler in 260, has the one the game's text gives it (see
build_part_names.py). For fighters, haulers and solars, the slots come out the same whether parts in lists
the descriptor never goes through count or not.

Players name the parts of the other ships: shuttles, exotics, Sentinel ships, freighters and capital
freighters. tools/community_part_names.tsv has their names, the No Man's Sky Coordinate Exchange's (NMSCE)
and this project's own for parts NMSCE has no name for, each with groups of part IDs (kept in
src/core/data/community-part-names.json by tools/build_community_part_names.py): the IDs that make the part
and any the ship must have as well. A ship has each name it has every ID of a group of, made of the IDs that
make it of every such group, and has them in the order their first parts come on the ship; a name with no
parts, which every ship of its model has, comes first.

src/core/partnames.ts is the site's port.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import parts_model

TABLES = Path(__file__).resolve().parents[2] / "src" / "core" / "data" / "part-names.json"
COMMUNITY_TABLES = TABLES.parent / "community-part-names.json"


@lru_cache(maxsize=1)
def tables() -> dict:
    with open(TABLES, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def community_tables() -> dict:
    with open(COMMUNITY_TABLES, encoding="utf-8") as f:
        return json.load(f)


def models() -> list[str]:
    """The models whose parts have names, by the key of the parts tables (FIGHTER_PROC, ...): those the game
    names the parts of, then those players do."""
    return list(tables()["models"]) + list(community_tables()["models"])


@dataclass(frozen=True)
class Named:
    """A named part of a ship: its side ('left', 'right' or none), the name, and the ship's parts that make it,
    in the order the ship has them."""

    side: str
    name: str
    parts: tuple[str, ...]


def names(model: str, seed: int) -> list[Named]:
    """The named parts of ``model`` with ``seed``: a Fabricator ship's named slots, in the Fabricator's order,
    or the names players give the parts of another ship (see community_names); none for a model whose parts
    have no names."""
    t = tables()
    slots = t["models"].get(model)
    if slots is None:
        return community_names(model, seed)
    parts, reached = parts_model.parts_and_options(model, seed)
    have = set(parts)
    stands_for: dict[str, str] = {}  # a pair's second part, by the first, which the ship has instead
    for first, second in t["pairs"].get(model, []):
        if first in have:
            have = (have - {first}) | {second}
            stands_for[second] = first

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
            made = {stands_for.get(part, part) for group in fit for part in group}
            named = Named(side, name, tuple(part for part in parts if part in made))
        found.append(named)
    sides = [side for side, _ in slots]
    if stands_for and "left" in sides and "right" in sides:
        left = found[sides.index("left")]
        found[sides.index("right")] = left and Named("right", left.name, left.parts)
    return [n for n in found if n]


def community_names(model: str, seed: int) -> list[Named]:
    """The names players give the parts of ``model`` with ``seed``, in the order their first parts come on the
    ship, a name with no parts first; none for a model they don't name the parts of."""
    entries = community_tables()["models"].get(model)
    if entries is None:
        return []
    parts = parts_model.parts(model, seed)
    have = set(parts)
    found: list[tuple[int, int, Named]] = []
    for index, (name, groups) in enumerate(entries):
        fit = [group for group in groups if all(part in have for ids in group for part in ids)]
        if not fit:
            continue
        made = {part for group in fit for part in group[0]}
        ordered = tuple(part for part in parts if part in made)
        first = parts.index(ordered[0]) if ordered else -1
        found.append((first, index, Named("", name, ordered)))
    return [named for _, _, named in sorted(found, key=lambda entry: entry[:2])]
