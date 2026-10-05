# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["nmspy>=180132.0"]
#
# [tool.pymhf]
# exe = "NMS.exe"
# steam_gameid = 275850
# start_paused = true
#
# [tool.pymhf.logging]
# log_dir = "{CURR_DIR}"
# log_level = "info"
# window_name_override = "Trade Depot capture"
# ///

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trade Depot capture: records the star systems you visit in No Man's Sky.

Each time the game generates a star system, this NMS.py mod appends one line
to ``captures/systems.jsonl`` next to this file. The line holds the system's
universal address, its seed, the game's own description of it (name, star,
race, economy, planets) and ``SystemShips``, the list of ships the game
prepares for the system, and how many stars the game counts in it, if the mod
finds the game's star count function safe to call (see read_leaf). The
multi-tools the game builds for the system while it generates it go on a line
of their own, with each one's seed and parts, and so does the guild whose
envoy you say you saw, with the buttons on the mod's tab.
When the game builds the model of a ship from the system's list, the mod also
records the parts the game picked for it, with the ship's seed; and when the
game offers an item, such as a multi-tool to buy or as a gift or reward, what
the item holds: its inventories, and the seed and parts of its model. The One
Million Years Trade Depot uses these lines as ground truth for working out how
the game picks a system's ships and multi-tools, and what a seed makes them
look like.

The mod only reads. It changes nothing in the game or your save. Every read
of game memory goes through ReadProcessMemory, so if NMS.py's struct layouts
stop matching the game after an update, the mod logs a warning instead of
crashing the game. Besides, on the game's main thread, it calls two of the
game's own functions: the one that gives a system's name, and the one that
counts a system's stars, which it calls only once it has read the function's
code and found that the function can only read.

Run it with ``py -3.13 system_capture.py``. Short tones say when it has
recorded something, so you needn't leave the game. See README.md in this
folder.
"""

from __future__ import annotations

import array
import base64
import ctypes
import hashlib
import io
import json
import logging
import math
import os
import platform
import re
import socket
import struct
import sys
import threading
import time
import wave
import zlib
from collections import Counter
from importlib import metadata
from pathlib import Path

import nmspy.data.basic_types as basic
import nmspy.data.enums as enums
import nmspy.data.exported_types as nmse
import nmspy.data.types as nms
import pymhf.core._internal as pymhf_internal
from nmspy.common import gameData
from nmspy.decorators import main_loop
from pymhf import Mod
from pymhf.gui.decorators import STRING, gui_button

MOD_VERSION = "0.10.0"
# Bump when the meaning of a field changes; tools/captures/report.py checks it.
# 2: generation traces, raw system data, display names and query records.
# (0.3.0 to 0.10.0 only add or drop record types, fields and controls, or let a field hold more
# kinds of thing, as 0.8.2 does with an item's "tools", so they keep format 2.)
FORMAT_VERSION = 2
STEAM_APP_ID = 275850

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_FILE = CAPTURE_DIR / "systems.jsonl"

# Record the parts the game picks for each ship of the system's own ship list
# when it builds the ship's model. This watches a function the game calls for
# everything it loads; set it to False if the game crashes or loads slowly
# with the mod, and the mod won't touch that function at all.
RECORD_SHIP_PARTS = True
# Record the multi-tools the game makes for each system, and the items it
# offers, such as a multi-tool on a rack or at a merchant, or as a gift or
# reward. The seeds and parts of multi-tools come through the same function as
# the ships', so they need RECORD_SHIP_PARTS too. Set it to False if the game
# misbehaves near a multi-tool rack with the mod, and the mod won't watch the
# function that updates items for sale.
RECORD_MULTITOOLS = True
# Record how many stars each system has. The mod finds the game's own function
# for it, cGcSolarSystem::GetStarCount, which NMS.py names but can't hook, and
# calls it on the game's main thread, as it does the function that gives a
# system's name, if the function's code shows that calling it can't change
# anything (see read_leaf). Set it to False if the game misbehaves once a system
# loads, and the mod won't look for the function.
RECORD_STARS = True
# Short tones tell you what happened while the log is hidden behind the game.
PLAY_SOUNDS = True
# Also play the "recorded" tone once per system, a few seconds after you
# arrive, when the system is in the capture file.
CHIME_ON_ARRIVAL = True
SOUND_VOLUME = 0.3  # 0 to 1
# Notes as (frequency in Hz, seconds); a frequency of 0 is a rest.
SOUNDS = {
    "recorded": [(880.0, 0.07), (1318.5, 0.12)],  # two rising notes
    # high, high, higher: the parts of the system's exotic are recorded
    "exotic parts": [(1318.5, 0.06), (0.0, 0.05), (1318.5, 0.06), (0.0, 0.05), (1760.0, 0.12)],
    # two quick very high notes: a system's multi-tools, or one the game offers, are recorded
    "multi-tool": [(2093.0, 0.05), (0.0, 0.04), (2093.0, 0.05)],
    "problem": [(220.0, 0.18), (0.0, 0.07), (220.0, 0.18)],  # two low notes
}

# How often the main loop looks at the current system. The Generate hook
# records systems as they are made; polling catches anything filled in later.
POLL_SECONDS = 2.0
# The mod sees the game through NMS.py, which finds the game at the game's
# first change of state after pyMHF is in it. Launched by the mod, the game
# changes state as it starts; attached to a game that's already running, it
# may not for a while. After this long without, the mod says what to do.
FIND_GAME_NOTICE_SECONDS = 15.0
NOT_FOUND_YET = (
    "The mod hasn't found the game yet. Attached to a game that's already running, it finds it when "
    "the game next changes state: opening the galaxy map should do it."
)
# Query records (systems the game describes without loading them) are queued
# and written from the main loop at most this often.
FLUSH_SECONDS = 1.0
MAX_QUERY_RECORDS = 5_000
MAX_NAME_RECORDS = 20_000
# Ship models: resources whose name holds one of these, and that come with a
# descriptor (the parts picked and the seed they were picked with).
SHIP_MODEL_PATHS = ("/SPACECRAFT/",)
MAX_MODEL_RECORDS = 20_000
MAX_MODEL_PARTS = 256
MODEL_NAME_LENGTH = 0x100  # cTkFixedString<0x100>, the game's resource names
# Ship models built before the mod has read their system's ship list wait this
# many at a time; those whose seed then isn't in the list (your own ships and
# other players') are dropped unrecorded.
WAITING_MODELS = 2_000
# The first few model records of a session keep the descriptor's raw bytes, to
# check NMS.py's layout of it against the game.
RAW_DESCRIPTORS = 20
# Names of other models with parts that the log mentions, to show what the
# game builds that isn't a ship.
OTHER_MODELS_LOGGED = 30
# Models the game built with a descriptor, kept in memory only, by seed and by
# resource handle, so that an item the game offers can be paired with its
# model. Outside a system's set of multi-tools (below), one is written to the
# file only as part of an item that holds its seed or handle, and never if it's
# a ship outside the ship lists read lately: the game also builds the ships and
# multi-tools you and other players have. A handle stays paired with its model
# until the game hands the number to something else, however long that takes.
MODELS_KEPT = 4096
# Multi-tool models: resources in this folder, but for the parts in these.
MULTITOOL_MODEL_DIR = "/WEAPONS/MULTITOOL/"
NOT_MULTITOOL_DIRS = ("/MULTITOOLPARTS/",)  # the fishing rod's float, say
# The multi-tools the game builds while it generates a system, on the thread
# that generates it, are the system's own set: they're written with the
# system, seeds, parts and all. In the captures so far, the game built yours and
# other players' at other times. Each other multi-tool model the game builds
# gets a "built" line: when, its file, how many parts it has and its resource
# handle, but not its seed or parts.
POOL_TOOLS = 64  # the most multi-tools in one system's set
POOL_SECONDS = 60.0  # a generation that hasn't ended after this long is taken to have ended unseen
MAX_POOL_RECORDS = 2_000
MULTITOOL_NAMES_LOGGED = 10  # the log names the first few multi-tool model files
TOOL_BUILDS_RECORDED = 500  # "built" lines for multi-tool models, per session
# The game's resource manager lists the resources it holds, and a resource handle picks one of
# them. For each item the game offers, the mod reads the one the item's handle picks, as a check
# on the model it paired the item with.
MAX_RESOURCES = 1 << 22
# cGcSolarSystem::GetStarCount, by the pattern NMS.py gives for it: it starts by loading a value
# from a fixed place in the game and one from the solar system. The mod calls it only if its code
# can't change anything (see read_leaf). Each session header holds the function's first bytes and
# the values it reads from fixed places, so what it does can be checked, and each system's record
# holds the bytes of the solar system around what the function reads of it, in case the other
# stars' colours are kept there; up to STAR_WINDOW_MAX bytes from the first read to the last, or else
# only around the value the pattern shows.
STAR_COUNT_PATTERN = "F3 0F 10 0D ? ? ? ? 33 C0 F3 0F 10 91"
STAR_CODE_BYTES = 128
STAR_FIELD_BEFORE, STAR_FIELD_AFTER = 0x20, 0x60
STAR_WINDOW_MAX = 0x200
MAX_STARS = 8  # a count above this means the function isn't what the mod takes it for
# Other models with parts that aren't ships get a "built" line the first time
# the game builds each file in a session, for up to this many files.
OTHER_BUILDS_RECORDED = 500
# Items the game offers (a multi-tool on a rack or at a merchant, gifts,
# rewards): how often the mod looks at each one. An item is recorded once what
# it holds has looked the same twice in a row, so anything shown for about a
# second or more, and again whenever that changes. A look at an item whose
# bytes haven't changed skips decoding it, but not for longer than
# ITEM_REFRESH_SECONDS, since what its inventories point to may change.
ITEM_CHECK_SECONDS = 0.5
ITEM_REFRESH_SECONDS = 5.0
# An item that hasn't looked the same twice in this many looks is recorded as it is.
ITEM_UNSETTLED_LOOKS = 20
# An item the game hasn't updated for this long may be another item at the same address
# now: the mod forgets which model it was paired with.
ITEM_FORGET_SECONDS = 30.0
# The most records for one item in one system: for each thing it offers, and in all.
ITEM_RECORDS_PER_OFFER = 10
ITEM_RECORDS_PER_PLACE = 100
ITEMS_TRACKED = 4096
MAX_ITEM_RECORDS = 5_000
# Where an item's five inventories (cGcInventoryStore) seem to start, going by
# the items 0.8.1 recorded; NMS.py doesn't place them. Text in the bytes before
# them is recorded too, with your player name and title taken out.
ITEM_STORES_AT = 0x4F0
ITEM_STORES = 5
MAX_STORE_ENTRIES = 256
# An inventory bigger than this, or of a class beyond S, isn't one: its lists aren't read.
MAX_STORE_SIDE = 16  # mxValidSlots has 16 rows of 16 bits
NO_HANDLE = (0, 0xFFFFFFFF)  # resource handle values that mean no resource
# When the log first counts the resources the game has loaded, and how often after
# that while the count changes.
FIRST_RESOURCE_COUNT_SECONDS = 60.0
RESOURCE_COUNT_SECONDS = 300.0
NAME_LENGTH = 0x7F  # cTkFixedString<0x7F>, what the name generator writes
MAX_SHIPS = 512
MAX_LOCATORS = 4096
MAX_READ = 1 << 20
MASK64 = (1 << 64) - 1
PLANET_BITS = 0xF << 52  # the planet digit of a universal address
ZERO_SEED = "0" * 16

logger = logging.getLogger("TradeDepotCapture")

# Column names for the positional rows in each record. They are written into
# every session header so a capture file explains itself.
SHIP_COLUMNS = ["seed", "useSeed", "class", "role", "faction", "frigateClass", "textureHint"]
BODY_COLUMNS = [
    "seed", "useSeed", "biome", "biomeSubType", "class", "index",
    "size", "reality", "star", "flags", "commonSubstance", "rareSubstance",
]  # fmt: skip
BODY_FLAGS = [
    "ForceContinents", "HasRings", "InAbandonedSystem", "InEmptySystem",
    "InGasGiantSystem", "InPirateSystem", "Prime",
]  # fmt: skip
TRADER_COLUMNS = ["sequenceDelayX", "sequenceDelayY", "chanceToDelayLaunch", "initialDelay", "maxToSpawn"]
VOXEL_COLUMNS = [
    "atlasStations", "blackHoles", "guideStarMinimum", "guideStarRenegades",
    "purpleSystems", "purpleStart", "insideGoalGap",
]  # fmt: skip
# An inventory's entries (what's in its slots) and special slots, in item records.
STORE_ENTRY_COLUMNS = [
    "id", "x", "y", "amount", "maxAmount", "type", "damage", "addedAutomatically", "installed",
]  # fmt: skip
SPECIAL_SLOT_COLUMNS = ["x", "y", "type"]
LOCATION_COLUMNS = ["galaxy", "voxelX", "voxelY", "voxelZ", "system", "planet"]
STAR_FLAGS = ["AbandonedSystem", "IsGasGiantSystem", "IsGiantSystem", "IsPirateSystem", "IsSystemSafe"]

# Record key -> NMS.py enum. The name tables go into the session header,
# because game updates can renumber enums.
ENUM_SOURCES = {
    "shipClass": "cGcSpaceshipClasses",
    "role": "cGcAISpaceshipRoles",
    "faction": "cGcRealityCommonFactions",
    "frigateClass": "cGcFrigateClass",
    "systemClass": "cGcSolarSystemClass",
    "conflict": "cGcPlayerConflictData",
    "race": "cGcAlienRace",
    "star": "cGcGalaxyStarTypes",
    "trade": "cGcTradingClass",
    "wealth": "cGcWealthClass",
    "anomaly": "cGcGalaxyStarAnomaly",
    "size": "cGcPlanetSize",
    "biome": "cGcBiomeType",
    "biomeSubType": "cGcBiomeSubType",
    "planetClass": "cGcPlanetClass",
    "resourceType": "ResourceTypes",
    "inventoryClass": "cGcInventoryClass",
    "inventoryType": "cGcInventoryType",
    "slotType": "cGcInventorySpecialSlotType",
    "stackSizeGroup": "cGcInventoryStackSizeGroup",
}

# In-game names for the log, keyed by cGcSpaceshipClasses member name.
SHIP_LABELS = {
    "Freighter": "Freighter",
    "Dropship": "Hauler",
    "Fighter": "Fighter",
    "Scientific": "Explorer",
    "Shuttle": "Shuttle",
    "PlayerFreighter": "Player freighter",
    "Royal": "Exotic",
    "Alien": "Living ship",
    "Sail": "Solar",
    "Robot": "Interceptor",
    "Corvette": "Corvette",
    "SwarmDrone": "Swarm drone",
}


class CaptureError(Exception):
    """Game memory couldn't be read, or held something implausible."""


class Layout:
    """Byte offsets taken from NMS.py's struct definitions."""

    def __init__(self) -> None:
        system = nms.cGcSolarSystem
        data = nmse.cGcSolarSystemData
        generator = nms.cGcSolarSystemGenerator
        self.data = system.mSolarSystemData.offset
        self.data_size = ctypes.sizeof(data)
        self.system_size = ctypes.sizeof(system)
        self.ua = system.mUA.offset
        self.attributes = system.mGalaxyAttributes.offset
        self.attributes_size = ctypes.sizeof(nms.cGcGalaxyAttributesAtAddress)
        self.key_attributes_size = ctypes.sizeof(nms.cGcGalaxyAttributeGenerator.StarSystemKeyAttributes)
        self.generator = system.mSolarSystemGenerator.offset
        self.rng = generator.mRNG.offset
        self.metadata = generator.GenerationData.mMetaData.offset
        self.head = max(
            self.data + ctypes.sizeof(data),
            self.ua + 8,
            self.attributes + ctypes.sizeof(nms.cGcGalaxyAttributesAtAddress),
        )
        self.seed = self.data + data.Seed.offset
        self.ships = self.data + data.SystemShips.offset
        self.locators = self.data + data.Locators.offset
        self.locators_type = dict(data._fields_)["Locators"]  # the dynamic array header
        self.locator_size = ctypes.sizeof(nmse.cGcSolarSystemLocator)
        self.simulation_system = nms.cGcSimulation.mpSolarSystem.offset
        self.simulation_ua = nms.cGcSimulation.mCurrentUA.offset
        self.location = nms.cGcPlayerState.mLocation.offset
        self.location_size = ctypes.sizeof(nmse.cGcUniverseAddressData)
        # The player's name with title: read only to take it out of what the mod records.
        self.player_name = nms.cGcPlayerState.mNameWithTitle.offset
        self.player_name_size = ctypes.sizeof(basic.cTkFixedString0x100)
        # Where the player is (in the space station, on foot on a planet...), from the simulation.
        environment = nms.cGcSimulation.mEnvironment.offset + nms.cGcEnvironment.mPlayerEnvironment.offset
        self.player_where = environment + nms.cGcPlayerEnvironment.meLocation.offset
        self.player_planet = environment + nms.cGcPlayerEnvironment.miNearestPlanetIndex.offset
        self.item_size = ctypes.sizeof(nms.cGcPurchaseableItem)
        self.item_text_from = nms.cGcPurchaseableItem.mbAddAdditionalItem.offset + 1
        self.store_size = ctypes.sizeof(nms.cGcInventoryStore)
        # The resource manager's list of resources, and what the mod reads of each resource.
        resource = nms.cTkResource
        self.resources = nms.cTkResourceManager.mResources.offset
        self.resource_size = ctypes.sizeof(resource)
        self.resource_type = resource.miType.offset
        self.resource_name = resource.msName.offset
        self.resource_name_size = MODEL_NAME_LENGTH  # a cTkFixedString<0x100>, as the name it was built from
        self.resource_handle = resource.mHandle.offset
        self.resource_refs = resource.muRefCount.offset
        self.resource_descriptor = resource.mDescriptor.offset


LAYOUT = Layout()


def _make_reader():
    """Return read(address, size) -> bytes, or None if the memory isn't readable."""
    if sys.platform != "win32":
        # Only reached by the tests, which run off Windows against buffers
        # they allocated themselves. Unchecked.
        def read_unchecked(address: int, size: int) -> bytes | None:
            if not address or not 0 < size <= MAX_READ:
                return None
            return ctypes.string_at(address, size)

        return read_unchecked

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read_process_memory = kernel32.ReadProcessMemory
    read_process_memory.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.LPVOID,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    read_process_memory.restype = wintypes.BOOL
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    process = get_current_process()

    def read_checked(address: int, size: int) -> bytes | None:
        if not address or not 0 < size <= MAX_READ:
            return None
        buffer = ctypes.create_string_buffer(size)
        done = ctypes.c_size_t(0)
        ok = read_process_memory(
            process, ctypes.c_void_p(address), ctypes.byref(buffer), size, ctypes.byref(done)
        )
        if not ok or done.value != size:
            return None
        return buffer.raw

    return read_checked


read_memory = _make_reader()


def read_u64(address: int) -> int | None:
    raw = read_memory(address, 8)
    return None if raw is None else int.from_bytes(raw, "little")


def address_of(pointer) -> int:
    """Address held by a ctypes pointer (or a plain integer address)."""
    if pointer is None:
        return 0
    if isinstance(pointer, int):
        return pointer
    try:
        return ctypes.cast(pointer, ctypes.c_void_p).value or 0
    except (TypeError, ctypes.ArgumentError):
        return int(getattr(pointer, "value", 0) or 0)


def hex64(value: int) -> str:
    return f"{value & MASK64:016X}"


def as_int(value) -> int:
    """A plain int from an int, a bool or an NMS.py enum field."""
    return int(value) if isinstance(value, int) else int(value.value)


def text(value) -> str:
    return str(value).replace("\x00", "")


def number(value: float) -> float | None:
    return round(value, 4) if math.isfinite(value) else None


def bitmask(obj, names: list[str]) -> int:
    mask = 0
    for bit, name in enumerate(names):
        if getattr(obj, name):
            mask |= 1 << bit
    return mask


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def portal_code(ua: int) -> str:
    """12-digit portal code (PSSSYYZZZXXX) of a universal address."""
    planet = (ua >> 52) & 0xF
    system = (ua >> 40) & 0xFFF
    return f"{planet:X}{system:03X}{ua & 0xFFFFFFFF:08X}"


def galaxy_of(ua: int) -> int:
    return (ua >> 32) & 0xFF


def enum_tables() -> dict[str, list[str | None]]:
    """Value -> member name for every enum a record refers to."""
    sources = {key: getattr(enums, name, None) for key, name in ENUM_SOURCES.items()}
    sources["asteroids"] = getattr(nmse.cGcSolarSystemData, "eAsteroidLevelEnum", None)
    sources["where"] = getattr(getattr(enums, "EnvironmentLocation", None), "Enum", None)
    tables: dict[str, list[str | None]] = {}
    for key, enum in sources.items():
        members = list(enum) if enum is not None else []
        if not members:
            continue
        top = max(int(m.value) for m in members)
        if not 0 <= top <= 4096:
            continue
        table: list[str | None] = [None] * (top + 1)
        for member in members:
            table[int(member.value)] = member.name
        tables[key] = table
    return tables


ENUM_TABLES = enum_tables()


def ship_label(ship_class: int) -> str:
    names = ENUM_TABLES.get("shipClass", [])
    name = names[ship_class] if 0 <= ship_class < len(names) else None
    return SHIP_LABELS.get(name or "", name or f"Class {ship_class}")


def ship_rows(data) -> list[list]:
    ships = data.SystemShips
    count, pointer = as_int(ships.Size), as_int(ships.ArrayPointer)
    if count == 0:
        return []
    if not pointer or not 0 < count <= MAX_SHIPS:
        raise CaptureError(f"implausible ship list (count {count}, pointer {pointer:#x})")
    item = nmse.cGcAISpaceshipPreloadCacheData
    raw = read_memory(pointer, count * ctypes.sizeof(item))
    if raw is None:
        raise CaptureError(f"ship list at {pointer:#x} couldn't be read")
    return [
        [
            hex64(ship.Seed.Seed),
            as_int(ship.Seed.UseSeedValue),
            as_int(ship.ShipClass),
            as_int(ship.ShipRole),
            as_int(ship.Faction),
            as_int(ship.FrigateClass),
            text(ship.TextureDescriptorHint),
        ]
        for ship in (item * count).from_buffer_copy(raw)
    ]


def body_rows(data) -> list[list]:
    rows = [
        [
            hex64(body.Seed.Seed),
            as_int(body.Seed.UseSeedValue),
            as_int(body.Biome),
            as_int(body.BiomeSubType),
            as_int(body.Class),
            as_int(body.PlanetIndex),
            as_int(body.PlanetSize),
            as_int(body.RealityIndex),
            as_int(body.Star),
            bitmask(body, BODY_FLAGS),
            text(body.CommonSubstance),
            text(body.RareSubstance),
        ]
        for body in data.PlanetGenerationInputs
    ]
    while rows and rows[-1][0] == ZERO_SEED and not rows[-1][10] and not rows[-1][11]:
        rows.pop()
    return rows


def trader_row(spawn) -> list:
    delay = spawn.SequenceTakeoffDelay
    return [
        number(delay.x),
        number(delay.y),
        as_int(spawn.ChanceToDelayLaunch),
        number(spawn.InitialTakeoffDelay),
        as_int(spawn.MaxToSpawn),
    ]


def body_positions(data) -> list[list[float]]:
    """Where the generator put each planet and moon, or nothing if it hasn't yet."""
    count = max(0, min(as_int(data.Planets), len(data.PlanetPositions)))
    positions = [[round(p.x, 1), round(p.y, 1), round(p.z, 1)] for p in list(data.PlanetPositions)[:count]]
    return positions if any(any(v for v in p) for p in positions) else []


def system_fields(data) -> dict:
    trading = data.TradingData
    fields = {
        "seed": hex64(data.Seed.Seed),
        "useSeed": as_int(data.Seed.UseSeedValue),
        "name": text(data.Name),
        "systemClass": as_int(data.Class),
        "star": as_int(data.StarType),
        "race": as_int(data.InhabitingRace),
        "trade": as_int(trading.TradingClass),
        "wealth": as_int(trading.WealthClass),
        "conflict": as_int(data.ConflictData),
        "planets": as_int(data.Planets),
        "prime": as_int(data.PrimePlanets),
        "primeInCount": bool(data.PrimePlanetsIncludedInPlanetCount),
        "freighters": as_int(data.MaxNumFreighters),
        "startWithFreighters": bool(data.StartWithFreighters),
        "tradeRoutes": [as_int(data.NumTradeRoutes), as_int(data.NumVisibleTradeRoutes)],
        "asteroids": as_int(data.AsteroidLevel),
        "crashShip": hex64(data.SentinelCrashSiteShipSeed.Seed),
        "orbits": [as_int(orbit) for orbit in data.PlanetOrbits],
        "traders": [trader_row(data.TraderSpawnInStations), trader_row(data.TraderSpawnOnOutposts)],
    }
    if positions := body_positions(data):
        fields["positions"] = positions
    return fields


def galaxy_attributes(attributes) -> dict:
    """The galaxy generator's view of the same system (cGcGalaxyAttributesAtAddress)."""
    voxel, star = attributes.mVoxel, attributes.mStar
    seeds = [hex64(seed.Seed) for seed in star.PlanetSeeds]
    bodies = len(seeds)
    while bodies and seeds[bodies - 1] == ZERO_SEED:
        bodies -= 1
    atlas_count, hole_count = as_int(voxel.AtlasStationCount), as_int(voxel.BlackholeCount)
    return {
        "valid": bool(attributes.mbValid),
        "voxel": [
            atlas_count,
            hole_count,
            as_int(voxel.GuideStarMinimumCount),
            as_int(voxel.GuideStarRenegadeCount),
            as_int(voxel.PurpleSystemsCount),
            as_int(voxel.PurpleSystemsStart),
            int(bool(voxel.InsideGoalGap)),
        ],
        "atlasIndices": list(voxel.AtlasStationIndices)[: clamp(atlas_count, 0, 12)],
        "blackHoleIndices": list(voxel.BlackholeIndices)[: clamp(hole_count, 0, 12)],
        "star": as_int(star.Type),
        "race": as_int(star.Race),
        "trade": as_int(star.TradingData.TradingClass),
        "wealth": as_int(star.TradingData.WealthClass),
        "conflict": as_int(star.ConflictData),
        "anomaly": as_int(star.Anomaly),
        # A value of the region the system is in, recorded to compare with the guild seen there.
        "regionColour": number(voxel.RegionColourValue),
        "planets": as_int(star.NumberOfPlanets),
        "prime": as_int(star.NumberOfPrimePlanets),
        "spacePois": as_int(star.NumberOfSpacePois),
        "flags": [name for name in STAR_FLAGS if getattr(star, name)],
        "seeds": seeds[:bodies],
        "parents": list(star.PlanetParentIndices)[:bodies],
        "sizes": [as_int(size) for size in star.PlanetSizes][:bodies],
    }


def unusual_values(record: dict) -> list[str]:
    """Fields whose values suggest NMS.py's layout no longer matches the game."""
    unusual = []
    name = record.get("name")
    # An empty name is fine: the game may name the system after generating it.
    if name and (len(name) > 64 or not name.isprintable()):
        unusual.append("name")
    for key, top in (("star", 15), ("race", 31), ("planets", 16), ("prime", 16)):
        value = record.get(key)
        if value is not None and not 0 <= value <= top:
            unusual.append(key)
    return unusual


def _attempt(problems: list[str], label: str, read, *args):
    try:
        return read(*args)
    except Exception as exc:  # one unreadable section shouldn't lose the rest
        problems.append(f"{label}: {exc}")
        return None


def snapshot(address: int) -> dict:
    """Everything the record holds about the solar system object at ``address``."""
    head = read_memory(address, LAYOUT.head)
    if head is None:
        raise CaptureError(f"the solar system at {address:#x} couldn't be read")
    problems: list[str] = []
    data = nmse.cGcSolarSystemData.from_buffer_copy(head, LAYOUT.data)
    record: dict = {"ua": hex64(int.from_bytes(head[LAYOUT.ua : LAYOUT.ua + 8], "little"))}
    record.update(_attempt(problems, "system", system_fields, data) or {})
    ships = _attempt(problems, "ships", ship_rows, data)
    if ships is not None:
        record["ships"] = ships
    bodies = _attempt(problems, "bodies", body_rows, data)
    if bodies is not None:
        record["bodies"] = bodies
    galaxy = _attempt(
        problems,
        "galaxy attributes",
        lambda: galaxy_attributes(nms.cGcGalaxyAttributesAtAddress.from_buffer_copy(head, LAYOUT.attributes)),
    )
    if galaxy is not None:
        record["galaxy"] = galaxy
    unusual = unusual_values(record)
    if unusual:
        record["unusual"] = unusual
    if problems:
        record["errors"] = problems
    return record


def rng_state(generator: int) -> str | None:
    """The solar system generator's random-number state (cTkPersonalRNG), as 16 hex digits."""
    return None if (value := read_u64(generator + LAYOUT.rng)) is None else hex64(value)


def packed(raw: bytes | None) -> str | None:
    return None if raw is None else base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def raw_data(address: int) -> str | None:
    """The whole generated cGcSolarSystemData, compressed, for offline analysis."""
    return packed(read_memory(address + LAYOUT.data, LAYOUT.data_size))


def locator_data(address: int) -> dict | None:
    """The system's Locators, the spawn points generation places, compressed.

    In the systems traced so far, generation drew about four random numbers
    per locator between the planet biomes and the ships, so the locators look
    like what decides where the ships start in the random-number stream.
    """
    header = read_memory(address + LAYOUT.locators, ctypes.sizeof(LAYOUT.locators_type))
    if header is None:
        return None
    array = LAYOUT.locators_type.from_buffer_copy(header)
    count, pointer = as_int(array.Size), as_int(array.ArrayPointer)
    if count == 0:
        return {"count": 0}
    if not pointer or not 0 < count <= MAX_LOCATORS:
        raise CaptureError(f"implausible locator list (count {count}, pointer {pointer:#x})")
    raw = read_memory(pointer, count * LAYOUT.locator_size)
    if raw is None:
        raise CaptureError(f"locator list at {pointer:#x} couldn't be read")
    return {"count": count, "size": LAYOUT.locator_size, "raw": packed(raw)}


def raw_galaxy(address: int) -> str | None:
    """The system's whole cGcGalaxyAttributesAtAddress, compressed."""
    return packed(read_memory(address + LAYOUT.attributes, LAYOUT.attributes_size))


def read_text(address: int, size: int) -> str | None:
    raw = read_memory(address, size)
    return None if raw is None else raw.split(b"\0", 1)[0].decode("utf-8", errors="backslashreplace")


def read_c_string(address: int, limit: int) -> str | None:
    """A NUL-terminated string of at most ``limit`` bytes, read a page at a time, so a short
    string near the end of readable memory doesn't fail for want of bytes it doesn't have."""
    if not address:
        return None
    text_bytes = b""
    while len(text_bytes) < limit:
        start = address + len(text_bytes)
        raw = read_memory(start, min(limit - len(text_bytes), 0x1000 - (start & 0xFFF)))
        if raw is None:
            return None
        end = raw.find(b"\0")
        if end >= 0:
            text_bytes += raw[:end]
            break
        text_bytes += raw
    return text_bytes.decode("utf-8", errors="backslashreplace")


def resource_descriptor(address: int, keep_raw: bool = False) -> dict | None:
    """The parts and seeds in a cTkResourceDescriptor, or None if it has neither.

    The game hands one of these over with each model it builds: the IDs of
    the parts it picked and the seed it picked them with.
    """
    raw = read_memory(address, ctypes.sizeof(nms.cTkResourceDescriptor))
    if raw is None:
        raise CaptureError(f"the descriptor at {address:#x} couldn't be read")
    descriptor = nms.cTkResourceDescriptor.from_buffer_copy(raw)
    parts, seed, seed2 = descriptor.maDescriptors, descriptor.mSeed, descriptor.mSecondarySeed
    count, pointer = as_int(parts.vector_size), address_of(parts._ptr)
    if not count and not seed.Seed and not seed2.Seed:
        return None
    found: dict = {"seed": hex64(seed.Seed), "useSeed": as_int(seed.UseSeedValue)}
    if seed2.Seed or seed2.UseSeedValue:
        found["seed2"] = hex64(seed2.Seed)
        found["useSeed2"] = as_int(seed2.UseSeedValue)
    problems: list[str] = []
    found["parts"] = []
    if count:
        size = ctypes.sizeof(basic.TkID0x20)
        if not pointer or not 0 < count <= MAX_MODEL_PARTS:
            problems.append(f"implausible part list (count {count}, pointer {pointer:#x})")
        elif (part_bytes := read_memory(pointer, count * size)) is None:
            problems.append(f"part list at {pointer:#x} couldn't be read")
        else:
            found["parts"] = [
                part_bytes[i : i + size].split(b"\0", 1)[0].decode("ascii", errors="backslashreplace")
                for i in range(0, len(part_bytes), size)
            ]
            if not all(part.isprintable() for part in found["parts"]):
                problems.append("part IDs that aren't text")
    if problems:
        found["errors"] = problems
    if problems or keep_raw:
        found["raw"] = raw.hex().upper()
    return found


def is_ship_model(name: str) -> bool:
    path = name.replace("\\", "/").upper()
    return any(part in path for part in SHIP_MODEL_PATHS)


def is_multitool_model(name: str) -> bool:
    path = "/" + name.replace("\\", "/").upper()
    return (
        MULTITOOL_MODEL_DIR in path
        and not any(folder in path for folder in NOT_MULTITOOL_DIRS)
        and not is_ship_model(name)
    )


def model_file(name: str) -> str:
    """A model's file name without its folder and extension, such as MULTITOOL."""
    return name.replace("\\", "/").rsplit("/", 1)[-1].split(".", 1)[0]


def model_key(model: dict) -> tuple:
    """What tells one model from another: its file, seeds and parts."""
    return (model["name"], model["seed"], model.get("seed2"), tuple(model["parts"]))


def resource_manager_address() -> int | None:
    """Where the game's resource manager is, from the pointer NMS.py finds by pattern, or None
    if NMS.py hasn't found that pointer or the game hasn't set it."""
    pointer = getattr(nms.cEgModules, "mgpResourceManager", None)
    try:
        where = ctypes.addressof(pointer)  # the game's own pointer, which pyMHF maps in place
    except TypeError:
        return None
    return read_u64(where) or None


def resource_info(handle: int) -> dict | None:
    """What the game's resource manager holds for ``handle``: the resource's file, type and how
    many hold it, and the seeds and parts of its descriptor if it has one; or why that couldn't be
    read; or None if the resource manager can't be found. Only resources that say they have this
    handle count, so a list laid out otherwise than the mod expects gives no false answer."""
    manager = resource_manager_address()
    if not manager:
        return None
    header = read_memory(manager + LAYOUT.resources, 16)
    if header is None:
        return {"error": "the resource list couldn't be read"}
    allocated, count, pointer = struct.unpack("<IIQ", header)
    if not pointer or not 0 < count <= allocated or count > MAX_RESOURCES:
        return {"error": f"implausible resource list (count {count} of {allocated}, pointer {pointer:#x})"}
    seen: list[int | None] = []
    for index in (handle - 1, handle):  # handles may count from 1, as in Horde3D, the engine's ancestor
        if not 0 <= index < count:
            continue
        address = read_u64(pointer + 8 * index)
        raw = read_memory(address, LAYOUT.resource_size) if address else None
        if raw is None:
            seen.append(None)
            continue
        held = int.from_bytes(raw[LAYOUT.resource_handle : LAYOUT.resource_handle + 4], "little")
        if held != handle:
            seen.append(held)
            continue
        name = raw[LAYOUT.resource_name : LAYOUT.resource_name + LAYOUT.resource_name_size]
        found: dict = {
            "slot": index,
            "name": name.split(b"\0", 1)[0].decode("utf-8", errors="backslashreplace"),
            "type": int.from_bytes(raw[LAYOUT.resource_type : LAYOUT.resource_type + 4], "little"),
            "refs": int.from_bytes(raw[LAYOUT.resource_refs : LAYOUT.resource_refs + 4], "little"),
        }
        try:
            descriptor = resource_descriptor(address + LAYOUT.resource_descriptor)
        except CaptureError as exc:
            found["errors"] = [str(exc)]
        else:
            if descriptor is not None:
                found.update(descriptor)
        return found
    return {"error": "no resource with this handle", "seen": seen}


def seeds_in(raw: bytes, wanted) -> list[tuple[int, int]]:
    """(offset, seed) for each 8-byte little-endian value in ``raw``, at any 4-byte boundary,
    that is one of ``wanted``; each seed once, at its first offset, in order of offset.
    ``wanted`` (a set or dict) is only asked about values, never walked, so another thread
    may add to it meanwhile."""
    first: dict[int, int] = {}
    for start in (0, 4):
        count = (len(raw) - start) // 8
        if count <= 0:
            continue
        values = struct.unpack_from(f"<{count}Q", raw, start)
        for value in set(values):
            if value in wanted:
                offset = start + 8 * values.index(value)
                first[value] = min(offset, first.get(value, offset))
    return sorted((offset, value) for value, offset in first.items())


def _entries(vector, kind, row, problems: list[str], label: str) -> list:
    """The entries of a TkStd::tk_vector copied out of the game, read through its pointer."""
    count, allocated = as_int(vector.vector_size), as_int(vector.allocated_size)
    if not count:
        return []
    pointer = address_of(vector._ptr)
    if not pointer or not 0 < count <= min(allocated, MAX_STORE_ENTRIES):
        problems.append(f"{label}: implausible list (count {count} of {allocated}, pointer {pointer:#x})")
        return []
    raw = read_memory(pointer, count * ctypes.sizeof(kind))
    if raw is None:
        problems.append(f"{label}: list at {pointer:#x} couldn't be read")
        return []
    return [row(entry) for entry in (kind * count).from_buffer_copy(raw)]


def store_entry_row(entry) -> list:
    """One cGcInventoryElement, in STORE_ENTRY_COLUMNS order."""
    return [
        text(entry.Id),
        as_int(entry.Index.X),
        as_int(entry.Index.Y),
        as_int(entry.Amount),
        as_int(entry.MaxAmount),
        as_int(entry.Type),
        number(entry.DamageFactor),
        int(bool(entry.AddedAutomatically)),
        int(bool(entry.FullyInstalled)),
    ]


def inventory_store(raw: bytes, offset: int) -> dict | None:
    """What the cGcInventoryStore at ``offset`` in ``raw`` holds, following its lists into the
    game's memory; None for an empty 1x1 (or 0x0) store, which is what an item's unused
    inventories are, and {"implausible": 1} for bytes that can't be a store."""
    store = nms.cGcInventoryStore.from_buffer_copy(raw, offset)
    width, height, slots = as_int(store.miWidth), as_int(store.miHeight), as_int(store.miCapacity)
    grade = as_int(store.mClass)
    if not (
        0 <= width <= MAX_STORE_SIDE
        and 0 <= height <= MAX_STORE_SIDE
        and 0 <= slots <= MAX_STORE_SIDE**2
        and 0 <= grade <= 3
    ):
        return {"implausible": 1}  # its bytes are in the item's raw bytes
    problems: list[str] = []
    valid = [int(row.array[0]) for row in store.mxValidSlots]  # a bit per slot, a row at a time
    while valid and not valid[-1]:
        valid.pop()
    layout = store.mLayoutDescriptor
    element = nmse.cGcInventoryElement
    lists = {
        "entries": _entries(store.mStore, element, store_entry_row, problems, "entries"),
        "history": _entries(store.mStoreHistory, element, store_entry_row, problems, "history"),
        "special": _entries(
            store.maSpecialSlots,
            nmse.cGcInventorySpecialSlot,
            lambda slot: [as_int(slot.Index.X), as_int(slot.Index.Y), as_int(slot.Type)],
            problems,
            "special slots",
        ),
        "stats": _entries(
            store.maBaseStats,
            nmse.cGcInventoryBaseStatEntry,
            lambda stat: [text(stat.BaseStatID), number(stat.Value)],
            problems,
            "base stats",
        ),
    }
    found = {
        "size": [width, height, slots],
        "valid": valid,
        "class": grade,
        "layout": [
            hex64(layout.Seed.Seed),
            as_int(layout.Seed.UseSeedValue),
            as_int(layout.Level),
            as_int(layout.Slots),
        ],
        "autoMax": int(bool(store.mbAutoMaxEnabled)),
        "stack": as_int(store.meStackSizeGroup),
    }
    name = text(store.mInventoryName)
    unused = found["size"] in ([1, 1, 1], [0, 0, 0]) and found["class"] == 0 and layout.Seed.Seed <= 1
    if unused and not valid and not name and not any(lists.values()) and not problems:
        return None
    if name:
        found["name"] = name
    found.update((key, rows) for key, rows in lists.items() if rows)
    if problems:
        found["errors"] = problems
    return found


def item_stores(raw: bytes) -> list[dict]:
    """The inventories an item the game offers holds, numbered by where they are in it."""
    stores = []
    for index in range(ITEM_STORES):
        offset = ITEM_STORES_AT + index * LAYOUT.store_size
        if offset + LAYOUT.store_size > len(raw):
            break
        if (store := inventory_store(raw, offset)) is not None:
            stores.append({"i": index, **store})
    return stores


TEXT_RUN = re.compile(rb"[\x20-\x7e]{4,}")


def item_texts(raw: bytes) -> list[list]:
    """[offset, text] for each run of four or more printable characters, a letter among them, in an
    item's bytes between its flags and its inventories."""
    found = []
    for match in TEXT_RUN.finditer(raw, LAYOUT.item_text_from, ITEM_STORES_AT):
        run = match.group().decode("ascii")
        if any(c.isalpha() for c in run):
            found.append([match.start(), run])
    return found


# Short words a player's title may hold that aren't taken out of text on their own.
COMMON_WORDS = {"the", "and", "of", "to", "in", "on", "at", "an", "de", "la", "le", "el", "du", "da", "di"}
NAME_SEPARATORS = re.compile(r"[\s,.:;!?|/\\<>()\[\]{}\"'`]+")
CONTROL_BYTES = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WORD_BYTE = rb"[0-9A-Za-z\x80-\xff]"  # a letter or digit, or part of a non-ASCII character


def name_problem(name: bytes) -> str | None:
    """Why ``name``, read from the game, can't be taken out of what the mod records, or None if it
    can. Said in the log, so it never says the name."""
    name = name.strip()
    if not name:
        return "empty"
    if CONTROL_BYTES.search(name):
        return "not text"
    try:
        name.decode("utf-8")
    except UnicodeDecodeError:
        return "not UTF-8"
    return None


def name_pattern(name: bytes) -> re.Pattern[bytes] | None:
    """What to take out of what the mod records: ``name`` (a player's name with title, UTF-8) and
    each word in it, ignoring case, but for a few common short ones; two-character words only where
    they stand alone, and one-character words not on their own: a lone letter says nothing of who
    you are, and can't be taken out of bytes without taking out much else. None if ``name`` is empty
    or isn't text (see name_problem): then nothing that might hold it is recorded."""
    if name_problem(name) is not None:
        return None
    whole = name.strip().decode("utf-8")
    words = NAME_SEPARATORS.split(whole)
    kept = {word for word in words if len(word) >= 2 and word.lower() not in COMMON_WORDS}
    if len(whole) >= 2:
        kept.add(whole)
    alternatives = [re.escape(w.encode()) for w in sorted(kept, key=len, reverse=True) if len(w) >= 3]
    alternatives += [
        rb"(?<!" + WORD_BYTE + rb")" + re.escape(w.encode()) + rb"(?!" + WORD_BYTE + rb")"
        for w in sorted(kept)
        if len(w) == 2
    ]
    return re.compile(b"|".join(alternatives) if alternatives else rb"(?!)", re.IGNORECASE)


def player_name_pattern() -> tuple[re.Pattern[bytes] | None, str | None]:
    """(name_pattern() of the player's name with title, None), or (None, why it can't be made)."""
    try:
        state = gameData.player_state
    except (ValueError, AttributeError):
        return None, "no player state"
    if state is None:
        return None, "no player state"
    raw = read_memory(ctypes.addressof(state) + LAYOUT.player_name, LAYOUT.player_name_size)
    if raw is None:
        return None, "unreadable"
    name = raw.split(b"\0", 1)[0]
    if (problem := name_problem(name)) is not None:
        return None, problem
    return name_pattern(name), None


def scrub(raw: bytes, pattern: re.Pattern[bytes]) -> tuple[bytes, int]:
    """``raw`` with each match of ``pattern`` overwritten by as many asterisks, and how many there were."""
    return pattern.subn(lambda match: b"*" * len(match.group()), raw)


def scrub_text(value: str, pattern: re.Pattern[bytes]) -> str:
    """scrub() for text the mod decoded."""
    return scrub(value.encode("utf-8"), pattern)[0].decode("utf-8", "backslashreplace")


def item_summary(offer: dict) -> str:
    """An item's inventories and model, for the log."""
    classes = ENUM_TABLES.get("inventoryClass", [])
    stores = []
    for store in offer.get("stores", []):
        if "size" not in store:
            stores.append(f"{store['i']} (not an inventory after all)")
            continue
        width, height, slots = store["size"]
        grade = classes[store["class"]] if 0 <= store["class"] < len(classes) else store["class"]
        stores.append(f"{store['i']} ({width}x{height}, {slots} slots, class {grade})")
    said = ["inventories " + ", ".join(stores) if stores else "no inventories"]
    if model := offer.get("model"):
        place = f", number {model['pool'] + 1} of the system's set" if "pool" in model else ""
        said.append(f"model {model['name']}, seed {model['seed']}{place}")
    elif offer.get("handle", 0) not in NO_HANDLE:
        said.append(f"a model the mod didn't see the game build (handle {offer['handle']})")
    else:
        said.append("no model")
    return "; ".join(said)


def offered_item(raw: bytes) -> dict:
    """What a cGcPurchaseableItem holds, from its bytes and the lists its inventories point to."""
    item = nms.cGcPurchaseableItem.from_buffer_copy(raw)
    found = {
        "itemType": as_int(item.mItemType),
        "state": as_int(item.mePurchaseState),
        "free": int(bool(item.mbIsFree)),
        "gift": int(bool(item.mbIsGift)),
        "reward": int(bool(item.mbIsReward)),
        "extra": int(bool(item.mbAddAdditionalItem)),
        "handle": as_int(item.mItemResource.miInternalHandle) & 0xFFFFFFFF,
        "node": as_int(item.mItemNode.lookupInt),
    }
    if stores := item_stores(raw):
        found["stores"] = stores
    entitlement = [text(item.mLinkedEntitlementId), text(item.mLinkedEntitlementRewardId)]
    if any(entitlement):
        found["entitlement"] = entitlement
    return found


def key_attributes(address: int) -> dict | None:
    """The galaxy generator's summary of a system (StarSystemKeyAttributes) that generation starts from."""
    raw = read_memory(address, LAYOUT.key_attributes_size)
    if raw is None:
        return None
    keys = nms.cGcGalaxyAttributeGenerator.StarSystemKeyAttributes.from_buffer_copy(raw)
    return {
        "trade": as_int(keys.meTradingClass),
        "wealth": as_int(keys.meWealthClass),
        "conflict": as_int(keys.meConflictLevel),
        "race": as_int(keys.meRace),
        "star": as_int(keys.meType),
        "tag": as_int(keys.meTag),
        "anomaly": f"{as_int(keys.meAnomaly):08X}",  # four bytes, not yet understood
        "planets": as_int(keys.muPlanetCount),
        "safeStart": as_int(keys.muSafeStartPlanet),
        "abandoned": bool(keys.mbAbandonedSystem),
        "pirate": bool(keys.mbIsPirateSystem),
        "prime": as_int(keys.muPrimePlanetCount),
        "raw": raw.hex().upper(),
    }


def steam_build(binary_path: str | None) -> str | None:
    """Steam's build ID for the installed game, from the library's app manifest."""
    if not binary_path:
        return None
    for folder in Path(binary_path).parents:
        if folder.name.lower() == "steamapps":
            manifest = folder / f"appmanifest_{STEAM_APP_ID}.acf"
            match = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text(encoding="utf-8", errors="replace"))
            return match.group(1) if match else None
    return None


def hook_status(mod: Mod) -> dict[str, str]:
    """Whether each of the mod's detours is attached to the game ("enabled") or not."""
    from pymhf.core.hooking import hook_manager

    status = {hook.__name__: "not found" for hook in mod.hooks}
    for function in list(hook_manager.hooks.values()):
        attached = [
            *function._before_detours,
            *function._after_detours,
            *function._after_detours_with_results,
        ]
        for detours, state in (
            (attached, function.state or "registered"),
            (function._disabled_detours, "disabled"),
        ):
            for detour in detours:
                if getattr(detour, "__self__", None) is mod:
                    status[detour.__name__] = state
    return status


def system_display_name(address: int) -> str | None:
    """The name the game shows for the loaded system. Main thread only: this calls the game."""
    buffer = basic.cTkFixedString0x80()
    nms.cGcSolarSystem.from_address(address).GetName(ctypes.byref(buffer))
    return text(buffer) or None


# --- Calling a function of the game ---
# The mod calls a game function of its own accord only once read_leaf has found, from the function's
# code, that calling it can't change anything. The Windows x64 calling convention lets a function
# change rax, rcx, rdx, r8 to r11 and xmm0 to xmm5 without putting them back; a function the mod calls
# may change all of these but rcx, which holds the address of the object it's called on, so that
# every read through rcx is a read of that object.
WRITABLE_REGISTERS = frozenset({0, 2, 8, 9, 10, 11})
WRITABLE_XMM = frozenset(range(6))
THIS_REGISTER = 1  # rcx
# The opcodes read_leaf knows that come with a ModRM byte: one-byte ones, but for add, or, adc, sbb,
# and, sub, xor and cmp (below 0x40), and those after 0F.
MODRM_OPCODES = frozenset({
    0x63, 0x69, 0x6B, 0x80, 0x81, 0x83, 0x84, 0x85, 0x88, 0x89, 0x8A, 0x8B, 0x8D,
    0xC0, 0xC1, 0xC6, 0xC7, 0xD0, 0xD1, 0xD2, 0xD3, 0xF6, 0xF7, 0xFE, 0xFF,
})  # fmt: skip
ESCAPED_MODRM_OPCODES = frozenset({
    0x10, 0x11, 0x14, 0x15, 0x1F, 0x28, 0x29, 0x2A, 0x2C, 0x2D, 0x2E, 0x2F, *range(0x40, 0x50),
    0x51, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x5C, 0x5D, 0x5E, 0x5F, 0x6E, 0x6F, 0x7E,
    *range(0x90, 0xA0), 0xAF, 0xB6, 0xB7, 0xBE, 0xBF, 0xC2, 0xC6, 0xEF,
})  # fmt: skip


class Leaf:
    """A function's code that read_leaf found can't change anything when called: ``length``, bytes from
    the start of its first instruction to the end of its last; ``fields``, (offset in the object, bytes)
    of each read of the object; ``values``, (offset in the code of the instruction, offset of the value
    from the code's start, bytes) of each read of a value at a fixed place in the game."""

    def __init__(self, length: int, fields: list[tuple[int, int]], values: list[tuple[int, int, int]]):
        self.length, self.fields, self.values = length, fields, values


def writable(register: int, byte: bool, rex: int) -> bool:
    """Whether a function may write the general register numbered ``register``; ``byte``, as a byte
    register, which without a REX prefix makes 4 to 7 ah, ch, dh and bh."""
    if byte and not rex and 4 <= register <= 7:
        register -= 4
    return register in WRITABLE_REGISTERS


class Operand:
    """What an instruction's ModRM byte, with its SIB byte and displacement, names: a register, ``rm``
    (``memory`` False), or memory at ``base`` (None if the address has no base register) plus
    ``displacement``, plus a register ``index`` unless it's None; with ``rip``, the displacement is from
    the end of the instruction. ``reg`` is the register in the reg field, and ``group`` that field
    without REX, which picks the operation of a group opcode."""

    def __init__(self, code: bytes, at: int, rex: int):
        modrm = code[at]
        at += 1
        mode, rm = modrm >> 6, modrm & 7
        self.group = modrm >> 3 & 7
        self.reg = self.group | (rex & 4) << 1
        self.rm = rm | (rex & 1) << 3
        self.memory = mode != 3
        self.base: int | None = self.rm
        self.index: int | None = None
        self.rip = False
        size = (0, 1, 4, 0)[mode]
        if self.memory and rm == 4:  # a SIB byte follows
            sib = code[at]
            at += 1
            index = (sib >> 3 & 7) | (rex & 2) << 2
            self.index = None if index == 4 else index
            self.base = (sib & 7) | (rex & 1) << 3
            if mode == 0 and sib & 7 == 5:
                self.base, size = None, 4
        elif mode == 0 and rm == 5:
            self.base, self.rip, size = None, True, 4
        if at + size > len(code):
            raise IndexError(at + size)
        self.displacement = int.from_bytes(code[at : at + size], "little", signed=True)
        self.end = at + size


def decode(code: bytes, at: int, object_size: int) -> tuple | str:
    """The instruction at ``at`` of a function read_leaf is reading: (where the next one starts; how it
    goes on: "next", "branch", "jump" or "ret"; where it jumps to, or None; what it reads: ("field",
    offset in the object, bytes), ("value", offset in the code, bytes) or None), or why the mod won't
    call a function with it in. Raises IndexError if it runs past the end of ``code``."""
    prefixes: set[int] = set()
    while code[at] in (0x66, 0xF2, 0xF3):
        if code[at] in prefixes:
            return "a repeated prefix"
        prefixes.add(code[at])
        at += 1
    if {0xF2, 0xF3} <= prefixes:
        return "both F2 and F3"
    rex = code[at] if 0x40 <= code[at] <= 0x4F else 0
    at += 1 if rex else 0
    op = code[at]
    at += 1
    escaped = op == 0x0F
    if escaped:
        op = code[at]
        at += 1
        if op not in ESCAPED_MODRM_OPCODES and not 0x80 <= op <= 0x8F:
            return f"instruction 0F {op:02X}"
    elif prefixes & {0xF2, 0xF3} and op not in (0x90, 0xC3):
        return f"instruction {op:02X} after F2 or F3"
    operand = None
    if (escaped and op in ESCAPED_MODRM_OPCODES) or (
        not escaped and ((op < 0x40 and op & 7 < 4) or op in MODRM_OPCODES)
    ):
        operand = Operand(code, at, rex)
        at = operand.end
    group = operand.group if operand else None
    word = 8 if rex & 8 else 2 if 0x66 in prefixes else 4  # the size of an operation on general registers
    # After 0F, the prefix that picks the instruction: F3 or F2 if there is one, else 66 or none.
    mandatory = next((prefix for prefix in (0xF3, 0xF2, 0x66) if prefix in prefixes), None)
    plain = mandatory in (None, 0x66)  # neither F2 nor F3
    scalar = {0xF3: 4, 0xF2: 8}.get(mandatory, 16)  # how many bytes an SSE instruction reads
    # What the instruction writes besides flags, rax and rdx: "reg" or "rm", the register ModRM names
    # in its reg or r/m field, or the memory its r/m field names; "xreg" or "xrm", the same with xmm
    # registers; "op", the register in the opcode's low bits; "lea", the reg field's register. ``byte``:
    # what it writes is a byte register. ``reads``: how many bytes it reads of the memory ModRM names.
    writes, byte, reads, immediate, flow = "", False, 0, 0, "next"
    if not escaped:
        if op < 0x40 and op & 7 < 6:  # add, or, adc, sbb, and, sub, xor, cmp
            kind = op & 7
            byte = kind in (0, 2, 4)
            writes = "" if op >= 0x38 or kind >= 4 else ("rm", "rm", "reg", "reg")[kind]
            immediate = (0, 0, 0, 0, 1, min(word, 4))[kind]
            reads = 1 if byte else word
        elif op == 0x63:  # movsxd
            writes, reads = "reg", 4
        elif op in (0x69, 0x6B):  # imul with an immediate
            writes, reads, immediate = "reg", word, 1 if op == 0x6B else min(word, 4)
        elif 0x70 <= op <= 0x7F and not prefixes:  # conditional jump
            immediate, flow = 1, "branch"
        elif op in (0x80, 0x81, 0x83):  # add to cmp with an immediate
            byte = op == 0x80
            writes, reads = "" if group == 7 else "rm", 1 if byte else word
            immediate = min(word, 4) if op == 0x81 else 1
        elif op in (0x84, 0x85):  # test
            byte = op == 0x84
            reads = 1 if byte else word
        elif 0x88 <= op <= 0x8B:  # mov
            byte = op in (0x88, 0x8A)
            writes, reads = "rm" if op < 0x8A else "reg", 1 if byte else word
        elif op == 0x8D:  # lea: works an address out, reading nothing
            writes = "lea"
        elif (op == 0x90 and not rex & 1 and prefixes in ({0x66}, {0xF3}, set())) or op in (0x98, 0x99):
            pass  # nop or pause; cdqe, cqo and the like
        elif op in (0xA8, 0xA9):  # test al or eax with an immediate
            immediate = 1 if op == 0xA8 else min(word, 4)
        elif 0xB0 <= op <= 0xBF:  # mov a register an immediate
            writes, byte = "op", op < 0xB8
            immediate = 1 if byte else word
        elif op in (0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3) and group != 6:  # shifts and rotations
            byte = op in (0xC0, 0xD0, 0xD2)
            writes, immediate = "rm", 1 if op in (0xC0, 0xC1) else 0
        elif op == 0xC3 and not prefixes - {0xF3}:  # ret
            flow = "ret"
        elif op in (0xC6, 0xC7) and group == 0:  # mov r/m an immediate
            byte = op == 0xC6
            writes, immediate = "rm", 1 if byte else min(word, 4)
        elif op in (0xE9, 0xEB) and not prefixes:  # jmp
            immediate, flow = 4 if op == 0xE9 else 1, "jump"
        elif op in (0xF6, 0xF7) and group in (0, 2, 3):  # test with an immediate, not, neg
            byte = op == 0xF6
            if group == 0:
                immediate, reads = (1, 1) if byte else (min(word, 4), word)
            else:
                writes = "rm"
        elif op in (0xFE, 0xFF) and group in (0, 1):  # inc, dec
            byte = op == 0xFE
            writes = "rm"
        else:
            return f"instruction {op:02X}" + ("" if group is None else f" /{group}")
    elif op == 0x10 or (op == 0x28 and plain) or (op == 0x6F and mandatory in (0x66, 0xF3)):  # loads
        writes, reads = "xreg", scalar if op == 0x10 else 16
    elif op == 0x11 or (op == 0x29 and plain):  # stores
        writes = "xrm"
    elif op in (0x14, 0x15, 0x54, 0x55, 0x56, 0x57, 0xC6) and plain:  # unpck, and, andn, or, xor, shuf
        writes, reads, immediate = "xreg", 16, 1 if op == 0xC6 else 0
    elif op == 0x2A and not plain:  # cvtsi2ss, cvtsi2sd
        writes, reads = "xreg", 8 if rex & 8 else 4
    elif op in (0x2C, 0x2D) and not plain:  # cvttss2si and the like
        writes, reads = "reg", scalar
    elif op in (0x2E, 0x2F) and plain:  # ucomiss, comiss and the like
        reads = 8 if mandatory == 0x66 else 4
    elif op in (0x51, 0x58, 0x59, 0x5A, 0x5C, 0x5D, 0x5E, 0x5F, 0xC2):
        # sqrt, add, mul, cvt between single and double, sub, min, div, max, cmp
        writes, reads, immediate = "xreg", scalar, 1 if op == 0xC2 else 0
    elif op == 0x6E and mandatory == 0x66:  # movd or movq into xmm
        writes, reads = "xreg", 8 if rex & 8 else 4
    elif op == 0x7E and mandatory == 0x66:  # movd or movq out of xmm
        writes = "rm"
    elif op == 0x7E and mandatory == 0xF3:  # movq into xmm
        writes, reads = "xreg", 8
    elif op == 0xEF and mandatory == 0x66:  # pxor
        writes, reads = "xreg", 16
    elif not plain:  # the rest are general-purpose instructions, which don't go with F2 or F3
        return f"instruction 0F {op:02X} after F2 or F3"
    elif op == 0x1F:  # nop with an operand, which it doesn't read
        pass
    elif 0x40 <= op <= 0x4F:  # cmov
        writes, reads = "reg", word
    elif 0x80 <= op <= 0x8F and not prefixes:  # conditional jump
        immediate, flow = 4, "branch"
    elif 0x90 <= op <= 0x9F:  # setcc
        writes, byte = "rm", True
    elif op == 0xAF:  # imul
        writes, reads = "reg", word
    elif op in (0xB6, 0xB7, 0xBE, 0xBF):  # movzx, movsx
        writes, reads = "reg", 1 if op in (0xB6, 0xBE) else 2
    else:
        return f"instruction 0F {op:02X}"
    if at + immediate > len(code):
        raise IndexError(at + immediate)
    value = int.from_bytes(code[at : at + immediate], "little", signed=True)
    at += immediate
    if writes in ("rm", "xrm") and operand.memory:
        return "a write to memory"
    if writes == "lea" and not operand.memory:
        return "instruction 8D"
    if writes in ("reg", "lea"):
        allowed = writable(operand.reg, byte, rex)
    elif writes == "rm":
        allowed = writable(operand.rm, byte, rex)
    elif writes == "op":
        allowed = writable((op & 7) | (rex & 1) << 3, byte, rex)
    elif writes in ("xreg", "xrm"):
        allowed = (operand.reg if writes == "xreg" else operand.rm) in WRITABLE_XMM
    else:
        allowed = True
    if not allowed:
        return "a write to a register the function must put back"
    read = None
    if reads and operand is not None and operand.memory:
        if operand.rip:
            read = ("value", at + operand.displacement, reads)
        elif operand.base != THIS_REGISTER or operand.index is not None:
            return "a read of memory other than the object's"
        elif not 0 <= operand.displacement <= object_size - reads:
            return "a read outside the object"
        else:
            read = ("field", operand.displacement, reads)
    return at, flow, at + value if flow in ("branch", "jump") else None, read


def read_leaf(code: bytes, object_size: int) -> Leaf | str:
    """``code`` read as a function called with the address of an object ``object_size`` bytes long in
    rcx: a Leaf if calling it can't change anything, or else why not, as "<what> at <offset>". Calling it
    can't change anything if, every way through, it runs only instructions this knows, reading nothing
    but the object and values at fixed places in the game, writing nothing but registers it may change
    (see WRITABLE_REGISTERS), and jumping only forward, to the start of one of its own instructions, to
    end in ret."""
    starts: set[int] = set()
    targets: set[int] = set()
    fields: list[tuple[int, int]] = []
    values: list[tuple[int, int, int]] = []
    at = 0
    while True:
        try:
            decoded = decode(code, at, object_size)
        except IndexError:
            return f"it doesn't end within the {len(code)} bytes read"
        if isinstance(decoded, str):
            return f"{decoded} at {at:#x}"
        end, flow, target, read = decoded
        if target is not None:
            if target < end:
                return f"a jump back at {at:#x}"
            targets.add(target)
        if read is not None:
            if read[0] == "value":
                values.append((at, *read[1:]))
            elif read[1:] not in fields:
                fields.append(read[1:])
        starts.add(at)
        at = end
        if flow in ("jump", "ret") and all(target < at for target in targets):
            break
    if not targets <= starts:
        return "a jump into the middle of an instruction"
    return Leaf(at, fields, values)


class StarCount:
    """cGcSolarSystem::GetStarCount, found in the game by STAR_COUNT_PATTERN: where it is, its first
    bytes, what it reads, and whether the mod may call it: only if read_leaf finds that calling it can't
    change anything, and the values it reads from fixed places in the game can be read."""

    def __init__(self, address: int, offset: int, code: bytes):
        self.address, self.offset, self.code = address, offset, code
        self.field = int.from_bytes(code[14:18], "little", signed=True)  # movss xmm2, [rcx + field]
        leaf = read_leaf(code, LAYOUT.system_size)
        self.leaf = leaf if isinstance(leaf, Leaf) else None
        self.why = None if self.leaf else leaf  # why the mod won't call it
        # (offset in the code of the instruction, of the value, the value's bytes or None) of each value
        # it reads from a fixed place in the game.
        if self.leaf:
            reads = self.leaf.values
        else:  # the pattern shows the first instruction reads one
            reads = [(0, 8 + int.from_bytes(code[4:8], "little", signed=True), 4)]
        self.values = [(at, where, read_memory(address + where, size)) for at, where, size in reads]
        if self.leaf and any(raw is None for _, _, raw in self.values):
            self.leaf, self.why = None, "a value it reads couldn't be read"
        fields = (self.leaf.fields if self.leaf else []) or [(self.field, 4)]
        low, high = min(field for field, _ in fields), max(field + size for field, size in fields)
        if high - low > STAR_WINDOW_MAX:
            low, high = self.field, self.field + 4
        start, end = max(0, low - STAR_FIELD_BEFORE), min(LAYOUT.system_size, high + STAR_FIELD_AFTER)
        self.window = (start, end - start) if end > start else None  # (offset, bytes) recorded with systems
        self.callable = self.leaf is not None
        self._function = None

    def info(self) -> dict:
        """What the session header says of the function."""
        found = {"offset": f"{self.offset:X}", "code": self.code.hex().upper(), "field": self.field}
        if self.leaf is not None:
            found["length"] = self.leaf.length
        found["values"] = [[at, where, raw.hex().upper() if raw else None] for at, where, raw in self.values]
        if self.window is not None:
            found["window"] = list(self.window)
        found["callable"] = int(self.callable)
        if self.why:
            found["why"] = self.why
        return found

    def count(self, system: int) -> int:
        """How many stars the game says the solar system at ``system`` has. Main thread only: this calls
        the game. Raises CaptureError instead if the mod won't call it, or can't read what it reads."""
        if not self.callable or self.leaf is None:
            raise CaptureError("the mod doesn't call the game's star count function")
        if any(read_memory(system + field, size) is None for field, size in self.leaf.fields):
            raise CaptureError("the solar system's values it reads couldn't be read")
        if self._function is None:
            self._function = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(self.address)
        return int(self._function(system))

    def window_bytes(self, system: int) -> str | None:
        """The solar system's bytes in ``window``, as hex."""
        if self.window is None:
            return None
        raw = read_memory(system + self.window[0], self.window[1])
        return None if raw is None else raw.hex().upper()


def locate_star_count() -> StarCount | str | None:
    """The game's GetStarCount, or why it couldn't be found; None if RECORD_STARS is off or the mod
    isn't running inside the game."""
    base = getattr(pymhf_internal, "BASE_ADDRESS", -1)
    if not RECORD_STARS or not isinstance(base, int) or base <= 0:
        return None
    from pymhf.core.memutils import find_pattern_in_binary

    offset = find_pattern_in_binary(STAR_COUNT_PATTERN, False)
    if offset is None:
        return "its pattern isn't in this version of the game"
    code = read_memory(base + offset, STAR_CODE_BYTES)
    if code is None:
        return "its code couldn't be read"
    return StarCount(base + offset, offset, code)


def query_metadata(generation_data: int) -> dict:
    """What GenerateQueryInfo wrote into its cGcSolarSystemData."""
    pointer = read_u64(generation_data + LAYOUT.metadata) if generation_data else None
    raw = read_memory(pointer, LAYOUT.data_size) if pointer else None
    if raw is None:
        raise CaptureError("the query's system data couldn't be read")
    data = nmse.cGcSolarSystemData.from_buffer_copy(raw)
    problems: list[str] = []
    record = _attempt(problems, "system", system_fields, data) or {}
    ships = _attempt(problems, "ships", ship_rows, data)
    if ships:
        record["ships"] = ships
    if problems:
        record["errors"] = problems
    return record


def fingerprint(address: int) -> tuple | None:
    """Cheap identity of the current system, for deciding when to take a full snapshot."""
    parts = (
        read_memory(address + LAYOUT.ua, 8),
        read_memory(address + LAYOUT.seed, 8),
        read_memory(address + LAYOUT.ships, 12),
    )
    if any(part is None for part in parts) or parts[0] == bytes(8):
        return None
    return (address, *parts)


def active_system() -> tuple[int, int | None] | None:
    """(address of the loaded solar system, simulation's current UA), or None."""
    try:
        simulation = gameData.simulation
    except (ValueError, AttributeError):  # NULL pointers while the game starts or quits
        return None
    if simulation is None:
        return None
    base = ctypes.addressof(simulation)
    address = read_u64(base + LAYOUT.simulation_system)
    if not address:
        return None
    return address, read_u64(base + LAYOUT.simulation_ua)


def player_location() -> list[int] | None:
    try:
        state = gameData.player_state
    except (ValueError, AttributeError):
        return None
    if state is None:
        return None
    raw = read_memory(ctypes.addressof(state) + LAYOUT.location, LAYOUT.location_size)
    if raw is None:
        return None
    location = nmse.cGcUniverseAddressData.from_buffer_copy(raw)
    address = location.GalacticAddress
    return [
        as_int(location.RealityIndex),
        as_int(address.VoxelX),
        as_int(address.VoxelY),
        as_int(address.VoxelZ),
        as_int(address.SolarSystemIndex),
        as_int(address.PlanetIndex),
    ]


def player_environment() -> tuple[int | None, int | None]:
    """(where the player is, as an EnvironmentLocation value; the index of the nearest planet),
    each None if it can't be read."""
    try:
        simulation = gameData.simulation
    except (ValueError, AttributeError):
        return None, None
    if simulation is None:
        return None, None
    base = ctypes.addressof(simulation)
    where = read_memory(base + LAYOUT.player_where, 4)
    planet = read_memory(base + LAYOUT.player_planet, 4)
    return (
        None if where is None else int.from_bytes(where, "little"),
        None if planet is None else int.from_bytes(planet, "little", signed=True),
    )


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _guarded(read, *args):
    try:
        return read(*args)
    except Exception as exc:  # diagnostics must never stop a record being written
        return f"error: {exc}"


def session_header(mod: Mod | None = None) -> dict:
    return {
        "t": "session",
        "format": FORMAT_VERSION,
        "mod": MOD_VERSION,
        "at": int(time.time()),
        "exe": str(getattr(pymhf_internal, "BINARY_HASH", "") or "") or None,
        "steamBuild": _guarded(steam_build, getattr(pymhf_internal, "BINARY_PATH", None)),
        "hooks": _guarded(hook_status, mod) if mod is not None else None,
        # The game's star count function, or why it wasn't found (see StarCount).
        "starCount": getattr(mod, "_star_info", None),
        "nmspy": package_version("nmspy"),
        "pymhf": package_version("pymhf"),
        "python": platform.python_version(),
        "columns": {
            "ships": SHIP_COLUMNS,
            "bodies": BODY_COLUMNS,
            "bodyFlags": BODY_FLAGS,
            "traders": TRADER_COLUMNS,
            "voxel": VOXEL_COLUMNS,
            "loc": LOCATION_COLUMNS,
            "storeEntries": STORE_ENTRY_COLUMNS,
            "specialSlots": SPECIAL_SLOT_COLUMNS,
        },
        "enums": ENUM_TABLES,
    }


def dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), allow_nan=False)


def describe(record: dict) -> str:
    """One log line: name, address and ship pool."""
    # While a system is being generated its address isn't set yet, but its
    # seed is the same universal address.
    ua = int(record["ua"], 16) or int(record.get("seed", "0"), 16)
    where = f"{portal_code(ua)}, galaxy {galaxy_of(ua)}"
    name = record.get("displayName") or record.get("name") or "Unnamed system"
    ships = record.get("ships")
    if ships is None:
        pool = "ship list unreadable"
    else:
        counts = Counter(row[2] for row in ships)
        pool = f"{len(ships)} ships"
        if counts:
            pool += " (" + ", ".join(f"{ship_label(c)} {n}" for c, n in counts.most_common()) + ")"
    stars = record.get("stars")
    if isinstance(stars, int) and stars != 1:
        pool += f"; {stars} stars"
    return f"{name} ({where}): {pool}"


def tone(notes: list[tuple[float, float]], volume: float = SOUND_VOLUME, rate: int = 22050) -> bytes:
    """A WAV file (mono, 16-bit) playing ``notes``, as bytes."""
    volume = min(max(volume, 0.0), 1.0)
    samples = array.array("h")
    for frequency, seconds in notes:
        count = round(rate * seconds)
        fade = max(1, min(count // 2, round(rate * 0.006)))  # 6 ms each end, so notes don't click
        for i in range(count):
            if frequency <= 0:
                samples.append(0)
                continue
            phase = 2 * math.pi * frequency * i / rate
            # Some second harmonic makes a note easier to hear on small speakers.
            level = 0.8 * math.sin(phase) + 0.2 * math.sin(2 * phase)
            envelope = min(1.0, i / fade, (count - 1 - i) / fade)
            samples.append(round(32767 * volume * envelope * level))
    if sys.byteorder == "big":  # WAV samples are little-endian
        samples.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


_sound_cache: dict[str, bytes] = {}
_sound_lock = threading.Lock()
_sound_failed: set[str] = set()


def prepare_sounds() -> None:
    """Build the sounds once, at startup, rather than while you play."""
    if PLAY_SOUNDS:
        for name, notes in SOUNDS.items():
            if name not in _sound_cache:
                _sound_cache[name] = tone(notes)


def play_sound(name: str) -> threading.Thread | None:
    """Play one of SOUNDS on a thread of its own, so the game doesn't wait for
    it. Does nothing where sound isn't available."""
    if not PLAY_SOUNDS or name not in SOUNDS:
        return None
    try:
        import winsound
    except ImportError:
        if sys.platform == "win32" and "winsound" not in _sound_failed:  # only expected off Windows
            _sound_failed.add("winsound")
            logger.warning("No sounds: Python's winsound module couldn't be loaded.", exc_info=True)
        return None

    def run() -> None:
        try:
            data = _sound_cache.get(name)
            if data is None:
                data = _sound_cache[name] = tone(SOUNDS[name])
            with _sound_lock:  # one at a time, so none cuts another off
                # Sounds from memory can't be asynchronous; this thread waits instead.
                winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception:
            if name not in _sound_failed:  # once per sound, not every time
                _sound_failed.add(name)
                logger.warning("Couldn't play the %r sound.", name, exc_info=True)

    thread = threading.Thread(target=run, name="TradeDepotSound", daemon=True)
    thread.start()
    return thread


class TradeDepotCapture(Mod):
    __author__ = "One Million Years Trade Depot contributors"
    __description__ = (
        "Records each star system you visit, the ships the game prepares for it "
        "and the parts it picks for them, and the items the game offers, such as multi-tools."
    )
    __version__ = MOD_VERSION
    __pymhf_required_version__ = "0.2.4"

    # Class-level defaults: pyMHF reads the GUI properties while the mod is
    # still being set up.
    _status = "Waiting for a star system to load."
    _last = "None yet."
    _count = 0
    _query_count = 0
    _name_count = 0
    _model_count = 0
    _ship_models_seen = 0
    _tool_count = 0
    _pool_count = 0
    _offer_count = 0
    _item_count = 0

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        # Writing the capture file has a lock of its own, so no hook waits for the disk.
        self._write_lock = threading.Lock()
        self._recorded_keys: set[str] = set()
        self._session_started = False
        self._reported: set[str] = set()
        self._record_requested = False
        self._next_poll = 0.0
        self._last_seen: tuple | None = None
        self._last_polled: tuple | None = None
        # Random-number states at each generation step, keyed by generator address.
        self._traces: dict[int, list] = {}
        # Key attributes each generation started from, keyed by generator address.
        self._keys: dict[int, dict] = {}
        # GenerateQueryInfo calls outside a full generation, keyed by generator address.
        self._queries: dict[int, dict] = {}
        self._query_seeds: set[str] = set()
        self._name_seeds: set[tuple[str, int]] = set()
        self._pending: list[dict] = []
        self._next_flush = 0.0
        # Systems (universal address without the planet digit) whose arrival tone has played.
        self._chimed: set[int] = set()
        # When the main loop first ran, whether the mod has said it can't see the game yet,
        # and whether it has found it.
        self._first_frame: float | None = None
        self._waiting_for_game = False
        self._game_found = False
        # Ship models. The ship seeds of the last few systems read, newest last, as
        # system -> {seed: (slot, ship class)}; models built before their system was read;
        # models written; distinct ship models seen; other models the log has mentioned;
        # exotics whose tone has played.
        self._ship_systems: dict[int, dict[str, tuple[int | str, int | None]]] = {}
        self._waiting_models: dict[tuple, dict] = {}
        self._model_keys: set[tuple] = set()
        self._seen_models: set[tuple] = set()
        self._other_models: set[str] = set()
        self._exotics_heard: set[str] = set()
        self._raw_descriptors = 0
        # Items and their models. Models built lately with a descriptor, in memory only, as
        # seed -> [model] and resource handle -> model (None once the game has handed the
        # handle to something else); models being built, by (thread, address of the handle the
        # game fills in); "built" lines written, and the files they named; multi-tool files the
        # log has named.
        self._recent_models: dict[int, list[dict]] = {}
        self._handle_models: dict[int, dict | None] = {}
        self._building: dict[tuple[int, int], dict] = {}
        self._tool_builds = 0
        self._built_names: set[str] = set()
        self._tool_model_names: set[str] = set()
        # Systems' own multi-tools: what each thread generating a system has built so far, by
        # thread; sets written, by (system, their files and seeds); the systems they're of.
        self._generating: dict[int, dict] = {}
        self._pool_keys: set[tuple] = set()
        self._pool_systems: set[int] = set()
        # What the mod knows of each item the game offers, by address (see _item_updated);
        # items written, by (system, what they held); item types the log has mentioned;
        # multi-tools recorded, by seed; offers of one recorded, by (system, seed).
        self._items: dict[int, dict] = {}
        self._item_keys: set[tuple] = set()
        self._item_types_logged: set[int] = set()
        self._tools_heard: set[str] = set()
        self._offers_heard: set[tuple] = set()
        # Resources the game has loaded, and how many came with a descriptor, for the log.
        self._resources = 0
        self._described = 0
        self._resources_logged = 0
        self._next_resource_count = time.monotonic() + FIRST_RESOURCE_COUNT_SECONDS
        try:
            prepare_sounds()
        except Exception:
            logger.warning("Couldn't prepare the sounds.", exc_info=True)
        logger.info("Trade Depot capture %s is recording to %s", MOD_VERSION, CAPTURE_FILE)
        if RECORD_MULTITOOLS and RECORD_SHIP_PARTS:
            logger.info(
                "A system's multi-tools are recorded as you arrive. To record the one on offer, with its "
                "class and slots, go up to the space station's multi-tool case or a settlement's "
                "multi-tool rack and look at what's for sale."
            )
        # The game's star count function (see StarCount), and what the session header says of it.
        self._stars: StarCount | None = None
        self._star_info: dict | str | None = None
        self._guild_requested: str | None = None
        try:
            found = locate_star_count()
        except Exception:
            found = None
            self._report_once("stars-find", "Couldn't look for the game's star count function.")
        if isinstance(found, StarCount):
            self._stars, self._star_info = found, found.info()
            if found.callable:
                logger.info("Found the game's star count function: each system's stars are recorded.")
            else:
                logger.info(
                    "Found the game's star count function, but the mod won't call it (%s), so it records "
                    "only the bytes of each system the function reads.",
                    found.why,
                )
        elif found is not None:
            self._star_info = found
            logger.info("Couldn't find the game's star count function (%s): stars aren't recorded.", found)

    # --- GUI (read on the GUI thread, so these only return cached values) ---

    @property
    @STRING("Status")
    def status(self):
        return self._status

    @property
    @STRING("Systems recorded this session")
    def recorded(self):
        return str(self._count)

    @property
    @STRING("Lookups recorded (systems described, not visited)")
    def lookups(self):
        return str(self._query_count)

    @property
    @STRING("Planet and region names recorded")
    def names(self):
        return str(self._name_count)

    @property
    @STRING("Ship parts recorded")
    def ship_parts(self):
        if not RECORD_SHIP_PARTS:
            return "Off (RECORD_SHIP_PARTS is False)"
        return f"{self._model_count} of {self._ship_models_seen} ship models seen"

    @property
    @STRING("Multi-tools recorded")
    def multitools(self):
        if not RECORD_MULTITOOLS:
            return "Off (RECORD_MULTITOOLS is False)"
        if not RECORD_SHIP_PARTS:
            return "Off: needs RECORD_SHIP_PARTS too"
        return (
            f"{self._tool_count} in {self._pool_count} systems' sets; {self._offer_count} on offer "
            f"(items recorded: {self._item_count})"
        )

    @property
    @STRING("Last system")
    def last_system(self):
        return self._last

    @property
    @STRING("Capture file")
    def capture_file(self):
        return str(CAPTURE_FILE)

    @gui_button("Record the current system now")
    def record_now(self):
        # The game thread does the reading, on its next frame.
        self._record_requested = True
        self._status = "Recording the current system..."

    # The guild envoy on a space station's upper level says which guild a region's stations have. The game
    # decides it where the mod can't read it yet, so you say which, and the mod records it with the system.
    @gui_button("Guild envoy here: Merchants")
    def guild_merchants(self):
        self._request_guild("Merchants")

    @gui_button("Guild envoy here: Explorers")
    def guild_explorers(self):
        self._request_guild("Explorers")

    @gui_button("Guild envoy here: Mercenaries")
    def guild_mercenaries(self):
        self._request_guild("Mercenaries")

    @gui_button("Open the captures folder")
    def open_folder(self):
        try:
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(CAPTURE_DIR))  # Windows only
        except Exception:
            logger.warning("Couldn't open %s", CAPTURE_DIR, exc_info=True)

    # --- Game hooks ---
    # pyMHF treats a value returned by a "before" detour as replacement
    # arguments, and one returned by an "after" detour as the function's
    # result, so every detour here deliberately returns nothing.

    @nms.cGcSolarSystem.Generate.before
    def before_generate(self, this, lbUseSettingsFile, lSeed):
        if RECORD_SHIP_PARTS and RECORD_MULTITOOLS:
            # The multi-tools this thread builds from now until Generate returns are the system's; those
            # other threads build meanwhile are only counted.
            self._generating[threading.get_ident()] = {"tools": [], "since": time.monotonic(), "elsewhere": 0}
        try:
            generator = address_of(this) + LAYOUT.generator
            self._traces[generator] = [["generate>", rng_state(generator)]]
        except Exception:
            self._report_once("trace", "Couldn't trace a system's generation.")

    @nms.cGcSolarSystem.Generate.after
    def after_generate(self, this, lbUseSettingsFile, lSeed):
        pool = self._generating.pop(threading.get_ident(), None)
        try:
            self._record_generated(this, lbUseSettingsFile, lSeed)
        except Exception:
            self._report_once("generate", "Couldn't record a newly generated system.")
        if pool is not None:
            try:
                self._record_pool(this, lSeed, pool)
            except Exception:
                self._report_once("pool", "Couldn't record a system's multi-tools.")

    @nms.cGcSolarSystemGenerator.GenerateBasics.before
    def before_basics(self, this, lSeed, lAttributes, lStarKeyAttributes, lData):
        self._trace(this, "basics>")

    @nms.cGcSolarSystemGenerator.GenerateBasics.after
    def after_basics(self, this, lSeed, lAttributes, lStarKeyAttributes, lData):
        self._trace(this, "basics<")
        try:
            generator = address_of(this)
            if generator in self._traces:
                self._keys[generator] = key_attributes(address_of(lStarKeyAttributes))
            elif (query := self._queries.get(generator)) is not None:
                query["keyAttributes"] = key_attributes(address_of(lStarKeyAttributes))
        except Exception:
            self._report_once("keys", "Couldn't read a system's key attributes.")

    @nms.cGcSolarSystemGenerator.GeneratePlanetPositions.before
    def before_positions(self, this, lAttributes, lData, lpGeometry):
        self._trace(this, "positions>")

    @nms.cGcSolarSystemGenerator.GeneratePlanetPositions.after
    def after_positions(self, this, lAttributes, lData, lpGeometry):
        self._trace(this, "positions<")

    @nms.cGcSolarSystemGenerator.GeneratePlanetBiomes.before
    def before_biomes(self, this, lAttributes, lData, lStarKeyAttributes):
        self._trace(this, "biomes>")

    @nms.cGcSolarSystemGenerator.GeneratePlanetBiomes.after
    def after_biomes(self, this, lAttributes, lData, lStarKeyAttributes):
        self._trace(this, "biomes<")

    @nms.cGcSolarSystemGenerator.GenerateQueryInfo.before
    def before_query(self, this, lSeed, lAttributes, lData):
        try:
            self._query_started(this, lSeed)
        except Exception:
            self._report_once("query", "Couldn't record a system lookup.")

    @nms.cGcSolarSystemGenerator.GenerateQueryInfo.after
    def after_query(self, this, lSeed, lAttributes, lData):
        try:
            self._query_finished(this, lData)
        except Exception:
            self._report_once("query", "Couldn't record a system lookup.")

    @nms.cGcNameGenerator.GeneratePlanetName.after
    def after_planet_name(self, this, lu64Seed, lResult, lLocResult):
        self._named("planet", lu64Seed, lResult, lLocResult)

    @nms.cGcNameGenerator.GenerateGalacticRegionName.after
    def after_region_name(self, this, lu64Seed, lResult, lLocResult):
        self._named("region", lu64Seed, lResult, lLocResult)

    if RECORD_SHIP_PARTS:  # otherwise the mod leaves this function alone
        # Engine::AddResource(type, name, flags, descriptor) loads a resource for the game.
        # NMS.py 180383 lists the resource manager's own AddResource among the functions whose
        # pattern no longer finds them; this one's still does. NMS.py calls the descriptor
        # lAlternateMaterialId, and declares one argument more than the function's mangled name
        # shows; that one goes on the stack, where the function never reads it.
        @nms.Engine.AddResource.before
        def before_add_resource(self, result, liType, lpcName, liFlags, lAlternateMaterialId, unknown):
            # Read before the game uses the descriptor, in case it moves the part list out.
            try:
                self._model_requested(liType, lpcName, lAlternateMaterialId, result)
            except Exception:
                self._report_once("model", "Couldn't record a ship's parts.")

    if RECORD_SHIP_PARTS and RECORD_MULTITOOLS:  # otherwise the mod leaves these functions alone
        # Once AddResource returns, the handle it filled in names the model it built; an item
        # the game offers holds the handle of its model.
        @nms.Engine.AddResource.after
        def after_add_resource(self, result, liType, lpcName, liFlags, lAlternateMaterialId, unknown):
            try:
                self._model_added(result)
            except Exception:
                self._report_once("model-handle", "Couldn't note which model a resource handle is.")

        # cGcPurchaseableItem::Update(float) runs each frame for each item the game offers: a
        # multi-tool on a rack or at a merchant, a gift or a reward. NMS.py declares two arguments
        # more than the function's mangled name shows; they go in registers it never reads.
        @nms.cGcPurchaseableItem.Update.before
        def before_item_update(self, this, lfTimeStep, a3, a4):
            try:
                self._item_updated(this)
            except Exception:
                self._report_once("item", "Couldn't record an item the game offers.")

    @main_loop.after
    def on_frame(self):
        try:
            self._watch_for_game(time.monotonic())
            self._record_guild()
            self._flush_pending()
            self._poll()
            self._count_resources(time.monotonic())
        except Exception:
            self._status = "Couldn't read the current system. See the log."
            self._report_once("poll", "Couldn't read the current system.")

    # --- Internals ---

    def _watch_for_game(self, now: float) -> bool:
        """Whether NMS.py has found the game's application object, which the mod reads the game through.

        The mod never sets that pointer itself. Version 0.5.1 took it from the
        argument of the game's main loop function, and the game crashed; NMS.py
        takes it from the game's state machine instead.
        """
        if gameData.GcApplication is not None:
            if not self._game_found:
                self._game_found = True
                logger.info("Found the game. Recording from now on.")
            if self._waiting_for_game:
                self._waiting_for_game = False
                self._status = "Waiting for a star system to load."
            return True
        if self._first_frame is None:
            self._first_frame = now
        elif not self._waiting_for_game and now - self._first_frame >= FIND_GAME_NOTICE_SECONDS:
            self._waiting_for_game = True
            logger.info(NOT_FOUND_YET)
            self._status = NOT_FOUND_YET
        return False

    def _trace(self, generator_pointer, label: str) -> None:
        """Note the RNG at a generation step, in the system being generated or looked up."""
        try:
            generator = address_of(generator_pointer)
            trace = self._traces.get(generator)
            if trace is None and (query := self._queries.get(generator)) is not None:
                trace = query["trace"]
            if trace is not None and len(trace) < 64:
                trace.append([label, rng_state(generator)])
        except Exception:
            self._report_once("trace", "Couldn't trace a system's generation.")

    def _query_started(self, generator_pointer, seed_pointer) -> None:
        generator = address_of(generator_pointer)
        if generator in self._traces:  # part of generating the system being loaded
            self._trace(generator_pointer, "query>")
            return
        raw_seed = read_memory(address_of(seed_pointer), ctypes.sizeof(basic.GcSeed))
        if raw_seed is None:
            return
        self._queries[generator] = {
            "seed": hex64(basic.GcSeed.from_buffer_copy(raw_seed).Seed),
            "trace": [["query>", rng_state(generator)]],
        }

    def _query_finished(self, generator_pointer, data_pointer) -> None:
        generator = address_of(generator_pointer)
        if generator in self._traces:
            self._trace(generator_pointer, "query<")
            return
        query = self._queries.pop(generator, None)
        if query is None:
            return
        with self._lock:
            if query["seed"] in self._query_seeds or len(self._query_seeds) >= MAX_QUERY_RECORDS:
                return
            self._query_seeds.add(query["seed"])
        query["trace"].append(["query<", rng_state(generator)])
        entry = {"t": "query", "at": int(time.time()), "seed": query["seed"], "trace": query["trace"]}
        if "keyAttributes" in query:
            entry["keyAttributes"] = query["keyAttributes"]
        try:
            entry.update(query_metadata(address_of(data_pointer)))
        except CaptureError as exc:
            entry["errors"] = [str(exc)]
        with self._lock:
            self._pending.append(entry)

    def _named(self, kind: str, seed: int, result_pointer, local_pointer) -> None:
        """A name the game just generated, with the seed it generated it from."""
        try:
            seed = as_int(seed) & MASK64
            with self._lock:
                if (kind, seed) in self._name_seeds or len(self._name_seeds) >= MAX_NAME_RECORDS:
                    return
                self._name_seeds.add((kind, seed))
            name = read_text(address_of(result_pointer), NAME_LENGTH)
            if not name:
                return
            entry = {"t": "name", "kind": kind, "at": int(time.time()), "seed": hex64(seed), "name": name}
            local = read_text(address_of(local_pointer), NAME_LENGTH)
            if local and local != name:
                entry["local"] = local
            active = active_system()
            if active is not None and (ua := read_u64(active[0] + LAYOUT.ua)):
                entry["system"] = hex64(ua)  # the loaded system when the name was made
            with self._lock:
                self._pending.append(entry)
        except Exception:
            self._report_once("name-hook", "Couldn't record a planet or region name.")

    def _model_requested(self, type_value, name_pointer, descriptor_pointer, result_pointer=None) -> None:
        """The game is about to build a model: note its parts if it's a ship from a system's ship list,
        and keep it in memory for a while, for an item the game offers to be paired with."""
        self._resources += 1  # counts for the log; a miss when threads race doesn't matter
        address = address_of(descriptor_pointer)
        if not address:
            return
        descriptor = resource_descriptor(address, keep_raw=self._raw_descriptors < RAW_DESCRIPTORS)
        if descriptor is None:
            return
        self._described += 1
        name = read_c_string(address_of(name_pointer), MODEL_NAME_LENGTH)
        if not name:
            return
        resource_type = as_int(type_value)
        if RECORD_MULTITOOLS:
            entry = self._model_built(name, resource_type, descriptor, address_of(result_pointer))
            if is_multitool_model(name):
                self._join_pool(entry)
        if is_multitool_model(name):
            self._multitool_model_built(name, len(descriptor["parts"]))
            return
        if not is_ship_model(name):
            if descriptor["parts"]:
                self._other_model(
                    name, f"not a ship, so its parts aren't recorded ({len(descriptor['parts'])} parts)"
                )
            return
        if not descriptor["parts"] and "errors" not in descriptor:
            self._other_model(
                name, f"a ship's, but without parts, so not recorded (resource type {resource_type})"
            )
            return
        entry = {"name": name, "type": resource_type, **descriptor}
        key = (name, descriptor["seed"], descriptor.get("seed2"), tuple(descriptor["parts"]))
        with self._lock:
            if key in self._model_keys:
                return
            if key not in self._seen_models and len(self._seen_models) < 2 * MAX_MODEL_RECORDS:
                self._seen_models.add(key)
                self._ship_models_seen += 1
            place = self._ship_place(descriptor["seed"])
            if place is not None:
                self._write_model(key, entry, place)
                return
            # Not (yet) known as a ship of this system: wait for its ship list.
            self._waiting_models.pop(key, None)
            self._waiting_models[key] = dict(entry, at=int(time.time()))
            while len(self._waiting_models) > WAITING_MODELS:
                del self._waiting_models[next(iter(self._waiting_models))]

    def _ship_place(self, seed: str) -> tuple[int, int | str, int | None] | None:
        """(system, slot, ship class) of a ship seed in the systems read lately. The caller holds the lock."""
        for system, slots in reversed(self._ship_systems.items()):
            if (place := slots.get(seed)) is not None:
                return (system, *place)
        return None

    def _write_model(self, key: tuple, entry: dict, place: tuple[int, int | str, int | None]) -> None:
        """Queue a ship's model for the capture file. The caller holds the lock."""
        if key in self._model_keys or len(self._model_keys) >= MAX_MODEL_RECORDS:
            return
        self._model_keys.add(key)
        system, slot, ship_class = place
        record = {
            "t": "model",
            "at": entry.get("at", int(time.time())),
            "system": hex64(system),
            "slot": slot,
        }
        record.update((k, v) for k, v in entry.items() if k != "at")
        if "raw" in record and "errors" not in record:
            self._raw_descriptors += 1
        self._pending.append(record)
        parts = ", ".join(record["parts"]) or "no parts"
        if len(self._model_keys) == 1:
            logger.info(
                "Recording ship parts. The first: %s, seed %s: %s", record["name"], record["seed"], parts
            )
        classes = ENUM_TABLES.get("shipClass", [])
        if ship_class is not None and 0 <= ship_class < len(classes) and classes[ship_class] == "Royal":
            logger.info("Recorded the parts of the exotic (seed %s): %s", record["seed"], parts)
            self._status = "Recorded the parts of this system's exotic."
            if record["seed"] not in self._exotics_heard:  # one tone per exotic, however many models
                self._exotics_heard.add(record["seed"])
                play_sound("exotic parts")

    def _remember_ships(self, record: dict) -> None:
        """Note a system's ship seeds, so the parts of its ships can be recorded when the game builds them."""
        ships = record.get("ships")
        if not ships or not RECORD_SHIP_PARTS:
            return
        system = (int(record["ua"], 16) or int(record.get("seed") or "0", 16)) & ~PLANET_BITS
        slots: dict[str, tuple[int | str, int | None]] = {}
        for slot, row in enumerate(ships):
            if row[0] != ZERO_SEED:
                slots.setdefault(row[0], (slot, row[2]))
        if (crash := record.get("crashShip")) and crash != ZERO_SEED:
            slots.setdefault(crash, ("crash", None))
        with self._lock:
            self._ship_systems.pop(system, None)
            self._ship_systems[system] = slots
            while len(self._ship_systems) > 8:
                del self._ship_systems[next(iter(self._ship_systems))]
            for key in [k for k, waiting in self._waiting_models.items() if waiting["seed"] in slots]:
                entry = self._waiting_models.pop(key)
                self._write_model(key, entry, (system, *slots[entry["seed"]]))

    def _count_resources(self, now: float) -> None:
        """Every few minutes, while it changes, say in the log how many resources the game has
        loaded through the function the mod watches for ship parts."""
        if (
            not RECORD_SHIP_PARTS
            or now < self._next_resource_count
            or self._resources == self._resources_logged
        ):
            return
        self._next_resource_count = now + RESOURCE_COUNT_SECONDS
        self._resources_logged = self._resources
        logger.info(
            "Resources the game has loaded so far: %d, %d of them with a descriptor; ship models: %d seen, "
            "%d recorded.",
            self._resources,
            self._described,
            self._ship_models_seen,
            self._model_count,
        )

    def _other_model(self, name: str, why: str) -> None:
        """Name in the log the first few models the game builds from a descriptor that aren't
        recorded, to show what the game builds that way."""
        with self._lock:
            if name in self._other_models or len(self._other_models) >= OTHER_MODELS_LOGGED:
                return
            self._other_models.add(name)
        logger.info("Model %s: %s.", name, why)

    def _multitool_model_built(self, name: str, parts: int) -> None:
        """Name in the log the first few multi-tool model files the game builds."""
        with self._lock:
            if name in self._tool_model_names or len(self._tool_model_names) >= MULTITOOL_NAMES_LOGGED:
                return
            self._tool_model_names.add(name)
        logger.info(
            "Model %s: a multi-tool's (%d parts); its seed and parts are recorded with the system's set if "
            "the game built it for the system, or with an item the game offers that holds it.",
            name,
            parts,
        )

    def _model_built(self, name: str, resource_type: int, descriptor: dict, result: int) -> dict:
        """Keep a model the game builds from a descriptor in memory for a while, by its seed and, once
        AddResource returns, by the resource handle it filled in at ``result``, in case an item the game
        offers holds either. Returns what's kept."""
        entry = {"name": name, "type": resource_type}
        entry.update((k, v) for k, v in descriptor.items() if k != "raw" or "errors" in descriptor)
        seed = int(descriptor["seed"], 16)
        with self._lock:
            if seed >= 1 << 32:  # a smaller one is too easily mistaken for other numbers in an item
                models = self._recent_models.pop(seed, [])
                if not any(m["name"] == name and m["parts"] == entry["parts"] for m in models):
                    models.append(entry)
                self._recent_models[seed] = models[-4:]
                while len(self._recent_models) > MODELS_KEPT:
                    del self._recent_models[next(iter(self._recent_models))]
            if result:
                self._building[(threading.get_ident(), result)] = entry
                while len(self._building) > 256:  # in case AddResource ever returns without the after hook
                    del self._building[next(iter(self._building))]
        return entry

    def _join_pool(self, entry: dict) -> bool:
        """Add a multi-tool model to the set of the system this thread is generating, if it's generating
        one; if another thread is, count it there. Only this thread adds to its set, so no lock is needed;
        a count another thread misses now and then doesn't matter."""
        pool = self._generating.get(threading.get_ident())
        if pool is None:
            for other in list(self._generating.values()):
                other["elsewhere"] += 1
            return False
        if time.monotonic() - pool["since"] > POOL_SECONDS:
            return False
        key = model_key(entry)
        for place, tool in enumerate(pool["tools"]):
            if model_key(tool) == key:  # built again: the same one
                entry["pool"] = place
                return True
        if len(pool["tools"]) >= POOL_TOOLS:
            return False
        entry["pool"] = len(pool["tools"])  # its place in the set, which items holding it then show
        pool["tools"].append(entry)
        return True

    def _model_added(self, result_pointer) -> None:
        """AddResource has returned. For a model built from a descriptor, note the resource handle it
        filled in, and add a "built" line for a multi-tool model outside a system's set, or for another
        model file with parts the first time: when, which file and how many parts, but not its seed or
        parts. For anything else, see whether the game has handed it a handle the mod has a model for."""
        if not self._building and not self._handle_models:  # nothing to do
            return
        result = address_of(result_pointer)
        key = (threading.get_ident(), result)
        entry = None
        if key in self._building:  # asked without the lock, which this call then needn't wait for
            with self._lock:
                entry = self._building.pop(key, None)
        if entry is None:
            self._handle_reused(result)
            return
        raw = read_memory(result, 4)
        handle = int.from_bytes(raw, "little") if raw is not None else 0
        name = entry["name"]
        in_pool = "pool" in entry  # see _join_pool
        with self._lock:
            if handle not in NO_HANDLE:
                entry["handle"] = handle  # before an item can pair with it: records copy what they hold
                self._handle_models.pop(handle, None)
                self._handle_models[handle] = entry
                while len(self._handle_models) > MODELS_KEPT:
                    del self._handle_models[next(iter(self._handle_models))]
            if in_pool:
                return  # written with the system's set
            if is_multitool_model(name):
                if self._tool_builds >= TOOL_BUILDS_RECORDED:
                    return
                self._tool_builds += 1
            elif is_ship_model(name) or not entry["parts"] or name in self._built_names:
                return
            elif len(self._built_names) >= OTHER_BUILDS_RECORDED:
                return
            else:
                self._built_names.add(name)
            self._pending.append(
                {
                    "t": "built",
                    "at": int(time.time()),
                    "name": name,
                    "type": entry["type"],
                    "parts": len(entry["parts"]),
                    "handle": handle,
                }
            )

    def _handle_reused(self, result: int) -> None:
        """The game has loaded something without a descriptor: if it handed that the handle of a model
        the mod knows, the handle no longer names the model, so no item holding it is paired with that
        model, which may be another player's."""
        if not result:
            return
        raw = read_memory(result, 4)
        handle = int.from_bytes(raw, "little") if raw is not None else 0
        if self._handle_models.get(handle) is None:  # asked without the lock, as above
            return
        with self._lock:
            if self._handle_models.get(handle) is not None:
                self._handle_models[handle] = None

    def _pairable(self, model: dict) -> bool:
        """Whether a model may be written with an item that holds it: anything but a ship outside the
        ship lists read lately, such as yours or another player's. The caller holds the lock."""
        return not is_ship_model(model["name"]) or self._ship_place(model["seed"]) is not None

    def _item_updated(self, item_pointer, now: float | None = None) -> None:
        """Look at an item the game offers, twice a second, and record it once what it holds looks the
        same two looks in a row, and again whenever that changes: its kind and flags, its inventories,
        and the models whose resource handle or seed it holds, with the text in it."""
        now = time.monotonic() if now is None else now
        address = address_of(item_pointer)
        if not address:
            return
        with self._lock:
            watch = self._items.get(address)
            if watch is not None and now < watch["due"]:
                return
            if len(self._item_keys) >= MAX_ITEM_RECORDS:
                self._report_once(
                    "items-full", "Recorded %d items this session; no more until the next.", MAX_ITEM_RECORDS,
                    with_traceback=False,
                )  # fmt: skip
                return
            if watch is None:
                # crc and decoded: (the item's bytes, the system) when last decoded, and when;
                # candidate: what it held then, and unsettled: how many looks in a row that has
                # changed; paired and settled: (handle, offer, model) of the last look, and of the
                # last time it settled with a model; recorded: (system, what it held) last written;
                # system, offers and records: how often it was written in that system, for each
                # offer and in all.
                watch = dict.fromkeys(
                    ("crc", "decoded", "candidate", "paired", "settled", "recorded", "system")
                )
                watch.update(unsettled=0, offers={}, records=0)
            else:
                del self._items[address]  # to the end: the items looked at longest ago go first
            self._items[address] = watch
            while len(self._items) > ITEMS_TRACKED:
                del self._items[next(iter(self._items))]
            watch["due"] = now + ITEM_CHECK_SECONDS
        raw = read_memory(address, LAYOUT.item_size)
        if raw is None:
            return
        active = active_system()
        system = read_u64(active[0] + LAYOUT.ua) if active is not None else None
        crc = (zlib.crc32(raw), system)
        if crc == watch["crc"] and not watch["unsettled"] and now - watch["decoded"] < ITEM_REFRESH_SECONDS:
            return  # the same bytes in the same system, settled, and decoded lately
        offer = offered_item(raw)
        pattern = self._without_player_name(offer)
        hits = seeds_in(raw, self._recent_models)  # outside the lock: it only asks about seeds
        resource = self._resource_of(offer["handle"])
        with self._lock:
            if watch["decoded"] is not None and now - watch["decoded"] > ITEM_FORGET_SECONDS:
                watch["paired"] = watch["settled"] = None
            watch["crc"], watch["decoded"] = crc, now
            handle = offer["handle"]
            fields = ("i", "size", "class", "layout")
            stores = [[store.get(k) for k in fields] for store in offer.get("stores", [])]
            identity = dumps([offer["itemType"], stores])
            model = self._paired_by_handle(watch["paired"], watch["settled"], handle, identity)
            watch["paired"] = (handle, identity, model)
            if model is not None and self._pairable(model):
                offer["model"] = dict(model)  # a copy: the mod may yet add to what it keeps
            if resource is not None:
                if "seed" in resource and not self._pairable(resource):
                    resource = {k: v for k, v in resource.items() if k in ("slot", "name", "type", "refs")}
                offer["resource"] = resource
            offer["tools"] = [
                dict(found, offset=offset)
                for offset, seed in hits
                for found in self._recent_models.get(seed, ())
                if self._pairable(found)
            ]
            # Not compared: the text, which is anything printable in bytes NMS.py doesn't name (and
            # isn't read till the item is recorded); the scene node; what the resource manager says of
            # the handle, which counts the things that hold it; and the handles of the item and its
            # models, but for an item's handle of a model the mod can't name: the game may build the
            # same model again with another.
            compared = {k: v for k, v in offer.items() if k not in ("handle", "node", "resource")}
            if "model" in offer:
                compared["model"] = model_key(offer["model"])
            elif handle not in NO_HANDLE:
                compared["handle"] = handle
            compared["tools"] = [(model_key(tool), tool["offset"]) for tool in offer["tools"]]
            signature = hashlib.sha1(dumps(compared).encode()).hexdigest()
            if signature != watch["candidate"]:
                watch["candidate"] = signature
                watch["unsettled"] += 1
                if watch["unsettled"] < ITEM_UNSETTLED_LOOKS:
                    return  # recorded if it looks the same next time
                watch["unsettled"] = 0  # it keeps changing: record it as it is now
                offer["unsettled"] = 1
                self._report_once(
                    f"item-unsettled:{address:x}",
                    "An item the game offers hasn't looked the same twice in %d looks; it's recorded as it "
                    "is every %d looks while that lasts.",
                    ITEM_UNSETTLED_LOOKS,
                    ITEM_UNSETTLED_LOOKS,
                    with_traceback=False,
                )
            else:
                watch["unsettled"] = 0
                if "model" in offer:
                    watch["settled"] = (handle, identity, model)
            place = (system, signature)
            if watch["recorded"] == place:
                return
            watch["recorded"] = place
            if place in self._item_keys:
                return  # recorded already in this system, from this item or another
            if watch["system"] != system:
                watch["system"], watch["offers"], watch["records"] = system, {}, 0
            offers = watch["offers"].get(identity, 0)
            if offers >= ITEM_RECORDS_PER_OFFER or watch["records"] >= ITEM_RECORDS_PER_PLACE:
                self._report_once(
                    f"item-changes:{address:x}",
                    "An item the game offers keeps changing here; the mod has stopped recording some of "
                    "its changes in this system.",
                    with_traceback=False,
                )
                return
            watch["offers"][identity] = offers + 1
            watch["records"] += 1
            self._item_keys.add(place)
        self._write_item(address, raw, offer, system, pattern)

    def _paired_by_handle(
        self, paired: tuple | None, settled: tuple | None, handle: int, identity: str
    ) -> dict | None:
        """The model an item that holds ``handle`` while offering ``identity`` (its kind and inventories)
        is paired with by that handle: the model the game last built with that handle, however long
        ago, unless the game has since handed the handle to something else, or the model is the one the
        item settled with while offering something else (the last offer's model, still on while the
        item changes to the next). If the mod no longer remembers the handle, the model of the item's
        last look, or of when it last settled, if it held the same handle and offered the same thing
        then. ``paired`` and ``settled`` are (handle, offer, model) of the item's last look and of the
        last time it settled with a model. The caller holds the lock."""
        if handle in NO_HANDLE:
            return None
        if handle in self._handle_models:
            model = self._handle_models[handle]
            if model is None:
                return None  # the handle names something else now
            if settled is not None and settled[1] != identity and model_key(settled[2]) == model_key(model):
                return None
            return model
        for kept in (paired, settled):
            if kept is not None and kept[0] == handle and kept[1] == identity and kept[2] is not None:
                return kept[2]
        return None

    def _resource_of(self, handle: int) -> dict | None:
        """resource_info() for an item's handle, or None if it holds none or the resource manager can't
        be found. A failure is noted in what's returned, and said in the log once."""
        if handle in NO_HANDLE:
            return None
        try:
            return resource_info(handle)
        except Exception as exc:
            self._report_once("resource", "Couldn't read what the game's resource manager holds for an item.")
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _without_player_name(self, offer: dict) -> re.Pattern[bytes] | None:
        """Take the player's name and title out of the text in ``offer``, and return the pattern that
        finds them, for the item's bytes; or, if the name can't be read, leave the text out, note why,
        and return None."""
        pattern, problem = player_name_pattern()
        if pattern is None:
            self._report_once(
                f"player-name:{problem}",
                "Couldn't read your player name (%s); until the mod can, items are recorded without the "
                "text in them or their bytes.",
                problem,
                with_traceback=False,
            )
            for store in offer.get("stores", []):
                store.pop("name", None)
            offer.pop("entitlement", None)
            offer["nameUnread"] = problem
            return None
        for store in offer.get("stores", []):
            if "name" in store:
                store["name"] = scrub_text(store["name"], pattern)
        if "entitlement" in offer:
            offer["entitlement"] = [scrub_text(value, pattern) for value in offer["entitlement"]]
        return pattern

    def _write_item(
        self, address: int, raw: bytes, offer: dict, system: int | None, pattern: re.Pattern[bytes] | None
    ) -> None:
        """Queue an item the game offers for the capture file, with where you are, and with its text
        and bytes after taking out the player's name and title (``pattern``), or without them if
        that's None."""
        shown, scrubbed = scrub(raw, pattern) if pattern is not None else (None, 0)
        if shown is not None and (texts := item_texts(shown)):
            offer["texts"] = texts
        where, planet = player_environment()
        location = player_location()
        found = [m for m in [offer.get("model"), *offer["tools"]] if m is not None]
        tools = [m for m in found if is_multitool_model(m["name"])]
        record = {
            "t": "item",
            "at": int(time.time()),
            "system": hex64(system) if system else None,
            "where": where,
            "planet": planet,
            "loc": location,
            "addr": f"{address:X}",
            **offer,
        }
        if shown is not None:
            record["raw"] = packed(shown)
        if scrubbed:
            record["scrubbed"] = scrubbed
        with self._lock:
            self._pending.append(record)
            self._item_count += 1
            # The multi-tools this system offers that no record has shown yet. By handle and by seed,
            # an item can hold the same one twice.
            offered = []
            for tool in tools:
                if (system, tool["seed"]) not in self._offers_heard:
                    self._offers_heard.add((system, tool["seed"]))
                    offered.append(tool)
                self._tools_heard.add(tool["seed"])
            self._offer_count = len(self._offers_heard)
            self._tool_count = len(self._tools_heard)
            first_of_type = offer["itemType"] not in self._item_types_logged
            self._item_types_logged.add(offer["itemType"])
        for tool in offered:
            parts = ", ".join(tool["parts"]) or "no parts"
            place = f", number {tool['pool'] + 1} of the system's set" if "pool" in tool else ""
            logger.info(
                "Recorded a multi-tool the game offers (seed %s%s): %s: %s",
                tool["seed"],
                place,
                tool["name"],
                parts,
            )
        if first_of_type:
            logger.info(
                "Recorded an item the game offers, of a kind new this session (type %d, state %d): %s.",
                offer["itemType"],
                offer["state"],
                item_summary(offer),
            )
        if tools:
            self._status = "Recorded a multi-tool the game offers here."
            if offered:
                play_sound("multi-tool")
        else:
            self._status = "Recorded an item the game offers here."

    def _record_pool(self, this, seed_pointer, pool: dict) -> None:
        """Write the multi-tools the game built while it generated a system, its own set, in the order it
        built them: each one's file, seeds, parts and resource handle, and how many other threads built
        meanwhile, which aren't taken for the system's. Once per system and set in a session; the tone
        plays for the first set of a system in a session."""
        tools, elsewhere = pool["tools"], pool["elsewhere"]
        if not tools and not elsewhere:
            return
        address = address_of(this)
        system = (read_u64(address + LAYOUT.ua) or read_u64(address + LAYOUT.seed) or 0) if address else 0
        if not system and (raw := read_memory(address_of(seed_pointer), ctypes.sizeof(basic.GcSeed))):
            system = basic.GcSeed.from_buffer_copy(raw).Seed
        system &= MASK64 & ~PLANET_BITS
        key = (system, tuple((tool["name"], tool["seed"]) for tool in tools))
        with self._lock:
            if key in self._pool_keys or len(self._pool_keys) >= MAX_POOL_RECORDS:
                return
            self._pool_keys.add(key)
            record = {
                "t": "pool",
                "at": int(time.time()),
                "system": hex64(system),
                "tools": [{k: v for k, v in tool.items() if k != "pool"} for tool in tools],
            }
            if time.monotonic() - pool["since"] > POOL_SECONDS:
                record["late"] = 1  # the generation took longer than the mod waits: there may be more
            if elsewhere:
                record["elsewhere"] = elsewhere
            self._pending.append(record)
            if not tools:
                new = False
            else:
                new = system not in self._pool_systems
                self._pool_systems.add(system)
                self._tools_heard.update(tool["seed"] for tool in tools)
                self._tool_count = len(self._tools_heard)
                self._pool_count = len(self._pool_systems)
        if not tools:
            logger.info(
                "While the game generated the system at %s, galaxy %d, it built %d multi-tools on other "
                "threads and none on its own, so none were taken for the system's.",
                portal_code(system),
                galaxy_of(system),
                elsewhere,
            )
            return
        kinds = Counter(model_file(tool["name"]) for tool in tools)
        logger.info(
            "Recorded the %d multi-tools of the system at %s, galaxy %d (%s).",
            len(tools),
            portal_code(system),
            galaxy_of(system),
            ", ".join(f"{kind} {count}" for kind, count in kinds.most_common()),
        )
        if new:
            play_sound("multi-tool")

    def _flush_pending(self) -> None:
        """Write queued lookups, names, models and items (their hooks may run on any thread)."""
        now = time.monotonic()
        if not self._pending or now < self._next_flush:
            return
        self._next_flush = now + FLUSH_SECONDS
        # Where you were, for "built" lines: read here because the game may build models on any thread.
        context = {"system": None, "where": None}
        try:
            active = active_system()
            system = read_u64(active[0] + LAYOUT.ua) if active is not None else None
            context = {"system": hex64(system) if system else None, "where": player_environment()[0]}
        except Exception:
            self._report_once("built-context", "Couldn't tell where you were when the game built a model.")
        with self._lock:
            pending, self._pending = self._pending, []
        for entry in pending:
            if entry["t"] == "built":
                entry.update(context)
        try:
            with self._write_lock:
                self._append(*pending)
        except Exception:
            self._status = "Couldn't write the capture file. See the log."
            raise
        kinds = Counter(entry["t"] for entry in pending)
        with self._lock:
            self._query_count += kinds["query"]
            self._name_count += kinds["name"]
            self._model_count += kinds["model"]

    def _record_generated(self, this, use_settings_file, seed_pointer) -> None:
        address = address_of(this)
        if not address:
            return
        generator = address + LAYOUT.generator
        trace = self._traces.pop(generator, None)
        keys = self._keys.pop(generator, None)
        if trace is not None:
            trace.append(["generate<", rng_state(generator)])
        context: dict = {}
        raw_seed = read_memory(address_of(seed_pointer), ctypes.sizeof(basic.GcSeed))
        if raw_seed is not None:
            context["arg"] = hex64(basic.GcSeed.from_buffer_copy(raw_seed).Seed)
        if use_settings_file:
            context["settingsFile"] = True
        active = active_system()
        if active is not None:
            context["active"] = active[0] == address
            context.update(self._where(active[1]))
        if trace is not None:
            context["trace"] = trace
        if keys is not None:
            context["keyAttributes"] = keys
        if (raw := raw_data(address)) is not None:
            context["raw"] = raw
        if (raw := raw_galaxy(address)) is not None:
            context["rawGalaxy"] = raw
        try:
            if (locators := locator_data(address)) is not None:
                context["locators"] = locators
        except CaptureError as exc:
            context["locators"] = {"error": str(exc)}
        context.update(self._star_context(address, call=False))  # not the main thread: no calling the game
        self._record(address, "gen", context)

    def _poll(self) -> None:
        now = time.monotonic()
        requested = self._record_requested
        if not requested and now < self._next_poll:
            return
        self._record_requested = False
        self._next_poll = now + POLL_SECONDS
        active = active_system()
        if active is None:
            self._last_seen = None
            if requested:
                if gameData.GcApplication is None:
                    logger.info("Couldn't record: %s", NOT_FOUND_YET)
                    self._status = NOT_FOUND_YET
                else:
                    logger.info("Couldn't record: no star system is loaded yet.")
                    self._status = "No star system is loaded yet."
                play_sound("problem")
            return
        address, current_ua = active
        seen = fingerprint(address)
        if requested:
            try:
                self._record(address, "btn", self._where(current_ua, address), announce=True)
            except Exception:
                play_sound("problem")
                raise
            # Recorded now or earlier: either way the system is in the capture file.
            play_sound("recorded")
            self._arrived(seen, chime=False)
            self._last_polled = seen
        elif seen is not None and seen == self._last_seen and seen != self._last_polled:
            # Unchanged for a whole interval: settled enough to read in full.
            self._record(address, "poll", self._where(current_ua, address))
            self._last_polled = seen
            self._arrived(seen)
        self._last_seen = seen

    def _request_guild(self, guild: str) -> None:
        """A guild button: the game thread records it on its next frame."""
        self._guild_requested = guild
        self._status = f"Recording the {guild} Guild here..."

    def _record_guild(self) -> None:
        """Record the guild whose envoy you said you saw, with the system you're in: the region's stations
        all have the same one. The tone says whether it was recorded."""
        guild, self._guild_requested = self._guild_requested, None
        if guild is None:
            return
        try:
            active = active_system()
            ua = read_u64(active[0] + LAYOUT.ua) if active is not None else None
            if not ua:
                logger.info("Couldn't record the %s Guild: no star system is loaded yet.", guild)
                self._status = "No star system is loaded yet."
                play_sound("problem")
                return
            system = ua & ~PLANET_BITS
            entry = {"t": "guild", "at": int(time.time()), "system": hex64(system), "guild": guild}
            if (location := player_location()) is not None:
                entry["loc"] = location
            if (where := player_environment()[0]) is not None:
                entry["where"] = where  # in a space station, say
            with self._lock:
                self._pending.append(entry)
        except Exception:
            self._report_once("guild", "Couldn't record a guild.")
            play_sound("problem")
            return
        logger.info(
            "Recorded the %s Guild for the region of %s, galaxy %d.",
            guild,
            portal_code(system),
            galaxy_of(system),
        )
        self._status = f"Recorded the {guild} Guild here."
        play_sound("recorded")

    def _arrived(self, seen: tuple | None, chime: bool = True) -> None:
        """The system has settled and is in the capture file: tone once per system per session."""
        if seen is None:
            return
        system = int.from_bytes(seen[1], "little") & ~PLANET_BITS
        if system in self._chimed:
            return
        self._chimed.add(system)
        if chime and CHIME_ON_ARRIVAL:
            play_sound("recorded")

    def _where(self, current_ua: int | None, named_system: int | None = None) -> dict:
        """Cross-checks for a record; with ``named_system``, also the name the game shows for it."""
        context: dict = {}
        if current_ua:
            context["sim"] = hex64(current_ua)
        location = player_location()
        if location is not None:
            context["loc"] = location
        if named_system:
            try:
                if name := system_display_name(named_system):
                    context["displayName"] = name
            except Exception:
                self._report_once("name", "Couldn't get the system's name from the game.")
            context.update(self._star_context(named_system, call=True))
        return context

    def _star_context(self, system: int, call: bool) -> dict:
        """The bytes of the solar system around what the game counts its stars by, and with ``call`` (main
        thread only), how many stars it has, if the mod may ask the game."""
        stars = self._stars
        if stars is None:
            return {}
        context: dict = {}
        if (raw := stars.window_bytes(system)) is not None:
            context["starField"] = raw
        if not call or not stars.callable:
            return context
        try:
            count = stars.count(system)
        except CaptureError as exc:
            self._report_once("stars-read", "Couldn't count a system's stars: %s.", exc, with_traceback=False)
            return context
        except Exception:
            stars.callable = False
            self._report_once(
                "stars", "Couldn't count a system's stars; the mod won't ask the game again this session."
            )
            return context
        if 0 <= count <= MAX_STARS:
            context["stars"] = count
        else:
            stars.callable = False
            self._report_once(
                "stars-range",
                "The game's star count function said a system has %d stars, so it isn't what the mod took it "
                "for; the mod won't call it again this session.",
                count,
                with_traceback=False,
            )
        return context

    def _record(self, address: int, via: str, context: dict, announce: bool = False) -> bool:
        record = snapshot(address)
        self._remember_ships(record)
        keyed = dict(record, displayName=context.get("displayName"))
        key = hashlib.sha1(json.dumps(keyed, sort_keys=True).encode()).hexdigest()
        entry = {"t": "sys", "via": via, "at": int(time.time()), "ua": record["ua"]}
        entry.update(context)
        entry.update(record)
        summary = describe(entry)
        with self._lock:
            if key in self._recorded_keys:
                if announce:
                    logger.info("Already recorded this session: %s", summary)
                    self._status = "Already recorded; nothing has changed."
                return False
            self._recorded_keys.add(key)  # claimed, so no other thread writes it meanwhile
        try:
            with self._write_lock:
                self._append(entry)
        except Exception:
            with self._lock:
                self._recorded_keys.discard(key)
            self._status = "Couldn't write the capture file. See the log."
            raise
        with self._lock:
            self._count += 1
        logger.info("Recorded %s", summary)
        self._last = summary
        self._status = "Recording."
        if record.get("unusual"):
            self._report_once(
                "unusual",
                "Some values look wrong (%s). If this happens for every system, NMS.py probably "
                "doesn't match this game version yet; records are kept but marked.",
                ", ".join(record["unusual"]),
                with_traceback=False,
            )
        if record.get("errors"):
            self._report_once(
                "errors:" + "|".join(e.split(":")[0] for e in record["errors"]),
                "Part of the system couldn't be read: %s",
                "; ".join(record["errors"]),
                with_traceback=False,
            )
        return True

    def _append(self, *entries: dict) -> None:
        """Write lines to the capture file, after the session's header the first time. The caller
        holds self._write_lock."""
        lines = [] if self._session_started else [dumps(session_header(self))]
        lines.extend(dumps(entry) for entry in entries)
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        with CAPTURE_FILE.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
        self._session_started = True

    def _report_once(self, key: str, message: str, *args, with_traceback: bool = True) -> None:
        if key in self._reported:
            return
        self._reported.add(key)
        logger.warning(message, *args, exc_info=with_traceback)


PYTHON_DOWNLOAD = "https://www.python.org/downloads/release/python-31316/"


def launcher_problems(
    executable: str = sys.executable,
    prefixes: tuple[str, ...] = (sys.base_prefix, sys.prefix),
    pointer_size: int = struct.calcsize("P"),
) -> list[str]:
    """Reasons pyMHF won't be able to load this Python into the game, caught before it tries."""
    problems = []
    if pointer_size != 8:
        problems.append(f"This is 32-bit Python. The game needs 64-bit Python 3.13: {PYTHON_DOWNLOAD}")
    if any("\\windowsapps\\" in path.replace("/", "\\").lower() for path in (executable, *prefixes) if path):
        problems.append(
            "This is the Microsoft Store version of Python, which the game can't load (pyMHF stops "
            'with "DLL load failed ... Access is denied"). Uninstall it, install Python 3.13 from '
            f'{PYTHON_DOWNLOAD}, run "py -3.13 -m pip install nmspy" again, then start the mod again.'
        )
    return problems


GAME_EXE = "NMS.exe"
PYMHF_PORT = 6770  # pyMHF's code inside the game listens here for the launcher


def port_taken(port: int = PYMHF_PORT) -> bool:
    """True if a program on this computer is already listening on ``port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def game_running(exe: str = GAME_EXE) -> bool:
    try:
        import psutil  # installed with pyMHF
    except ImportError:
        return False
    try:
        return any((p.info.get("name") or "").lower() == exe.lower() for p in psutil.process_iter(["name"]))
    except Exception:  # a process vanishing mid-scan, access denied...
        return False


def attach_problems(running: bool, taken: bool) -> list[str]:
    """Reasons attaching to the game now would go wrong, caught before pyMHF tries.

    pyMHF attaches to a game that is already running, but it can't be inside
    the game twice: a second copy loads the mod again alongside the first,
    can't open its connection to the launcher, and the launcher waits for it
    forever.
    """
    if not taken:
        return []
    if running:
        return [
            "pyMHF from an earlier run of the mod is already inside No Man's Sky. If that run's "
            "terminal window is still open, keep using it. If you closed it, pyMHF stayed in the "
            "game: save, quit the game, then start the mod again."
        ]
    return [
        f"Another program is using port {PYMHF_PORT}, which pyMHF needs. Close any other pyMHF tool, "
        "then start the mod again."
    ]


if __name__ == "__main__":
    running = game_running()
    if problems := launcher_problems() + attach_problems(running, port_taken()):
        lines = ["The Trade Depot capture mod can't start:", *(f"- {p}" for p in problems)]
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(1)
    if running:
        print("No Man's Sky is already running, so the mod will attach to it.")

    from pymhf import load_mod_file

    load_mod_file(__file__)
