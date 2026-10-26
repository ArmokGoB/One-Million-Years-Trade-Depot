# SPDX-License-Identifier: AGPL-3.0-or-later
"""The game's random-number generator, as the capture tools need it.

A 32-bit multiply-with-carry generator, and the mixer that turns two of its
32-bit draws into a 64-bit seed (nms_namegen prng.py and system.py
_bodySeed). The game seeds one of these with a system's universal address
for the planet positions, the locators and the ships.

The game seeds the generator from a 64-bit seed the same way wherever its
code has been read: the seed's low word is the first word, 1 if it's 0, and
the carry is that word with its halves swapped, the word itself and the
seed's high word, xored, 0 or not (seeded_state()). nms_namegen's
planetSeeds makes a zero carry 1 instead (namegen_state()). The two differ
only for a seed whose low word or carry is 0.
"""

from __future__ import annotations

MASK32 = 0xFFFFFFFF
MASK64 = (1 << 64) - 1
MULTIPLIER = 0x5A76F899
MIX_A = 0x64DD81482CBD31D7
MIX_B = 0xE36AA5C613612997
_MIX_A_INVERSE = pow(MIX_A, -1, 1 << 64)
_MIX_B_INVERSE = pow(MIX_B, -1, 1 << 64)


def mix(value: int) -> int:
    value = (((value >> 33) ^ value) * MIX_A) & MASK64
    value = (((value >> 33) ^ value) * MIX_B) & MASK64
    return (value >> 33) ^ value


def unmix(value: int) -> int:
    """Inverse of mix(): the two 32-bit draws (high << 32 | low) behind a seed."""
    value ^= value >> 33
    value = (value * _MIX_B_INVERSE) & MASK64
    value ^= value >> 33
    value = (value * _MIX_A_INVERSE) & MASK64
    return value ^ (value >> 33)


def swap16(value: int) -> int:
    """The two 16-bit halves of a 32-bit value, swapped."""
    return ((value & 0xFFFF0000) >> 16) | ((value & 0x0000FFFF) << 16)


def seeded_state(seed: int) -> int:
    """Generator state the game builds from a 64-bit seed: the carry in the high word, the word in the low."""
    low = seed & MASK32
    carry = (swap16(low) ^ low ^ (seed >> 32)) & MASK32
    return (carry << 32) | (low or 1)


def namegen_state(seed: int) -> int:
    """Generator state nms_namegen's planetSeeds builds from a 64-bit seed: a zero carry made 1, not a zero
    word."""
    low = seed & MASK32
    carry = (swap16(low) ^ low ^ (seed >> 32)) & MASK32
    return ((carry or 1) << 32) | low


def step(state: int) -> int:
    return (state & MASK32) * MULTIPLIER + (state >> 32)


def stream_states(seed: int, count: int) -> list[int]:
    """Generator state after each of the first ``count`` draws; a draw's output is the low 32 bits."""
    state, states = seeded_state(seed), []
    for _ in range(count):
        state = step(state)
        states.append(state)
    return states


class Stream:
    """Draws from the generator seeded with ``seed``, counting them."""

    def __init__(self, seed: int):
        self.state = seeded_state(seed)
        self.count = 0

    def word(self) -> int:
        self.state = step(self.state)
        self.count += 1
        return self.state & MASK32

    def unit(self) -> float:
        """A draw as a fraction in [0, 1)."""
        return self.word() / 4294967296.0

    def below(self, limit: int) -> int:
        """A draw as a whole number in [0, limit), the way the game scales one."""
        return (self.word() * limit) >> 32
