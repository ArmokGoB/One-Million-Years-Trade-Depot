# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for mods/system_capture.py against fake game memory built from NMS.py's own structs.

Run from the repository root:
    python -m unittest discover -s mods/tests -v
Set NMS_NAMEGEN to a clone of nms_namegen to include the generator comparison test.
"""

from __future__ import annotations

import array
import base64
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

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("capture_report", ROOT / "tools" / "captures" / "report.py")
report = importlib.util.module_from_spec(_spec)
sys.modules["capture_report"] = report
_spec.loader.exec_module(report)

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
        expected |= {name for pair in STEPS for name in pair} | {"find_application"}
        self.assertEqual({h.__name__ for h in self.capture.hooks}, expected)
        self.assertEqual({c.__name__ for c in self.capture._custom_callbacks}, {"on_frame"})
        self.assertEqual(len(self.capture._gui_widgets), 10)

    def test_application_hook_targets_the_main_loop(self):
        hook = mod.TradeDepotCapture.find_application
        self.assertEqual(hook._hook_func_name, "cGcApplication.Update")
        self.assertEqual(hook._hook_time, DetourTime.BEFORE)
        self.assertEqual(hook._hook_pattern, nms.cGcApplication.Update._signature)

    def test_hotkeys_are_registered_on_key_release(self):
        keys = {f.__name__: (f._hotkey, f._hotkey_press) for f in self.capture._hotkey_funcs}
        self.assertEqual(
            keys,
            {"record_key": ("f6", "up"), "squid_key": ("f7", "up"), "not_squid_key": ("f8", "up")},
        )

    def test_pymhf_acts_on_key_releases_while_the_game_has_focus(self):
        import pymhf.core.mod_loader as loader

        callbacks = []
        manager = loader.ModManager()
        manager.hook_manager = types.SimpleNamespace(
            register_hook=lambda hook: None, _add_custom_callbacks=lambda found: None
        )
        focused = mock.Mock(return_value=True)
        with (
            mock.patch.object(loader.keyboard, "hook", callbacks.append, create=True),
            mock.patch.object(loader, "does_pid_have_focus", focused),
        ):
            capture = manager.instantiate_mod(mod.TradeDepotCapture)

            def key(name: str, kind: str) -> None:
                for callback in callbacks:
                    callback(types.SimpleNamespace(name=name, event_type=kind))

            self.assertEqual(len(callbacks), 3)
            key("f7", "down")
            self.assertIsNone(capture._label_requested, "nothing until the key is released")
            key("f7", "up")
            self.assertEqual(capture._label_requested, "squid")
            key("f8", "up")
            self.assertEqual(capture._label_requested, "not a squid")
            key("f6", "up")
            self.assertTrue(capture._record_requested)
            capture._label_requested = None
            focused.return_value = False
            key("f7", "up")
            self.assertIsNone(capture._label_requested, "nothing while another window has focus")

    def test_hotkeys_are_distinct_single_keys(self):
        names = list(mod.HOTKEYS.values())
        self.assertEqual(len(set(names)), len(names))
        for name in names:
            self.assertEqual(name, name.lower(), "the keyboard library reports lower-case names")
            self.assertNotIn("+", name, "pyMHF can't bind key combinations")

    def test_buttons_name_their_keys(self):
        labels = {w._widget_data.label for w in self.capture._gui_widgets if hasattr(w, "_widget_data")}
        self.assertIn("Record the current system now (F6)", labels)
        self.assertIn("Exotic seen here: squid (F7)", labels)
        self.assertIn("Exotic seen here: not a squid (F8)", labels)

    def test_key_names(self):
        for key, shown in (("f6", "F6"), ("f12", "F12"), ("page up", "Page Up"), ("o", "O")):
            with self.subTest(key=key):
                self._patch("HOTKEYS", dict(mod.HOTKEYS, record=key))
                self.assertEqual(mod.key_name("record"), shown)

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


class LabelTests(CaptureTestCase):
    def test_squid_label_names_the_systems_exotic_seed(self):
        self.capture.exotic_squid()
        self.assertEqual(self.capture.status, "Noting that the exotic here is squid...")
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture.on_frame()
        (label,) = [line for line in self.lines() if line["t"] == "label"]
        self.assertEqual(
            {k: v for k, v in label.items() if k != "at"},
            {
                "t": "label",
                "ua": f"{UA:016X}",
                "seed": f"{UA:016X}",
                "label": "squid",
                "exotic": ["8000000000000001"],
                "displayName": "Shown-Name",
            },
        )
        self.assertIn(
            "Noted: the exotic in Shown-Name (03E9F3545C3E, galaxy 1) (seed 8000000000000001) is squid.",
            "\n".join(logs.output),
        )
        self.assertEqual(self.capture.status, "Noted: the exotic here is squid.")
        self.assertEqual(self.sounds, ["squid"])

    def test_hotkeys_label_like_the_buttons(self):
        keys = ((self.capture.squid_key, "squid", "F7"), (self.capture.not_squid_key, "not a squid", "F8"))
        for key, label, name in keys:
            with self.assertLogs("TradeDepotCapture", "INFO") as logs:
                key()
            self.assertEqual(logs.output, [f"INFO:TradeDepotCapture:{name} pressed."])
            self.assertEqual(self.capture.status, f"Noting that the exotic here is {label}...")
            self.capture.on_frame()
        self.assertEqual([line["label"] for line in self.lines() if line["t"] == "label"],
                         ["squid", "not a squid"])  # fmt: skip
        self.assertEqual(self.sounds, ["squid", "not a squid"])

    def test_label_without_an_exotic_in_the_list(self):
        self.game.set_ships(SHIPS[:2])
        self.capture.exotic_not_squid()
        self.capture.on_frame()
        (label,) = [line for line in self.lines() if line["t"] == "label"]
        self.assertEqual((label["label"], label["exotic"]), ("not a squid", []))
        self.assertEqual(self.capture.status, "Noted, but this system's ship list has no exotic.")
        self.assertEqual(self.sounds, ["problem"])

    def test_label_without_a_system(self):
        self.game.loaded = False
        self.capture.exotic_squid()
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture.on_frame()
        self.assertIn("Couldn't note the exotic: no star system is loaded yet.", "\n".join(logs.output))
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.capture.status, "No star system is loaded yet.")
        self.assertEqual(self.sounds, ["problem"])

    def test_label_that_cant_be_written(self):
        blocker = Path(self._tmp.name) / "blocked"
        blocker.write_text("not a folder")
        self._patch("CAPTURE_DIR", blocker)
        self._patch("CAPTURE_FILE", blocker / "systems.jsonl")
        self.capture.exotic_squid()
        with self.assertLogs("TradeDepotCapture", "WARNING"):
            self.capture.on_frame()
        self.assertEqual(self.sounds, ["problem"])

    def test_report_keeps_the_last_label_per_system_and_session(self):
        for press in (self.capture.exotic_squid, self.capture.exotic_not_squid):
            press()
            self.capture.on_frame()
        lines = report.label_lines(report.read_captures([mod.CAPTURE_FILE]))
        text = "\n".join(lines)
        self.assertIn(
            "Exotic sightings labelled: 1 (not a squid 1); 1 earlier label(s) replaced by a later one "
            "for the same system and session",
            text,
        )
        self.assertIn("03E9F3545C3E galaxy 1 Shown-Name: not a squid (8000000000000001)", text)
        self.assertNotIn(": squid (", text)
        self.assertNotIn("both ways", text)

    def test_report_lists_labels_that_disagree_across_sessions(self):
        self.capture.exotic_squid()
        self.capture.on_frame()
        later = mod.TradeDepotCapture()  # a new session
        later.exotic_not_squid()
        later.on_frame()
        text = "\n".join(report.label_lines(report.read_captures([mod.CAPTURE_FILE])))
        self.assertIn("Exotic sightings labelled: 2 (squid 1, not a squid 1)", text)
        self.assertIn("03E9F3545C3E galaxy 1 Shown-Name: squid (8000000000000001)", text)
        self.assertIn("labelled both ways in different sessions: 8000000000000001", text)


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
    def lookup(self, seed: int, ships=SHIPS, steps: bool = False) -> None:
        """A GenerateQueryInfo call on a generator that isn't generating a loaded system;
        with ``steps``, the basics, positions and biomes steps run inside it."""
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

    def test_record_key_records_like_the_button(self):
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture.record_key()
        self.assertEqual(logs.output, ["INFO:TradeDepotCapture:F6 pressed."])
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
        self.assertEqual(logs.output, [expected])
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
    """Attached to a game that was already running, NMS.py hasn't found the application object."""

    def setUp(self):
        super().setUp()
        from nmspy.common import GameData

        self.data = GameData()
        self._patch("gameData", self.data)

    def application(self):
        app = self.game._alloc(nms.cGcApplication)
        return app, ctypes.cast(ctypes.addressof(app), ctypes.POINTER(nms.cGcApplication))

    def test_the_main_loop_supplies_the_application(self):
        app, pointer = self.application()
        self.assertIsNone(self.data.GcApplication)
        self.assertIsNone(self.capture.find_application(pointer))
        self.assertEqual(ctypes.addressof(self.data.GcApplication), ctypes.addressof(app))

    def test_a_different_pointer_is_replaced_and_the_right_one_kept(self):
        wrong, _ = self.application()
        self.data.GcApplication = wrong
        app, pointer = self.application()
        self.capture.find_application(pointer)
        kept = self.data.GcApplication
        self.assertEqual(ctypes.addressof(kept), ctypes.addressof(app))
        self.capture.find_application(pointer)
        self.assertIs(self.data.GcApplication, kept)
        self.capture.find_application(None)
        self.assertIs(self.data.GcApplication, kept)

    def test_the_loaded_system_is_seen_through_it(self):
        self.poll()
        self.poll()
        self.assertEqual(self.lines(), [], "no application yet: no system")
        data = self.game._alloc(nms.cGcApplication.Data)
        data.mSimulation.mpSolarSystem = ctypes.cast(self.game.address, ctypes.POINTER(nms.cGcSolarSystem))
        data.mSimulation.mCurrentUA = UA
        app, pointer = self.application()
        app.mpData = ctypes.pointer(data)
        self.capture.find_application(pointer)
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
        self.assertLessEqual({"recorded", "squid", "not a squid", "problem"}, set(mod.SOUNDS))
        self.assertNotEqual(mod.SOUNDS["squid"], mod.SOUNDS["not a squid"])
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
            thread = mod.play_sound("squid")
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
                self.assertIsNone(mod.play_sound("squid"))
            self.assertIsNone(mod.play_sound("no such sound"))
        with mock.patch.dict(sys.modules, {"winsound": None}):  # importing it fails, as off Windows
            with mock.patch.object(mod.sys, "platform", "linux"), self.assertNoLogs("TradeDepotCapture"):
                self.assertIsNone(mod.play_sound("squid"))
        play.assert_not_called()

    def test_missing_winsound_on_windows_is_logged_once(self):
        with (
            mock.patch.object(mod, "_sound_failed", set()),
            mock.patch.dict(sys.modules, {"winsound": None}),
            mock.patch.object(mod.sys, "platform", "win32"),
            self.assertLogs("TradeDepotCapture", "WARNING") as logs,
        ):
            self.assertIsNone(mod.play_sound("squid"))
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

    def test_names_are_scored_against_the_generator(self):
        sys.path.insert(0, str(Path(os.environ["NMS_NAMEGEN"]).resolve()))
        from nms_namegen.planet import planetName
        from nms_namegen.region import regionName

        code, galaxy = 0x03E9F3545C3E, 1  # the fake system: UA's region and galaxy
        names = NameTests.name.__get__(self)  # reuse the detour driver
        planet_seed = 0xAAAA000000000001  # one of the fake system's planet seeds
        names("planet", planet_seed, planetName(planet_seed))
        names("planet", 0x1234, "Not-The-Generators-Name")
        # The seed the game passes for a region, if it is the value before nms_namegen's mixing.
        raw = (galaxy >> 1) ^ ((galaxy << 32) | (code & 0xFFFFFFFF))
        names("region", raw, regionName(code, galaxy))
        self.game.generate(self.capture)
        self.poll()

        lines = report.name_lines(
            report.read_captures([mod.CAPTURE_FILE]), Path(os.environ["NMS_NAMEGEN"]), 5
        )
        text = "\n".join(lines)
        self.assertIn("planet name = generator's name for the same seed", text)
        self.assertRegex(text, r"planet name = generator's name for the same seed\s+1/2 ")
        self.assertRegex(text, r"planet name seeds that are the loaded system's planet seeds\s+1/2 ")
        self.assertRegex(text, r"taking the seed before mixing\s+1/1\s+100.0%")
        self.assertRegex(text, r"taking the seed after mixing\s+0/1 ")
        self.assertRegex(text, r"region names that are the loaded system's region\s+1/1\s+100.0%")


if __name__ == "__main__":
    unittest.main()
