# SPDX-License-Identifier: AGPL-3.0-or-later
"""How many stars a system has, from its address alone.

The game counts a system's stars from its NebulaSeed, a number between 0
and 1: a second star when it's above 1 minus the binary star chance, and a
third when it's also above 1 minus the ternary star chance. Both chances
are the game's sky globals, 0.2 and 0.05 in single precision, as the
capture mod read them (0.11.0). NebulaSeed is the 9th draw of the generator
seeded with the system's universal address, as a fraction of the largest
draw, in single precision. tools/captures/report.py checks both against
every capture, and src/core/stars.ts is the site's port of this file.

In two game modes, Seasonal (expeditions) and Unspecified, with a setting
on, the game also gives three stars to one system whose address it holds
(see the mod's StarCount); this covers the normal game.
"""

from __future__ import annotations

import struct

from game_rng import MASK32, stream_states


def float32(value: float) -> float:
    """``value`` rounded to single precision, as the game holds it."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


BINARY_STAR_CHANCE = float32(0.2)
TERNARY_STAR_CHANCE = float32(0.05)


def nebula_seed(seed: int) -> float:
    """A system's NebulaSeed from its seed (its universal address): the 9th draw of the stream the seed
    starts, as a fraction of the largest draw, in single precision."""
    return float32((stream_states(seed, 9)[8] & MASK32) / 4294967295.0)


def star_count(
    nebula: float, binary: float = BINARY_STAR_CHANCE, ternary: float = TERNARY_STAR_CHANCE, one: float = 1.0
) -> int:
    """How many stars the game counts for a system with this NebulaSeed, as its star count function does
    in the normal game (no debug options; see the mod's STAR_COUNT_CODE). The game subtracts in single
    precision and counts a star only when NebulaSeed is strictly above the difference."""
    return 1 + (nebula > float32(one - ternary)) + (nebula > float32(one - binary))


def stars(ua: int) -> int:
    """How many stars the system at universal address ``ua`` has, with the game's chances."""
    return star_count(nebula_seed(ua))
