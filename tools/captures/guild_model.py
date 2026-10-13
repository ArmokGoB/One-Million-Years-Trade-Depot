# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which guild's envoy a system's space station has, from the address alone.

The first draw of the generator seeded with the system's universal address
(seeded as for NebulaSeed, star_model.py), scaled to three, picks the guild,
in the order the game lists the three: the Merchants (its Trade guild), the
Mercenaries (Warrior) and the Explorers. A draw scaled to three hardly
depends on anything but the address's low 32 bits, the region's
coordinates, which is why a region's stations all have the same guild. A
seed of the region's coordinates alone, with or without the galaxy, fits
the captures as well; it would give another guild in about 1 system in
20,000. tools/captures/report.py checks every guild the capture mod records
against this, and src/core/guild.ts is the site's port of this file.
"""

from __future__ import annotations

from game_rng import MASK32, stream_states

# In the game's order: its Trade, Warrior and Explorer guilds.
GUILDS = ("Merchants", "Mercenaries", "Explorers")


def guild(ua: int) -> str:
    """The guild whose envoy the space station of the system at universal address ``ua`` has."""
    first = stream_states(ua, 1)[0] & MASK32
    return GUILDS[(first * len(GUILDS)) >> 32]
