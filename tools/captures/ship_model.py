# SPDX-License-Identifier: AGPL-3.0-or-later
"""A system's ship seeds from its address alone: a model of the game's generator.

Worked out from capture-mod records, and checked against every capture by
tools/captures/report.py. The game seeds its random-number generator with
the system's universal address and, after the planet positions and biomes,
starts again from that seed for the space station, the locators and the
ships:

1. 38 draws: the space station and the 9 locators around it.
2. For each planet that isn't a prime planet, in order, its "attractor"
   locators: one draw for the number of attempts (30 plus a draw below 36),
   then per attempt an elevation (y = 1 - 2u), an azimuth (2 pi u), a
   distance (the planet's base radius plus 40,000u) and one more draw. An
   attempt whose point lies within 500 of the planet's base radius, or of
   its moon's or parent's, is dropped; any other draws one more number.
3. 3 draws.
4. The ships: each seed mixes the next two draws, 50 ships with the crashed
   Sentinel ship's seed drawn between ships 41 and 42.

The planets' sizes, moons and prime flags come from nms_namegen. Every body
of a purple system is a prime planet or moon, giant planet layouts included, so
none of them has attractors. A moon sits 225,792 from its parent; a lone
moon along +x. A planet's two moons sit at +30 and -30 degrees of elevation,
the first above, at azimuths 0 and 137.5 degrees (the golden angle), but
which of them gets which azimuth varies in a way not worked out yet. So a
system whose planets aren't prime and have two moons can come out one of
two ways per such planet: predictions() gives them all, first moon at 0 first.

Whether the exotic is a squid comes from the exotic's own seed. The game
picks the first part of a ship's model with the first draw from the ship's
seed, each option taking its own stretch of the draw's range. An exotic's
first part is the squid's body (_SCLASSSHIP_SQU) when that draw is near
the top of the range, and the other exotics' body (_SCLASSSHIP_ROY) below.
exotic_squid() draws the line at 20/21 of the range: the squid weighted
0.05 against the other's 1, the likeliest place for it between the closest
exotics recorded on either side.
"""

from __future__ import annotations

import itertools
import math
from typing import NamedTuple

from game_rng import Stream, mix, seeded_state, step, stream_states

MASK32 = 0xFFFFFFFF

# Base radius of a planet's attractor shell, by PlanetSize (0 large, 1 medium, 2 small, 3 moon).
BASE_RADIUS = {0: 195072.0, 1: 147456.0, 2: 96768.0, 3: 23040.0}
SHELL = 40000.0  # attractors lie between the base radius and this much further out
CLEARANCE = 500.0  # an attractor's own radius: it may not come closer than this to a body
MOON_DISTANCE = 225792.0
GOLDEN_ANGLE = math.radians(137.50776405003785)
STATION_DRAWS = 38
TAIL_DRAWS = 3
SHIPS = 50
CRASH_BEFORE = 42  # the crashed ship's seed is drawn before this ship

# The first part of an exotic's model: the squid's body, or the other exotics'.
SQUID_PART = "_SCLASSSHIP_SQU"
OTHER_EXOTIC_PART = "_SCLASSSHIP_ROY"
# Among the exotics recorded so far, the highest first draw of one that isn't a squid, and the
# lowest of a squid. Between the two, where exactly the line lies isn't known.
NOT_SQUID_HIGHEST = 4088215205
SQUID_LOWEST = 4093481076


class Body(NamedTuple):
    size: int  # PlanetSize: 0 large, 1 medium, 2 small, 3 moon
    parent: int  # index of the planet a moon orbits, or -1
    prime: bool


class Prediction(NamedTuple):
    start: int  # draws made before the first ship's
    ships: list[int]
    crash: int
    uncertain: str | None  # why the prediction may be wrong, if a known gap applies


class SquidCall(NamedTuple):
    squid: bool  # whether the game makes the exotic with this seed a squid
    close: bool  # its first draw lies where the line could still be, so `squid` rests on 20/21


def bodies(ua: int) -> list[Body] | None:
    """Every body of the system at ``ua``, in the game's order, or None for a giant-planet layout.

    Follows nms_namegen.system.planetSeeds draw for draw (nms_namegen must be
    importable), keeping the size, parent and prime flag of each body, and
    checks the result against its planet seeds."""
    from nms_namegen.prng import PRNG
    from nms_namegen.system import CONST_A, CONST_B, planetSeeds, systemAttributes

    portal = (((ua >> 40) & 0xFFF) << 32) | (ua & MASK32)
    galaxy = (ua >> 32) & 0xFF
    attributes = systemAttributes(portal, galaxy)
    if attributes.get("gas_giant"):
        return None
    galactic, index = portal & MASK32, ((portal & 0x0FFF00000000) >> 24) | galaxy
    register = (index << 32) | galactic
    register = (((register >> 33) ^ register) * CONST_A) & 0xFFFFFFFFFFFFFFFF
    register = (((register >> 33) ^ register) * CONST_B) & 0xFFFFFFFFFFFFFFFF
    register = (register >> 33) ^ register
    rng = PRNG(seeded_state(register))

    def seed() -> int:
        low = rng.randi() & MASK32
        return mix((rng.randi() & MASK32) << 32 | low)

    primary = attributes["planet_count"]
    total = primary + attributes["prime_planet_count"]
    stop = attributes["safe_start_planet"] - 1
    found: list[Body] = []
    seeds: list[int] = []
    i = 0
    while i < primary:
        i += 1
        size = rng.random(3)
        found.append(Body(size, -1, False))
        parent = len(found) - 1
        if size == 0:
            moons = rng.random(max(0, min(2, primary - i)) + 1)
            while moons > 0 and i != stop:
                i += 1
                found.append(Body(3, parent, False))
                moons -= 1
    for _ in range(primary):
        seeds.append(seed())
    while i < total:
        size = rng.random(3)
        seeds.append(seed())
        found.append(Body(size, -1, True))
        parent = len(found) - 1
        i += 1
        if size == 0:
            moons = rng.random(max(0, min(2, total - i)) + 1)
            while moons > 0 and i != stop:
                seeds.append(seed())
                found.append(Body(3, parent, True))
                moons -= 1
                i += 1
    expected = [s & 0xFFFFFFFFFFFFFFFF for s in planetSeeds(portal, galaxy)["planet_seeds"]]
    if seeds != expected:
        raise RuntimeError(f"{ua:016X}: body list doesn't follow nms_namegen's planet seeds")
    return found


def moon_offsets(system: list[Body], swapped: frozenset[int] = frozenset()) -> dict[int, tuple[float, float, float]]:
    """Each moon's position relative to its parent. For the planets in ``swapped``, the two moons
    take each other's azimuth."""
    moons: dict[int, list[int]] = {}
    for k, body in enumerate(system):
        if body.parent >= 0:
            moons.setdefault(body.parent, []).append(k)
    offsets = {}
    for parent, siblings in moons.items():
        if len(siblings) == 1:
            offsets[siblings[0]] = (MOON_DISTANCE, 0.0, 0.0)
            continue
        for j, k in enumerate(siblings):
            elevation = math.radians(30.0 if j % 2 == 0 else -30.0)
            azimuth = ((j + (parent in swapped)) % 2) * GOLDEN_ANGLE
            offsets[k] = (
                MOON_DISTANCE * math.cos(elevation) * math.cos(azimuth),
                MOON_DISTANCE * math.sin(elevation),
                MOON_DISTANCE * math.cos(elevation) * math.sin(azimuth),
            )
    return offsets


def two_moon_planets(system: list[Body]) -> list[int]:
    """The planets that aren't prime and have two moons, whose arrangement the model can't tell."""
    return [k for k, body in enumerate(system) if not body.prime and [b.parent for b in system].count(k) == 2]


def uncertainty(system: list[Body]) -> str | None:
    """Why a prediction for this system may be wrong, if a known gap in the model applies."""
    planets = len(two_moon_planets(system))  # at most two: a system has six bodies at most
    if planets == 1:
        return "a planet with two moons, which the game arranges in one of two ways"
    if planets:
        return "two planets with two moons each, which the game arranges in one of two ways"
    return None


def ships_start(ua: int, system: list[Body], swapped: frozenset[int] = frozenset()) -> int:
    """How many draws the generator makes before the first ship's, with the two moons of the
    planets in ``swapped`` the other way round."""
    offsets = moon_offsets(system, swapped)

    def obstacles(k: int) -> list[tuple[tuple[float, float, float], float]]:
        """Bodies near enough to planet k to block its attractors: (center relative to k, clearance)."""
        near = []
        body = system[k]
        if body.parent >= 0:
            x, y, z = offsets[k]
            near.append(((-x, -y, -z), BASE_RADIUS[system[body.parent].size] + CLEARANCE))
        for j, other in enumerate(system):
            if other.parent == k:
                near.append((offsets[j], BASE_RADIUS[other.size] + CLEARANCE))
        return near

    draws = Stream(ua)
    for _ in range(STATION_DRAWS):
        draws.word()
    for k, body in enumerate(system):
        if body.prime:
            continue
        near = obstacles(k)
        for _ in range(30 + draws.below(36)):
            y = 1.0 - 2.0 * draws.unit()
            azimuth = 2.0 * math.pi * draws.unit()
            distance = BASE_RADIUS[body.size] + SHELL * draws.unit()
            draws.word()
            if distance < BASE_RADIUS[body.size] + CLEARANCE:
                continue
            ring = math.sqrt(max(0.0, 1.0 - y * y))
            point = (distance * ring * math.cos(azimuth), distance * y, distance * ring * math.sin(azimuth))
            if any(math.dist(point, center) < clearance for center, clearance in near):
                continue
            draws.word()
    return draws.count + TAIL_DRAWS


def ship_seeds(ua: int, start: int) -> tuple[list[int], int]:
    """The 50 ship seeds and the crashed ship's seed, drawn after ``start`` draws."""
    words = [state & MASK32 for state in stream_states(ua, start + 2 * SHIPS + 2)][start:]
    seeds = [mix((words[i + 1] << 32) | words[i]) for i in range(0, len(words) - 1, 2)]
    crash = seeds.pop(CRASH_BEFORE)
    return seeds, crash


def predictions(ua: int) -> list[Prediction]:
    """Every way the ships of the system at universal address ``ua`` can come out: one per
    arrangement of its two-moon planets' moons, first moon at azimuth 0 first."""
    # nms_namegen doesn't lay out a giant planet system's bodies, but it only occurs in purple
    # systems, whose bodies are all prime planets and moons: none has attractors.
    system = bodies(ua) or []
    planets = two_moon_planets(system)
    found = []
    for flips in itertools.product((False, True), repeat=len(planets)):
        swapped = frozenset(k for k, flip in zip(planets, flips) if flip)
        start = ships_start(ua, system, swapped)
        ships, crash = ship_seeds(ua, start)
        found.append(Prediction(start, ships, crash, uncertainty(system)))
    return found


def predict(ua: int) -> Prediction:
    """The ship seeds of the system at universal address ``ua``, the model's first guess where
    a planet has two moons."""
    return predictions(ua)[0]


def first_draw(seed: int) -> int:
    """The first draw the game makes from a ship's seed, which picks the first part of its model."""
    return step(seeded_state(seed)) & MASK32


def exotic_squid(seed: int) -> SquidCall:
    """Whether the exotic with this seed is a squid: its first draw is at least 20/21 of the range."""
    draw = first_draw(seed)
    return SquidCall(21 * draw >= 20 << 32, NOT_SQUID_HIGHEST < draw < SQUID_LOWEST)
