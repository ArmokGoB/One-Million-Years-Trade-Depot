# SPDX-License-Identifier: AGPL-3.0-or-later
"""A system's own multi-tools, from its address and the day.

The game builds a system's set of multi-tools just before it generates the
system (the capture mod's "pool" lines), from five pools its simulation
globals list, each drawn with a chance, 1 for all five, and a number between
a least and a most: 2 to 4 standard multi-tools, a royal one, a Sentinel
one, an Atlas one, and 3 more standard ones, a pool the game's data calls
SettlementRotational.

The first four pools, the first run, come from the generator seeded with the
address, mixed (game_rng.mix), as nms_namegen seeds the stream of the
planets' seeds. Its first draw, scaled to three, gives how many standard
multi-tools there are; then each multi-tool's seed is the next two draws,
mixed into 64 bits as a ship's seed is: the standard ones first, then the
royal, the Sentinel and the Atlas one.

The last pool's three, the rotation, come from a generator seeded with the
address and the day hashed together (day_hash()), the day being how many
whole days the game's clock is past 1 January 1970 UTC. Each one's seed is
the next two draws, mixed. When the day changes, the game makes the three
again from the new day, so they change at midnight UTC. A multi-tool
terminal offers the Sentinel one if it's a Sentinel terminal, one of the
three if it restocks after a while, and one of the first run's standard
ones otherwise.

The address is the player's as the game generates the system: the system's
own, planet digit 0, after a warp, but a planet's, with its digit, when the
game generates the system with the player at that planet, as when a save
loads there. tools/captures/report.py checks every recorded set and every
multi-tool on offer against this, and src/core/multitools.ts is the site's
port of this file.
"""

from __future__ import annotations

from game_rng import MASK64, Stream, mix

STANDARD = "MULTITOOL"
# The model files of the first run after its standard multi-tools, in the game's order.
SPECIAL = ("ROYALMULTITOOL", "SENTINELMULTITOOL", "ATLASMULTITOOL")
# How many standard multi-tools the first run can have: the first draw picks one, each as likely.
STANDARD_COUNTS = (2, 3, 4)
# How many standard multi-tools the rotation has.
ROTATION = 3
DAY_SECONDS = 86400
# The multiplier of the hash that seeds the rotation (CityHash's Hash128to64).
HASH_MUL = 0x9DDFEA08EB382D69


def first_run(ua: int) -> list[tuple[str, int]]:
    """The model file and seed of each multi-tool in the first run of the set made from universal
    address ``ua``, in the order the game builds them."""
    stream = Stream(mix(ua))
    standard = STANDARD_COUNTS[stream.below(len(STANDARD_COUNTS))]
    run = []
    for name in (STANDARD,) * standard + SPECIAL:
        low = stream.word()
        high = stream.word()
        run.append((name, mix((high << 32) | low)))
    return run


def day_of(seconds: int) -> int:
    """The day a time in whole seconds since 1970 UTC falls on: what the rotation is made from."""
    return seconds // DAY_SECONDS


def day_hash(ua: int, day: int) -> int:
    """The seed of the rotation's generator: CityHash's Hash128to64 of a 128-bit value whose low half
    is the address and whose high half is the day."""
    a = ((ua ^ day) * HASH_MUL) & MASK64
    a ^= a >> 47
    b = ((day ^ a) * HASH_MUL) & MASK64
    b ^= b >> 47
    return (b * HASH_MUL) & MASK64


def rotation(ua: int, day: int) -> list[tuple[str, int]]:
    """The model file and seed of each multi-tool in the rotation of the set made from universal address
    ``ua`` on ``day`` (day_of()), in the order the game builds them."""
    stream = Stream(day_hash(ua, day))
    run = []
    for _ in range(ROTATION):
        low = stream.word()
        high = stream.word()
        run.append((STANDARD, mix((high << 32) | low)))
    return run
