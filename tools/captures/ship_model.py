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
none of them has attractors. A moon sits 225,792 from its parent, at a point
the game spreads over a sphere in a golden spiral: a lone moon along +x; a
planet's two moons at +30 and -30 degrees of elevation, the first above, one
at azimuth 0 and the other at 137.5 degrees (the golden angle). Which moon
gets which azimuth comes from the generator the game seeds with the system's
address to place the planets: after one draw, and three for each planet that
isn't prime, it draws once for each such planet with moons, in order, and
with two moons an even draw puts the first moon at the golden angle (see
swapped_moons()).

Whether the exotic is a squid comes from the exotic's own seed: its first
part, its body, is the squid's (_SCLASSSHIP_SQU) or the other exotics'
(_SCLASSSHIP_ROY), picked as parts_model.py picks every part. The squid's
body is a rare option, weighing 0.05 against the other's 1, so the first
draw from the seed picks it in the top 1/21 of the draw's range.

The first 20 ships are civilian: haulers, fighters, explorers and shuttles,
as many of each as the dominant race's weights in the game's solar
generation globals give (CIVILIAN), in that order. Then the game makes some
of them solar ships, its pirates' class: for each, it hashes the ship's
seed with the system's universal address, seeds a generator with the hash
and compares its first draw, as a fraction, with a chance from the same
globals: PirateClassShipOverrideProbability, 0.1, for a shuttle, and in an
outlaw system for any other civilian ship; PirateClassShipOverride-
ProbabilityPirateSystem, 0.85, for a shuttle in an outlaw system. Outside
outlaw systems, haulers, fighters and explorers are never made solar.
"""

from __future__ import annotations

import math
import struct
from collections import Counter
from typing import NamedTuple

import parts_model
from game_rng import MULTIPLIER, Stream, mix, seeded_state, step, stream_states, swap16

MASK32 = 0xFFFFFFFF
MASK64 = (1 << 64) - 1

# Base radius of a planet's attractor shell, by PlanetSize (0 large, 1 medium, 2 small, 3 moon).
BASE_RADIUS = {0: 195072.0, 1: 147456.0, 2: 96768.0, 3: 23040.0}
SHELL = 40000.0  # attractors lie between the base radius and this much further out
CLEARANCE = 500.0  # an attractor's own radius: it may not come closer than this to a body
MOON_DISTANCE = 225792.0
GOLDEN_ANGLE = math.radians(137.50776405003785)
STATION_DRAWS = 38
TAIL_DRAWS = 3
PLANET_DRAWS = 3  # the draws for each planet that isn't prime, as the game places them, before their moons
SHIPS = 50
CRASH_BEFORE = 42  # the crashed ship's seed is drawn before this ship

# How many haulers, fighters and explorers come first, by dominant race (0 for none); shuttles fill up to 20.
CIVILIAN = {0: (5, 5, 5), 1: (7, 3, 3), 2: (3, 3, 7), 3: (3, 7, 3)}
CIVILIAN_SHIPS = 20
# The chances that the game makes a civilian ship solar (see above), as single-precision numbers.
SOLAR_CHANCE = 0.10000000149011612  # 0.1 in single precision
SOLAR_CHANCE_OUTLAW_SHUTTLE = 0.8500000238418579  # 0.85 in single precision
HASH_MULTIPLIER = 0x9DDFEA08EB382D69  # the hash of a ship's seed with its system's address
DRAW_SCALE = 1 / 4294967295  # what a draw is multiplied by to make a fraction of it

# The first part of an exotic's model: the squid's body, or the other exotics'.
SQUID_PART = "_SCLASSSHIP_SQU"
OTHER_EXOTIC_PART = "_SCLASSSHIP_ROY"
EXOTIC_MODEL = "S-CLASS_PROC"


class Body(NamedTuple):
    size: int  # PlanetSize: 0 large, 1 medium, 2 small, 3 moon
    parent: int  # index of the planet a moon orbits, or -1
    prime: bool


class Prediction(NamedTuple):
    start: int  # draws made before the first ship's
    ships: list[int]
    crash: int


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


def planet_words(ua: int, count: int) -> list[int]:
    """The first ``count`` draws of the generator the game seeds with the system's address to place its
    planets and moons. It's seeded as stream_states() seeds it, but for a low word of 0, which counts as 1,
    and a carry of 0, which stays 0."""
    low = ua & MASK32
    word, carry = low or 1, (swap16(low) ^ low ^ (ua >> 32)) & MASK32
    words = []
    for _ in range(count):
        state = word * MULTIPLIER + carry
        word, carry = state & MASK32, state >> 32
        words.append(word)
    return words


def swapped_moons(ua: int, system: list[Body]) -> frozenset[int]:
    """The planets that aren't prime and whose two moons the game puts the other way round from
    moon_offsets()' default: the first at the golden angle, the second at azimuth 0. The game places a
    planet's moons at the points of a golden spiral, the first moon at the top point, and turns point k of
    n to azimuth (k + draw) mod n times the golden angle, with a draw of the planet's own; so with two
    moons, an even draw puts the first at the golden angle. The draws come after one draw and
    PLANET_DRAWS for each planet that isn't prime, one for each such planet with moons, in order. Prime
    planets' moons come from draws after those, but no prime planet has attractors."""
    planets = [k for k, body in enumerate(system) if not body.prime and body.parent < 0]
    moons = Counter(body.parent for body in system if body.parent >= 0)
    with_moons = [k for k in planets if moons[k]]
    before = 1 + PLANET_DRAWS * len(planets)
    words = planet_words(ua, before + len(with_moons))[before:]
    return frozenset(k for k, word in zip(with_moons, words) if moons[k] == 2 and word % 2 == 0)


def moon_offsets(system: list[Body], swapped: frozenset[int] = frozenset()) -> dict[int, tuple[float, float, float]]:
    """Each moon's position relative to its parent. For the planets in ``swapped``, the two moons
    take each other's azimuth (see swapped_moons())."""
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


def ships_start(ua: int, system: list[Body], swapped: frozenset[int] | None = None) -> int:
    """How many draws the generator makes before the first ship's, with the moons where the game puts
    them, or with the two moons of the planets in ``swapped`` the other way round."""
    offsets = moon_offsets(system, swapped_moons(ua, system) if swapped is None else swapped)

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


def predict(ua: int) -> Prediction:
    """The ship seeds of the system at universal address ``ua``."""
    # nms_namegen doesn't lay out a giant planet system's bodies, but it only occurs in purple
    # systems, whose bodies are all prime planets and moons: none has attractors.
    system = bodies(ua) or []
    start = ships_start(ua, system)
    ships, crash = ship_seeds(ua, start)
    return Prediction(start, ships, crash)


def first_draw(seed: int) -> int:
    """The first draw the game makes from a ship's seed, which picks the first part of its model."""
    return step(seeded_state(seed)) & MASK32


def exotic_squid(seed: int) -> bool:
    """Whether the exotic with this seed is a squid: whether its first part is the squid's body."""
    return parts_model.parts(EXOTIC_MODEL, seed)[0] == SQUID_PART


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def solar_roll(seed: int, ua: int) -> float:
    """The number the game compares with a chance to decide whether the civilian ship with ``seed`` in the
    system at ``ua`` is a solar ship: the first draw of a generator seeded with the two hashed together, as a
    single-precision fraction."""
    a = ((ua ^ seed) * HASH_MULTIPLIER) & MASK64
    b = (((a >> 47) ^ ua ^ a) * HASH_MULTIPLIER) & MASK64
    hashed = (((b >> 47) ^ b) * HASH_MULTIPLIER) & MASK64
    low = hashed & MASK32
    carry = swap16(low) ^ (hashed >> 32) ^ low
    draw = ((low or 1) * MULTIPLIER + carry) & MASK32
    return _f32(draw * DRAW_SCALE)


def civilian_types(ua: int, ships: list[int], dominant_race: int, outlaw: bool) -> list[str]:
    """What the game makes each of the system's first 20 ships, from their seeds: Hauler, Fighter, Explorer,
    Shuttle or Solar."""
    haulers, fighters, explorers = CIVILIAN.get(dominant_race, CIVILIAN[0])
    types = ["Hauler"] * haulers + ["Fighter"] * fighters + ["Explorer"] * explorers
    types += ["Shuttle"] * (CIVILIAN_SHIPS - len(types))
    out = []
    for kind, seed in zip(types, ships):
        if kind == "Shuttle":
            chance = SOLAR_CHANCE_OUTLAW_SHUTTLE if outlaw else SOLAR_CHANCE
        else:
            chance = SOLAR_CHANCE if outlaw else 0.0
        out.append("Solar" if chance and solar_roll(seed, ua) < chance else kind)
    return out
