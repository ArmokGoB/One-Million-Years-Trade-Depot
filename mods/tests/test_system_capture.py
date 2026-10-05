# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for mods/system_capture.py against fake game memory built from NMS.py's own structs.

Run from the repository root:
    python -m unittest discover -s mods/tests -v
Set NMS_NAMEGEN to a clone of nms_namegen to include the generator comparison test.
"""

from __future__ import annotations

import array
import base64
import contextlib
import ctypes
import importlib.util
import inspect
import io
import json
import math
import os
import socket
import sys
import tempfile
import threading
import types
import unittest
import wave
import zlib
from pathlib import Path
from unittest import mock

import harness

mod = harness.load_mod()
nms, nmse, basic = mod.nms, mod.nmse, mod.basic

from pymhf.core._types import DetourTime  # noqa: E402  (importable only after harness.load_mod)
from pymhf.extensions.ctypes import c_char_p64  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("capture_report", ROOT / "tools" / "captures" / "report.py")
report = importlib.util.module_from_spec(_spec)
sys.modules["capture_report"] = report
_spec.loader.exec_module(report)
import game_rng  # noqa: E402  (tools/captures is on the path once report.py is loaded)
import ship_model  # noqa: E402

# Portal 03E9F3545C3E in galaxy 1 (Hilbert Dimension), planet digit 0. In the
# game a system's seed is its universal address.
UA = (0x3E9 << 40) | (1 << 32) | 0xF3545C3E
ROYAL, FIGHTER, DROPSHIP = 6, 2, 1
SHIPS = [
    (0x1111111111111111, FIGHTER, 0, 1, 0, ""),
    (0x2222222222222222, DROPSHIP, 0, 1, 0, ""),
    (0x8000000000000001, ROYAL, 0, 1, 0, "EXOTIC"),
]
M32 = 0xFFFFFFFF
STEPS = [
    ("before_basics", "after_basics"),
    ("before_positions", "after_positions"),
    ("before_biomes", "after_biomes"),
    ("before_query", "after_query"),
]


def stream_ships(seed: int, offset: int, count: int = 50, crash_before: int = 42) -> tuple[list[int], int]:
    """Ship seeds the way the game draws them: two draws each from the stream seeded by ``seed``,
    starting ``offset`` draws in, with the crash-site ship's two draws before slot ``crash_before``."""
    outputs = [state & M32 for state in report.stream_states(seed, offset + 2 * count + 4)]
    seeds, crash, position = [], 0, offset
    for slot in range(count):
        if slot == crash_before:
            crash = report.mix((outputs[position + 1] << 32) | outputs[position])
            position += 2
        seeds.append(report.mix((outputs[position + 1] << 32) | outputs[position]))
        position += 2
    return seeds, crash


class Game:
    """Fake memory for one loaded solar system, the simulation and the player."""

    def __init__(self, ua: int = UA, name: str = "Abarof-Dulin", ships=SHIPS):
        self.memory = harness.FakeMemory()
        self._keep = []
        self.system = self._alloc(nms.cGcSolarSystem)
        self.address = ctypes.addressof(self.system)
        self.simulation = self._alloc(nms.cGcSimulation)
        self.player_state = self._alloc(nms.cGcPlayerState)
        self.seed = self._alloc(basic.GcSeed)
        self.keys = self._alloc(nms.cGcGalaxyAttributeGenerator.StarSystemKeyAttributes)
        self.loaded = True
        self.display_name = "Shown-Name"
        self.simulation.mpSolarSystem = ctypes.cast(self.address, ctypes.POINTER(nms.cGcSolarSystem))
        self.set_address(ua)
        self.fill(ua, name)
        self.set_ships(ships)

    def _alloc(self, struct):
        buffer = (ctypes.c_ubyte * ctypes.sizeof(struct))()
        self.memory.keep(buffer)
        self._keep.append(buffer)
        return struct.from_buffer(buffer)

    @property
    def generator(self):
        return self.system.mSolarSystemGenerator

    def generator_pointer(self, generator=None):
        target = self.generator if generator is None else generator
        return ctypes.cast(ctypes.addressof(target), ctypes.POINTER(nms.cGcSolarSystemGenerator))

    def set_rng(self, state: int, generator=None) -> None:
        rng = (self.generator if generator is None else generator).mRNG
        rng.mState0 = state & M32
        rng.mState1 = state >> 32

    def set_address(self, ua: int) -> None:
        self.system.mUA = ua
        self.simulation.mCurrentUA = ua
        location = self.player_state.mLocation
        location.RealityIndex = (ua >> 32) & 0xFF
        galactic = location.GalacticAddress
        signed = lambda value, bits: value - (1 << bits) if value >= 1 << (bits - 1) else value  # noqa: E731
        galactic.VoxelX = signed(ua & 0xFFF, 12)
        galactic.VoxelZ = signed((ua >> 12) & 0xFFF, 12)
        galactic.VoxelY = signed((ua >> 24) & 0xFF, 8)
        galactic.SolarSystemIndex = (ua >> 40) & 0xFFF
        galactic.PlanetIndex = 0

    def fill(self, seed: int, name: str) -> None:
        data = self.system.mSolarSystemData
        data.Seed.Seed = seed
        data.Seed.UseSeedValue = 1
        self.seed.Seed = seed
        self.seed.UseSeedValue = 1
        data.Name.value = name.encode()
        data.Class = 0
        data.StarType = 1  # Green
        data.InhabitingRace = 2  # Explorers (Korvax)
        data.TradingData.TradingClass = 5  # Scientific
        data.TradingData.WealthClass = 2  # Wealthy
        data.ConflictData = 0  # Low
        data.Planets = 4  # the game counts prime planets in
        data.PrimePlanets = 1
        data.PrimePlanetsIncludedInPlanetCount = True
        data.MaxNumFreighters = 4
        data.StartWithFreighters = False
        data.NumTradeRoutes = 3
        data.NumVisibleTradeRoutes = 2
        data.AsteroidLevel = 1
        data.SentinelCrashSiteShipSeed.Seed = 0x0102030405060708
        for i in range(8):
            data.PlanetOrbits[i] = i * 10
        data.TraderSpawnInStations.SequenceTakeoffDelay.x = 1.5
        data.TraderSpawnInStations.SequenceTakeoffDelay.y = 3.25
        data.TraderSpawnInStations.ChanceToDelayLaunch = 20
        data.TraderSpawnInStations.InitialTakeoffDelay = 0.123456
        data.TraderSpawnInStations.MaxToSpawn = 6
        data.TraderSpawnOnOutposts.MaxToSpawn = 2

        bodies = data.PlanetGenerationInputs
        for i, (body_seed, biome) in enumerate([(0xAAAA000000000001, 0), (0xAAAA000000000002, 4)]):
            body = bodies[i]
            body.Seed.Seed = body_seed
            body.Seed.UseSeedValue = 1
            body.Biome = biome
            body.BiomeSubType = 1
            body.Class = 0
            body.PlanetIndex = i
            body.PlanetSize = i
            body.RealityIndex = 1
            body.Star = 1
            body.HasRings = i == 1
            body.Prime = i == 1
            body.CommonSubstance.value = b"LAND1"
            body.RareSubstance.value = b"" if i == 0 else b"COLD1"

        keys = self.keys
        keys.meTradingClass, keys.meWealthClass, keys.meConflictLevel = 5, 2, 0
        keys.meRace, keys.meType, keys.meTag, keys.meAnomaly = 2, 1, 7, 0x01020304
        keys.muPlanetCount, keys.muSafeStartPlanet, keys.muPrimePlanetCount = 3, 2, 1
        keys.mbAbandonedSystem, keys.mbIsPirateSystem = False, True

        attributes = self.system.mGalaxyAttributes
        attributes.mbValid = True
        voxel = attributes.mVoxel
        voxel.AtlasStationCount = 1
        voxel.BlackholeCount = 1
        voxel.AtlasStationIndices[0] = 0x7A
        voxel.BlackholeIndices[0] = 0x79
        voxel.GuideStarMinimumCount = 0x78
        voxel.GuideStarRenegadeCount = 30
        voxel.PurpleSystemsCount = 0x40
        voxel.PurpleSystemsStart = 0x3E8
        star = attributes.mStar
        star.Type = 1
        star.Race = 2
        star.TradingData.TradingClass = 5
        star.TradingData.WealthClass = 2
        star.ConflictData = 0
        star.Anomaly = 0
        star.NumberOfPlanets = 3
        star.NumberOfPrimePlanets = 1
        star.NumberOfSpacePois = 7
        star.IsSystemSafe = True
        for i, body_seed in enumerate([0xAAAA000000000001, 0xAAAA000000000002]):
            star.PlanetSeeds[i].Seed = body_seed
            star.PlanetParentIndices[i] = -1 if i == 0 else 0
            star.PlanetSizes[i] = i

    def set_ships(self, ships) -> None:
        item = nmse.cGcAISpaceshipPreloadCacheData
        array = (item * max(len(ships), 1))()
        self.memory.keep(array)
        self._keep.append(array)
        for entry, (seed, ship_class, role, faction, frigate, hint) in zip(array, ships):
            entry.Seed.Seed = seed
            entry.Seed.UseSeedValue = 1
            entry.ShipClass = ship_class
            entry.ShipRole = role
            entry.Faction = faction
            entry.FrigateClass = frigate
            entry.TextureDescriptorHint.value = hint.encode()
        dynamic = self.system.mSolarSystemData.SystemShips
        dynamic.ArrayPointer = ctypes.addressof(array) if ships else 0
        dynamic.Size = len(ships)

    def set_locators(self, count: int):
        """``count`` locators with distinct contents; returns the array."""
        array = (nmse.cGcSolarSystemLocator * count)()
        self.memory.keep(array)
        self._keep.append(array)
        for i, locator in enumerate(array):
            locator.Position.x, locator.Position.y, locator.Position.z = i * 1000.5, -i * 2.25, i + 0.5
            locator.Direction.x, locator.Direction.y, locator.Direction.z = 0.0, 1.0, 0.0
            locator.Radius = 100.0 + i
            locator.Type = i % 4
            locator.Name.value = f"LOC{i}".encode()
        dynamic = self.system.mSolarSystemData.Locators
        dynamic.ArrayPointer = ctypes.addressof(array) if count else 0
        dynamic.Size = count
        return array

    def this(self):
        return ctypes.cast(self.address, ctypes.POINTER(nms.cGcSolarSystem))

    def generate(self, capture) -> object:
        """Call the mod's Generate detour the way pyMHF does."""
        return capture.after_generate(self.this(), False, ctypes.pointer(self.seed))

    def generate_traced(self, capture, states: list[int]) -> None:
        """A full generation: Generate, then each generator step, with the RNG at ``states``
        (one per hook call, in order: Generate>, 4 x step>/step<, Generate<)."""
        states = iter(states)
        self.set_rng(next(states))
        self.assertIsNone(capture.before_generate(self.this(), False, ctypes.pointer(self.seed)))
        for before, after in STEPS:
            for name in (before, after):
                self.set_rng(next(states))
                args = (ctypes.pointer(self.seed), None, None) if "query" in name else (None, None, None)
                if "basics" in name:
                    args = (ctypes.pointer(self.seed), None, ctypes.pointer(self.keys), None)
                self.assertIsNone(getattr(capture, name)(self.generator_pointer(), *args))
        self.set_rng(next(states))
        self.assertIsNone(self.generate(capture))

    @staticmethod
    def assertIsNone(value):
        assert value is None, "detours must return None"


class FakeGameData:
    GcApplication = "found"  # NMS.py has found the game

    def __init__(self, game: Game):
        self.game = game

    @property
    def simulation(self):
        return self.game.simulation if self.game.loaded else None

    @property
    def player_state(self):
        return self.game.player_state if self.game.loaded else None


class CaptureTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.game = Game()
        self._patch("CAPTURE_DIR", Path(self._tmp.name) / "captures")
        self._patch("CAPTURE_FILE", Path(self._tmp.name) / "captures" / "systems.jsonl")
        self._patch("read_memory", self.game.memory.read)
        self._patch("gameData", FakeGameData(self.game))
        self._patch("system_display_name", lambda address: self.game.display_name)
        self.sounds: list[str] = []
        self._patch("play_sound", self.sounds.append)
        self.capture = mod.TradeDepotCapture()

    def _patch(self, name, value):
        old = getattr(mod, name)
        setattr(mod, name, value)
        self.addCleanup(setattr, mod, name, old)

    def lines(self) -> list[dict]:
        if not mod.CAPTURE_FILE.exists():
            return []
        return [json.loads(line) for line in mod.CAPTURE_FILE.read_text(encoding="utf-8").splitlines()]

    def poll(self):
        self.capture._next_poll = 0.0
        self.capture._next_flush = 0.0
        self.capture.on_frame()


class WiringTests(CaptureTestCase):
    def test_generate_hooks_target_solar_system_generate(self):
        for hook, time in ((mod.TradeDepotCapture.after_generate, DetourTime.AFTER),
                           (mod.TradeDepotCapture.before_generate, DetourTime.BEFORE)):  # fmt: skip
            self.assertEqual(hook._hook_func_name, "cGcSolarSystem.Generate")
            self.assertEqual(hook._hook_time, time)
            self.assertEqual(hook._hook_pattern, nms.cGcSolarSystem.Generate._signature)
            self.assertEqual(len(hook._hook_func_def.argtypes), 3)

    def test_generator_step_hooks_match_nmspy_signatures(self):
        functions = {
            "basics": "GenerateBasics",
            "positions": "GeneratePlanetPositions",
            "biomes": "GeneratePlanetBiomes",
            "query": "GenerateQueryInfo",
        }
        for short, function in functions.items():
            target = getattr(nms.cGcSolarSystemGenerator, function)
            for when, time in (("before", DetourTime.BEFORE), ("after", DetourTime.AFTER)):
                hook = getattr(mod.TradeDepotCapture, f"{when}_{short}")
                self.assertEqual(hook._hook_func_name, f"cGcSolarSystemGenerator.{function}")
                self.assertEqual(hook._hook_time, time)
                self.assertEqual(hook._hook_pattern, target._signature)

    def test_detours_take_exactly_the_arguments_pymhf_passes(self):
        for hook in self.capture.hooks:  # bound methods, so without self
            self.assertEqual(
                len(inspect.signature(hook).parameters), len(hook._hook_func_def.argtypes), hook.__name__
            )

    def test_frame_callback_runs_after_the_main_loop(self):
        callback = mod.TradeDepotCapture.on_frame
        self.assertEqual(callback._custom_trigger, "MAIN_LOOP")
        self.assertEqual(callback._hook_time, DetourTime.AFTER)

    def test_mod_registers_hooks_callback_and_gui(self):
        expected = {"before_generate", "after_generate", "after_planet_name", "after_region_name"}
        expected |= {name for pair in STEPS for name in pair}
        expected |= {"before_add_resource", "after_add_resource", "before_item_update"}
        self.assertEqual({h.__name__ for h in self.capture.hooks}, expected)
        self.assertEqual({c.__name__ for c in self.capture._custom_callbacks}, {"on_frame"})
        self.assertEqual(len(self.capture._gui_widgets), 10)

    def test_ship_parts_hook_reads_the_engines_resource_loader_before_it_runs(self):
        hook = mod.TradeDepotCapture.before_add_resource
        self.assertEqual(hook._hook_func_name, "Engine.AddResource")
        self.assertEqual(hook._hook_time, DetourTime.BEFORE)
        self.assertEqual(hook._hook_pattern, nms.Engine.AddResource._signature)
        # (result, type, name, flags, descriptor) and one argument more, which the game ignores.
        self.assertEqual(len(hook._hook_func_def.argtypes), 6)
        argtypes = hook._hook_func_def.argtypes
        self.assertEqual(argtypes[4], ctypes.POINTER(nms.cTkResourceDescriptor))

    def test_no_detour_on_the_main_loop(self):
        # 0.5.1 took the application object from cGcApplication::Update's argument, and the game
        # crashed. The mod runs on the main loop through NMS.py's callback instead.
        self.assertNotIn("cGcApplication.Update", {hook._hook_func_name for hook in self.capture.hooks})

    def test_no_hotkeys_so_pymhf_leaves_the_keyboard_alone(self):
        import pymhf.core.mod_loader as loader

        callbacks = []
        manager = loader.ModManager()
        manager.hook_manager = types.SimpleNamespace(
            register_hook=lambda hook: None, _add_custom_callbacks=lambda found: None
        )
        with mock.patch.object(loader.keyboard, "hook", callbacks.append, create=True):
            capture = manager.instantiate_mod(mod.TradeDepotCapture)
        self.assertEqual(len(capture._hotkey_funcs), 0)
        self.assertEqual(callbacks, [], "pyMHF hooks the keyboard only for a mod's hotkeys")

    def test_buttons(self):
        buttons = [
            w._widget_data.label
            for w in self.capture._gui_widgets
            if type(getattr(w, "_widget_data", None)).__name__ == "ButtonWidgetData"
        ]
        self.assertEqual(buttons, ["Record the current system now", "Open the captures folder"])

    def test_layout_reads_inside_the_structs(self):
        self.assertEqual(mod.LAYOUT.ua, nms.cGcSolarSystem.mUA.offset)
        self.assertLessEqual(mod.LAYOUT.head, ctypes.sizeof(nms.cGcSolarSystem))
        self.assertLess(
            mod.LAYOUT.generator + mod.LAYOUT.rng + 8,
            ctypes.sizeof(nms.cGcSolarSystem),
            "RNG inside the system",
        )


class GenerateTests(CaptureTestCase):
    def test_record_holds_the_system_and_its_ships(self):
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.assertIsNone(self.game.generate(self.capture))
        header, record = self.lines()

        self.assertEqual(header["t"], "session")
        self.assertEqual(header["format"], mod.FORMAT_VERSION)
        self.assertEqual(header["columns"]["ships"], mod.SHIP_COLUMNS)
        self.assertEqual(header["enums"]["shipClass"][ROYAL], "Royal")
        self.assertEqual(header["enums"]["race"][7], "None_")

        self.assertEqual(record["t"], "sys")
        self.assertEqual(record["via"], "gen")
        self.assertEqual(record["ua"], f"{UA:016X}")
        self.assertEqual(record["seed"], f"{UA:016X}")
        self.assertEqual(record["arg"], f"{UA:016X}")
        self.assertIs(record["active"], True)
        self.assertEqual(record["sim"], f"{UA:016X}")
        self.assertEqual(record["loc"], [1, 0xC3E - 0x1000, 0xF3 - 0x100, 0x545, 0x3E9, 0])
        self.assertEqual(record["name"], "Abarof-Dulin")
        self.assertNotIn("displayName", record, "the game is only asked for names from the main loop")
        expected = {
            "useSeed": 1,
            "systemClass": 0,
            "star": 1,
            "race": 2,
            "trade": 5,
            "wealth": 2,
            "conflict": 0,
            "planets": 4,
            "prime": 1,
            "primeInCount": True,
            "freighters": 4,
            "startWithFreighters": False,
            "tradeRoutes": [3, 2],
            "asteroids": 1,
            "crashShip": "0102030405060708",
            "orbits": [0, 10, 20, 30, 40, 50, 60, 70],
            "traders": [[1.5, 3.25, 20, 0.1235, 6], [0.0, 0.0, 0, 0.0, 2]],
        }
        for key, value in expected.items():
            self.assertEqual(record[key], value, key)
        self.assertEqual(
            record["ships"],
            [
                ["1111111111111111", 1, FIGHTER, 0, 1, 0, ""],
                ["2222222222222222", 1, DROPSHIP, 0, 1, 0, ""],
                ["8000000000000001", 1, ROYAL, 0, 1, 0, "EXOTIC"],
            ],
        )
        self.assertEqual(
            record["bodies"],
            [
                ["AAAA000000000001", 1, 0, 1, 0, 0, 0, 1, 1, 0, "LAND1", ""],
                ["AAAA000000000002", 1, 4, 1, 0, 1, 1, 1, 1, 0b1000010, "LAND1", "COLD1"],
            ],
        )
        self.assertEqual(
            record["galaxy"],
            {
                "valid": True,
                "voxel": [1, 1, 0x78, 30, 0x40, 0x3E8, 0],
                "atlasIndices": [0x7A],
                "blackHoleIndices": [0x79],
                "star": 1,
                "race": 2,
                "trade": 5,
                "wealth": 2,
                "conflict": 0,
                "anomaly": 0,
                "planets": 3,
                "prime": 1,
                "spacePois": 7,
                "flags": ["IsSystemSafe"],
                "seeds": ["AAAA000000000001", "AAAA000000000002"],
                "parents": [-1, 0],
                "sizes": [0, 1],
            },
        )
        self.assertNotIn("errors", record)
        self.assertNotIn("unusual", record)
        self.assertIn(
            "Recorded Abarof-Dulin (03E9F3545C3E, galaxy 1): 3 ships (Fighter 1, Hauler 1, Exotic 1)",
            "\n".join(logs.output),
        )
        self.assertEqual(self.capture.recorded, "1")

    def test_raw_data_is_the_generated_system_data(self):
        self.game.generate(self.capture)
        raw = zlib.decompress(base64.b64decode(self.lines()[1]["raw"]))
        self.assertEqual(raw, bytes(self.game.system.mSolarSystemData))

    def test_seeds_above_2_63_are_unsigned(self):
        self.game.fill(0xFEDCBA9876543210, "Abarof-Dulin")
        self.game.generate(self.capture)
        record = self.lines()[1]
        self.assertEqual(record["seed"], "FEDCBA9876543210")
        self.assertEqual(record["arg"], "FEDCBA9876543210")

    def test_address_not_set_yet_is_logged_with_the_seed(self):
        self.game.system.mUA = 0  # as during the game's own Generate
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.game.generate(self.capture)
        record = self.lines()[1]
        self.assertEqual(record["ua"], "0" * 16)
        self.assertNotIn("unusual", record)
        self.assertIn("(03E9F3545C3E, galaxy 1)", "\n".join(logs.output))

    def test_repeat_generation_is_not_recorded_twice(self):
        self.game.generate(self.capture)
        self.game.generate(self.capture)
        self.assertEqual(len(self.lines()), 2)
        self.game.set_ships(SHIPS[:2])
        self.game.generate(self.capture)
        lines = self.lines()
        self.assertEqual([line["t"] for line in lines], ["session", "sys", "sys"])
        self.assertEqual(len(lines[-1]["ships"]), 2)

    def test_new_session_header_per_mod_instance(self):
        self.game.generate(self.capture)
        self.game.generate(mod.TradeDepotCapture())
        self.assertEqual([line["t"] for line in self.lines()], ["session", "sys", "session", "sys"])

    def test_empty_ship_list(self):
        self.game.set_ships([])
        self.game.generate(self.capture)
        self.assertEqual(self.lines()[1]["ships"], [])

    def test_unreadable_ship_list_keeps_the_rest(self):
        self.game.system.mSolarSystemData.SystemShips.ArrayPointer = 0xDEAD0000
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            self.game.generate(self.capture)
        record = self.lines()[1]
        self.assertNotIn("ships", record)
        self.assertEqual(record["errors"], ["ships: ship list at 0xdead0000 couldn't be read"])
        self.assertEqual(record["name"], "Abarof-Dulin")
        self.assertIn("Part of the system couldn't be read", "\n".join(logs.output))

    def test_implausible_ship_count_isnt_read(self):
        self.game.system.mSolarSystemData.SystemShips.Size = 100_000
        with self.assertLogs("TradeDepotCapture", "WARNING"):
            self.game.generate(self.capture)
        self.assertIn("implausible ship list", self.lines()[1]["errors"][0])

    def test_unreadable_system_writes_nothing_and_does_not_raise(self):
        this = ctypes.cast(0xBAD000, ctypes.POINTER(nms.cGcSolarSystem))
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            self.assertIsNone(self.capture.after_generate(this, False, ctypes.pointer(self.game.seed)))
            self.capture.after_generate(this, False, ctypes.pointer(self.game.seed))
        self.assertEqual(self.lines(), [])
        self.assertEqual(len(logs.output), 1, "reported once, not on every call")

    def test_unusual_values_are_marked(self):
        data = self.game.system.mSolarSystemData
        data.Name.value = b"\x01\x02garbage"
        data.StarType = 99
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            self.game.generate(self.capture)
        self.assertEqual(self.lines()[1]["unusual"], ["name", "star"])
        self.assertIn("NMS.py probably doesn't match this game version", "\n".join(logs.output))

    def test_non_finite_floats_are_written_as_null(self):
        self.game.system.mSolarSystemData.TraderSpawnInStations.InitialTakeoffDelay = math.nan
        self.game.generate(self.capture)
        self.assertIsNone(self.lines()[1]["traders"][0][3])

    def test_unwritable_capture_folder_is_reported(self):
        blocker = Path(self._tmp.name) / "blocked"
        blocker.write_text("not a folder")
        self._patch("CAPTURE_DIR", blocker)
        self._patch("CAPTURE_FILE", blocker / "systems.jsonl")
        with self.assertLogs("TradeDepotCapture", "WARNING"):
            self.game.generate(self.capture)
        self.assertEqual(self.capture.status, "Couldn't write the capture file. See the log.")
        self.assertEqual(self.capture.recorded, "0")


class TraceTests(CaptureTestCase):
    def test_generation_trace_records_the_rng_at_every_step(self):
        states = list(range(0x100, 0x100 + 10))
        self.game.generate_traced(self.capture, states)
        record = self.lines()[1]
        labels = ["generate>", "basics>", "basics<", "positions>", "positions<"]
        labels += ["biomes>", "biomes<", "query>", "query<", "generate<"]
        self.assertEqual(record["trace"], [[label, f"{s:016X}"] for label, s in zip(labels, states)])
        self.assertEqual(self.capture.lookups, "0", "a lookup inside a generation is part of its trace")

    def test_steps_outside_a_generation_are_ignored(self):
        self.capture.before_basics(
            self.game.generator_pointer(), ctypes.pointer(self.game.seed), None, None, None
        )
        self.capture.after_basics(
            self.game.generator_pointer(),
            ctypes.pointer(self.game.seed),
            None,
            ctypes.pointer(self.game.keys),
            None,
        )
        self.game.generate(self.capture)
        self.assertNotIn("trace", self.lines()[1])
        self.assertNotIn("keyAttributes", self.lines()[1])

    def test_key_attributes_and_raw_galaxy_attributes_are_kept(self):
        self.game.generate_traced(self.capture, list(range(10)))
        record = self.lines()[1]
        keys = record["keyAttributes"]
        self.assertEqual(
            {k: v for k, v in keys.items() if k != "raw"},
            {
                "trade": 5,
                "wealth": 2,
                "conflict": 0,
                "race": 2,
                "star": 1,
                "tag": 7,
                "anomaly": "01020304",
                "planets": 3,
                "safeStart": 2,
                "abandoned": False,
                "pirate": True,
                "prime": 1,
            },
        )
        self.assertEqual(bytes.fromhex(keys["raw"]), bytes(self.game.keys))
        raw = zlib.decompress(base64.b64decode(record["rawGalaxy"]))
        self.assertEqual(raw, bytes(self.game.system.mGalaxyAttributes))

    def test_trace_states_map_to_draw_counts(self):
        states = report.stream_states(UA, 2000)
        picks = [report.seeded_state(0x1234), report.seeded_state(UA), states[211], states[211], states[700]]
        picks += [states[700], states[880], states[880], states[1000], states[1500]]
        self.game.generate_traced(self.capture, picks)
        lines = report.trace_lines(report.read_captures([mod.CAPTURE_FILE]))
        self.assertIn(
            "generate>- basics>0 basics<212 positions>212 positions<701 biomes>701 biomes<881 "
            "query>881 query<1001 generate<1501",
            "\n".join(lines),
        )


class LocatorTests(CaptureTestCase):
    def test_generated_record_keeps_the_locators(self):
        locators = self.game.set_locators(3)
        self.game.generate(self.capture)
        kept = self.lines()[1]["locators"]
        self.assertEqual({k: v for k, v in kept.items() if k != "raw"}, {"count": 3, "size": 0x50})
        self.assertEqual(zlib.decompress(base64.b64decode(kept["raw"])), bytes(locators))

    def test_no_locators(self):
        self.game.generate(self.capture)
        self.assertEqual(self.lines()[1]["locators"], {"count": 0})

    def test_unreadable_or_implausible_locators_are_noted_and_the_record_kept(self):
        dynamic = self.game.system.mSolarSystemData.Locators
        cases = [(5, "couldn't be read"), (mod.MAX_LOCATORS + 1, "implausible")]
        for size, problem in cases:
            with self.subTest(size=size):
                dynamic.ArrayPointer, dynamic.Size = 0x10, size
                self.game.generate(mod.TradeDepotCapture())
                record = self.lines()[-1]
                self.assertIn(problem, record["locators"]["error"])
                self.assertEqual(len(record["ships"]), 3)

    def test_polls_dont_repeat_the_locators(self):
        self.game.set_locators(2)
        self.game.generate(self.capture)
        self.poll()
        self.poll()
        self.assertEqual([("locators" in line) for line in self.lines()[1:]], [True, False])


class NameTests(CaptureTestCase):
    def name(self, kind: str, seed: int, name: str, local: str | None = None):
        """Call a name-generator detour the way pyMHF does."""
        result = self.game._alloc(basic.cTkFixedString[0x7F])
        result.value = name.encode()
        localised = self.game._alloc(basic.cTkFixedString[0x7F])
        localised.value = (name if local is None else local).encode()
        hook = self.capture.after_planet_name if kind == "planet" else self.capture.after_region_name
        self.assertIsNone(hook(None, seed, ctypes.pointer(result), ctypes.pointer(localised)))

    def test_names_are_recorded_once_per_seed_with_the_loaded_system(self):
        self.name("planet", 0xAAAA000000000001, "Tupori")
        self.name("planet", 0xAAAA000000000001, "Tupori")
        self.name("region", 0x0123456789ABCDEF, "Yihelli Quadrant", local="Quadrant Yihelli")
        self.name("planet", 0xAAAA000000000002, "")  # nothing generated
        self.poll()
        names = [line for line in self.lines() if line["t"] == "name"]
        self.assertEqual(
            [{k: v for k, v in n.items() if k != "at"} for n in names],
            [
                {
                    "t": "name",
                    "kind": "planet",
                    "seed": "AAAA000000000001",
                    "name": "Tupori",
                    "system": f"{UA:016X}",
                },
                {
                    "t": "name",
                    "kind": "region",
                    "seed": "0123456789ABCDEF",
                    "name": "Yihelli Quadrant",
                    "local": "Quadrant Yihelli",
                    "system": f"{UA:016X}",
                },
            ],
        )
        self.assertEqual(self.capture.names, "2")

    def test_names_without_a_loaded_system(self):
        self.game.loaded = False
        self.name("planet", 0xAAAA000000000001, "Tupori")
        self.poll()
        (name,) = [line for line in self.lines() if line["t"] == "name"]
        self.assertNotIn("system", name)


FIGHTER_MODEL = "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN"
EXOTIC_MODEL = "MODELS/COMMON/SPACECRAFT/S-CLASS/S-CLASS_PROC.SCENE.MBIN"
CRASH_SEED = 0x0102030405060708  # the system's SentinelCrashSiteShipSeed in Game.fill


class ModelHelpers:
    """Builds models through the AddResource detour; mixed into CaptureTestCase subclasses."""

    def descriptor(self, seed: int, parts: list[str], seed2: int = 0, count=None, pointer=None):
        """A cTkResourceDescriptor in fake memory, with ``parts`` as its part IDs."""
        descriptor = self.game._alloc(nms.cTkResourceDescriptor)
        vector = descriptor.maDescriptors
        if parts:
            array = (basic.TkID0x20 * len(parts))()
            self.game.memory.keep(array)
            self.game._keep.append(array)
            for item, part in zip(array, parts):
                item.value = part.encode()
            if pointer is None:
                pointer = ctypes.addressof(array)
        if pointer is not None:
            vector._ptr = ctypes.cast(pointer, ctypes.POINTER(basic.TkID0x20))
        vector.vector_size = len(parts) if count is None else count
        vector.allocated_size = vector.vector_size
        descriptor.mSeed.Seed = seed
        descriptor.mSeed.UseSeedValue = 1
        descriptor.mSecondarySeed.Seed = seed2
        return ctypes.pointer(descriptor)

    def name_pointer(self, name: str) -> c_char_p64:
        text = ctypes.create_string_buffer(name.encode(), 0x100)
        self.game.memory.keep(text)
        self.game._keep.append(text)
        return c_char_p64(ctypes.addressof(text))

    def build(
        self, name: str, seed: int, parts: list[str], resource_type: int = 1, handle: int = 0, **kwargs
    ) -> None:
        """Call the AddResource detours the way pyMHF does: before the game builds the model, and after,
        once the game has filled in the model's resource ``handle``."""
        descriptor = self.descriptor(seed, parts, **kwargs)
        type_value, name_pointer = ctypes.c_int32(resource_type), self.name_pointer(name)
        result = self.game._alloc(nms.cTkSmartResHandle)
        args = (ctypes.pointer(result), type_value, name_pointer, 0, descriptor, 0)
        self.assertIsNone(self.capture.before_add_resource(*args), "detours must return None")
        result.miInternalHandle = handle
        if hasattr(self.capture, "after_add_resource"):
            self.assertIsNone(self.capture.after_add_resource(*args), "detours must return None")

    def models(self) -> list[dict]:
        self.poll()
        return [line for line in self.lines() if line["t"] == "model"]


class ModelTests(ModelHelpers, CaptureTestCase):
    def test_parts_of_the_systems_ships_are_recorded_once(self):
        self.game.generate(self.capture)  # the mod reads the system's ship list
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A", "_WINGS_B"])
            self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A", "_WINGS_B"])  # built again
            self.build(EXOTIC_MODEL, 0x8000000000000001, ["_BODY_SQUID"], seed2=0x42)
        models = self.models()
        self.assertEqual(
            [{k: v for k, v in m.items() if k not in ("at", "raw")} for m in models],
            [
                {
                    "t": "model",
                    "system": f"{UA:016X}",
                    "slot": 0,
                    "name": FIGHTER_MODEL,
                    "type": 1,
                    "seed": "1111111111111111",
                    "useSeed": 1,
                    "parts": ["_COCKPIT_A", "_WINGS_B"],
                },
                {
                    "t": "model",
                    "system": f"{UA:016X}",
                    "slot": 2,
                    "name": EXOTIC_MODEL,
                    "type": 1,
                    "seed": "8000000000000001",
                    "useSeed": 1,
                    "seed2": "0000000000000042",
                    "useSeed2": 0,
                    "parts": ["_BODY_SQUID"],
                },
            ],
        )
        raw = bytes.fromhex(models[0]["raw"])
        self.assertEqual(len(raw), ctypes.sizeof(nms.cTkResourceDescriptor), "the first records keep it")
        self.assertEqual(int.from_bytes(raw[0x10:0x18], "little"), 0x1111111111111111)
        text = "\n".join(logs.output)
        self.assertIn(
            f"Recording ship parts. The first: {FIGHTER_MODEL}, seed 1111111111111111: _COCKPIT_A, _WINGS_B",
            text,
        )
        self.assertIn("Recorded the parts of the exotic (seed 8000000000000001): _BODY_SQUID", text)
        self.assertEqual(self.capture.ship_parts, "2 of 2 ship models seen")
        self.assertEqual(self.sounds, ["exotic parts"])
        self.build(EXOTIC_MODEL.replace("_PROC", "_LOD"), 0x8000000000000001, ["_BODY_SQUID"])
        self.models()
        self.assertEqual(self.sounds.count("exotic parts"), 1, "one tone per exotic")

    def test_ships_not_in_the_systems_list_are_not_recorded(self):
        self.game.generate(self.capture)
        self.build(FIGHTER_MODEL, 0x9999999999999999, ["_COCKPIT_A"])  # your own ship, say
        self.assertEqual(self.models(), [])
        self.assertEqual(self.capture.ship_parts, "0 of 1 ship models seen")

    def test_ships_built_before_their_system_is_read_wait_for_its_list(self):
        self.build(FIGHTER_MODEL, 0x2222222222222222, ["_COCKPIT_B"])
        self.assertEqual(self.models(), [])
        self.game.generate(self.capture)
        (model,) = self.models()
        self.assertEqual((model["slot"], model["parts"]), (1, ["_COCKPIT_B"]))

    def test_waiting_ships_are_limited(self):
        self._patch("WAITING_MODELS", 1)
        self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"])
        self.build(FIGHTER_MODEL, 0x2222222222222222, ["_COCKPIT_B"])  # pushes the first out
        self.game.generate(self.capture)
        self.assertEqual([m["seed"] for m in self.models()], ["2222222222222222"])

    def test_the_crash_site_ship_is_recorded(self):
        self.game.generate(self.capture)
        self.build(FIGHTER_MODEL, CRASH_SEED, ["_COCKPIT_C"])
        (model,) = self.models()
        self.assertEqual(model["slot"], "crash")

    def test_other_models_are_named_in_the_log_once_and_not_recorded(self):
        self.game.generate(self.capture)
        creature = "MODELS/PLANETS/CREATURES/QUADRUPED/QUADRUPED.SCENE.MBIN"
        texture = "TEXTURES/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_BODY.DDS"
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.build(creature, 0x1111111111111111, ["_HEAD_A", "_LEGS_B"])
            self.build(creature, 0x1111111111111111, ["_HEAD_A", "_LEGS_C"])
            self.build(texture, 0x1111111111111111, [], resource_type=7)
        self.assertEqual(
            logs.output,
            [
                f"INFO:TradeDepotCapture:Model {creature}: not a ship, so its parts aren't recorded "
                "(2 parts).",
                f"INFO:TradeDepotCapture:Model {texture}: a ship's, but without parts, so not recorded "
                "(resource type 7).",
            ],
        )
        self.assertEqual(self.models(), [])

    def test_resources_without_a_descriptor_or_anything_in_one_are_ignored(self):
        self.game.generate(self.capture)
        name = self.name_pointer(FIGHTER_MODEL)
        with self.assertNoLogs("TradeDepotCapture", "INFO"):
            self.assertIsNone(self.capture.before_add_resource(None, 1, name, 0, None, 0))
            self.assertIsNone(self.capture.after_add_resource(None, 1, name, 0, None, 0))
            self.build(FIGHTER_MODEL, 0, [], handle=7)
        self.assertEqual(self.models(), [])
        self.assertEqual(self.capture._handle_models, {}, "nothing to pair an item with")

    def test_unreadable_or_implausible_part_lists_are_recorded_with_the_descriptors_bytes(self):
        self._patch("RAW_DESCRIPTORS", 0)
        self.game.generate(self.capture)
        self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"], count=100_000)
        self.build(FIGHTER_MODEL, 0x2222222222222222, ["_COCKPIT_A"], pointer=0xDEAD0000)
        first, second = self.models()
        self.assertRegex(first["errors"][0], r"^implausible part list \(count 100000, pointer 0x[0-9a-f]+\)$")
        self.assertEqual(second["errors"], ["part list at 0xdead0000 couldn't be read"])
        for model in (first, second):
            self.assertEqual(model["parts"], [])
            self.assertEqual(len(bytes.fromhex(model["raw"])), ctypes.sizeof(nms.cTkResourceDescriptor))

    def test_only_the_first_records_keep_the_descriptors_bytes(self):
        self._patch("RAW_DESCRIPTORS", 1)
        self.game.generate(self.capture)
        self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"])
        self.build(FIGHTER_MODEL, 0x2222222222222222, ["_COCKPIT_B"])
        first, second = self.models()
        self.assertIn("raw", first)
        self.assertNotIn("raw", second)

    def test_a_hook_failure_is_reported_once_and_the_game_carries_on(self):
        self.game.generate(self.capture)
        self._patch("resource_descriptor", mock.Mock(side_effect=RuntimeError("boom")))
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"])
            self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Couldn't record a ship's parts.", logs.output[0])

    def test_names_are_read_a_page_at_a_time(self):
        buffer = (ctypes.c_char * 0x2000)()
        start = ctypes.addressof(buffer)
        boundary = (start + 0x1000) & ~0xFFF  # a page boundary inside the buffer
        ctypes.memmove(boundary - 4, b"ABCDEFGH\0", 9)

        def readable_to(end):
            def read(address, size):
                inside = start <= address and address + size <= end
                return ctypes.string_at(address, size) if inside else None

            return read

        self._patch("read_memory", readable_to(start + 0x2000))
        self.assertEqual(mod.read_c_string(boundary - 4, 0x100), "ABCDEFGH", "across a page boundary")
        self.assertEqual(mod.read_c_string(boundary - 4, 6), "ABCDEF", "at most the limit")
        ctypes.memmove(boundary - 4, b"ABC\0", 4)
        self._patch("read_memory", readable_to(boundary))
        self.assertEqual(mod.read_c_string(boundary - 4, 0x100), "ABC", "up to unreadable memory")
        self.assertIsNone(mod.read_c_string(boundary, 0x100))
        self.assertIsNone(mod.read_c_string(0, 0x100))

    def test_the_log_counts_resources_every_few_minutes_while_the_count_changes(self):
        self.game.generate(self.capture)
        self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"])
        font = self.name_pointer("FONTS/A.TTF")
        self.assertIsNone(self.capture.before_add_resource(None, 1, font, 0, None, 0))  # no descriptor
        self.models()  # flush the record; the first count isn't due yet
        later = mod.time.monotonic() + mod.FIRST_RESOURCE_COUNT_SECONDS
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture._count_resources(later)
            self.capture._count_resources(later + 2 * mod.RESOURCE_COUNT_SECONDS)  # nothing new
        expected = (
            "INFO:TradeDepotCapture:Resources the game has loaded so far: 2, 1 of them with a "
            "descriptor; ship models: 1 seen, 1 recorded."
        )
        self.assertEqual(logs.output, [expected])

    def test_session_header_names_the_resource_types(self):
        self.game.generate(self.capture)
        self.assertEqual(self.lines()[0]["enums"]["resourceType"][1], "SceneGraph")

    def test_turning_ship_parts_off_leaves_the_function_alone(self):
        source = harness.MOD_PATH.read_text(encoding="utf-8")
        self.assertIn("\nRECORD_SHIP_PARTS = True\n", source)
        path = Path(self._tmp.name) / "system_capture_without_parts.py"
        path.write_text(source.replace("\nRECORD_SHIP_PARTS = True\n", "\nRECORD_SHIP_PARTS = False\n"))
        spec = importlib.util.spec_from_file_location("system_capture_without_parts", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        capture = module.TradeDepotCapture()
        hooks = {hook.__name__ for hook in capture.hooks}
        self.assertFalse(hooks & {"before_add_resource", "after_add_resource"})
        self.assertNotIn("before_item_update", hooks, "items are paired with models from that function")
        self.assertEqual(capture.ship_parts, "Off (RECORD_SHIP_PARTS is False)")
        self.assertEqual(capture.multitools, "Off: needs RECORD_SHIP_PARTS too")

    def test_report_lists_each_exotics_parts(self):
        self.game.generate(self.capture)
        self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"])
        self.build(EXOTIC_MODEL, 0x8000000000000001, ["_SCLASSSHIP_ROY", "_WINGS_A"])
        self.build(FIGHTER_MODEL, CRASH_SEED, ["_COCKPIT_C"])
        self.models()
        text = "\n".join(report.model_lines(report.read_captures([mod.CAPTURE_FILE])))
        self.assertIn("Ship models recorded with their parts: 3 (FIGHTER_PROC 2, S-CLASS_PROC 1)", text)
        self.assertIn("by ship type: Fighter 1, Exotic 1, Sentinel crash-site ship 1", text)
        self.assertIn("exotics: 1", text)
        self.assertIn(
            "03E9F3545C3E galaxy 1 Abarof-Dulin: 8000000000000001 (first draw 0.853393) "
            "_SCLASSSHIP_ROY _WINGS_A",
            text,
        )
        self.assertIn("squid rule (a squid when the seed's first draw is at least 20/21 of its range)", text)
        self.assertIn("1 of 1 exotic seeds agree", text)
        self.assertNotIn("disagrees", text)
        self.assertNotIn("not found in a recorded system's ship list", text)

    def test_report_flags_an_exotic_body_the_squid_rule_gets_wrong(self):
        self.game.generate(self.capture)
        self.build(EXOTIC_MODEL, 0x8000000000000001, ["_SCLASSSHIP_SQU", "TEXTURE_TEMP"])
        self.models()
        text = "\n".join(report.model_lines(report.read_captures([mod.CAPTURE_FILE])))
        self.assertIn("0 of 1 exotic seeds agree", text)
        disagrees = "disagrees: 03E9F3545C3E galaxy 1 Abarof-Dulin: 8000000000000001, first draw 0.853393"
        self.assertIn(disagrees, text)


MULTITOOL_MODEL = "MODELS/COMMON/WEAPONS/MULTITOOL/MULTITOOL.SCENE.MBIN"
ROYAL_TOOL_MODEL = "MODELS/COMMON/WEAPONS/MULTITOOL/ROYALMULTITOOL.SCENE.MBIN"
# A system's own multi-tools, as the game builds them while it generates the system: (file, seed,
# parts, resource handle).
SET = [
    (MULTITOOL_MODEL, 0x5EED000000000001, ["_GUN_A", "_GRIP_A"], 0x31000),
    (MULTITOOL_MODEL, 0x5EED000000000002, ["_GUN_B"], 0x31001),
    (ROYAL_TOOL_MODEL, 0x5EED000000000003, ["_ROYAL_A"], 0x31002),
]
TOOL_SEED = 0x7A11C0DE5EED0001  # a multi-tool the game offers
OTHER_TOOL_SEED = 0x0D0D0D0D0D0D0D0D  # another it offers later
OWN_TOOL_SEED = 0x0123456789ABCDEF  # one the player carries, or another player does
OWN_SHIP_SEED = 0x9999999999999999  # a ship that isn't in the system's ship list
TOOL_HANDLE, OWN_TOOL_HANDLE = 0x1234, 0x1235  # their models' resource handles
SPACE_STATION, PLANET_ON_FOOT = 2, 3  # EnvironmentLocation
TEXT_AT = 0x36A  # where an item 0.8.1 recorded held text
PLAYER = b"Zed Quorra, Seeker of the Atlas"  # the fake player's name with title
# Portal 01230EABCDEF in galaxy 1: another system.
OTHER_UA = (0x123 << 40) | (1 << 32) | 0x0EABCDEF


class ToolTests(ModelHelpers, CaptureTestCase):
    def setUp(self):
        super().setUp()
        self.now = 100.0  # the mod's clock (time.monotonic), which the tests move on
        self._patch("time", types.SimpleNamespace(monotonic=lambda: self.now, time=mod.time.time))
        self.game.player_state.mNameWithTitle.value = PLAYER
        self.game.generate(self.capture)  # a system is loaded
        self.place(SPACE_STATION, 1)

    def place(self, where: int, planet: int) -> None:
        """Where the player is, in the simulation's player environment."""
        base = ctypes.addressof(self.game.simulation)
        ctypes.c_uint32.from_address(base + mod.LAYOUT.player_where).value = where
        ctypes.c_int32.from_address(base + mod.LAYOUT.player_planet).value = planet

    def item(self, seeds=(), item_type=3, handle=0, offset=0x200, gift=False, text=b""):
        """A cGcPurchaseableItem in fake memory, as a pointer: ``seeds`` from ``offset`` on, 16 bytes
        apart, ``text`` at TEXT_AT, and five unused 1x1 inventories, as the game leaves them."""
        item = self.game._alloc(nms.cGcPurchaseableItem)
        item.mePurchaseState = 1
        item.mItemType = item_type
        item.mItemResource.miInternalHandle = handle
        item.mItemNode.lookupInt = 0x7FFFF  # no scene node
        item.mbIsGift = gift
        for index in range(mod.ITEM_STORES):
            self.store(item, index, size=(1, 1, 1), valid=())
        for i, seed in enumerate(seeds):
            ctypes.memmove(ctypes.addressof(item) + offset + 16 * i, seed.to_bytes(8, "little"), 8)
        self.write_text(item, text)
        return ctypes.pointer(item)

    @staticmethod
    def write_text(item, text: bytes) -> None:
        item = getattr(item, "contents", item)
        ctypes.memmove(ctypes.addressof(item) + TEXT_AT, text + b"\0", len(text) + 1)

    def store(
        self, item, index, size=(7, 3, 14), valid=(0x7F, 0x7F), grade=0, layout_seed=1,
        entries=(), special=(), stats=(), name=b"", history=(),
    ):  # fmt: skip
        """Fill inventory ``index`` of ``item`` (a struct or a pointer to one), and the lists it points to."""
        item = getattr(item, "contents", item)
        at = ctypes.addressof(item) + mod.ITEM_STORES_AT + index * mod.LAYOUT.store_size
        store = nms.cGcInventoryStore.from_address(at)
        store.miWidth, store.miHeight, store.miCapacity = size
        for row in range(len(store.mxValidSlots)):
            store.mxValidSlots[row].array[0] = valid[row] if row < len(valid) else 0
        store.mClass = grade
        layout = store.mLayoutDescriptor
        layout.Seed.Seed, layout.Seed.UseSeedValue, layout.Level, layout.Slots = layout_seed, 1, 1, 10
        store.mbAutoMaxEnabled = True
        store.mInventoryName.value = name
        self.fill(store.mStore, nmse.cGcInventoryElement, entries, self.set_entry)
        self.fill(store.mStoreHistory, nmse.cGcInventoryElement, history, self.set_entry)
        self.fill(store.maSpecialSlots, nmse.cGcInventorySpecialSlot, special, self.set_special)
        self.fill(store.maBaseStats, nmse.cGcInventoryBaseStatEntry, stats, self.set_stat)
        return store

    def fill(self, vector, kind, rows, setter) -> None:
        """A tk_vector of ``rows`` in fake memory."""
        vector.vector_size = vector.allocated_size = len(rows)
        if not rows:
            vector._ptr = ctypes.POINTER(kind)()
            return
        array = (kind * len(rows))()
        self.game.memory.keep(array)
        self.game._keep.append(array)
        for entry, row in zip(array, rows):
            setter(entry, row)
        vector._ptr = ctypes.cast(ctypes.addressof(array), ctypes.POINTER(kind))

    @staticmethod
    def set_entry(entry, row) -> None:
        entry.Id.value = row[0].encode()
        entry.Index.X, entry.Index.Y, entry.Amount, entry.MaxAmount, entry.Type = row[1:6]
        entry.DamageFactor, entry.AddedAutomatically, entry.FullyInstalled = row[6:]

    @staticmethod
    def set_special(slot, row) -> None:
        slot.Index.X, slot.Index.Y, slot.Type = row

    @staticmethod
    def set_stat(stat, row) -> None:
        stat.BaseStatID.value, stat.Value = row[0].encode(), row[1]

    def look(self, item, looks: int = 2) -> None:
        """The game updates ``item`` for as long as the mod takes for ``looks`` looks at it."""
        for _ in range(looks):
            self.capture._item_updated(item)
            self.now += mod.ITEM_CHECK_SECONDS

    def load(self, handle: int) -> None:
        """The game loads something without a descriptor, and AddResource fills in ``handle``."""
        result = self.game._alloc(nms.cTkSmartResHandle)
        args = (ctypes.pointer(result), 1, self.name_pointer("TEXTURES/A.DDS"), 0, None, 0)
        self.assertIsNone(self.capture.before_add_resource(*args))
        result.miInternalHandle = handle
        self.assertIsNone(self.capture.after_add_resource(*args))

    def items(self) -> list[dict]:
        self.poll()
        return [line for line in self.lines() if line["t"] == "item"]

    def built(self) -> list[dict]:
        self.poll()
        return [line for line in self.lines() if line["t"] == "built"]

    def pools(self) -> list[dict]:
        self.poll()
        return [line for line in self.lines() if line["t"] == "pool"]

    @contextlib.contextmanager
    def generation(self):
        """The game generates the loaded system again: what's built inside happens meanwhile."""
        self.assertIsNone(
            self.capture.before_generate(self.game.this(), False, ctypes.pointer(self.game.seed))
        )
        yield
        self.assertIsNone(self.game.generate(self.capture))

    def build_set(self, tools=SET) -> None:
        for name, seed, parts, handle in tools:
            self.build(name, seed, parts, handle=handle)

    def resource_table(self, resources: dict, one_based: bool = True):
        """A resource manager in fake memory listing ``resources``, handle -> (file, seed or None,
        parts, references), with the mod pointed at it; returns the manager."""
        manager = self.game._alloc(nms.cTkResourceManager)
        count = max(resources) + 2
        pointers = (ctypes.c_uint64 * count)()
        self.game.memory.keep(pointers)
        self.game._keep.append(pointers)
        self.resources = {}
        for handle, (name, seed, parts, refs) in resources.items():
            resource = self.resources[handle] = self.game._alloc(nms.cTkResource)
            resource.miType = 1
            resource.msName.value = name.encode()
            resource.mHandle = handle
            resource.muRefCount = refs
            if seed is not None:
                descriptor = self.descriptor(seed, parts).contents
                ctypes.memmove(ctypes.addressof(resource.mDescriptor), ctypes.addressof(descriptor),
                               ctypes.sizeof(descriptor))  # fmt: skip
            pointers[handle - 1 if one_based else handle] = ctypes.addressof(resource)
        vector = manager.mResources
        vector.allocated_size = vector.vector_size = count
        vector._ptr = ctypes.cast(ctypes.addressof(pointers), type(vector._ptr))
        self._patch("resource_manager_address", lambda: ctypes.addressof(manager))
        return manager

    def test_hooks_watch_the_items_the_game_offers_and_the_handles_of_models(self):
        hook = mod.TradeDepotCapture.before_item_update
        self.assertEqual(hook._hook_func_name, "cGcPurchaseableItem.Update")
        self.assertEqual(hook._hook_time, DetourTime.BEFORE)
        self.assertEqual(hook._hook_pattern, nms.cGcPurchaseableItem.Update._signature)
        argtypes = hook._hook_func_def.argtypes
        self.assertEqual(len(argtypes), 4)  # (this, time step) and two the function never reads
        self.assertEqual(argtypes[0], ctypes.POINTER(nms.cGcPurchaseableItem))
        after = mod.TradeDepotCapture.after_add_resource
        self.assertEqual(after._hook_func_name, "Engine.AddResource")
        self.assertEqual(after._hook_time, DetourTime.AFTER)
        self.assertEqual(after._hook_pattern, nms.Engine.AddResource._signature)
        self.assertEqual(after._hook_func_def.argtypes[0], ctypes.POINTER(nms.cTkSmartResHandle))
        item = self.item()
        for _ in range(2):
            self.assertIsNone(self.capture.before_item_update(item, 0.016, 0, 0))
            self.now += mod.ITEM_CHECK_SECONDS
        self.assertEqual(len(self.items()), 1)

    def test_an_offered_multi_tool_is_recorded_with_its_model_inventories_text_and_place(self):
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A", "_HANDLE_B"], handle=TOOL_HANDLE)
            item = self.item(handle=TOOL_HANDLE, gift=True, text=b"Glimmer of the Void AB1-C23")
            self.store(
                item,
                0,
                entries=[("LASER", 0, 0, 100, 100, 1, 0.0, True, True)],
                history=[("UT_SCAN", 1, 0, 50, 100, 1, 0.25, False, True)],
                special=[(3, 1, 4)],
                stats=[("WEAPON_DAMAGE", 1.25), ("WEAPON_MINING", 0.5)],
            )
            self.store(item, 2, size=(8, 3, 20), valid=(0xFF, 0xFF, 0xF0), grade=3, layout_seed=TOOL_SEED)
            self.capture._item_updated(item)
            queued = [entry for entry in self.capture._pending if entry["t"] == "item"]
            self.assertEqual(queued, [], "recorded once it looks the same twice in a row")
            self.now += mod.ITEM_CHECK_SECONDS
            self.capture._item_updated(item)
        (record,) = self.items()
        raw = zlib.decompress(base64.b64decode(record.pop("raw")))
        self.assertEqual(raw, ctypes.string_at(ctypes.addressof(item.contents), mod.LAYOUT.item_size))
        model = {
            "name": MULTITOOL_MODEL,
            "type": 1,
            "seed": "7A11C0DE5EED0001",
            "useSeed": 1,
            "parts": ["_GUN_A", "_HANDLE_B"],
            "handle": TOOL_HANDLE,
        }
        self.assertEqual(
            {k: v for k, v in record.items() if k != "at"},
            {
                "t": "item",
                "system": f"{UA:016X}",
                "where": SPACE_STATION,
                "planet": 1,
                "loc": mod.player_location(),
                "addr": f"{ctypes.addressof(item.contents):X}",
                "itemType": 3,
                "state": 1,
                "free": 0,
                "gift": 1,
                "reward": 0,
                "extra": 0,
                "handle": TOOL_HANDLE,
                "node": 0x7FFFF,
                "stores": [
                    {
                        "i": 0,
                        "size": [7, 3, 14],
                        "valid": [0x7F, 0x7F],
                        "class": 0,
                        "layout": ["0000000000000001", 1, 1, 10],
                        "autoMax": 1,
                        "stack": 0,
                        "entries": [["LASER", 0, 0, 100, 100, 1, 0.0, 1, 1]],
                        "history": [["UT_SCAN", 1, 0, 50, 100, 1, 0.25, 0, 1]],
                        "special": [[3, 1, 4]],
                        "stats": [["WEAPON_DAMAGE", 1.25], ["WEAPON_MINING", 0.5]],
                    },
                    {
                        "i": 2,
                        "size": [8, 3, 20],
                        "valid": [0xFF, 0xFF, 0xF0],
                        "class": 3,
                        "layout": ["7A11C0DE5EED0001", 1, 1, 10],
                        "autoMax": 1,
                        "stack": 0,
                    },
                ],
                "texts": [[TEXT_AT, "Glimmer of the Void AB1-C23"]],
                "model": model,
                # Its seed, where the item's third inventory keeps the seed of its layout.
                "tools": [dict(model, offset=mod.ITEM_STORES_AT + 2 * mod.LAYOUT.store_size + 0xE0)],
            },
        )
        self.assertEqual(
            [line.split(":", 2)[2] for line in logs.output],
            [
                f"Model {MULTITOOL_MODEL}: a multi-tool's (2 parts); its seed and parts are recorded with "
                "the system's set if the game built it for the system, or with an item the game offers "
                "that holds it.",
                f"Recorded a multi-tool the game offers (seed 7A11C0DE5EED0001): {MULTITOOL_MODEL}: "
                "_GUN_A, _HANDLE_B",
                "Recorded an item the game offers, of a kind new this session (type 3, state 1): inventories "
                f"0 (7x3, 14 slots, class C), 2 (8x3, 20 slots, class S); model {MULTITOOL_MODEL}, "
                "seed 7A11C0DE5EED0001.",
            ],
        )
        self.assertEqual(self.sounds, ["multi-tool"])
        self.assertEqual(self.capture.multitools, "1 in 0 systems' sets; 1 on offer (items recorded: 1)")
        self.assertEqual(self.capture.status, "Recorded a multi-tool the game offers here.")
        self.assertEqual(self.lines()[0]["columns"]["storeEntries"][0], "id")
        self.assertEqual(self.lines()[0]["enums"]["inventoryClass"], ["C", "B", "A", "S"])

    def test_an_item_is_recorded_once_it_settles_and_again_whenever_what_it_holds_changes(self):
        item = self.item(item_type=0)
        reads = []
        read = mod.read_memory
        self._patch("read_memory", lambda address, size: reads.append(size) or read(address, size))
        self.capture._item_updated(item)
        self.now += mod.ITEM_CHECK_SECONDS / 2
        self.capture._item_updated(item)  # not due yet: not even read
        self.assertEqual(reads.count(mod.LAYOUT.item_size), 1)
        self.now += mod.ITEM_CHECK_SECONDS / 2
        self.look(item, 3)  # recorded at the first of these, and nothing new after
        # The game uses the same item for the next offer, which 0.8.1 missed.
        self.place(PLANET_ON_FOOT, 2)
        item.contents.mItemType = 1
        self.store(item, 2, size=(8, 3, 20), layout_seed=TOOL_SEED)
        self.look(item)
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        item.contents.mItemResource.miInternalHandle = TOOL_HANDLE  # the game has built its model
        self.look(item)
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE + 1)  # and builds it again
        item.contents.mItemResource.miInternalHandle = TOOL_HANDLE + 1
        item.contents.mItemNode.lookupInt = 0x40001
        self.look(item)  # no news
        item.contents.mItemType = 0  # back to the first offer, recorded already in this system
        self.store(item, 2, size=(1, 1, 1), valid=())
        item.contents.mItemResource.miInternalHandle = 0
        self.look(item)
        records = self.items()
        self.assertEqual(
            [(r["itemType"], r["where"], r["planet"]) for r in records], [(0, 2, 1), (1, 3, 2), (1, 3, 2)]
        )
        self.assertEqual([r.get("model", {}).get("seed") for r in records], [None, None, "7A11C0DE5EED0001"])
        self.assertEqual([len(r["tools"]) for r in records], [0, 0, 1])
        self.assertEqual(self.sounds, ["multi-tool"])

    def test_what_an_item_holds_for_a_moment_while_it_changes_is_not_recorded(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        item = self.item(handle=TOOL_HANDLE)
        self.store(item, 2, layout_seed=TOOL_SEED)
        self.look(item)
        self.store(item, 2, grade=1, layout_seed=OTHER_TOOL_SEED)  # the next offer, its old model still on
        self.look(item, 1)
        self.build(MULTITOOL_MODEL, OTHER_TOOL_SEED, ["_GUN_B"], handle=TOOL_HANDLE + 1)
        item.contents.mItemResource.miInternalHandle = TOOL_HANDLE + 1
        self.look(item)
        records = self.items()
        self.assertEqual(
            [(r["stores"][0]["layout"][0], r["model"]["seed"]) for r in records],
            [("7A11C0DE5EED0001", "7A11C0DE5EED0001"), ("0D0D0D0D0D0D0D0D", "0D0D0D0D0D0D0D0D")],
        )

    def test_an_offer_is_recorded_once_per_system_even_by_the_same_item(self):
        item = self.item()
        self.look(item)
        self.look(self.item())  # another rack with the same in it
        self.game.set_address(OTHER_UA)
        self.look(item)  # the same item, unchanged, in another system: recorded there at once
        self.look(self.item())
        records = self.items()
        self.assertEqual([r["system"] for r in records], [f"{UA:016X}", f"{OTHER_UA:016X}"])
        self.assertEqual({r["addr"] for r in records}, {f"{ctypes.addressof(item.contents):X}"})

    def test_text_that_changes_by_itself_makes_no_new_record(self):
        item = self.item(text=b"Ticker 0000")
        for tick in range(1, 6):
            self.look(item, 1)
            self.write_text(item, b"Ticker %04d" % tick)
        (record,) = self.items()
        self.assertEqual(record["texts"], [[TEXT_AT, "Ticker 0001"]])

    def test_an_item_is_recorded_only_so_often_for_each_offer_and_in_all_in_one_system(self):
        self._patch("ITEM_RECORDS_PER_OFFER", 3)
        self._patch("ITEM_RECORDS_PER_PLACE", 5)
        item = self.item()
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            for handle in range(10, 16):  # the same offer, its handle changing: 3 records
                item.contents.mItemResource.miInternalHandle = handle
                self.look(item)
            for grade in (1, 2, 3):  # other offers: one record each, till 5 in all
                self.store(item, 0, grade=grade)
                self.look(item)
        self.assertEqual([r["handle"] for r in self.items()], [10, 11, 12, 15, 15])
        grades = [r["stores"][0]["class"] if "stores" in r else None for r in self.items()]
        self.assertEqual(grades, [None, None, None, 1, 2])
        self.assertEqual(len(logs.output), 1)
        stopped = "keeps changing here; the mod has stopped recording some of its changes"
        self.assertIn(stopped, logs.output[0])
        self.game.set_address(OTHER_UA)
        self.look(item)
        self.assertEqual(len(self.items()), 6, "another system: another budget")

    def test_reaching_the_most_items_a_session_records_is_logged_once(self):
        self._patch("MAX_ITEM_RECORDS", 1)
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            for item_type in (3, 4, 5):
                self.look(self.item(item_type=item_type))
        self.assertEqual([r["itemType"] for r in self.items()], [3])
        full = "WARNING:TradeDepotCapture:Recorded 1 items this session; no more until the next."
        self.assertEqual(logs.output, [full])

    def test_bytes_that_cant_be_an_inventory_are_noted_and_their_lists_not_read(self):
        item = self.item()
        store = self.store(item, 1, size=(500, 3, 14))
        store.maBaseStats.vector_size = store.maBaseStats.allocated_size = 1
        store.maBaseStats._ptr = ctypes.cast(0xDEAD0000, ctypes.POINTER(nmse.cGcInventoryBaseStatEntry))
        self.look(item)
        (record,) = self.items()
        self.assertEqual(record["stores"], [{"i": 1, "implausible": 1}])

    def test_unreadable_or_implausible_inventory_lists_are_noted(self):
        item = self.item()
        store = self.store(item, 0, entries=[("LASER", 0, 0, 1, 1, 1, 0.0, False, True)], stats=[("X", 1.0)])
        store.mStore.vector_size = 5  # more than it has room for
        store.maBaseStats._ptr = ctypes.cast(0xDEAD0000, ctypes.POINTER(nmse.cGcInventoryBaseStatEntry))
        self.look(item)
        (record,) = self.items()
        (stored,) = record["stores"]
        implausible = r"^entries: implausible list \(count 5 of 1, pointer 0x[0-9a-f]+\)$"
        self.assertRegex(stored["errors"][0], implausible)
        self.assertEqual(stored["errors"][1], "base stats: list at 0xdead0000 couldn't be read")
        self.assertNotIn("entries", stored)
        self.assertNotIn("stats", stored)

    def test_the_players_name_and_title_are_taken_out_of_text_bytes_and_ids(self):
        item = self.item(text=b"Gift for Zed Quorra")
        self.store(item, 0, name=b"quorra's spare")
        item.contents.mLinkedEntitlementId.value = b"QUORRA_GIFT"
        item.contents.mLinkedEntitlementRewardId.value = b"R_TOOL"
        self.look(item)
        (record,) = self.items()
        self.assertEqual(record["texts"], [[TEXT_AT, "Gift for *** ******"]])
        self.assertEqual(record["stores"][0]["name"], "******'s spare")
        self.assertEqual(record["entitlement"], ["******_GIFT", "R_TOOL"])
        self.assertEqual(record["scrubbed"], 4)
        raw = zlib.decompress(base64.b64decode(record["raw"]))
        self.assertEqual(len(raw), mod.LAYOUT.item_size)
        for word in (b"zed", b"quorra"):
            self.assertNotIn(word, raw.lower())
        self.assertNotIn("quorra", mod.CAPTURE_FILE.read_text(encoding="utf-8").lower())

    def test_the_name_pattern_covers_the_name_with_title_and_its_words(self):
        pattern = mod.name_pattern(PLAYER)
        said = b"ZED met quorra; the ATLAS seekers"
        self.assertEqual(mod.scrub(said, pattern), (b"*** met ******; the ***** ******s", 4))
        self.assertEqual(mod.scrub(PLAYER + b"!", pattern), (b"*" * len(PLAYER) + b"!", 1))
        short = mod.name_pattern(b"Al")  # two letters: only where they stand alone
        self.assertEqual(mod.scrub(b"Al met Alice; AL!", short), (b"** met Alice; **!", 2))
        titled = mod.name_pattern(b"Zed, a Seeker")  # "a" and "I" are one-letter words a title may have
        self.assertEqual(mod.scrub(b"a Seeker named zed", titled), (b"a ****** named ***", 2))
        cyrillic = mod.name_pattern("Жу Quorra".encode())  # characters, not bytes, count
        said = "Жу met quorra; ЖуЖу".encode()
        self.assertEqual(mod.scrub(said, cyrillic), ("**** met ******; ЖуЖу".encode(), 2))
        # A lone letter says nothing of who you are and can't be taken out of bytes without taking out
        # much else: it's left, and the rest of the name taken out.
        lettered = mod.name_pattern(b"Q, Seeker of the Atlas")
        self.assertEqual(
            mod.scrub(b"Q met the seeker Q of atlas", lettered), (b"Q met the ****** Q of *****", 2)
        )
        self.assertEqual(mod.scrub(b"Q, Seeker of the Atlas!", lettered), (b"*" * 22 + b"!", 1))
        for single in (b"Q", "Ж".encode()):  # nothing to take out
            self.assertEqual(mod.scrub(b"Q met \xd0\x96", mod.name_pattern(single)), (b"Q met \xd0\x96", 0))
        self.assertEqual(mod.scrub("Ö met bob".encode(), mod.name_pattern("Ö Bob".encode())),
                         ("Ö met ***".encode(), 1))  # fmt: skip
        # Nothing is recorded that might hold a name that isn't text at all, and the log says why.
        problems = {b"": "empty", b"   ": "empty", b"\x01\x02\x03": "not text", b"\xff\xfe Bob": "not UTF-8"}
        for unreadable, problem in problems.items():
            self.assertIsNone(mod.name_pattern(unreadable), unreadable)
            self.assertEqual(mod.name_problem(unreadable), problem)
        self.assertIsNone(mod.name_problem(PLAYER))

    def test_without_the_players_name_items_are_recorded_without_text_or_bytes(self):
        self.game.player_state.mNameWithTitle.value = b""  # not loaded, or not where NMS.py says
        item = self.item(text=b"Gift for someone")
        self.store(item, 0, name=b"someone's spare")
        item.contents.mLinkedEntitlementId.value = b"SOME_GIFT"
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            self.look(item)
            self.look(self.item(item_type=4))
            self.game.player_state.mNameWithTitle.value = (
                b"\x07\x13\x88garbage"  # NMS.py's place is out of date
            )
            self.look(self.item(item_type=5))
            self.look(self.item(item_type=6))
        first, second, third, fourth = self.items()
        for record in (first, second, third, fourth):
            for left_out in ("texts", "raw", "entitlement"):
                self.assertNotIn(left_out, record)
        self.assertEqual([r["nameUnread"] for r in self.items()], ["empty", "empty", "not text", "not text"])
        self.assertEqual(first["stores"][0]["size"], [7, 3, 14])
        self.assertNotIn("name", first["stores"][0])
        self.assertEqual(len(logs.output), 2, "once for each reason")
        self.assertIn(
            "Couldn't read your player name (empty); until the mod can, items are recorded", logs.output[0]
        )
        self.assertIn("Couldn't read your player name (not text)", logs.output[1])
        self.assertNotIn("someone", mod.CAPTURE_FILE.read_text(encoding="utf-8").lower())
        self.assertNotIn("garbage", "\n".join(logs.output), "the log never says what it read")

    def test_an_offer_is_paired_with_its_model_however_long_ago_the_game_built_it(self):
        # The game builds a system's multi-tools as it loads the system and offers one minutes later;
        # 0.8.2 paired an item only with a model built moments before, so it paired none.
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        self.now += 141.0
        item = self.item(handle=TOOL_HANDLE)
        self.store(item, 2, layout_seed=OTHER_TOOL_SEED)
        self.look(item)
        self.look(item, 100)  # still paired: no news
        self.store(item, 2, grade=2, layout_seed=OTHER_TOOL_SEED + 1)  # another, the handle kept
        self.look(item)
        first, second = self.items()
        self.assertEqual(first["model"]["seed"], "7A11C0DE5EED0001")
        self.assertEqual(
            (second["handle"], second.get("model")), (TOOL_HANDLE, None), "the last offer's model"
        )
        self.assertEqual(self.sounds, ["multi-tool"])

    def test_a_multi_tool_handle_the_game_hands_to_something_else_is_forgotten(self):
        self.build(MULTITOOL_MODEL, OWN_TOOL_SEED, ["_GUN_C"], handle=0x500)  # another player's, say
        self.load(0x500)  # the game reuses the number for something without a descriptor
        self.look(self.item(handle=0x500))
        (record,) = self.items()
        self.assertNotIn("model", record)
        recorded = mod.CAPTURE_FILE.read_text(encoding="utf-8")
        self.assertNotIn(f"{OWN_TOOL_SEED:016X}", recorded)
        self.assertNotIn("_GUN_C", recorded)
        self.assertEqual(self.sounds, [])
        # Nor does an item that was paired keep the model once the game hands its handle on.
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        item = self.item(item_type=4, handle=TOOL_HANDLE)
        self.look(item)
        self.load(TOOL_HANDLE)
        item.contents.mePurchaseState = 2
        self.look(item)
        self.assertEqual(
            [r.get("model", {}).get("seed") for r in self.items()[1:]], ["7A11C0DE5EED0001", None]
        )

    def test_handles_that_mean_no_resource_are_never_paired(self):
        for handle in mod.NO_HANDLE:
            self.build(MULTITOOL_MODEL, TOOL_SEED + handle % 7, ["_GUN_A"], handle=handle)
        self.assertEqual(self.capture._handle_models, {})
        self.look(self.item(handle=0xFFFFFFFF))
        (record,) = self.items()
        self.assertEqual((record["handle"], record.get("model")), (0xFFFFFFFF, None))
        self.assertEqual(mod.item_summary(record), "no inventories; no model")

    def test_only_ships_of_the_systems_list_pair_with_items(self):
        self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"], handle=31)  # one of the system's list
        self.build(FIGHTER_MODEL, OWN_SHIP_SEED, ["_COCKPIT_B"], handle=32)  # yours, say
        self.build(MULTITOOL_MODEL, 5, ["_GUN_A"])  # a seed too small to look for in an item's bytes
        self.look(self.item(handle=31))
        self.look(self.item(seeds=[OWN_SHIP_SEED, 5], handle=32))
        listed, own = self.items()
        self.assertEqual((listed["model"]["seed"], listed["tools"]), ("1111111111111111", []))
        self.assertEqual((own.get("model"), own["tools"]), (None, []))
        recorded = mod.CAPTURE_FILE.read_text(encoding="utf-8")
        self.assertNotIn(f"{OWN_SHIP_SEED:016X}", recorded)
        self.assertNotIn("_COCKPIT_B", recorded)

    def test_multi_tool_models_are_the_files_in_the_multi_tool_folder_but_its_parts(self):
        # Files 0.8.2 saw the game build: it took the effects for multi-tools.
        for name in (MULTITOOL_MODEL, ROYAL_TOOL_MODEL, "MODELS/COMMON/WEAPONS/MULTITOOL/ATLASMULTITOOL.SCENE.MBIN",
                     "MODELS/COMMON/WEAPONS/MULTITOOL/SENTINELMULTITOOL.SCENE.MBIN",
                     "MODELS\\COMMON\\WEAPONS\\MULTITOOL\\STAFFNPCMULTITOOL.SCENE.MBIN",
                     "models/common/weapons/multitool/staffmultitool.scene.mbin"):  # fmt: skip
            self.assertTrue(mod.is_multitool_model(name), name)
        for name in ("MODELS/EFFECTS/WEAPONS/PLAYER/MUZZLEFLASH.SCENE.MBIN",
                     "MODELS/EFFECTS/INEDITOR/MULTITOOL/STEAM/STEAM.SCENE.MBIN",
                     "MODELS/COMMON/WEAPONS/MULTITOOL/MULTITOOLPARTS/FISHINGFLOAT.SCENE.MBIN",
                     "MODELS/COMMON/WEAPONS/MULTITOOL.SCENE.MBIN", FIGHTER_MODEL):  # fmt: skip
            self.assertFalse(mod.is_multitool_model(name), name)
        self.assertEqual(mod.model_file(ROYAL_TOOL_MODEL), "ROYALMULTITOOL")
        self.assertEqual(mod.model_file("MODELS\\A\\B.SCENE.MBIN"), "B")

    def test_multi_tools_no_item_holds_are_never_written(self):
        # Like the multi-tool the player carries: the game builds it, but no item on offer holds it.
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.build(MULTITOOL_MODEL, OWN_TOOL_SEED, ["_GUN_C"], handle=OWN_TOOL_HANDLE)
            self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
            self.look(self.item(handle=TOOL_HANDLE))
        self.items()
        recorded = mod.CAPTURE_FILE.read_text(encoding="utf-8")
        self.assertIn("7A11C0DE5EED0001", recorded)
        for where in (recorded, "\n".join(logs.output)):
            self.assertNotIn(f"{OWN_TOOL_SEED:016X}", where)
            self.assertNotIn("_GUN_C", where)

    def test_the_multi_tools_built_while_a_system_generates_are_written_as_its_set(self):
        creature = "MODELS/PLANETS/CREATURES/QUADRUPED/QUADRUPED.SCENE.MBIN"
        self.build(MULTITOOL_MODEL, OWN_TOOL_SEED, ["_GUN_C"], handle=OWN_TOOL_HANDLE)  # yours, built before
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            with self.generation():
                self.build_set()
                self.build(creature, 0x5555555555555555, ["_HEAD_A"], handle=50)  # not a multi-tool
        self.build(MULTITOOL_MODEL, OWN_TOOL_SEED + 1, ["_GUN_D"], handle=OWN_TOOL_HANDLE + 1)  # and after
        (pool,) = self.pools()
        self.assertEqual(
            {k: v for k, v in pool.items() if k != "at"},
            {
                "t": "pool",
                "system": f"{UA:016X}",
                "tools": [
                    {
                        "name": name,
                        "type": 1,
                        "seed": f"{seed:016X}",
                        "useSeed": 1,
                        "parts": parts,
                        "handle": handle,
                    }
                    for name, seed, parts, handle in SET
                ],
            },
        )
        self.assertIn(
            "INFO:TradeDepotCapture:Recorded the 3 multi-tools of the system at 03E9F3545C3E, galaxy 1 "
            "(MULTITOOL 2, ROYALMULTITOOL 1).",
            logs.output,
        )
        self.assertEqual(self.sounds, ["multi-tool"])
        self.assertEqual(self.capture.multitools, "3 in 1 systems' sets; 0 on offer (items recorded: 0)")
        # Built lines only for what isn't in the set, and never with a seed or parts.
        self.assertEqual(
            sorted(line["handle"] for line in self.built()), [50, OWN_TOOL_HANDLE, OWN_TOOL_HANDLE + 1]
        )
        recorded = mod.CAPTURE_FILE.read_text(encoding="utf-8")
        for secret in (f"{OWN_TOOL_SEED:016X}", f"{OWN_TOOL_SEED + 1:016X}", "_GUN_C", "_GUN_D", "_HEAD_A"):
            self.assertNotIn(secret, recorded)
        self.assertEqual(self.capture._generating, {}, "nothing left open")

    def test_multi_tools_another_thread_builds_while_a_system_generates_arent_its_own(self):
        # Another player's, say, which the game may build on another thread meanwhile.
        with self.generation():
            self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
            other = threading.Thread(target=self.build, args=(MULTITOOL_MODEL, OWN_TOOL_SEED, ["_GUN_C"]),
                                     kwargs={"handle": OWN_TOOL_HANDLE})  # fmt: skip
            other.start()
            other.join()
        (pool,) = self.pools()
        self.assertEqual([tool["seed"] for tool in pool["tools"]], ["7A11C0DE5EED0001"])
        self.assertEqual(
            pool["elsewhere"], 1, "counted, so a capture shows if the game builds them elsewhere"
        )
        self.assertEqual([line["handle"] for line in self.built()], [OWN_TOOL_HANDLE])
        self.assertNotIn(f"{OWN_TOOL_SEED:016X}", mod.CAPTURE_FILE.read_text(encoding="utf-8"))
        # Built only on another thread: noted for the system, with nothing taken for its own.
        self.game.set_address(OTHER_UA)
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            with self.generation():
                other = threading.Thread(target=self.build, args=(MULTITOOL_MODEL, TOOL_SEED + 1, ["_GUN_B"]))
                other.start()
                other.join()
        noted = self.pools()[1]
        self.assertEqual(
            {k: v for k, v in noted.items() if k != "at"},
            {"t": "pool", "system": f"{OTHER_UA:016X}", "tools": [], "elsewhere": 1},
        )
        self.assertIn(
            "INFO:TradeDepotCapture:While the game generated the system at 01230EABCDEF, galaxy 1, it built 1 "
            "multi-tools on other threads and none on its own, so none were taken for the system's.",
            logs.output,
        )
        self.assertEqual(self.sounds.count("multi-tool"), 1, "no tone for the second")
        self.assertEqual(self.capture.multitools, "1 in 1 systems' sets; 0 on offer (items recorded: 0)")
        captures = report.read_captures([mod.CAPTURE_FILE])
        self.assertIn("1 system multi-tool set(s)", report.summary_lines(captures)[0])
        self.assertIn(
            "  generations during which other threads built multi-tools: 2 (2 multi-tools; 1 of them with none "
            "on the generating thread)",
            report.pool_lines(captures),
        )

    def test_a_systems_set_is_written_once_a_session_unless_it_changes(self):
        for _ in range(2):  # the same system and set twice
            with self.generation():
                self.build_set()
        with self.generation():  # the same system with another set
            self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        with self.generation():  # nothing built: nothing written
            pass
        self.game.set_address(OTHER_UA)
        for _ in range(2):  # another system with the first's set: its own record, once
            with self.generation():
                self.build_set()
        self.assertEqual(
            [(pool["system"], len(pool["tools"])) for pool in self.pools()],
            [(f"{UA:016X}", 3), (f"{UA:016X}", 1), (f"{OTHER_UA:016X}", 3)],
        )
        self.assertEqual(self.sounds, ["multi-tool"] * 2, "once for each system")
        self.assertEqual(self.capture.multitools, "4 in 2 systems' sets; 0 on offer (items recorded: 0)")

    def test_an_offer_says_which_of_the_systems_multi_tools_it_is(self):
        with self.generation():
            self.build_set()
        self.now += 140.0  # you walk up to the multi-tool case minutes later
        item = self.item(item_type=1, handle=SET[1][3])
        self.store(item, 2, size=(6, 3, 18), grade=2, layout_seed=0x33C46B92EF2FAB5F)
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.look(item)
        (record,) = self.items()
        expected = {
            "name": MULTITOOL_MODEL,
            "type": 1,
            "seed": "5EED000000000002",
            "useSeed": 1,
            "parts": ["_GUN_B"],
        }
        self.assertEqual(record["model"], dict(expected, handle=SET[1][3], pool=1))
        self.assertIn(
            "INFO:TradeDepotCapture:Recorded a multi-tool the game offers (seed 5EED000000000002, number 2 of "
            f"the system's set): {MULTITOOL_MODEL}: _GUN_B",
            logs.output,
        )
        self.assertEqual(self.sounds, ["multi-tool", "multi-tool"], "for the set, then for the offer")
        self.assertEqual(self.capture.multitools, "3 in 1 systems' sets; 1 on offer (items recorded: 1)")
        self.assertIn(", number 2 of the system's set", mod.item_summary(record))

    def test_a_systems_set_lists_each_model_once_and_is_bounded_in_size_and_time(self):
        self._patch("POOL_TOOLS", 2)
        with self.generation():
            for i in range(3):  # one too many
                self.build(MULTITOOL_MODEL, TOOL_SEED + i, ["_GUN_A"], handle=0x400 + i)
            self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=0x400)  # built again: listed once
        (pool,) = self.pools()
        self.assertEqual(
            [tool["seed"] for tool in pool["tools"]], [f"{TOOL_SEED:016X}", f"{TOOL_SEED + 1:016X}"]
        )
        self.assertEqual(self.capture._handle_models[0x400]["pool"], 0)
        self.assertEqual([line["handle"] for line in self.built()], [0x402], "the one left out")
        # A generation whose end the mod never sees stops gathering after a while.
        self.capture.before_generate(self.game.this(), False, ctypes.pointer(self.game.seed))
        self.now += mod.POOL_SECONDS + 1
        self.build(MULTITOOL_MODEL, OWN_TOOL_SEED, ["_GUN_C"], handle=OWN_TOOL_HANDLE)
        self.assertNotIn("pool", self.capture._handle_models[OWN_TOOL_HANDLE])

    def test_a_failure_recording_a_systems_set_is_reported_once_and_the_system_still_recorded(self):
        self._patch("model_file", mock.Mock(side_effect=RuntimeError("boom")))
        self.game.set_address(OTHER_UA)
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            for _ in range(2):
                with self.generation():
                    self.build_set(SET[:1])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Couldn't record a system's multi-tools.", logs.output[0])
        self.assertEqual([line["ua"] for line in self.lines() if line["t"] == "sys"][-1], f"{OTHER_UA:016X}")
        self.assertEqual(self.capture._generating, {})

    def test_an_offer_notes_what_the_resource_manager_holds_for_its_handle(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        self.resource_table({TOOL_HANDLE: (MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], 3)})
        item = self.item(handle=TOOL_HANDLE)
        self.look(item)
        self.resources[TOOL_HANDLE].muRefCount = 4  # more things hold it now: no news
        item.contents.mItemNode.lookupInt = 0x40001  # and the bytes change, so the mod looks again
        self.look(item)
        (record,) = self.items()
        self.assertEqual(
            record["resource"],
            {"slot": TOOL_HANDLE - 1, "name": MULTITOOL_MODEL, "type": 1, "refs": 3,
             "seed": "7A11C0DE5EED0001", "useSeed": 1, "parts": ["_GUN_A"]},
        )  # fmt: skip
        self.assertEqual(record["model"]["seed"], record["resource"]["seed"])

    def test_the_resource_manager_is_read_only_where_a_resource_says_it_has_the_handle(self):
        self.resource_table({0x40: (MULTITOOL_MODEL, None, [], 1), 0x41: (FIGHTER_MODEL, None, [], 2)},
                            one_based=False)  # fmt: skip
        self.assertEqual(
            mod.resource_info(0x40), {"slot": 0x40, "name": MULTITOOL_MODEL, "type": 1, "refs": 1}
        )
        self.assertEqual(mod.resource_info(0x41)["name"], FIGHTER_MODEL, "not the one before it")
        self.assertEqual(
            mod.resource_info(0x42), {"error": "no resource with this handle", "seen": [0x41, None]}
        )
        self.assertEqual(mod.resource_info(0x10000), {"error": "no resource with this handle", "seen": []})
        manager = self.resource_table({0x40: (MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], 1)})
        manager.mResources.vector_size = manager.mResources.allocated_size + 1
        self.assertRegex(
            mod.resource_info(0x40)["error"], r"^implausible resource list \(count 67 of 66, pointer 0x"
        )
        self._patch("resource_manager_address", lambda: 0xDEAD0000)
        self.assertEqual(mod.resource_info(0x40), {"error": "the resource list couldn't be read"})
        self._patch("resource_manager_address", lambda: None)
        self.assertIsNone(mod.resource_info(0x40))

    def test_what_the_resource_manager_says_of_a_ship_outside_the_lists_keeps_no_seed(self):
        self.resource_table({32: (FIGHTER_MODEL, OWN_SHIP_SEED, ["_COCKPIT_B"], 1)})
        self.look(self.item(handle=32))
        (record,) = self.items()
        self.assertEqual(record["resource"], {"slot": 31, "name": FIGHTER_MODEL, "type": 1, "refs": 1})
        recorded = mod.CAPTURE_FILE.read_text(encoding="utf-8")
        self.assertNotIn(f"{OWN_SHIP_SEED:016X}", recorded)
        self.assertNotIn("_COCKPIT_B", recorded)

    def test_a_failure_reading_the_resource_manager_is_noted_and_logged_once(self):
        self._patch("resource_info", mock.Mock(side_effect=RuntimeError("boom")))
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            self.look(self.item(handle=TOOL_HANDLE))
            self.look(self.item(item_type=4, handle=TOOL_HANDLE))
        self.assertEqual([r["resource"] for r in self.items()], [{"error": "RuntimeError: boom"}] * 2)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Couldn't read what the game's resource manager holds for an item.", logs.output[0])
        self.look(self.item(item_type=5))  # no handle: not looked up
        self.assertNotIn("resource", self.items()[-1])

    def test_the_resource_manager_is_found_where_pymhf_maps_the_games_pointer(self):
        self.assertIsNone(mod.resource_manager_address(), "NMS.py hasn't found it outside the game")
        manager = self.game._alloc(nms.cTkResourceManager)
        pointer = ctypes.pointer(manager)  # stands for the game's own pointer, which pyMHF maps in place
        self.game.memory.keep(pointer)
        with mock.patch.object(nms.cEgModules, "mgpResourceManager", pointer, create=True):
            self.assertEqual(mod.resource_manager_address(), ctypes.addressof(manager))
            ctypes.c_uint64.from_address(ctypes.addressof(pointer)).value = 0  # the game hasn't set it yet
            self.assertIsNone(mod.resource_manager_address())

    def test_built_lines_note_multi_tool_models_without_their_seed_or_parts(self):
        self._patch("TOOL_BUILDS_RECORDED", 2)
        creature = "MODELS/PLANETS/CREATURES/QUADRUPED/QUADRUPED.SCENE.MBIN"
        self.place(PLANET_ON_FOOT, 0)
        for handle in (40, 41, 42):  # the third is one too many
            self.build(MULTITOOL_MODEL, OWN_TOOL_SEED + handle, ["_GUN_C", "_GRIP_D"], handle=handle)
        self.build(creature, 0x5555555555555555, ["_HEAD_A"], handle=50)
        self.build(creature, 0x5555555555555556, ["_HEAD_B"], handle=51)  # the same file: noted once
        self.build("TEXTURES/PLANETS/ROCK.DDS", 0x6666666666666666, [], handle=52)  # no parts: never
        self.build(FIGHTER_MODEL, OWN_SHIP_SEED, ["_COCKPIT_B"], handle=53)  # ships: never
        place = {"system": f"{UA:016X}", "where": PLANET_ON_FOOT}
        self.assertEqual(
            [{k: v for k, v in line.items() if k != "at"} for line in self.built()],
            [
                {"t": "built", "name": MULTITOOL_MODEL, "type": 1, "parts": 2, "handle": 40, **place},
                {"t": "built", "name": MULTITOOL_MODEL, "type": 1, "parts": 2, "handle": 41, **place},
                {"t": "built", "name": creature, "type": 1, "parts": 1, "handle": 50, **place},
            ],
        )
        recorded = mod.CAPTURE_FILE.read_text(encoding="utf-8")
        for secret in ("_GUN_C", "_HEAD_A", f"{OWN_TOOL_SEED + 40:016X}", "5555555555555555", "_COCKPIT_B"):
            self.assertNotIn(secret, recorded)

    def test_a_built_line_says_so_when_where_you_were_cant_be_read(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=40)
        self.game.generate(self.capture)  # something else waits to be written too
        self._patch("player_environment", mock.Mock(side_effect=RuntimeError("boom")))
        with self.assertLogs("TradeDepotCapture", "WARNING"):
            (line,) = self.built()
        self.assertEqual((line["system"], line["where"]), (None, None))

    def test_a_failure_looking_at_an_item_is_reported_once_and_the_game_carries_on(self):
        self._patch("offered_item", mock.Mock(side_effect=RuntimeError("boom")))
        item = self.item()
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            for _ in range(3):
                self.assertIsNone(self.capture.before_item_update(item, 0.016, 0, 0))
                self.now += mod.ITEM_CHECK_SECONDS
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Couldn't record an item the game offers.", logs.output[0])

    def test_what_the_mod_keeps_in_memory_is_bounded(self):
        for name, value in (("MODELS_KEPT", 2), ("ITEMS_TRACKED", 2), ("OTHER_BUILDS_RECORDED", 1)):
            self._patch(name, value)
        for i in range(4):
            self.build(MULTITOOL_MODEL, TOOL_SEED + i, ["_GUN_A"], handle=60 + i)
            creature = f"MODELS/PLANETS/CREATURES/C{i}.SCENE.MBIN"
            self.build(creature, OWN_TOOL_SEED + i, ["_HEAD_A"], handle=70 + i)
            self.capture._item_updated(self.item())
        self.assertEqual(len(self.capture._recent_models), 2)
        self.assertEqual(len(self.capture._handle_models), 2)
        self.assertEqual(len(self.capture._items), 2)
        self.assertEqual(sum("CREATURES" in line["name"] for line in self.built()), 1)
        results = [self.game._alloc(nms.cTkSmartResHandle) for _ in range(300)]
        for result in results:  # AddResource never returning to the mod
            descriptor, name = self.descriptor(TOOL_SEED, []), self.name_pointer(MULTITOOL_MODEL)
            self.capture.before_add_resource(ctypes.pointer(result), 1, name, 0, descriptor, 0)
        self.assertEqual(len(self.capture._building), 256)

    def test_a_model_another_thread_is_building_is_left_to_that_thread(self):
        other = (threading.get_ident() + 1, 0x1000)
        self.capture._building[other] = {"name": MULTITOOL_MODEL, "type": 1, "parts": [], "seed": "0"}
        self.load(0x700)  # this thread loads something without a descriptor meanwhile
        self.assertIn(other, self.capture._building)
        self.assertEqual(self.capture._handle_models, {})

    def test_a_new_offer_isnt_paired_with_the_last_offers_model_however_long_it_stays_on(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        item = self.item(handle=TOOL_HANDLE)
        self.store(item, 2, layout_seed=TOOL_SEED)
        self.look(item)
        self.store(item, 2, grade=1, layout_seed=OTHER_TOOL_SEED)  # the next offer, the last model still on
        self.look(item, 3)
        self.build(MULTITOOL_MODEL, OTHER_TOOL_SEED, ["_GUN_B"], handle=TOOL_HANDLE + 1)
        item.contents.mItemResource.miInternalHandle = TOOL_HANDLE + 1
        self.look(item)
        records = self.items()
        self.assertEqual(
            [(r["stores"][0]["layout"][0], r.get("model", {}).get("seed")) for r in records],
            [("7A11C0DE5EED0001", "7A11C0DE5EED0001"), ("0D0D0D0D0D0D0D0D", None),
             ("0D0D0D0D0D0D0D0D", "0D0D0D0D0D0D0D0D")],
        )  # fmt: skip
        self.assertEqual(records[1]["handle"], TOOL_HANDLE)

    def test_an_offer_keeps_its_model_after_the_mod_has_forgotten_the_handle(self):
        self._patch("MODELS_KEPT", 1)
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        item = self.item(handle=TOOL_HANDLE)
        self.look(item)
        self.build(MULTITOOL_MODEL, OWN_TOOL_SEED, ["_GUN_C"], handle=OWN_TOOL_HANDLE)  # pushes it out
        self.assertNotIn(TOOL_HANDLE, self.capture._handle_models)
        self.now += 2 * mod.ITEM_REFRESH_SECONDS
        item.contents.mePurchaseState = 2  # something else changes
        self.look(item)
        self.assertEqual([r["model"]["seed"] for r in self.items()], ["7A11C0DE5EED0001"] * 2)

    def test_a_pairing_is_kept_while_the_offer_settles(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        self.now += 300.0
        item = self.item(handle=TOOL_HANDLE)
        for state in (1, 2, 3, 3):  # something else settles only later
            item.contents.mePurchaseState = state
            self.look(item, 1)
        self.now += 10.0  # and the game stops updating it for a few seconds
        item.contents.mePurchaseState = 4
        self.look(item)
        self.assertEqual([(r["state"], r["model"]["seed"]) for r in self.items()],
                         [(3, "7A11C0DE5EED0001"), (4, "7A11C0DE5EED0001")])  # fmt: skip

    def test_another_item_at_the_same_address_later_isnt_paired_with_the_last_ones_model(self):
        self._patch("MODELS_KEPT", 1)
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        item = self.item(handle=TOOL_HANDLE)
        self.look(item)
        self.build(MULTITOOL_MODEL, OWN_TOOL_SEED, ["_GUN_C"], handle=OWN_TOOL_HANDLE)  # forgets the handle
        self.now += mod.ITEM_FORGET_SECONDS + 1  # the game stops updating it; a new item gets its place
        item.contents.mePurchaseState = 2
        self.look(item)
        self.assertEqual([r.get("model", {}).get("seed") for r in self.items()], ["7A11C0DE5EED0001", None])

    def test_a_pairing_ends_when_the_game_builds_another_model_with_the_handle(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        item = self.item(handle=TOOL_HANDLE)
        self.look(item)
        self.build(FIGHTER_MODEL, OWN_SHIP_SEED, ["_COCKPIT_B"], handle=TOOL_HANDLE)  # the number reused
        self.now += 60.0
        item.contents.mePurchaseState = 2
        self.look(item)
        self.assertEqual([r.get("model", {}).get("seed") for r in self.items()], ["7A11C0DE5EED0001", None])

    def test_an_item_that_never_settles_is_recorded_as_it_is_and_said_so(self):
        item = self.item()
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            for look in range(mod.ITEM_UNSETTLED_LOOKS * 2):
                item.contents.mePurchaseState = look % 3
                self.look(item, 1)
        records = self.items()
        self.assertEqual([(r["unsettled"], r["state"]) for r in records], [(1, 1), (1, 0)])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("hasn't looked the same twice in 20 looks", logs.output[0])

    def test_an_unchanged_item_is_decoded_again_only_every_few_seconds(self):
        decoded = []
        offered_item = mod.offered_item
        self._patch("offered_item", lambda raw: decoded.append(1) or offered_item(raw))
        item = self.item()
        self.look(item, 2)  # settles and is recorded
        self.look(item, int(mod.ITEM_REFRESH_SECONDS / mod.ITEM_CHECK_SECONDS) - 1)  # the same bytes
        self.assertEqual(len(decoded), 2)
        self.look(item, 1)
        self.assertEqual(len(decoded), 3, "decoded again for what its inventories point to")
        item.contents.mePurchaseState = 3
        self.look(item, 1)
        self.assertEqual(len(decoded), 4, "its bytes changed")

    def test_after_a_load_without_a_descriptor_the_mod_takes_no_lock_unless_it_must(self):
        class CountingLock:
            def __init__(self, lock):
                self.lock, self.taken = lock, 0

            def __enter__(self):
                self.taken += 1
                return self.lock.__enter__()

            def __exit__(self, *exc):
                return self.lock.__exit__(*exc)

        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)  # a handle the mod watches
        self.capture._building[(threading.get_ident() + 1, 0x1000)] = {"name": "X", "parts": []}  # elsewhere
        lock = self.capture._lock = CountingLock(self.capture._lock)
        self.load(0x900)
        self.assertEqual(lock.taken, 0)
        self.load(TOOL_HANDLE)  # the multi-tool's handle, reused: that needs the lock
        self.assertEqual(lock.taken, 1)

    def test_every_handle_the_mod_has_a_model_for_is_watched_however_long_ago_it_was_built(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A"], handle=TOOL_HANDLE)
        self.build(FIGHTER_MODEL, 0x1111111111111111, ["_COCKPIT_A"], handle=31)
        self.now += 3600.0
        self.poll()
        self.load(0x900)  # a handle the mod has no model for: nothing to forget
        self.load(31)  # the ship's handle, handed to a texture
        self.assertEqual(sorted(self.capture._handle_models), [31, TOOL_HANDLE])
        self.assertIsNone(self.capture._handle_models[31])
        self.assertEqual(self.capture._handle_models[TOOL_HANDLE]["seed"], "7A11C0DE5EED0001")
        self.look(self.item(handle=31))
        self.look(self.item(item_type=4, handle=TOOL_HANDLE))
        self.assertEqual([r.get("model", {}).get("seed") for r in self.items()], [None, "7A11C0DE5EED0001"])
        self.build(FIGHTER_MODEL, 0x2222222222222222, ["_COCKPIT_B"], handle=31)  # a model again
        self.assertEqual(self.capture._handle_models[31]["seed"], "2222222222222222")

    def test_seeds_are_found_at_any_four_byte_boundary(self):
        raw = bytes(4) + (0x1122334455667788).to_bytes(8, "little") + bytes(20) + (9).to_bytes(8, "little")
        self.assertEqual(mod.seeds_in(raw, {0x1122334455667788, 9}), [(4, 0x1122334455667788), (32, 9)])
        self.assertEqual(mod.seeds_in(raw + raw, {9: "a dict will do"}), [(32, 9)], "each once, at its first")
        self.assertEqual(mod.seeds_in(raw[:11], {0x1122334455667788}), [])

    def test_turning_multi_tools_off_leaves_the_functions_alone(self):
        source = harness.MOD_PATH.read_text(encoding="utf-8")
        self.assertIn("\nRECORD_MULTITOOLS = True\n", source)
        path = Path(self._tmp.name) / "system_capture_without_tools.py"
        path.write_text(source.replace("\nRECORD_MULTITOOLS = True\n", "\nRECORD_MULTITOOLS = False\n"))
        spec = importlib.util.spec_from_file_location("system_capture_without_tools", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        capture = module.TradeDepotCapture()
        hooks = {hook.__name__ for hook in capture.hooks}
        self.assertFalse(hooks & {"before_item_update", "after_add_resource"})
        self.assertIn("before_add_resource", hooks)
        self.assertEqual(capture.multitools, "Off (RECORD_MULTITOOLS is False)")
        capture.before_generate(self.game.this(), False, ctypes.pointer(self.game.seed))
        self.assertEqual(capture._generating, {}, "no system's set gathered")

    def test_report_lists_each_systems_multi_tools_and_which_one_is_on_offer(self):
        self.game.player_state.mNameWithTitle.value = b""
        with self.generation():
            self.build_set()
        self.resource_table({SET[1][3]: (MULTITOOL_MODEL, SET[1][1], SET[1][2], 2)})
        self.look(self.item(item_type=1, handle=SET[1][3]))
        self.load(
            SET[2][3]
        )  # the game hands the royal's handle to something else, as far as the mod can tell
        self.look(self.item(item_type=2, handle=SET[2][3]))
        self.items()
        with mod.CAPTURE_FILE.open("a", encoding="utf-8") as stream:  # the same set, recorded another time
            stream.write(json.dumps(self.pools()[0]) + "\n")
        captures = report.read_captures([mod.CAPTURE_FILE])
        self.assertIn("2 system multi-tool set(s), 2 offered item(s)", report.summary_lines(captures)[0])
        text = "\n".join(report.pool_lines(captures))
        self.assertIn(
            "Systems' own multi-tools: 2 set(s) for 1 system(s), 6 multi-tools (MULTITOOL 4, ROYALMULTITOOL 2)",
            text,
        )
        self.assertIn("  multi-tools per set: 3 x2", text)
        self.assertIn("  systems recorded more than once: 1; with the same set each time: 1", text)
        self.assertIn("  seeds in more than one system's set: 0", text)
        self.assertIn(
            "  03E9F3545C3E galaxy 1 Shown-Name: MULTITOOL 5EED000000000001 (2 parts), "
            "MULTITOOL 5EED000000000002 (1 parts), ROYALMULTITOOL 5EED000000000003 (1 parts)",
            text,
        )
        items = "\n".join(report.item_lines(captures))
        self.assertIn(
            "item type 1, nameUnread (empty), state 1: no inventories, model MULTITOOL 5EED000000000002 "
            "(number 2 of the system's set): _GUN_B, resource MULTITOOL, 2 holding it, the same model",
            items,
        )
        self.assertIn(
            "item type 2, nameUnread (empty), state 1: no inventories, model handle 200706, not paired, "
            "number 3 of the system's set by its handle",
            items,
        )

    def test_report_lists_the_items_offered_and_the_multi_tool_models_built(self):
        self.build(MULTITOOL_MODEL, TOOL_SEED, ["_GUN_A", "_HANDLE_B"], handle=TOOL_HANDLE)
        item = self.item(handle=TOOL_HANDLE, text=b"Glimmer of the Void AB1-C23")
        laser = ("LASER", 0, 0, 100, 100, 1, 0.0, 1, 1)
        self.store(item, 0, entries=[laser], stats=[("WEAPON_DAMAGE", 1.25)])
        self.store(item, 2, size=(8, 3, 20), grade=3, layout_seed=TOOL_SEED)
        self.look(item)
        self.look(self.item(item_type=5, handle=9))
        self.items()
        with mod.CAPTURE_FILE.open("a", encoding="utf-8") as stream:  # as 0.8.1 wrote them
            old = {"t": "item", "at": 1, "system": f"{UA:016X}", "where": 2, "planet": 1, "itemType": 1}
            old.update(state=0, free=0, gift=0, reward=0, tools=[], raw="eJwDAAAAAAE=")
            stream.write(json.dumps(old) + "\n")
        captures = report.read_captures([mod.CAPTURE_FILE])
        self.assertIn("3 offered item(s), 1 model build note(s)", report.summary_lines(captures)[0])
        text = "\n".join(report.item_lines(captures))
        offered = "Items the game offered: 3 record(s), 1 with a multi-tool's model"
        self.assertIn(f"{offered} (item types: 1 x1, 3 x1, 5 x1)", text)
        place = "  03E9F3545C3E galaxy 1 Abarof-Dulin, SpaceStation, nearest planet 1, item type"
        self.assertIn(
            f"{place} 3, state 1: inventories [0] 7x3, 14 slots, class C, 1 in it, stats WEAPON_DAMAGE=1.25; "
            "[2] 8x3, 20 slots, class S, layout seed 7A11C0DE5EED0001, model MULTITOOL 7A11C0DE5EED0001: "
            "_GUN_A _HANDLE_B, seed of MULTITOOL 7A11C0DE5EED0001 at byte 0xa60: _GUN_A _HANDLE_B, "
            "text 'Glimmer of the Void AB1-C23'",
            text,
        )
        self.assertIn(f"{place} 5, state 1: no inventories, model handle 9, not paired", text)
        self.assertIn(f"{place} 1, state 0: bytes only", text)
        self.assertIn("multi-tools: 1; offered in more than one system: 0", text)
        built = "Multi-tool models the game built (seeds and parts not recorded): 1 (MULTITOOL 1)"
        self.assertIn(built, text)
        self.assertIn("other model files with parts: 0", text)
        self.assertIn("Abarof-Dulin, SpaceStation: MULTITOOL, 2 parts, handle 4660", text)


class DiagnosticsTests(CaptureTestCase):
    def test_steam_build_comes_from_the_app_manifest(self):
        library = Path(self._tmp.name) / "SteamLibrary" / "steamapps"
        exe = library / "common" / "No Man's Sky" / "Binaries" / "NMS.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        (library / "appmanifest_275850.acf").write_text(
            '"AppState"\n{\n\t"appid"\t\t"275850"\n\t"buildid"\t\t"19876543"\n}\n'
        )
        self.assertEqual(mod.steam_build(str(exe)), "19876543")
        self.assertIsNone(mod.steam_build(str(Path(self._tmp.name) / "elsewhere" / "NMS.exe")))
        self.assertIsNone(mod.steam_build(None))

    def test_hook_status_reports_attached_disabled_and_missing_hooks(self):
        from pymhf.core.hooking import hook_manager

        fake = types.SimpleNamespace(
            _before_detours=[self.capture.before_generate],
            _after_detours=[self.capture.after_generate],
            _after_detours_with_results=[],
            _disabled_detours={self.capture.after_planet_name},
            state="enabled",
        )
        hook_manager.hooks["test"] = fake
        self.addCleanup(hook_manager.hooks.pop, "test")
        status = mod.hook_status(self.capture)
        self.assertEqual(status["before_generate"], "enabled")
        self.assertEqual(status["after_generate"], "enabled")
        self.assertEqual(status["after_planet_name"], "disabled")
        self.assertEqual(status["after_region_name"], "not found")
        self.assertEqual(set(status), {hook.__name__ for hook in self.capture.hooks})

    def test_session_header_carries_the_diagnostics(self):
        self.game.generate(self.capture)
        header = self.lines()[0]
        self.assertIsNone(header["steamBuild"], "no game binary in the tests")
        self.assertEqual(set(header["hooks"]), {hook.__name__ for hook in self.capture.hooks})


class LookupTests(CaptureTestCase):
    def lookup(self, seed: int, ships=SHIPS, steps: bool = False, positions=()) -> None:
        """A GenerateQueryInfo call on a generator that isn't generating a loaded system;
        with ``steps``, the basics, positions and biomes steps run inside it, and with
        ``positions``, its bodies are where they say."""
        generator = self.game._alloc(nms.cGcSolarSystemGenerator)
        data = self.game._alloc(nmse.cGcSolarSystemData)
        generation = self.game._alloc(nms.cGcSolarSystemGenerator.GenerationData)
        generation.mMetaData = ctypes.pointer(data)
        query_seed = self.game._alloc(basic.GcSeed)
        query_seed.Seed = seed
        self.game.set_rng(report.seeded_state(seed), generator)
        pointer = self.game.generator_pointer(generator)
        self.capture.before_query(pointer, ctypes.pointer(query_seed), None, ctypes.pointer(generation))
        if steps:
            stream = report.stream_states(seed, 40)
            for name, state in (
                ("before_basics", report.seeded_state(seed)),
                ("after_basics", report.seeded_state(seed)),
                ("before_positions", report.seeded_state(seed)),
                ("after_positions", stream[5]),
                ("before_biomes", stream[5]),
                ("after_biomes", stream[9]),
            ):
                self.game.set_rng(state, generator)
                if "basics" in name:
                    args = (ctypes.pointer(query_seed), None, ctypes.pointer(self.game.keys), None)
                else:
                    args = (None, None, None)
                getattr(self.capture, name)(pointer, *args)
        data.Seed.Seed = seed
        data.StarType = 3
        data.Planets = len(positions)
        for slot, (x, y, z) in zip(data.PlanetPositions, positions):
            slot.x, slot.y, slot.z = x, y, z
        self.game.set_rng(report.stream_states(seed, 40)[39], generator)
        array = (nmse.cGcAISpaceshipPreloadCacheData * len(ships))()
        self.game.memory.keep(array)
        self.game._keep.append(array)
        for entry, (ship_seed, ship_class, *_rest) in zip(array, ships):
            entry.Seed.Seed = ship_seed
            entry.ShipClass = ship_class
        data.SystemShips.ArrayPointer = ctypes.addressof(array)
        data.SystemShips.Size = len(ships)
        self.capture.after_query(pointer, ctypes.pointer(query_seed), None, ctypes.pointer(generation))

    def test_lookup_is_queued_then_written_from_the_main_loop(self):
        self.lookup(0x0000ABC012345678)
        self.assertEqual(self.lines(), [], "written by the main loop, not the hook")
        self.game.loaded = False
        self.poll()
        header, query = self.lines()
        self.assertEqual(header["t"], "session")
        self.assertEqual(query["t"], "query")
        self.assertEqual(query["seed"], "0000ABC012345678")
        self.assertEqual(query["star"], 3)
        self.assertEqual([row[0] for row in query["ships"]], [f"{s[0]:016X}" for s in SHIPS])
        self.assertEqual([label for label, _ in query["trace"]], ["query>", "query<"])
        self.assertEqual(self.capture.lookups, "1")
        lines = report.trace_lines(report.read_captures([mod.CAPTURE_FILE]))
        self.assertIn("lookup 0000ABC012345678: query>0 query<40", "\n".join(lines))

    def test_steps_inside_a_lookup_join_its_trace_with_its_key_attributes(self):
        self.lookup(0x0000ABC012345678, steps=True)
        self.game.loaded = False
        self.poll()
        query = self.lines()[1]
        labels = ["query>", "basics>", "basics<", "positions>", "positions<", "biomes>", "biomes<", "query<"]
        self.assertEqual([label for label, _ in query["trace"]], labels)
        self.assertEqual(query["keyAttributes"]["anomaly"], "01020304")
        lines = report.trace_lines(report.read_captures([mod.CAPTURE_FILE]))
        self.assertIn(
            "lookup 0000ABC012345678: query>0 basics>0 basics<0 positions>0 positions<6 biomes>6 biomes<10 "
            "query<40",
            "\n".join(lines),
        )

    def test_a_lookup_records_where_its_bodies_are(self):
        moons = [(1000.25, -2.5, 300.0), (196541.6, 112896.0, 300.0), (-143186.3, -112896.0, 132386.5)]
        self.lookup(0x0000ABC012345678, steps=True, positions=moons)
        self.lookup(0x0000ABC012345679, steps=True)
        self.game.loaded = False
        self.poll()
        placed, unplaced = self.lines()[1:]
        self.assertEqual(
            placed["positions"],
            [[1000.2, -2.5, 300.0], [196541.6, 112896.0, 300.0], [-143186.3, -112896.0, 132386.5]],
        )
        self.assertNotIn("positions", unplaced, "nothing placed: nothing recorded")

    def test_each_seed_is_looked_up_once(self):
        self.lookup(0x0000ABC012345678)
        self.lookup(0x0000ABC012345678)
        self.lookup(0x0000ABC012345679)
        self.game.loaded = False
        self.poll()
        self.assertEqual([line["t"] for line in self.lines()], ["session", "query", "query"])


class PollingTests(CaptureTestCase):
    def test_settled_system_is_recorded_once_with_its_shown_name(self):
        self.poll()
        self.assertEqual(self.lines(), [], "first sighting only starts the settling interval")
        self.assertEqual(self.sounds, [])
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.poll()
        lines = self.lines()
        self.assertEqual([line["t"] for line in lines], ["session", "sys"])
        self.assertEqual(lines[1]["via"], "poll")
        self.assertEqual(lines[1]["displayName"], "Shown-Name")
        self.assertNotIn("arg", lines[1])
        self.assertIn("Recorded Shown-Name (03E9F3545C3E, galaxy 1)", "\n".join(logs.output))
        self.poll()
        self.assertEqual(len(self.lines()), 2)

    def test_arrival_tone_plays_once_per_system(self):
        other = (0x123 << 40) | (1 << 32) | 0x01020304
        visits = [
            (UA, 1),
            (UA | (5 << 52), 1),  # the same system, with a planet digit in its address
            (other, 2),
            (UA, 2),  # back again
        ]
        for ua, tones in visits:
            with self.subTest(ua=f"{ua:016X}"):
                self.game.set_address(ua)
                self.game.fill(ua, "Somewhere")
                self.poll()
                self.poll()
                self.assertEqual(self.sounds, ["recorded"] * tones)

    def test_arrival_tone_waits_for_a_generated_system_to_settle(self):
        self.game.generate(self.capture)
        self.assertEqual(self.sounds, [])
        self.poll()
        self.poll()
        self.assertEqual(self.sounds, ["recorded"])

    def test_arrival_tone_can_be_turned_off(self):
        self._patch("CHIME_ON_ARRIVAL", False)
        self.poll()
        self.poll()
        self.assertEqual(len(self.lines()), 2)
        self.assertEqual(self.sounds, [])

    def test_no_arrival_tone_without_a_record(self):
        blocker = Path(self._tmp.name) / "blocked"
        blocker.write_text("not a folder")
        self._patch("CAPTURE_DIR", blocker)
        self._patch("CAPTURE_FILE", blocker / "systems.jsonl")
        with self.assertLogs("TradeDepotCapture", "WARNING"):
            self.poll()
            self.poll()
        self.assertEqual(self.sounds, [])

    def test_poll_adds_the_name_to_a_generated_system(self):
        self.game.generate(self.capture)
        self.poll()
        self.poll()
        lines = self.lines()
        self.assertEqual([line.get("via") for line in lines], [None, "gen", "poll"])
        self.assertEqual(lines[2]["displayName"], "Shown-Name")

    def test_poll_does_not_duplicate_an_identical_record(self):
        self.poll()
        self.poll()
        self.capture._last_polled = None  # force a re-read of the same system
        self.poll()
        self.assertEqual(len(self.lines()), 2)

    def test_name_failure_is_reported_once_and_the_record_still_written(self):
        def broken(address):
            raise OSError("no name")

        self._patch("system_display_name", broken)
        with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
            self.poll()
            self.poll()
        self.assertNotIn("displayName", self.lines()[1])
        self.assertEqual(sum("Couldn't get the system's name" in line for line in logs.output), 1)

    def test_ships_filled_in_after_generation_are_recorded(self):
        self.game.set_ships([])
        self.game.generate(self.capture)
        self.game.set_ships(SHIPS)
        self.poll()
        self.poll()
        lines = self.lines()
        self.assertEqual([line.get("via") for line in lines], [None, "gen", "poll"])
        self.assertEqual(len(lines[2]["ships"]), 3)

    def test_polls_wait_for_the_interval(self):
        self.poll()
        self.capture.on_frame()  # next poll is POLL_SECONDS away
        self.assertEqual(self.lines(), [])

    def test_nothing_happens_before_a_game_is_loaded(self):
        self.game.loaded = False
        self.poll()
        self.poll()
        self.assertEqual(self.lines(), [])

    def test_record_button(self):
        self.capture.record_now()
        self.capture.on_frame()
        lines = self.lines()
        self.assertEqual(lines[1]["via"], "btn")
        self.assertEqual(self.sounds, ["recorded"])
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture.record_now()
            self.capture.on_frame()
        self.assertEqual(len(self.lines()), 2)
        self.assertIn("Already recorded this session", "\n".join(logs.output))
        self.assertEqual(self.capture.status, "Already recorded; nothing has changed.")
        self.assertEqual(self.sounds, ["recorded", "recorded"], "in the file either way")
        self.poll()
        self.poll()
        self.assertEqual(self.sounds, ["recorded", "recorded"], "no arrival tone after a manual record")

    def test_record_button_records_on_the_next_frame(self):
        self.capture.record_now()
        self.assertEqual(self.capture.status, "Recording the current system...")
        self.capture.on_frame()
        self.assertEqual(self.lines()[1]["via"], "btn")
        self.assertEqual(self.sounds, ["recorded"])

    def test_record_button_without_a_system(self):
        self.game.loaded = False
        self.capture.record_now()
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture.on_frame()
        expected = "INFO:TradeDepotCapture:Couldn't record: no star system is loaded yet."
        self.assertEqual(
            logs.output, ["INFO:TradeDepotCapture:Found the game. Recording from now on.", expected]
        )
        self.assertEqual(self.capture.status, "No star system is loaded yet.")
        self.assertEqual(self.sounds, ["problem"])

    def test_record_button_when_the_record_cant_be_written(self):
        blocker = Path(self._tmp.name) / "blocked"
        blocker.write_text("not a folder")
        self._patch("CAPTURE_DIR", blocker)
        self._patch("CAPTURE_FILE", blocker / "systems.jsonl")
        self.capture.record_now()
        with self.assertLogs("TradeDepotCapture", "WARNING"):
            self.capture.on_frame()
        self.assertEqual(self.sounds, ["problem"])


class ApplicationTests(CaptureTestCase):
    """Until NMS.py finds the game's application object, the mod can't see the game."""

    def setUp(self):
        super().setUp()
        from nmspy.common import GameData

        self.data = GameData()
        self._patch("gameData", self.data)

    def found(self) -> None:
        """Do what NMS.py does when the game's state machine first changes state."""
        data = self.game._alloc(nms.cGcApplication.Data)
        data.mSimulation.mpSolarSystem = ctypes.cast(self.game.address, ctypes.POINTER(nms.cGcSolarSystem))
        data.mSimulation.mCurrentUA = UA
        app = self.game._alloc(nms.cGcApplication)
        app.mpData = ctypes.pointer(data)
        self.data.GcApplication = app

    def test_the_mod_never_sets_the_application_itself(self):
        for _ in range(3):
            self.poll()
        self.assertIsNone(self.data.GcApplication)
        self.assertEqual(self.lines(), [], "no application yet: no system")

    def test_says_once_when_it_cant_see_the_game(self):
        notice = mod.FIND_GAME_NOTICE_SECONDS
        with self.assertNoLogs("TradeDepotCapture", "INFO"):
            self.assertFalse(self.capture._watch_for_game(100.0))
            self.assertFalse(self.capture._watch_for_game(100.0 + notice - 0.5))
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.assertFalse(self.capture._watch_for_game(100.0 + notice))
            self.assertFalse(self.capture._watch_for_game(100.0 + notice * 3))
        self.assertEqual(logs.output, [f"INFO:TradeDepotCapture:{mod.NOT_FOUND_YET}"])
        self.assertEqual(self.capture.status, mod.NOT_FOUND_YET)
        self.assertIn("galaxy map", mod.NOT_FOUND_YET)

    def test_says_when_it_finds_the_game(self):
        self.capture._watch_for_game(0.0)
        with self.assertLogs("TradeDepotCapture", "INFO"):
            self.capture._watch_for_game(mod.FIND_GAME_NOTICE_SECONDS)
        self.found()
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.assertTrue(self.capture._watch_for_game(mod.FIND_GAME_NOTICE_SECONDS + 1))
        self.assertEqual(logs.output, ["INFO:TradeDepotCapture:Found the game. Recording from now on."])
        self.assertEqual(self.capture.status, "Waiting for a star system to load.")
        with self.assertNoLogs("TradeDepotCapture", "INFO"):
            self.assertTrue(self.capture._watch_for_game(mod.FIND_GAME_NOTICE_SECONDS + 2))

    def test_found_at_once_says_so_once(self):
        self.found()
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.assertTrue(self.capture._watch_for_game(0.0))
            self.assertTrue(self.capture._watch_for_game(mod.FIND_GAME_NOTICE_SECONDS * 2))
        self.assertEqual(logs.output, ["INFO:TradeDepotCapture:Found the game. Recording from now on."])
        self.assertEqual(self.capture.status, "Waiting for a star system to load.")

    def test_record_button_before_the_game_is_found_says_why(self):
        self.capture.record_now()
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture.on_frame()
        self.assertIn(f"Couldn't record: {mod.NOT_FOUND_YET}", "\n".join(logs.output))
        self.assertEqual(self.capture.status, mod.NOT_FOUND_YET)
        self.assertEqual(self.sounds, ["problem"])

    def test_the_loaded_system_is_seen_once_nmspy_finds_the_game(self):
        self.poll()
        self.poll()
        self.assertEqual(self.lines(), [], "no application yet: no system")
        self.found()
        self.poll()
        self.poll()
        (record,) = [line for line in self.lines() if line["t"] == "sys"]
        self.assertEqual((record["via"], record["ua"], record["sim"]), ("poll", f"{UA:016X}", f"{UA:016X}"))
        self.assertEqual(self.sounds, ["recorded"])


class SoundTests(unittest.TestCase):
    def fake_winsound(self, play):
        return types.SimpleNamespace(SND_MEMORY=4, SND_NODEFAULT=2, PlaySound=play)

    def test_tone_is_a_wav_of_the_notes(self):
        data = mod.tone([(440.0, 0.1), (0.0, 0.05), (880.0, 0.1)], volume=0.5, rate=8000)
        with wave.open(io.BytesIO(data)) as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 8000))
            samples = array.array("h", wav.readframes(wav.getnframes()))
        if sys.byteorder == "big":
            samples.byteswap()
        self.assertEqual(len(samples), 800 + 400 + 800)
        self.assertEqual((samples[0], samples[799], samples[1200], samples[-1]), (0, 0, 0, 0), "faded")
        self.assertEqual(set(samples[800:1200]), {0}, "the rest is silent")
        self.assertLessEqual(max(map(abs, samples)), round(32767 * 0.5))
        self.assertGreater(max(map(abs, samples[:800])), 32767 * 0.5 * 0.7)

    def test_every_sound_is_a_short_wav(self):
        self.assertEqual(set(mod.SOUNDS), {"recorded", "exotic parts", "multi-tool", "problem"})
        self.assertEqual(len({tuple(notes) for notes in mod.SOUNDS.values()}), 4, "each sound is different")
        for name, notes in mod.SOUNDS.items():
            with self.subTest(name=name):
                data = mod.tone(notes)
                self.assertEqual((data[:4], data[8:12]), (b"RIFF", b"WAVE"))
                self.assertLess(sum(seconds for _, seconds in notes), 0.5)

    def test_sounds_are_built_at_startup_unless_turned_off(self):
        with mock.patch.object(mod, "_sound_cache", {}):
            mod.prepare_sounds()
            self.assertEqual(set(mod._sound_cache), set(mod.SOUNDS))
        with mock.patch.object(mod, "_sound_cache", {}), mock.patch.object(mod, "PLAY_SOUNDS", False):
            mod.prepare_sounds()
            self.assertEqual(mod._sound_cache, {})

    def test_sounds_play_from_memory_on_their_own_thread(self):
        calls = []

        def play(data, flags):
            calls.append((bytes(data[:4]), flags, threading.current_thread().name))

        with mock.patch.dict(sys.modules, {"winsound": self.fake_winsound(play)}):
            thread = mod.play_sound("recorded")
            thread.join(5)
        self.assertEqual(calls, [(b"RIFF", 4 | 2, "TradeDepotSound")])

    def test_sound_failures_are_logged_once_per_sound(self):
        def play(data, flags):
            raise RuntimeError("Failed to play sound")

        with mock.patch.object(mod, "_sound_failed", set()):
            with mock.patch.dict(sys.modules, {"winsound": self.fake_winsound(play)}):
                with self.assertLogs("TradeDepotCapture", "WARNING") as logs:
                    for _ in range(2):
                        mod.play_sound("problem").join(5)
        self.assertEqual(sum("Couldn't play the 'problem' sound." in line for line in logs.output), 1)

    def test_no_sound_when_turned_off_unknown_or_unavailable(self):
        play = mock.Mock()
        with mock.patch.dict(sys.modules, {"winsound": self.fake_winsound(play)}):
            with mock.patch.object(mod, "PLAY_SOUNDS", False):
                self.assertIsNone(mod.play_sound("recorded"))
            self.assertIsNone(mod.play_sound("no such sound"))
        with mock.patch.dict(sys.modules, {"winsound": None}):  # importing it fails, as off Windows
            with mock.patch.object(mod.sys, "platform", "linux"), self.assertNoLogs("TradeDepotCapture"):
                self.assertIsNone(mod.play_sound("recorded"))
        play.assert_not_called()

    def test_missing_winsound_on_windows_is_logged_once(self):
        with (
            mock.patch.object(mod, "_sound_failed", set()),
            mock.patch.dict(sys.modules, {"winsound": None}),
            mock.patch.object(mod.sys, "platform", "win32"),
            self.assertLogs("TradeDepotCapture", "WARNING") as logs,
        ):
            self.assertIsNone(mod.play_sound("recorded"))
            self.assertIsNone(mod.play_sound("problem"))
        self.assertEqual(sum("winsound module couldn't be loaded" in line for line in logs.output), 1)


class HelperTests(unittest.TestCase):
    def test_portal_code_and_galaxy(self):
        ua = (0x5 << 52) | UA
        self.assertEqual(mod.portal_code(ua), "53E9F3545C3E")
        self.assertEqual(mod.galaxy_of(ua), 1)

    def test_address_of_accepts_pointers_and_integers(self):
        buffer = ctypes.create_string_buffer(8)
        self.assertEqual(mod.address_of(ctypes.cast(buffer, ctypes.c_void_p)), ctypes.addressof(buffer))
        self.assertEqual(mod.address_of(1234), 1234)
        self.assertEqual(mod.address_of(None), 0)

    def test_ship_labels_use_in_game_names(self):
        self.assertEqual(
            [mod.ship_label(c) for c in (1, 3, 6, 7, 8, 9, 99)],
            ["Hauler", "Explorer", "Exotic", "Living ship", "Solar", "Interceptor", "Class 99"],
        )


class LauncherTests(unittest.TestCase):
    """The checks run by ``py -3.13 system_capture.py`` before pyMHF starts the game."""

    PYTHON_ORG = r"C:\Users\player\AppData\Local\Programs\Python\Python313"
    # Paths from a real failed run with the Microsoft Store build.
    STORE_ALIAS = (
        r"C:\Users\player\AppData\Local\Microsoft\WindowsApps"
        r"\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"
    )
    STORE_PREFIX = (
        r"C:\Program Files\WindowsApps"
        r"\PythonSoftwareFoundation.Python.3.13_3.13.3824.0_x64__qbz5n2kfra8p0"
    )

    def test_python_org_install_passes(self):
        problems = mod.launcher_problems(self.PYTHON_ORG + r"\python.exe", (self.PYTHON_ORG,), 8)
        self.assertEqual(problems, [])

    def test_microsoft_store_python_is_stopped_with_a_fix(self):
        for executable in (self.STORE_ALIAS, self.PYTHON_ORG + r"\python.exe"):
            (problem,) = mod.launcher_problems(executable, (self.STORE_PREFIX,), 8)
            self.assertIn("Microsoft Store version of Python", problem)
            self.assertIn("python.org", problem)

    def test_32_bit_python_is_stopped(self):
        (problem,) = mod.launcher_problems(self.PYTHON_ORG + r"\python.exe", (self.PYTHON_ORG,), 4)
        self.assertIn("32-bit", problem)

    def test_attaching_to_a_running_game_is_allowed(self):
        self.assertEqual(mod.attach_problems(running=True, taken=False), [])
        self.assertEqual(mod.attach_problems(running=False, taken=False), [])

    def test_pymhf_left_inside_the_game_is_stopped_with_a_fix(self):
        (problem,) = mod.attach_problems(running=True, taken=True)
        self.assertIn("already inside No Man's Sky", problem)
        self.assertIn("quit the game", problem)
        (problem,) = mod.attach_problems(running=False, taken=True)
        self.assertIn(f"port {mod.PYMHF_PORT}", problem)

    def test_port_taken_sees_a_listening_program(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = server.getsockname()[1]
            self.assertTrue(mod.port_taken(port))
        self.assertFalse(mod.port_taken(port))

    def test_game_running_looks_for_the_game_process(self):
        def processes(*names):
            listing = [types.SimpleNamespace(info={"name": name}) for name in names]
            return types.SimpleNamespace(process_iter=lambda attrs: iter(listing))

        def broken(attrs):
            raise RuntimeError("access denied")

        cases = [
            (processes("steam.exe", "NMS.exe"), True),
            (processes("steam.exe", "nms.exe"), True),
            (processes("steam.exe", None), False),
            (types.SimpleNamespace(process_iter=broken), False),
            (None, False),  # psutil can't be imported
        ]
        for psutil, expected in cases:
            with self.subTest(psutil=psutil), mock.patch.dict(sys.modules, {"psutil": psutil}):
                self.assertIs(mod.game_running(), expected)


class ReportTests(CaptureTestCase):
    def capture_systems(self) -> report.Captures:
        self.game.generate(self.capture)
        other = (0x079 << 40) | (1 << 32) | 0x01234567
        self.game.set_address(other)
        self.game.fill(other, "Abarof-Dulin")
        self.game.set_ships(SHIPS[:1])
        self.game.generate(self.capture)
        return report.read_captures([mod.CAPTURE_FILE])

    def test_summary(self):
        captures = self.capture_systems()
        text = "\n".join(report.summary_lines(captures))
        self.assertIn("1 file(s), 1 session(s), 2 record(s), 2 system(s), 0 lookup(s)", text)
        self.assertIn("4 ships, 1-3 per system", text)
        self.assertIn("by class: Fighter 2, Hauler 1, Exotic 1", text)
        self.assertIn("Systems with an exotic in the pool: 1", text)
        self.assertIn("03E9F3545C3E galaxy 1 Abarof-Dulin: 1 exotic (8000000000000001)", text)

    def test_generated_records_without_an_address_join_their_system(self):
        self.game.system.mUA = 0
        self.game.generate(self.capture)
        self.game.system.mUA = UA
        self.poll()
        self.poll()
        captures = report.read_captures([mod.CAPTURE_FILE])
        self.assertEqual(list(captures.by_system()), [UA])
        (chosen,) = captures.representative_by_system().values()
        self.assertEqual(chosen.data["via"], "gen", "the generated record is closest to the generator")
        self.assertEqual(chosen.display_name, "Shown-Name", "with the name the game showed later")

    def test_each_system_is_represented_by_its_first_record_with_ships(self):
        self.game.set_ships([])
        self.game.generate(self.capture)
        self.game.set_ships(SHIPS)
        self.game.generate(self.capture)
        self.game.set_ships(SHIPS[:1])
        self.game.generate(self.capture)
        captures = report.read_captures([mod.CAPTURE_FILE])
        (chosen,) = captures.representative_by_system().values()
        self.assertEqual(len(chosen.data["ships"]), 3)
        text = "\n".join(report.summary_lines(captures))
        self.assertIn("systems whose ship list changed between records: 1", text)

    def test_self_consistency_is_complete_for_a_consistent_capture(self):
        captures = self.capture_systems()
        lines = report.consistency_lines(captures, examples=5)
        self.assertTrue(lines[2:], "some checks ran")
        for line in lines[2:]:
            self.assertIn("100.0%", line)

    def test_inconsistency_is_listed(self):
        self.game.system.mGalaxyAttributes.mStar.Type = 3
        self.game.generate(self.capture)
        lines = report.consistency_lines(report.read_captures([mod.CAPTURE_FILE]), examples=5)
        self.assertIn(
            "star type = galaxy attributes: 03E9F3545C3E galaxy 1 Abarof-Dulin: 1 vs 3", "\n".join(lines)
        )

    def test_ship_stream_is_found_with_its_layout(self):
        ship_seeds, crash = stream_ships(UA, offset=881)
        self.game.set_ships([(seed, FIGHTER, 0, 1, 0, "") for seed in ship_seeds])
        self.game.system.mSolarSystemData.SentinelCrashSiteShipSeed.Seed = crash
        self.game.generate(self.capture)
        lines = report.ship_stream_lines(report.read_captures([mod.CAPTURE_FILE]), limit=2000)
        self.assertIn(
            "03E9F3545C3E galaxy 1 Abarof-Dulin: after 881 draws; 50/50 in sequence: "
            "ships 0-41, crash ship, ships 42-49",
            "\n".join(lines),
        )

    def test_trace_shows_where_the_ships_come_in_the_generation(self):
        ship_seeds, crash = stream_ships(UA, offset=429)
        self.game.set_ships([(seed, FIGHTER, 0, 1, 0, "") for seed in ship_seeds])
        self.game.system.mSolarSystemData.SentinelCrashSiteShipSeed.Seed = crash
        self.game.set_locators(95)
        states = report.stream_states(UA, 600)
        picks = [report.seeded_state(0x1234), report.seeded_state(UA), states[3], report.seeded_state(UA)]
        picks += [states[5], states[5], states[9], states[9], states[9], states[532]]
        self.game.generate_traced(self.capture, picks)
        self.poll()
        self.poll()  # the named record joins the generated one
        text = "\n".join(report.trace_lines(report.read_captures([mod.CAPTURE_FILE]), limit=2000))
        self.assertIn(
            "03E9F3545C3E galaxy 1 Shown-Name: biomes done after 10 draws, ships start after 429, "
            "Generate done after 533; 419 draws between biomes and ships, 95 locators (4.41 draws each)",
            text,
        )
        self.assertIn("Generate ended 104 draws after the ships started in 1 of 1 generation(s)", text)

    def test_ship_stream_reports_other_draws_and_absence(self):
        found = report.locate_ship_stream(
            UA, [f"{s:016X}" for s in stream_ships(UA, 10, 4, 99)[0]], None, 100
        )
        self.assertEqual((found.offset, found.found, found.layout), (10, 4, ["ships 0-3"]))
        outputs = [s & M32 for s in report.stream_states(UA, 40)]
        seeds = [report.mix((outputs[i + 1] << 32) | outputs[i]) for i in (5, 7, 12)]
        found = report.locate_ship_stream(UA, [f"{s:016X}" for s in seeds], None, 100)
        self.assertEqual(found.layout, ["ships 0-1", "3 other draws", "ship 2"])
        self.assertIsNone(report.locate_ship_stream(UA, ["0123456789ABCDEF"], None, 100).offset)

    def test_mix_and_unmix_are_inverses(self):
        for value in (0, 1, 0xDEADBEEFCAFEBABE, report.MASK64):
            self.assertEqual(report.unmix(report.mix(value)), value)

    def test_unsupported_format_is_rejected(self):
        path = Path(self._tmp.name) / "future.jsonl"
        path.write_text(json.dumps({"t": "session", "format": 99}) + "\n")
        with self.assertRaises(report.CaptureFormatError):
            report.read_captures([path])

    def test_main_prints_a_report(self):
        self.capture_systems()
        with tempfile.TemporaryFile("w+") as out:
            stdout, sys.stdout = sys.stdout, out
            try:
                self.assertEqual(report.main([str(mod.CAPTURE_FILE)]), 0)
            finally:
                sys.stdout = stdout
            out.seek(0)
            text = out.read()
        self.assertIn("Self-consistency of the game's data", text)
        self.assertIn("Ship seeds in the system seed's random-number stream", text)


class ShipModelTests(unittest.TestCase):
    """tools/captures/ship_model.py; the report checks it against real captures."""

    Body = ship_model.Body

    def test_ship_seeds_follow_the_layout_the_report_finds(self):
        seeds, crash = ship_model.ship_seeds(UA, 123)
        found = report.locate_ship_stream(UA, [f"{s:016X}" for s in seeds], f"{crash:016X}", 1000)
        self.assertEqual(
            (found.offset, found.found, found.layout), (123, 50, ["ships 0-41", "crash ship", "ships 42-49"])
        )

    def test_prime_planets_have_no_attractors(self):
        system = [self.Body(0, -1, True), self.Body(3, 0, True), self.Body(2, -1, True)]
        self.assertEqual(ship_model.ships_start(UA, system), 38 + 3)

    def test_attractor_draws_around_a_lone_planet(self):
        # Written out step by step: four draws per attempt, and a fifth unless the distance
        # draw puts the attractor within 500 of the planet.
        draws = game_rng.Stream(UA)
        for _ in range(38):
            draws.word()
        expected = 38 + 1
        for _ in range(30 + draws.below(36)):
            draws.unit(), draws.unit()
            too_close = draws.unit() * 40000 < 500
            draws.word()
            expected += 4
            if not too_close:
                draws.word()
                expected += 1
        self.assertEqual(ship_model.ships_start(UA, [self.Body(1, -1, False)]), expected + 3)

    def test_draw_count_for_a_planet_with_a_moon_is_pinned(self):
        Body = self.Body
        system = [Body(1, -1, False), Body(0, -1, False), Body(3, 1, False), Body(2, -1, True)]
        self.assertEqual(ship_model.ships_start(UA, system), 676)

    def test_moon_positions(self):
        planet, moon = self.Body(0, -1, False), self.Body(3, 0, False)
        self.assertEqual(ship_model.moon_offsets([planet, moon]), {1: (225792.0, 0.0, 0.0)})
        pair = ship_model.moon_offsets([planet, moon, moon])
        for offset in pair.values():
            self.assertAlmostEqual(math.dist((0, 0, 0), offset), 225792.0, places=3)
        self.assertAlmostEqual(pair[1][1], 112896.0, places=3)
        self.assertAlmostEqual(pair[2][1], -112896.0, places=3)

    def test_two_moon_planets_are_flagged_unless_all_prime(self):
        two = [self.Body(0, -1, False), self.Body(3, 0, False), self.Body(3, 0, False)]
        self.assertIn("two moons", ship_model.uncertainty(two))
        self.assertIsNone(ship_model.uncertainty([b._replace(prime=True) for b in two]))
        self.assertIsNone(ship_model.uncertainty(two[:2]))
        self.assertEqual(ship_model.two_moon_planets(two), [0])

    def test_swapped_moons_trade_azimuths_and_keep_elevations(self):
        two = [self.Body(0, -1, False), self.Body(3, 0, False), self.Body(3, 0, False)]
        first, other = ship_model.moon_offsets(two), ship_model.moon_offsets(two, frozenset({0}))
        for k in (1, 2):
            self.assertAlmostEqual(first[k][1], other[k][1], places=6, msg="elevation stays with the moon")
        azimuth = lambda v: math.atan2(v[2], v[0]) % math.tau  # noqa: E731
        self.assertAlmostEqual(azimuth(first[1]), azimuth(other[2]), places=9)
        self.assertAlmostEqual(azimuth(first[2]), azimuth(other[1]), places=9)
        self.assertAlmostEqual(azimuth(first[2]), ship_model.GOLDEN_ANGLE, places=9)

    @staticmethod
    def seed_with_first_draw(draw: int, low: int = 0x2468ACE1) -> int:
        """A made-up seed whose first draw is ``draw``: the game's seeding, run backwards."""
        high = (draw - low * game_rng.MULTIPLIER) & M32
        assert high, "the game would make this high word 1; pick another low word"
        return ((high ^ game_rng.swap16(low) ^ low) << 32) | low

    def test_squid_line_at_20_21_between_the_closest_exotics_recorded(self):
        line = 20 * 2**32 / 21
        self.assertEqual(ship_model.first_draw(0x0123456789ABCDEF), 4005469434)  # as in tests/ships.test.ts
        self.assertLess(ship_model.NOT_SQUID_HIGHEST, line)
        self.assertGreater(ship_model.SQUID_LOWEST, line)
        expected = [  # first draw, (squid, close)
            (0, (False, False)),
            (ship_model.NOT_SQUID_HIGHEST, (False, False)),
            (ship_model.NOT_SQUID_HIGHEST + 1, (False, True)),
            (math.floor(line), (False, True)),
            (math.ceil(line), (True, True)),
            (ship_model.SQUID_LOWEST - 1, (True, True)),
            (ship_model.SQUID_LOWEST, (True, False)),
            (M32, (True, False)),
        ]
        for draw, call in expected:
            seed = self.seed_with_first_draw(draw)
            self.assertEqual(ship_model.first_draw(seed), draw)
            self.assertEqual(tuple(ship_model.exotic_squid(seed)), call, draw)

    def test_report_checks_recorded_exotic_bodies_against_the_squid_line(self):
        class Record(str):
            def label(self) -> str:
                return str(self)

        def exotic(name: str, draw: int, body: str) -> tuple[Record, dict]:
            seed = self.seed_with_first_draw(draw)
            return Record(name), {"seed": f"{seed:016X}", "parts": [body, "TEXTURE_TEMP"]}

        squid, other = ship_model.SQUID_PART, ship_model.OTHER_EXOTIC_PART
        narrower = report.squid_lines(
            [
                exotic("A", ship_model.NOT_SQUID_HIGHEST + 5, other),
                exotic("B", ship_model.SQUID_LOWEST - 5, squid),
            ]
        )
        self.assertIn("2 of 2 exotic seeds agree", narrower[0])
        self.assertIn("closer than ship_model.py's edges: update them", narrower[1])
        overlap = report.squid_lines([exotic("A", 4_100_000_000, other), exotic("B", 4_095_000_000, squid)])
        overlap = "\n".join(overlap)
        self.assertIn("1 of 2 exotic seeds agree", overlap)
        self.assertIn("disagrees: A:", overlap)
        self.assertIn("they overlap, so no line fits them all", overlap)
        odd = "\n".join(report.squid_lines([exotic("A", 0, "_SOMETHING_ELSE")]))
        self.assertIn("0 of 0 exotic seeds agree", odd)
        self.assertIn("first part neither _SCLASSSHIP_SQU nor _SCLASSSHIP_ROY: 1", odd)


@unittest.skipUnless(os.environ.get("NMS_NAMEGEN"), "set NMS_NAMEGEN to a clone of nms_namegen")
class NamegenComparisonTests(CaptureTestCase):
    """Systems built from nms_namegen's own predictions must score 100% in the report."""

    ADDRESSES = [(0x03E9F3545C3E, 0), (0x0079F3545C3E, 0), (0x007AF3545C3E, 0), (0x00A1F3545C3E, 7)]

    def test_generator_predictions_round_trip(self):
        sys.path.insert(0, str(Path(os.environ["NMS_NAMEGEN"]).resolve()))
        from nms_namegen.region import voxelAttributes
        from nms_namegen.system import planetSeeds, systemAttributes, systemName

        inverse = lambda table: {v: k for k, v in table.items()}  # noqa: E731
        names = mod.ENUM_TABLES
        for code, galaxy in self.ADDRESSES:
            ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)
            attrs = systemAttributes(code, galaxy)
            seeds = planetSeeds(code, galaxy)["planet_seeds"]
            va = voxelAttributes(code)
            self.game.set_address(ua)
            self.game.fill(ua, systemName(code, galaxy))
            data = self.game.system.mSolarSystemData
            star = self.game.system.mGalaxyAttributes.mStar
            voxel = self.game.system.mGalaxyAttributes.mVoxel
            race = names["race"].index(inverse(report.NAMEGEN_RACE)[attrs["dominant_race"]])
            trade = names["trade"].index(inverse(report.NAMEGEN_ECONOMY)[attrs["economy_type"]])
            wealth = names["wealth"].index(inverse(report.NAMEGEN_WEALTH)[attrs["wealth"]])
            conflict = names["conflict"].index(inverse(report.NAMEGEN_CONFLICT)[attrs["conflict_level"]])
            anomaly = report._namegen_anomaly(va, (code >> 32) & 0xFFF)
            data.StarType = star.Type = attrs["star_type"]
            data.InhabitingRace = star.Race = race
            data.TradingData.TradingClass = star.TradingData.TradingClass = trade
            data.TradingData.WealthClass = star.TradingData.WealthClass = wealth
            data.ConflictData = star.ConflictData = conflict
            star.Anomaly = names["anomaly"].index({0: "None_", 1: "AtlasStation", 2: "BlackHole"}[anomaly])
            star.NumberOfPlanets = attrs["planet_count"]
            star.NumberOfPrimePlanets = attrs["prime_planet_count"]
            star.AbandonedSystem = attrs["abandoned"]
            star.IsPirateSystem = attrs["pirate"]
            star.IsGasGiantSystem = attrs["gas_giant"]
            for i in range(16):
                star.PlanetSeeds[i].Seed = seeds[i] if i < len(seeds) else 0
            voxel.AtlasStationCount = va["atlas_station_count"]
            voxel.BlackholeCount = va["black_hole_count"]
            voxel.GuideStarMinimumCount = va["guide_star_count"]
            voxel.GuideStarRenegadeCount = va["guide_star_renegade_count"]
            voxel.InsideGoalGap = bool(va["inside_gap"])
            keys = self.game.keys
            keys.muPlanetCount = attrs["planet_count"]
            keys.muPrimePlanetCount = attrs["prime_planet_count"]
            keys.muSafeStartPlanet = attrs["safe_start_planet"]
            keys.mbAbandonedSystem = attrs["abandoned"]
            keys.mbIsPirateSystem = attrs["pirate"]
            self.game.generate_traced(self.capture, list(range(10)))

        captures = report.read_captures([mod.CAPTURE_FILE])
        self.assertEqual(len(captures.representative_by_system()), len(self.ADDRESSES))
        lines = report.namegen_lines(captures, Path(os.environ["NMS_NAMEGEN"]), examples=5)
        scored = [line for line in lines[2:] if "/" in line]
        self.assertTrue(any("key attributes: safe start planet" in line for line in scored))
        for line in scored:
            self.assertIn("100.0%", line)

    def test_moon_layouts_are_read_from_recorded_positions(self):
        # Two made-up systems whose second body, a large planet, has two moons (bodies 2 and 3):
        # the first laid out the way the model guesses, the second the other way round.
        lookup = LookupTests.lookup.__get__(self)
        planet = (500000.0, 1200.0, -300000.0)
        for code, galaxy, swapped in (
            (0x021B7BE06E75, 248, frozenset()),
            (0x6226B9E3A187, 0, frozenset({1})),
        ):
            ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)
            system = ship_model.bodies(ua)
            self.assertEqual(ship_model.two_moon_planets(system), [1])
            offsets = ship_model.moon_offsets(system, swapped)
            positions = [(1.0e6 * (k + 1), 0.0, 0.0) for k in range(len(system))]
            positions[1] = planet
            for k in (2, 3):
                positions[k] = tuple(a + b for a, b in zip(planet, offsets[k]))
            lookup(ua, steps=True, positions=positions)
            lookup(ua | (3 << 52), steps=True, positions=positions)  # the same system, from a planet
        self.game.loaded = False
        self.poll()
        lines = report.moon_layout_lines(
            report.read_captures([mod.CAPTURE_FILE]), Path(os.environ["NMS_NAMEGEN"]), 5
        )
        self.assertEqual(
            lines[1:],
            [
                "Two-moon planets whose moons' positions were recorded: 2",
                "  first moon at azimuth 0 (the model's first guess): 1",
                "  first moon at 137.5 degrees: 1",
            ],
        )

    def test_names_are_scored_against_the_generator(self):
        sys.path.insert(0, str(Path(os.environ["NMS_NAMEGEN"]).resolve()))
        from nms_namegen.planet import planetName
        from nms_namegen.region import regionName

        code, galaxy = 0x03E9F3545C3E, 1  # the fake system: UA's region and galaxy
        names = NameTests.name.__get__(self)  # reuse the detour driver
        planet_seed = 0xAAAA000000000001  # one of the fake system's planet seeds
        names("planet", planet_seed, planetName(planet_seed))
        names("planet", 0x1234, "Not-The-Generators-Name")
        # The seed the game passes for a region: the galaxy and the portal code's low 32 bits, as
        # nms_namegen's regionName() puts them together before it mixes them in with galaxy >> 1, which
        # only galaxies from 2 on have (a galaxy 166 name, as recorded in Touchuork, says so).
        names("region", (galaxy << 32) | (code & 0xFFFFFFFF), regionName(code, galaxy))
        names("region", (166 << 32) | (code & 0xFFFFFFFF), regionName(code, 166))
        self.game.generate(self.capture)
        self.poll()

        lines = report.name_lines(
            report.read_captures([mod.CAPTURE_FILE]), Path(os.environ["NMS_NAMEGEN"]), 5
        )
        text = "\n".join(lines)
        self.assertIn("planet name = generator's name for the same seed", text)
        self.assertRegex(text, r"planet name = generator's name for the same seed\s+1/2 ")
        self.assertRegex(text, r"planet name seeds that are the loaded system's planet seeds\s+1/2 ")
        self.assertRegex(text, r"taking the seed before mixing\s+2/2\s+100.0%")
        self.assertRegex(text, r"taking the seed after mixing\s+0/2 ")
        self.assertRegex(text, r"region names that are the loaded system's region\s+1/2 ")

    def test_bodies_follow_the_generator(self):
        sys.path.insert(0, str(Path(os.environ["NMS_NAMEGEN"]).resolve()))
        from nms_namegen.system import planetSeeds

        for code, galaxy in self.ADDRESSES:
            ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)
            system = ship_model.bodies(ua)  # raises if its draws stray from planetSeeds'
            self.assertEqual(len(system), len(planetSeeds(code, galaxy)["planet_seeds"]))
            for body in system:
                self.assertIn(body.size, ship_model.BASE_RADIUS)
                if body.parent >= 0:  # moons orbit large planets
                    self.assertEqual((body.size, system[body.parent].size), (3, 0))

    def test_predicted_ships_are_scored(self):
        prediction = ship_model.predict(UA)
        self.game.set_ships([(seed, FIGHTER, 0, 1, 0, "") for seed in prediction.ships])
        self.game.system.mSolarSystemData.SentinelCrashSiteShipSeed.Seed = prediction.crash
        self.game.generate(self.capture)
        other = (0x079 << 40) | (0x00F3545C3E)
        self.game.set_address(other)
        self.game.fill(other, "Elsewhere")  # keeps the 50 ships, which aren't this system's
        self.game.generate(mod.TradeDepotCapture())
        text = "\n".join(
            report.ship_model_lines(report.read_captures([mod.CAPTURE_FILE]), Path(os.environ["NMS_NAMEGEN"]))
        )
        self.assertIn("03E9F3545C3E galaxy 1 Abarof-Dulin: all 50 ships and the crashed ship match", text)
        self.assertIn("079F3545C3E galaxy 0 Elsewhere: 0/50 ships match", text)
        self.assertIn("1 of 2 systems: every ship seed and the crashed ship's match", text)


if __name__ == "__main__":
    unittest.main()
