# SPDX-License-Identifier: AGPL-3.0-or-later
"""A system's own multi-tools, from the address alone.

The game builds a system's set of multi-tools just before it generates the
system (the capture mod's "pool" lines), in two runs. The first comes from
the generator seeded with the system's universal address, mixed
(game_rng.mix), as nms_namegen seeds the stream of the planets' seeds. Its
first draw, scaled to three, gives how many standard multi-tools there are,
2, 3 or 4; then each multi-tool's seed is the next two draws, mixed into 64
bits as a ship's seed is: the standard ones first, then the royal, the
Sentinel and the Atlas one. The second run, three more standard
multi-tools, comes from a seed not worked out yet. NMS.py names a type of
multi-tool pool SettlementRotational, so they are probably settlements'
stock, which may change with time. tools/captures/report.py checks every
recorded set and every multi-tool on offer against this, and
src/core/multitools.ts is the site's port of this file.
"""

from __future__ import annotations

from game_rng import Stream, mix

STANDARD = "MULTITOOL"
# The model files of the first run after its standard multi-tools, in the game's order.
SPECIAL = ("ROYALMULTITOOL", "SENTINELMULTITOOL", "ATLASMULTITOOL")
# How many standard multi-tools the first run can have: the first draw picks one, each as likely.
STANDARD_COUNTS = (2, 3, 4)
# The second run: how many, all standard, from a seed not worked out.
SECOND_RUN = 3


def first_run(ua: int) -> list[tuple[str, int]]:
    """The model file and seed of each multi-tool in the first run of the set of the system at universal
    address ``ua``, in the order the game builds them."""
    stream = Stream(mix(ua))
    standard = STANDARD_COUNTS[stream.below(len(STANDARD_COUNTS))]
    run = []
    for name in (STANDARD,) * standard + SPECIAL:
        low = stream.word()
        high = stream.word()
        run.append((name, mix((high << 32) | low)))
    return run
