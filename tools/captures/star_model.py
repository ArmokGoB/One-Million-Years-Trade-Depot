# SPDX-License-Identifier: AGPL-3.0-or-later
"""How many stars a system has, and what color each is, from its address alone.

The game counts a system's stars from its NebulaSeed, a number between 0
and 1: a second star when it's above 1 minus the binary star chance, and a
third when it's also above 1 minus the ternary star chance. Both chances
are the game's sky globals, 0.2 and 0.05 in single precision, as the
capture mod read them (0.11.0). NebulaSeed is the 9th draw of the generator
seeded with the system's universal address, as a fraction of the largest
draw, in single precision. tools/captures/report.py checks both against
every capture, and src/core/stars.ts is the site's port of this file.

In two game modes, Seasonal (expeditions) and Unspecified, with a setting
on, the game also gives three stars to one system whose address it holds,
as capture mods 0.11.0 to 0.14.0 found in its code; this covers the normal game.

Each star has a color of its own. In the game's code each sun is a copy of
the system's one space point of interest of type Star, numbered from 0, the
main sun; that point's entry in the game's space POI table names five color
variants for suns, in the order of the game's star types, which capture
mods 0.13.0 and 0.14.0 recorded: YellowStar, GreenStar, BlueStar, RedStar
and PurpleStar. Sun number k is drawn with the variant k places after the
system's star type, going round, so the main sun has the system's star
color. A binary and a trinary system's suns had in the game the colors this
gives them.
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
    in the normal game, without debug options, as capture mods 0.11.0 to 0.14.0 found it in the game's code.
    The game subtracts in single precision and counts a star only when NebulaSeed is strictly above the
    difference."""
    return 1 + (nebula > float32(one - ternary)) + (nebula > float32(one - binary))


def stars(ua: int) -> int:
    """How many stars the system at universal address ``ua`` has, with the game's chances."""
    return star_count(nebula_seed(ua))


# The game's star colors, in the order of its star types (cGcGalaxyStarTypes) and of its color variants for
# suns, each of which is named for one of them: YellowStar and so on.
STAR_COLORS = ("Yellow", "Green", "Blue", "Red", "Purple")


def star_colors(star_type: int, count: int) -> list[str]:
    """The color of each of the ``count`` stars of a system whose star type is ``star_type`` (its place in
    STAR_COLORS), the main star first: each the color after the one before, going round."""
    return [STAR_COLORS[(star_type + k) % len(STAR_COLORS)] for k in range(count)]
