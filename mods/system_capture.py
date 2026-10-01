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
prepares for the system. The One Million Years Trade Depot uses these lines
as ground truth for working out how the game picks a system's ships.

The mod only reads. It changes nothing in the game or your save. Every read
of game memory goes through ReadProcessMemory, so if NMS.py's struct layouts
stop matching the game after an update, the mod logs a warning instead of
crashing the game.

Run it with ``py -3.13 system_capture.py``. See README.md in this folder.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import logging
import math
import os
import platform
import re
import struct
import sys
import threading
import time
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

MOD_VERSION = "0.3.0"
# Bump when the meaning of a field changes; tools/captures/report.py checks it.
# 2: generation traces, raw system data, display names and query records.
# (0.3.0 only adds fields and record types, so it keeps format 2.)
FORMAT_VERSION = 2
STEAM_APP_ID = 275850

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_FILE = CAPTURE_DIR / "systems.jsonl"

# How often the main loop looks at the current system. The Generate hook
# records systems as they are made; polling catches anything filled in later.
POLL_SECONDS = 2.0
# Query records (systems the game describes without loading them) are queued
# and written from the main loop at most this often.
FLUSH_SECONDS = 1.0
MAX_QUERY_RECORDS = 5_000
MAX_NAME_RECORDS = 20_000
NAME_LENGTH = 0x7F  # cTkFixedString<0x7F>, what the name generator writes
MAX_SHIPS = 512
MAX_READ = 1 << 20
MASK64 = (1 << 64) - 1
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
        self.simulation_system = nms.cGcSimulation.mpSolarSystem.offset
        self.simulation_ua = nms.cGcSimulation.mCurrentUA.offset
        self.location = nms.cGcPlayerState.mLocation.offset
        self.location_size = ctypes.sizeof(nmse.cGcUniverseAddressData)


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


def system_fields(data) -> dict:
    trading = data.TradingData
    return {
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


def raw_galaxy(address: int) -> str | None:
    """The system's whole cGcGalaxyAttributesAtAddress, compressed."""
    return packed(read_memory(address + LAYOUT.attributes, LAYOUT.attributes_size))


def read_text(address: int, size: int) -> str | None:
    raw = read_memory(address, size)
    return None if raw is None else raw.split(b"\0", 1)[0].decode("utf-8", errors="backslashreplace")


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
    return f"{name} ({where}): {pool}"


class TradeDepotCapture(Mod):
    __author__ = "One Million Years Trade Depot contributors"
    __description__ = "Records each star system you visit and the ships the game prepares for it."
    __version__ = MOD_VERSION
    __pymhf_required_version__ = "0.2.4"

    # Class-level defaults: pyMHF reads the GUI properties while the mod is
    # still being set up.
    _status = "Waiting for a star system to load."
    _last = "None yet."
    _count = 0
    _query_count = 0
    _name_count = 0

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._recorded_keys: set[str] = set()
        self._session_started = False
        self._reported: set[str] = set()
        self._record_requested = False
        self._label_requested: str | None = None
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
        logger.info("Trade Depot capture %s is recording to %s", MOD_VERSION, CAPTURE_FILE)

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

    @gui_button("Exotic seen here: squid")
    def exotic_squid(self):
        self._request_label("squid")

    @gui_button("Exotic seen here: not a squid")
    def exotic_not_squid(self):
        self._request_label("not a squid")

    def _request_label(self, label: str) -> None:
        # Read on the game thread, on its next frame, like the record button.
        self._label_requested = label
        self._status = f"Noting that the exotic here is {label}..."

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
        try:
            generator = address_of(this) + LAYOUT.generator
            self._traces[generator] = [["generate>", rng_state(generator)]]
        except Exception:
            self._report_once("trace", "Couldn't trace a system's generation.")

    @nms.cGcSolarSystem.Generate.after
    def after_generate(self, this, lbUseSettingsFile, lSeed):
        try:
            self._record_generated(this, lbUseSettingsFile, lSeed)
        except Exception:
            self._report_once("generate", "Couldn't record a newly generated system.")

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

    @main_loop.after
    def on_frame(self):
        try:
            self._flush_pending()
            self._apply_label()
            self._poll()
        except Exception:
            self._status = "Couldn't read the current system. See the log."
            self._report_once("poll", "Couldn't read the current system.")

    # --- Internals ---

    def _trace(self, generator_pointer, label: str) -> None:
        try:
            generator = address_of(generator_pointer)
            trace = self._traces.get(generator)
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

    def _flush_pending(self) -> None:
        """Write queued lookups and names (their hooks may run on any thread)."""
        now = time.monotonic()
        if not self._pending or now < self._next_flush:
            return
        self._next_flush = now + FLUSH_SECONDS
        with self._lock:
            pending, self._pending = self._pending, []
            try:
                self._append(*pending)
            except Exception:
                self._status = "Couldn't write the capture file. See the log."
                raise
            kinds = Counter(entry["t"] for entry in pending)
            self._query_count += kinds["query"]
            self._name_count += kinds["name"]

    def _apply_label(self) -> None:
        label, self._label_requested = self._label_requested, None
        if label is None:
            return
        active = active_system()
        if active is None:
            self._status = "No star system is loaded yet."
            return
        record = snapshot(active[0])
        record.update(self._where(None, active[0]))
        classes = ENUM_TABLES.get("shipClass", [])
        exotic = [
            row[0]
            for row in record.get("ships") or []
            if 0 <= row[2] < len(classes) and classes[row[2]] == "Royal"
        ]
        entry = {
            "t": "label",
            "at": int(time.time()),
            "ua": record["ua"],
            "seed": record.get("seed"),
            "label": label,
            "exotic": exotic,
        }
        if record.get("displayName"):
            entry["displayName"] = record["displayName"]
        with self._lock:
            self._append(entry)
        where = describe(record).split("):")[0] + ")"
        if exotic:
            logger.info("Noted: the exotic in %s (seed %s) is %s.", where, ", ".join(exotic), label)
            self._status = f"Noted: the exotic here is {label}."
        else:
            logger.info("Noted, but %s has no exotic in its ship list.", where)
            self._status = "Noted, but this system's ship list has no exotic."

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
                self._status = "No star system is loaded yet."
            return
        address, current_ua = active
        seen = fingerprint(address)
        if requested:
            self._record(address, "btn", self._where(current_ua, address), announce=True)
            self._last_polled = seen
        elif seen is not None and seen == self._last_seen and seen != self._last_polled:
            # Unchanged for a whole interval: settled enough to read in full.
            self._record(address, "poll", self._where(current_ua, address))
            self._last_polled = seen
        self._last_seen = seen

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
        return context

    def _record(self, address: int, via: str, context: dict, announce: bool = False) -> bool:
        record = snapshot(address)
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
            try:
                self._append(entry)
            except Exception:
                self._status = "Couldn't write the capture file. See the log."
                raise
            self._recorded_keys.add(key)
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


if __name__ == "__main__":
    if problems := launcher_problems():
        lines = ["The Trade Depot capture mod can't start:", *(f"- {p}" for p in problems)]
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(1)

    from pymhf import load_mod_file

    load_mod_file(__file__)
