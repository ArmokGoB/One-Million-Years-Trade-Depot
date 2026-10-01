# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for mods/system_capture.py against fake game memory built from NMS.py's own structs.

Run from the repository root:
    python -m unittest discover -s mods/tests -v
Set NMS_NAMEGEN to a clone of nms_namegen to include the generator comparison test.
"""

from __future__ import annotations

import base64
import ctypes
import importlib.util
import inspect
import json
import math
import os
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

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
                    args = (ctypes.pointer(self.seed), None, None, None)
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
        expected = {"before_generate", "after_generate"} | {name for pair in STEPS for name in pair}
        self.assertEqual({h.__name__ for h in self.capture.hooks}, expected)
        self.assertEqual({c.__name__ for c in self.capture._custom_callbacks}, {"on_frame"})
        self.assertEqual(len(self.capture._gui_widgets), 7)

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
        self.game.generate(self.capture)
        self.assertNotIn("trace", self.lines()[1])

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


class LookupTests(CaptureTestCase):
    def lookup(self, seed: int, ships=SHIPS) -> None:
        """A GenerateQueryInfo call on a generator that isn't generating a loaded system."""
        generator = self.game._alloc(nms.cGcSolarSystemGenerator)
        data = self.game._alloc(nmse.cGcSolarSystemData)
        generation = self.game._alloc(nms.cGcSolarSystemGenerator.GenerationData)
        generation.mMetaData = ctypes.pointer(data)
        query_seed = self.game._alloc(basic.GcSeed)
        query_seed.Seed = seed
        self.game.set_rng(report.seeded_state(seed), generator)
        pointer = self.game.generator_pointer(generator)
        self.capture.before_query(pointer, ctypes.pointer(query_seed), None, ctypes.pointer(generation))
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
        with self.assertLogs("TradeDepotCapture", "INFO") as logs:
            self.capture.record_now()
            self.capture.on_frame()
        self.assertEqual(len(self.lines()), 2)
        self.assertIn("Already recorded this session", "\n".join(logs.output))
        self.assertEqual(self.capture.status, "Already recorded; nothing has changed.")

    def test_record_button_without_a_system(self):
        self.game.loaded = False
        self.capture.record_now()
        self.capture.on_frame()
        self.assertEqual(self.capture.status, "No star system is loaded yet.")


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
            self.game.generate(self.capture)

        captures = report.read_captures([mod.CAPTURE_FILE])
        self.assertEqual(len(captures.representative_by_system()), len(self.ADDRESSES))
        lines = report.namegen_lines(captures, Path(os.environ["NMS_NAMEGEN"]), examples=5)
        scored = [line for line in lines[2:] if "/" in line]
        self.assertTrue(scored)
        for line in scored:
            self.assertIn("100.0%", line)


if __name__ == "__main__":
    unittest.main()
