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

The planets' sizes, moons and prime flags come from nms_namegen. A moon sits
225,792 from its parent; a lone moon along +x. Where a planet has two moons
the layout varies in ways not worked out yet: predictions for those systems
use the one layout seen so far and are flagged as uncertain.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from game_rng import Stream, mix, seeded_state, stream_states

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


class Body(NamedTuple):
    size: int  # PlanetSize: 0 large, 1 medium, 2 small, 3 moon
    parent: int  # index of the planet a moon orbits, or -1
    prime: bool


class Prediction(NamedTuple):
    start: int  # draws made before the first ship's
    ships: list[int]
    crash: int
    uncertain: str | None  # why the prediction may be wrong, if a known gap applies


def bodies(ua: int) -> list[Body] | None:
    """Every body of the system at ``ua``, in the game's order, or None for a gas-giant layout.

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


def moon_offsets(system: list[Body]) -> dict[int, tuple[float, float, float]]:
    """Each moon's position relative to its parent."""
    moons: dict[int, list[int]] = {}
    for k, body in enumerate(system):
        if body.parent >= 0:
            moons.setdefault(body.parent, []).append(k)
    offsets = {}
    for siblings in moons.values():
        if len(siblings) == 1:
            offsets[siblings[0]] = (MOON_DISTANCE, 0.0, 0.0)
            continue
        # The one two-moon layout seen so far; another system's differed.
        for j, k in enumerate(siblings):
            elevation = math.radians(30.0 if j % 2 == 0 else -30.0)
            azimuth = j * GOLDEN_ANGLE
            offsets[k] = (
                MOON_DISTANCE * math.cos(elevation) * math.cos(azimuth),
                MOON_DISTANCE * math.sin(elevation),
                MOON_DISTANCE * math.cos(elevation) * math.sin(azimuth),
            )
    return offsets


def uncertainty(system: list[Body]) -> str | None:
    """Why a prediction for this system may be wrong, if a known gap in the model applies."""
    for k, body in enumerate(system):
        family = [k] + [j for j, other in enumerate(system) if other.parent == k]
        if len(family) > 2 and not all(system[j].prime for j in family):
            return "a planet with two moons, whose layout isn't known yet"
    return None


def ships_start(ua: int, system: list[Body]) -> int:
    """How many draws the generator makes before the first ship's."""
    offsets = moon_offsets(system)

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


def predict(ua: int) -> Prediction | None:
    """The ship seeds of the system at universal address ``ua``, or None if its layout isn't modelled."""
    system = bodies(ua)
    if system is None:
        return None
    start = ships_start(ua, system)
    ships, crash = ship_seeds(ua, start)
    return Prediction(start, ships, crash, uncertainty(system))
