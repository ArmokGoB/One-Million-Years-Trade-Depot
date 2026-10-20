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
to the session's file in ``captures`` next to this file, named for your Steam
ID and when the file was made (see new_capture_file). The line holds the system's
universal address, its seed, the game's own description of it (name, star,
race, economy, planets) and ``SystemShips``, the list of ships the game
prepares for the system, and how many stars it has, worked out as the game's
own star count function would (see StarCount). The multi-tools the game builds
for the system as it generates it go on a line of their own, with each one's
seed and parts, and so does the guild whose envoy you say you saw, with the
buttons on the mod's tab.
When the game builds the model of a ship from the system's list, the mod also
records the parts the game picked for it, with the ship's seed; and when the
game offers an item, such as a multi-tool to buy or as a gift or reward, what
the item holds: its inventories, and the seed and parts of its model. To work out
how the game colors ships and multi-tools, it also records what the game makes
your own ships, multi-tool and freighter from: each one's seed, the texture
option picked for each layer of its paint and the colors picked from each
palette; the paint the game picks for the ships of each system's list and the
system's multi-tools; and, once a session, the game's color variants for suns.
The One Million Years Trade Depot uses these lines as ground truth for
working out how the game picks a system's ships and multi-tools, and what a
seed makes them look like.

The mod only reads. It changes nothing in the game or your save. Every read
of game memory goes through ReadProcessMemory, so if NMS.py's struct layouts
stop matching the game after an update, the mod logs a warning instead of
crashing the game. Besides, on the game's main thread, it calls the game's
own function that gives a system's name.

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
import uuid
import wave
import zlib
from collections import Counter
from importlib import metadata
from pathlib import Path
from typing import Annotated

import nmspy.data.basic_types as basic
import nmspy.data.enums as enums
import nmspy.data.exported_types as nmse
import nmspy.data.types as nms
import pymhf.core._internal as pymhf_internal
from nmspy.common import gameData
from nmspy.decorators import main_loop
from pymhf import Mod
from pymhf.core.hooking import Structure, static_function_hook
from pymhf.gui.decorators import STRING, gui_button

MOD_VERSION = "0.14.0"
# Bump when the meaning of a field changes; tools/captures/report.py checks it.
# 2: generation traces, raw system data, display names and query records.
# (0.3.0 to 0.14.0 only add or drop record types, fields and controls, or let a field hold more
# kinds of thing, as 0.8.2 does with an item's "tools", so they keep format 2.)
FORMAT_VERSION = 2
STEAM_APP_ID = 275850

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
# Each session's lines go to a file of its own in CAPTURE_DIR, named as the project keeps captures:
# <your Steam ID>_<when the file was made, in UTC>.jsonl, the time as CAPTURE_TIME_FORMAT. The Steam ID
# is the SteamID64 that steamcommunity.com/profiles/ knows your account by: that of the account Steam says is
# logged in (STEAM_USER_KEY), or else the one in the name of the game's newest save folder (SAVE_FOLDERS). If
# neither can be found, a random identifier made once and kept in CAPTURE_DIR (IDENTIFIER_FILE) stands in.
CAPTURE_TIME_FORMAT = "%Y_%m_%d_%H_%M"
# Under HKEY_CURRENT_USER: Steam keeps the account number of the user logged in there as ActiveUser.
STEAM_USER_KEY = r"Software\Valve\Steam\ActiveProcess"
STEAM_ID_BASE = 76561197960265728  # an individual Steam account's SteamID64, less its account number
SAVE_FOLDERS = Path("HelloGames") / "NMS"  # in %APPDATA%: a folder st_<SteamID64> for each Steam account
IDENTIFIER_FILE = "identifier.txt"

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
# for it, cGcSolarSystem::GetStarCount, which NMS.py names but can't hook, reads
# its code, and works the count out the same way from the values it reads
# (see StarCount). Once a session it also records the game's color variants for
# suns, which a system's suns are drawn with (see STAR_POI_DATA). Set it to False
# if the game misbehaves with the mod, and the mod won't look for the function.
RECORD_STARS = True
# Record what the game makes your own ships, multi-tool and freighter from, to work out how it colors
# ships and multi-tools: the seed each one is made from, the texture option it picked for each layer of
# its paint, and the colors it picked from each palette. The mod watches the function the game makes them
# with, cGcResourceCustomisation::CreateGenerationTask, and reads your ships and what the game keeps of
# their customisation (see CUSTOMISATION_READ). Set it to False if the game misbehaves with the mod, and the
# mod won't watch that function or read them.
RECORD_COLORS = True
# Record the paint the game picks for the ships and multi-tools it makes, the NPCs' as well as yours: the
# texture option for each layer, and the color it's painted in. The mod watches the function the game picks
# them with, which NMS.py doesn't name (see PAINT_PATTERN). Set it to False if the game misbehaves with the
# mod, and the mod won't watch that function.
RECORD_PAINT = True
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
    # three quick rising notes: the colors of one of your ships or multi-tools are recorded
    "colors": [(1046.5, 0.05), (1318.5, 0.05), (1568.0, 0.09)],
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
# A system's own multi-tools, its set, are written with the system, seeds, parts and all. In 0.10.0's
# captures the game built each system's set in one quick run just before it started generating the
# system, and none while it did: several standard multi-tools and one each of the royal, sentinel and
# Atlas files. It built your own multi-tool a few seconds after each system was generated, and as a save
# loaded, and in 0.8.2's, other players' in the Nexus at other times. So a system's set is the
# multi-tools the game builds while it generates the system, on the thread that generates it, and before
# them the run it built last, on any thread, while no system was being generated: each less than
# POOL_LEAD_SECONDS after the one before, the last less than that before the generation started, with
# the files in POOL_SIGNATURE among them, and not before a session's first generation, for which a save
# is loading. Each other multi-tool model the game builds gets a "built" line: when, on which thread
# (numbered in the order the mod sees them), its file, how many parts it has and its resource handle,
# but not its seed or parts. So do those of a run, as the game builds them, before the mod knows that
# a generation follows.
POOL_TOOLS = 64  # the most multi-tools in one system's set
POOL_SECONDS = 60.0  # a generation that hasn't ended after this long is taken to have ended unseen
POOL_LEAD_SECONDS = 2.0
POOL_SIGNATURE = ("ROYALMULTITOOL", "SENTINELMULTITOOL", "ATLASMULTITOOL")
MAX_POOL_RECORDS = 2_000
MULTITOOL_NAMES_LOGGED = 10  # the log names the first few multi-tool model files
TOOL_BUILDS_RECORDED = 500  # "built" lines for multi-tool models, per session
# The game's resource manager lists the resources it holds, and a resource handle picks one of
# them. For each item the game offers, the mod reads the one the item's handle picks, as a check
# on the model it paired the item with.
MAX_RESOURCES = 1 << 22
# cGcSolarSystem::GetStarCount, found by the pattern NMS.py gives for it. Its code (as 0.10.0 recorded it
# in October 2026) counts a system's stars from the system's NebulaSeed, a value of its sky between 0
# and 1, and two chances in the game's sky globals:
#     1 + (NebulaSeed > 1 - TernaryStarChance) + (NebulaSeed > 1 - BinaryStarChance)
# or 2 if the debug option ForceBinaryStar is on, or 3 if ForceTernaryStar is. In two game modes, with a
# setting on that the mod doesn't know, the function goes on another way, which the mod doesn't follow.
# The mod doesn't call the function: it checks that its code still has this shape, reads the values the
# code reads, from the places the code reads them from, and works the count out the same way. Each
# session's first line holds the function's first STAR_CODE_BYTES and those values.
STAR_COUNT_PATTERN = "F3 0F 10 0D ? ? ? ? 33 C0 F3 0F 10 91"
STAR_CODE_BYTES = 256
# The function's instructions: hex bytes; <name>, an address relative to the next instruction; [name],
# an offset in the solar system; ~name, where a short jump goes (each ~count goes to the same place).
STAR_COUNT_CODE = (
    ("F3 0F 10 0D <one>", "movss xmm1, [one]"),
    ("33 C0", "xor eax, eax"),
    ("F3 0F 10 91 [nebula]", "movss xmm2, [rcx + NebulaSeed]"),
    ("8B D0", "mov edx, eax"),
    ("0F 28 C1", "movaps xmm0, xmm1"),
    ("4C 8B C1", "mov r8, rcx"),
    ("F3 0F 5C 05 <ternary>", "subss xmm0, [TernaryStarChance]"),
    ("F3 0F 5C 0D <binary>", "subss xmm1, [BinaryStarChance]"),
    ("0F 2F D0", "comiss xmm2, xmm0"),
    ("0F 97 C2", "seta dl"),
    ("0F 2F D1", "comiss xmm2, xmm1"),
    ("0F 97 C0", "seta al"),
    ("FF C0", "inc eax"),
    ("03 D0", "add edx, eax: edx is the count"),
    ("B8 02 00 00 00", "mov eax, 2"),
    ("80 3D <forceBinary> 00", "cmp byte [ForceBinaryStar], 0"),
    ("0F 45 D0", "cmovne edx, eax"),
    ("80 3D <forceTernary> 00", "cmp byte [ForceTernaryStar], 0"),
    ("B8 03 00 00 00", "mov eax, 3"),
    ("75 ~three", "jne to return 3"),
    ("83 3D <bootMode> 05", "cmp dword [BootMode], Scratchpad"),
    ("74 ~count", "je to return the count"),
    ("8B 0D <gameMode>", "mov ecx, [the application's meGameMode]"),
    ("85 C9", "test ecx, ecx"),
    ("74 05", "je over the next two: Unspecified"),
    ("83 F9 06", "cmp ecx, Seasonal"),
    ("75 ~count", "jne to return the count"),
    ("48 8B 0D <data>", "mov rcx, [the application's mpData]"),
    ("80 B9 [setting] 00", "cmp byte [rcx + setting], 0"),
    ("74 ~count", "je to return the count, or else go on another way"),
)
# The values the mod reads where the function's code reads them, as struct formats and sizes.
STAR_VALUES = {
    "one": ("<f", 4),
    "binary": ("<f", 4),
    "ternary": ("<f", 4),
    "forceBinary": ("<B", 1),
    "forceTernary": ("<B", 1),
    "bootMode": ("<i", 4),
    "gameMode": ("<I", 4),
    "data": ("<Q", 8),
}
SCRATCHPAD_BOOT = 5  # cGcDebugOptions.BootMode, in which the function returns the count
STAR_SETTING_MODES = (0, 6)  # cGcGameMode Unspecified and Seasonal, in which the setting matters
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
# Colors (RECORD_COLORS). The game keeps how each of your ships, your multi-tool, your freighter and so on
# is customised in a cGcResourceCustomisation, 26 of them in your player state, one for each kind of thing
# (cGcCustomisationComponentData: Player, Vehicle, Weapon, Ship_01...), and hands one to CreateGenerationTask
# to make the model. NMS.py places its seed, the IDs of the parts it's made of and the texture options
# picked for it, and two sets of colors, five from each of the game's 66 palettes; an earlier version of
# the game had 64, and NMS.py may not have caught up everywhere. So the mod reads more than NMS.py's size of one,
# keeps all it read, compressed, and reads the colors where NMS.py puts them only if they look like colors
# there (see color_sets).
CUSTOMISATION_READ = 0x3C00
CUSTOMISATION_SLOTS = 26
# How far apart the customisations may be in your player state, besides NMS.py's size of one: its size as
# declared, which an earlier version of the game had, and that with two more palettes in each color set.
CUSTOMISATION_STRIDES = (0x3920, 0x3AE0)
PALETTE_COUNT = 66
MAX_TEXTURE_SAMPLERS = 64
MAX_TEXTURE_OPTIONS = 64
MAX_CUSTOM_RECORDS = 300
# After the game makes something from a customisation, the mod reads the customisation again this many
# seconds later, in case the game fills it in as it makes the model, and records it if it changed.
CUSTOM_RECHECK_SECONDS = (1.0, 5.0, 20.0)
CUSTOM_WATCHED = 64  # customisations being read again at once
CUSTOM_MIN_SECONDS = 0.2  # a customisation the game hands over again sooner isn't read again
# Of a customisation that isn't yours and doesn't make one of the system's ships or multi-tools, such as
# another player's, only the file it makes is recorded, without its seed or anything else, the first few
# times in a session.
OTHER_CUSTOM_RECORDED = 20
# Your player state: your ships (cGcPlayerState.mShipResources, as NMS.py places them: each one's model
# file, seed and texture options) and the region NMS.py puts the customisations in, read whole. Recorded
# PLAYER_FIRST_SECONDS after the mod first records a system, then whenever it has changed and the game has
# made something from a customisation since, at most every PLAYER_EVERY_SECONDS, and when you click the
# button; at most PLAYER_RECORDS times a session.
SHIP_RESOURCES = 12
PLAYER_FIRST_SECONDS = 30.0
PLAYER_EVERY_SECONDS = 60.0
PLAYER_RECORDS = 12
# Models the game builds with the seed of one of your ships or multi-tools, recorded at most this many times
# a session.
OWN_MODELS_RECORDED = 300
# The textures of ships and multi-tools the game loads with a descriptor, as it may when it paints them for
# a seed: recorded (`tex` lines), the first this many of each file and seed a session.
TEXTURE_FOLDERS = ("/SPACECRAFT/", "/WEAPONS/")
TEXTURES_RECORDED = 200
# The paint the game picks for a model it makes (RECORD_PAINT). In the game's code (NMS.exe, October 2026)
# the task that makes a model first makes the model's 66 palettes from its seed, then hands one function the
# part of the task that keeps what's picked, the seed and the palettes; for each of the model's samplers
# that function picks a texture option for each layer of the model's textures, each painted in a color from
# a palette, unless it's handed options to keep, as a customisation has. NMS.py doesn't name that function:
# the mod finds it by PAINT_PATTERN, and once it returns reads the model's file from the task, and what was
# picked (`paint` lines). Only ships and multi-tools are read (PAINT_FOLDERS), and only those of the ships in
# a recorded system's ship list, of the multi-tools in recorded `pool` and `item` lines, and of yours are
# written, at most PAINT_RECORDED a session. The others wait in memory, at most PAINT_WAITING of them, up to
# PAINT_WAIT_SECONDS for such a line to name their seed, which the mod looks for every PAINT_CHECK_SECONDS,
# and are then dropped unwritten, as other players' are.
PAINT_PATTERN = (
    "4C 89 4C 24 ? 48 89 54 24 ? 55 56 57 41 54 41 55 41 56 41 57 48 8D 6C 24 ? 48 81 EC ? ? ? ? 8B"
)
PAINT_FOLDERS = ("/SPACECRAFT/", "/WEAPONS/")
PAINT_RECORDED = 5000
PAINT_WAITING = 500
PAINT_WAIT_SECONDS = 120.0
PAINT_CHECK_SECONDS = 1.0
# Where, as the game's code places them, the part of the task the function is handed sits in the task, the
# task's model file (a cTkFixedString<0x100>) and descriptor (whose seed the function is handed, unless the
# task holds another to paint with) are in the task, and the list of what was picked (a
# cTkProceduralTextureChosenOptionList) is pointed to from the part handed over.
PAINT_TASK_PART = 0x1D8
PAINT_TASK_FILE = 0x28
PAINT_TASK_DESCRIPTOR = 0x128
PAINT_PART_OPTIONS = 0x10
# 0.13.0's captures showed that a ship's paint takes its colors from the palettes the game makes from the
# ship's seed, and a freighter's or a frigate's from those of its system's seed; a multi-tool's from neither.
# So for multi-tools the mod also records the palettes the function was handed: PALETTE_COUNT of PALETTE_ENTRY
# bytes, each five colors and then their places in the palette (at PALETTE_PLACES); and for every model,
# whether the task was told to use the game's older palettes (a flag at PAINT_TASK_LEGACY), and the color it
# was told to paint with, if it was.
PAINT_TASK_LEGACY = 0x1C9
PALETTE_ENTRY = 0x70
PALETTE_PLACES = 0x50
# A system's suns (RECORD_STARS). In the game's code (NMS.exe, October 2026) each sun is a copy of the
# system's one space POI of type Star, numbered from 0, the main sun, by how many stars the system has. The
# behaviour of that POI's entry in the game's space POI table is a cGcSpacePoiStarData, whose ColourVariants
# name five color variants for suns; sun number k is drawn with the one at (the system's star type + k) mod 5.
# The game tells a behaviour's class by a hash of its name, STAR_POI_DATA, next to the pointer to it. Once a
# session, the mod records each Star entry of the table with the names (a `suns` line), looking for the table
# every SUNS_RETRY_SECONDS until the game has loaded it.
STAR_POI_DATA = 0x72DD9DBF
MAX_POI_ITEMS = 1024
MAX_POI_TYPE = 0xFF  # a type beyond this means the table isn't where, or as, NMS.py says
SUNS_RETRY_SECONDS = 10.0
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
# The texture options picked for something, and your ships, in customisation and player records.
TEXTURE_OPTION_COLUMNS = [
    "sampler", "layer", "group", "option", "palette", "colorAlt", "index", "color", "override",
]  # fmt: skip
PLAYER_SHIP_COLUMNS = ["place", "file", "seed", "useSeed", "altId", "options"]
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
    "customisation": "cGcCustomisationComponentData",
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
        # Your own ships and their customisations (RECORD_COLORS).
        player = nms.cGcPlayerState
        self.ship_resources = player.mShipResources.offset
        self.ship_resource_size = ctypes.sizeof(nmse.cGcResourceElement)
        self.primary_ship = player.miPrimaryShip.offset
        self.customisations = player.mCustomisationData.offset
        self.customisation_size = ctypes.sizeof(nms.cGcResourceCustomisation)
        custom = nms.CustomisationData
        self.custom_seed = custom.mResourceSeed.offset
        self.custom_parts = custom.mDescriptors.offset
        self.custom_options = custom.mTextureOptions.offset
        self.custom_legacy = custom.mbUseLegacyColourPalettes.offset
        self.custom_edited = custom.mbEditedColours.offset
        self.color_sets = (custom.mEditColours.offset, custom.mFinalColours.offset)
        # The customisations as one region: as many bytes as the biggest a customisation may be (see
        # CUSTOMISATION_READ) times how many there are.
        self.customisations_size = CUSTOMISATION_SLOTS * max(CUSTOMISATION_READ, self.customisation_size)
        # The game's space POI table, for its color variants for suns (see STAR_POI_DATA).
        item = nmse.cGcSpacePoiTableItem
        self.application_data = nms.cGcApplication.mpData.offset
        self.poi_table = (
            nms.cGcApplication.Data.mRealityManager.offset + nms.cGcRealityManager.mpSpacePoiTable.offset
        )
        self.poi_items = nmse.cGcSpacePoiTable.Items.offset
        self.poi_item_size = ctypes.sizeof(item)
        self.poi_id = item.Id.offset
        self.poi_behaviour = item.Behaviour.offset
        self.poi_type = item.Type.offset
        variants = dict(nmse.cGcSpacePoiStarData._fields_)["ColourVariants"]  # a ctypes array of names
        self.star_variants = nmse.cGcSpacePoiStarData.ColourVariants.offset
        self.star_variant_size = ctypes.sizeof(variants._type_)
        self.star_variant_count = variants._length_

    def color_layout(self) -> dict:
        """Where the mod reads your ships and their customisations, as NMS.py places them, for the
        session header: a capture can then be read again if the places turn out wrong."""
        custom = nms.CustomisationData
        return {
            "shipResources": f"{self.ship_resources:X}",
            "shipResourceSize": self.ship_resource_size,
            "primaryShip": f"{self.primary_ship:X}",
            "customisations": f"{self.customisations:X}",
            "customisationSize": self.customisation_size,
            "customisationsRead": self.customisations_size,
            "fields": {
                name: f"{getattr(custom, name).offset:X}"
                for name in ("mResourceSeed", "mDescriptors", "mTextureOptions", "mbUseLegacyColourPalettes",
                             "mbEditedColours", "mEditColours", "mFinalColours", "mfScale")
            },
            "colorSets": [f"{offset:X}" for offset in self.color_sets],
        }  # fmt: skip

    def poi_layout(self) -> dict:
        """Where the mod reads the game's space POI table, as NMS.py places it, for the session header."""
        return {
            "table": f"{self.application_data:X}>{self.poi_table:X}",
            "items": f"{self.poi_items:X}",
            "itemSize": self.poi_item_size,
            "fields": {
                "id": f"{self.poi_id:X}",
                "behaviour": f"{self.poi_behaviour:X}",
                "type": f"{self.poi_type:X}",
            },
            "variants": [f"{self.star_variants:X}", self.star_variant_size, self.star_variant_count],
        }


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
    sources["palette"] = getattr(nmse.cTkPaletteTexture, "ePaletteEnum", None)
    sources["colorAlt"] = getattr(nmse.cTkPaletteTexture, "eColourAltEnum", None)
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
    found["parts"] = part_ids(pointer, count, problems)
    if problems:
        found["errors"] = problems
    if problems or keep_raw:
        found["raw"] = raw.hex().upper()
    return found


def part_ids(pointer: int, count: int, problems: list[str]) -> list[str]:
    """The ``count`` IDs (TkID<0x20>) of the list at ``pointer``, such as the parts of a model, noting in
    ``problems`` why they couldn't be read."""
    if not count:
        return []
    size = ctypes.sizeof(basic.TkID0x20)
    if not pointer or not 0 < count <= MAX_MODEL_PARTS:
        problems.append(f"implausible part list (count {count}, pointer {pointer:#x})")
        return []
    part_bytes = read_memory(pointer, count * size)
    if part_bytes is None:
        problems.append(f"part list at {pointer:#x} couldn't be read")
        return []
    parts = [
        part_bytes[i : i + size].split(b"\0", 1)[0].decode("ascii", errors="backslashreplace")
        for i in range(0, len(part_bytes), size)
    ]
    if not all(part.isprintable() for part in parts):
        problems.append("part IDs that aren't text")
    return parts


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


def is_texture(name: str) -> bool:
    """Whether ``name`` is one of the textures of a ship or a multi-tool."""
    path = name.replace("\\", "/").upper()
    return path.startswith("TEXTURES/") and any(folder in path for folder in TEXTURE_FOLDERS)


def is_painted_model(name: str) -> bool:
    """Whether ``name`` is the model of a ship or a multi-tool, whose paint the mod reads (RECORD_PAINT)."""
    path = name.replace("\\", "/").upper()
    return path.startswith("MODELS/") and any(folder in path for folder in PAINT_FOLDERS)


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


# --- Your ships' colors (RECORD_COLORS) ---


def texture_options(address: int, problems: list[str]) -> list[list]:
    """The texture options picked for something, from the cTkProceduralTextureChosenOptionList at
    ``address``: one row per option, [sampler, layer, group, option, palette, color alt, index, [r, g, b,
    a], override], the sampler counting from 0, the palette and color alt as values of the game's
    cTkPaletteTexture enums. Why any couldn't be read goes in ``problems``."""
    options_type = nmse.cTkProceduralTextureChosenOptionList
    raw = read_memory(address, ctypes.sizeof(options_type))
    if raw is None:
        problems.append(f"texture options at {address:#x} couldn't be read")
        return []
    samplers = options_type.from_buffer_copy(raw).Samplers
    count, pointer = as_int(samplers.Size), as_int(samplers.ArrayPointer)
    if not count:
        return []
    sampler_type = nmse.cTkProceduralTextureChosenOptionSampler
    option_type = nmse.cTkProceduralTextureChosenOption
    if not pointer or count > MAX_TEXTURE_SAMPLERS:
        problems.append(f"implausible texture samplers (count {count}, pointer {pointer:#x})")
        return []
    raw = read_memory(pointer, count * ctypes.sizeof(sampler_type))
    if raw is None:
        problems.append(f"texture samplers at {pointer:#x} couldn't be read")
        return []
    rows: list[list] = []
    for index, sampler in enumerate((sampler_type * count).from_buffer_copy(raw)):
        size, at = as_int(sampler.Options.Size), as_int(sampler.Options.ArrayPointer)
        if not size:
            continue
        if not at or size > MAX_TEXTURE_OPTIONS:
            problems.append(f"implausible texture options (sampler {index}, count {size}, pointer {at:#x})")
            continue
        options = read_memory(at, size * ctypes.sizeof(option_type))
        if options is None:
            problems.append(f"texture options at {at:#x} couldn't be read")
            continue
        for option in (option_type * size).from_buffer_copy(options):
            colour, palette = option.Colour, option.Palette
            rows.append(
                [
                    index,
                    text(option.Layer),
                    text(option.Group),
                    text(option.OptionName),
                    as_int(palette.Palette),
                    as_int(palette.ColourAlt),
                    as_int(palette.Index),
                    [number(colour.r), number(colour.g), number(colour.b), number(colour.a)],
                    int(bool(option.OverrideColour)),
                ]
            )
    return rows


def color_sets(raw: bytes) -> dict[str, list[list[int]]]:
    """The sets of colors in a customisation's bytes, where NMS.py puts them (the colors you edited, then
    those the game uses), if they look like colors there, by their offset in hex: for each of the 66
    palettes, the five colors' places in the palette (Primary and Alternative1 to 4; -1 for a color that
    isn't one of the palette's). A set looks like colors if all its places are -1 to 63, all its colors'
    components are finite numbers from 0 to 16, and some are not 0."""
    palette_type = nmse.cGcColourPaletteData
    size = ctypes.sizeof(palette_type)
    found: dict[str, list[list[int]]] = {}
    for offset in LAYOUT.color_sets:
        if offset + PALETTE_COUNT * size > len(raw):
            continue
        palettes = (palette_type * PALETTE_COUNT).from_buffer_copy(raw, offset)
        places = [[int(i) for i in palette.ColourIndices] for palette in palettes]
        components = [
            value
            for palette in palettes
            for colour in palette.Colours
            for value in (colour.r, colour.g, colour.b, colour.a)
        ]
        if (
            all(-1 <= i < 64 for row in places for i in row)
            and all(math.isfinite(v) and 0.0 <= v <= 16.0 for v in components)
            and any(components)
        ):
            found[f"{offset:X}"] = places
    return found


def customisation(address: int) -> tuple[dict, bytes]:
    """What the cGcResourceCustomisation at ``address`` holds, as NMS.py places it: its `seed`, the IDs of
    the parts it's made of (`parts`), the texture options picked for it (`options`), whether it uses the
    game's older palettes and whether you edited its colors (`flags`), and its sets of colors (`colors`,
    see color_sets); and the bytes it was read from (see CUSTOMISATION_READ). Raises CaptureError if
    nothing could be read."""
    raw = None
    for size in (CUSTOMISATION_READ, LAYOUT.customisation_size, LAYOUT.custom_options + 0x60):
        if (raw := read_memory(address, size)) is not None:
            break
    if raw is None:
        raise CaptureError(f"the customisation at {address:#x} couldn't be read")
    seed = basic.GcSeed.from_buffer_copy(raw, LAYOUT.custom_seed)
    allocated, count, pointer = struct.unpack_from("<IIQ", raw, LAYOUT.custom_parts)
    problems: list[str] = []
    found: dict = {
        "seed": hex64(seed.Seed),
        "useSeed": as_int(seed.UseSeedValue),
        "parts": part_ids(pointer, count, problems) if count <= allocated else [],
        "options": texture_options(address + LAYOUT.custom_options, problems),
        "flags": [raw[LAYOUT.custom_legacy], raw[LAYOUT.custom_edited]],
    }
    if count > allocated:
        problems.append(f"implausible part list (count {count} of {allocated})")
    if colors := color_sets(raw):
        found["colors"] = colors
    if problems:
        found["errors"] = problems
    return found, raw


def variable_string(raw: bytes, offset: int, limit: int = MODEL_NAME_LENGTH) -> str | None:
    """The text of the VariableSizeString at ``offset`` in ``raw``: "" if it's empty, None if it can't be
    read or isn't text."""
    pointer, count = struct.unpack_from("<QI", raw, offset)
    if not count:
        return ""
    if not pointer or count > limit:
        return None
    value = read_memory(pointer, count)
    if value is None:
        return None
    value = value.split(b"\0", 1)[0].decode("utf-8", errors="backslashreplace")
    return value if value.isprintable() else None


def player_ships(state: int) -> tuple[list[list], bytes | None]:
    """Your ships, as NMS.py places them in your player state (cGcPlayerState.mShipResources): one row per
    place, [place, model file, seed, use-seed flag, alternative ID, texture options], the file and ID None
    where they can't be read; and the bytes they were read from."""
    element = nmse.cGcResourceElement
    size = LAYOUT.ship_resource_size
    raw = read_memory(state + LAYOUT.ship_resources, SHIP_RESOURCES * size)
    if raw is None:
        return [], None
    rows = []
    for place in range(SHIP_RESOURCES):
        at = place * size
        seed = basic.GcSeed.from_buffer_copy(raw, at + element.Seed.offset)
        problems: list[str] = []
        options = texture_options(
            state + LAYOUT.ship_resources + at + element.ProceduralTexture.offset, problems
        )
        row = [
            place,
            variable_string(raw, at + element.Filename.offset),
            hex64(seed.Seed),
            as_int(seed.UseSeedValue),
            variable_string(raw, at + element.AltId.offset),
            options,
        ]
        if problems:
            row.append(problems)
        rows.append(row)
    return rows, raw


def customisation_region(state: int) -> bytes | None:
    """The region of your player state that holds your customisations (see CUSTOMISATION_READ), or, if
    that can't be read, as much of it as NMS.py places them in; None if neither can."""
    at = state + LAYOUT.customisations
    region = read_memory(at, LAYOUT.customisations_size)
    if region is None:  # the player state may end sooner than the most the mod reads
        region = read_memory(at, CUSTOMISATION_SLOTS * LAYOUT.customisation_size)
    return region


def customisation_strides() -> list[int]:
    """How far apart the customisations in your player state may be (see CUSTOMISATION_STRIDES)."""
    return sorted({*CUSTOMISATION_STRIDES, LAYOUT.customisation_size})


def own_seeds(ships_raw: bytes | None, region: bytes | None) -> dict[str, str]:
    """The seeds of your ships and of your customisations, with what each is ("ship 3", your fourth ship;
    "slot 2 at 3A78", the third customisation if they're 0x3A78 bytes apart), from the bytes of your ships
    (see player_ships) and of the region your customisations are in. A seed below 2^32 is left out: a
    customisation's place read at the wrong distance is likelier to hold a small number than a seed."""
    seeds: dict[str, str] = {}
    if ships_raw is not None:
        at_seed = nmse.cGcResourceElement.Seed.offset
        for place in range(len(ships_raw) // LAYOUT.ship_resource_size):
            at = place * LAYOUT.ship_resource_size + at_seed
            if (value := int.from_bytes(ships_raw[at : at + 8], "little")) >= 1 << 32:
                seeds.setdefault(hex64(value), f"ship {place}")
    if region is not None:
        for stride in customisation_strides():
            for slot in range(CUSTOMISATION_SLOTS):
                at = slot * stride + LAYOUT.custom_seed
                if (
                    at + 8 <= len(region)
                    and (value := int.from_bytes(region[at : at + 8], "little")) >= 1 << 32
                ):
                    seeds.setdefault(hex64(value), f"slot {slot} at {stride:X}")
    return seeds


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


def steam_account() -> int | None:
    """The account number of the Steam user logged in now, which Steam keeps as ActiveUser under
    STEAM_USER_KEY while it runs, or None (off Windows, or with no one logged in)."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STEAM_USER_KEY) as key:
            value, kind = winreg.QueryValueEx(key, "ActiveUser")
    except OSError:
        return None
    return value if kind == winreg.REG_DWORD and value else None


def save_folder_steam_id(appdata: str | None = None) -> str | None:
    """The SteamID64 in the name of the game's most recently changed save folder (st_<SteamID64> in
    SAVE_FOLDERS, in your roaming application data, ``appdata``), or None."""
    root = os.environ.get("APPDATA") if appdata is None else appdata
    if not root:
        return None
    try:
        folders = [
            (folder.stat().st_mtime, folder.name[3:])
            for folder in (Path(root) / SAVE_FOLDERS).glob("st_*")
            if folder.is_dir() and folder.name[3:].isdigit()
        ]
    except OSError:
        return None
    return max(folders)[1] if folders else None


def local_identifier() -> str:
    """A random identifier for this computer's captures, made the first time it's needed and kept in
    CAPTURE_DIR (IDENTIFIER_FILE), for when no Steam ID can be found."""
    path = CAPTURE_DIR / IDENTIFIER_FILE
    try:
        kept = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        kept = ""
    if re.fullmatch(r"[0-9a-f]{32}", kept):
        return kept
    made = uuid.uuid4().hex
    try:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(made + "\n", encoding="ascii")
    except OSError:
        logger.warning("Couldn't keep the identifier for this computer's captures in %s", path, exc_info=True)
    return made


def capture_identifier() -> tuple[str, str]:
    """Whose captures these are, for the files' names (see CAPTURE_DIR), and how the mod knows: the SteamID64
    of the Steam user logged in ("steam") or of the newest save folder ("save"), or the random identifier
    kept for this computer ("local")."""
    if account := steam_account():
        return str(STEAM_ID_BASE + account), "steam"
    if (found := save_folder_steam_id()) is not None:
        return found, "save"
    return local_identifier(), "local"


def new_capture_file(now: float | None = None) -> tuple[Path, str]:
    """Where a session's lines go (see CAPTURE_DIR): a file named for whose captures they are and for the
    time, ``now`` or else the present, in UTC; and how the mod knows whose they are (capture_identifier)."""
    identifier, source = capture_identifier()
    stamp = time.strftime(CAPTURE_TIME_FORMAT, time.gmtime(time.time() if now is None else now))
    return CAPTURE_DIR / f"{identifier}_{stamp}.jsonl", source


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


# --- How many stars a system has ---


def float32(value: float) -> float:
    """``value`` rounded to the nearest 32-bit float, as the game's float arithmetic rounds."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def read_star_shape(code: bytes) -> dict[str, int] | str:
    """Match ``code`` against STAR_COUNT_CODE: what each name in it stands for (an offset from the start
    of the code for <name> and ~name, the displacement itself for [name]), or why it doesn't match."""
    at = 0
    found: dict[str, int] = {}
    for text, _ in STAR_COUNT_CODE:
        tokens = text.split()
        end = at + sum(4 if token[0] in "<[" else 1 for token in tokens)
        if end > len(code):
            return f"its code ends before {at:#x}"
        position, named = at, []
        for token in tokens:
            size = 4 if token[0] in "<[" else 1 if token[0] == "~" else 0
            if size:
                named.append((token, int.from_bytes(code[position : position + size], "little", signed=True)))
                position += size
            elif code[position] != int(token, 16):
                return f"its code differs at {position:#x}"
            else:
                position += 1
        for token, value in named:
            name = token.strip("<>[]~")
            resolved = value if token[0] == "[" else end + value  # rip-relative and jumps count from the end
            if token[0] == "~" and found.get(name, resolved) != resolved:
                return f"its jumps differ at {at:#x}"
            found[name] = resolved
        at = end
    return found


def star_shape_problem(found: dict[str, int]) -> str | None:
    """Why what the matched code reads doesn't match where NMS.py says those values are, or None."""
    sky, debug, application = nmse.cGcSkyGlobals, nmse.cGcDebugOptions, nms.cGcApplication
    nebula = LAYOUT.data + nmse.cGcSolarSystemData.Sky.offset + nmse.cGcSpaceSkyProperties.NebulaSeed.offset
    if found["nebula"] != nebula:
        return f"it reads the solar system at +{found['nebula']:X}, not at its NebulaSeed (+{nebula:X})"
    if found["ternary"] - found["binary"] != sky.TernaryStarChance.offset - sky.BinaryStarChance.offset:
        return "the chances it reads aren't where NMS.py puts the sky globals' star chances"
    force = debug.ForceTernaryStar.offset - debug.ForceBinaryStar.offset
    boot = debug.BootMode.offset - debug.ForceBinaryStar.offset
    if (
        found["forceTernary"] - found["forceBinary"] != force
        or found["bootMode"] - found["forceBinary"] != boot
    ):
        return "the debug options it reads aren't where NMS.py puts them"
    if found["gameMode"] - found["data"] != application.meGameMode.offset - application.mpData.offset:
        return "the game mode it reads isn't where NMS.py puts the application's"
    if found["three"] == found["count"]:
        return "its jumps don't go where the count's shape says"
    return None


class StarCount:
    """cGcSolarSystem::GetStarCount, found in the game by STAR_COUNT_PATTERN: where it is, its first
    bytes, and, if its code has the shape of STAR_COUNT_CODE, where the values it reads are, so that the
    mod can read them and work a system's star count out as the function would."""

    def __init__(self, address: int, offset: int, code: bytes):
        self.address, self.offset, self.code = address, offset, code
        found = read_star_shape(code)
        self.why = found if isinstance(found, str) else star_shape_problem(found)
        self.places: dict[str, int] = {}
        if self.why is None:
            self.nebula, self.setting = found["nebula"], found["setting"]
            self.places = {name: address + found[name] for name in STAR_VALUES}

    def settings(self) -> dict | None:
        """The values the function reads besides the solar system's, now: None if one can't be read."""
        values: dict = {}
        for name, (kind, size) in STAR_VALUES.items():
            raw = read_memory(self.places[name], size)
            if raw is None:
                return None
            values[name] = struct.unpack(kind, raw)[0]
        data = values.pop("data")
        raw = read_memory(data + self.setting, 1) if data else None
        if raw is None:
            return None
        values["setting"] = raw[0]
        return values

    def count(self, system: int) -> int | None:
        """How many stars the solar system at ``system`` has, worked out as the function would; None if
        the function would take the way the mod doesn't know (see STAR_COUNT_CODE). Raises CaptureError
        if what it reads can't be read."""
        values = self.settings()
        raw = read_memory(system + self.nebula, 4) if values is not None else None
        if raw is None:
            raise CaptureError("the values the game counts a system's stars by couldn't be read")
        nebula = struct.unpack("<f", raw)[0]
        stars = 1 + (nebula > float32(values["one"] - values["ternary"]))
        stars += nebula > float32(values["one"] - values["binary"])
        if values["forceBinary"]:
            stars = 2
        if values["forceTernary"]:
            return 3
        if values["bootMode"] == SCRATCHPAD_BOOT or values["gameMode"] not in STAR_SETTING_MODES:
            return stars
        return None if values["setting"] else stars

    def info(self) -> dict:
        """What the session header says of the function: its code, and the values it reads now."""
        found = {
            "offset": f"{self.offset:X}",
            "code": self.code.hex().upper(),
            "shape": int(self.why is None),
        }
        if self.why is not None:
            found["why"] = self.why
        elif (values := self.settings()) is not None:
            found.update(values)
        return found


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


def application_data() -> int | None:
    """Where the game's application data is (cGcApplication::Data), or None while NMS.py hasn't found
    the game."""
    application = gameData.GcApplication
    if not isinstance(application, ctypes.Structure):
        return None
    return read_u64(ctypes.addressof(application) + LAYOUT.application_data) or None


def star_pois() -> list[dict] | None:
    """The Star entries of the game's space POI table (see STAR_POI_DATA): each one's place in the table
    and ID, and the names of the color variants for suns that its behaviour holds (``variants``), or the hash
    of its behaviour's class (``behaviour``) if that isn't cGcSpacePoiStarData. None while the table can't be
    read; raises CaptureError if what's read there doesn't look like the table."""
    data = application_data()
    table = read_u64(data + LAYOUT.poi_table) if data else None
    header = read_memory(table + LAYOUT.poi_items, 12) if table else None
    if header is None:
        return None
    pointer, count = struct.unpack("<QI", header)
    if not count:
        return None  # not loaded yet
    if not pointer or count > MAX_POI_ITEMS:
        raise CaptureError(f"implausible space POI table (count {count}, pointer {pointer:#x})")
    size = LAYOUT.poi_item_size
    raw = read_memory(pointer, count * size)
    if raw is None:
        raise CaptureError("the space POI table couldn't be read")
    stars: list[dict] = []
    for index in range(count):
        item = raw[index * size : (index + 1) * size]
        kind = int.from_bytes(item[LAYOUT.poi_type : LAYOUT.poi_type + 4], "little")
        if kind > MAX_POI_TYPE:
            raise CaptureError(f"implausible space POI type {kind} in entry {index}")
        if kind != enums.cGcSpacePoiType.Star:
            continue
        name = item[LAYOUT.poi_id : LAYOUT.poi_id + 16].split(b"\0", 1)[0]
        star: dict = {"index": index, "id": name.decode("utf-8", errors="backslashreplace")}
        behaviour, hashed = struct.unpack_from("<QI", item, LAYOUT.poi_behaviour)
        length, many = LAYOUT.star_variant_size, LAYOUT.star_variant_count
        names = None
        if hashed == STAR_POI_DATA and behaviour:
            names = read_memory(behaviour + LAYOUT.star_variants, length * many)
        if names is None:
            star["behaviour"] = f"{hashed:08X}"
        else:
            texts = (names[i * length : (i + 1) * length].split(b"\0", 1)[0] for i in range(many))
            star["variants"] = [name.decode("utf-8", errors="backslashreplace") for name in texts]
        stars.append(star)
    return stars


def paint_layout() -> dict:
    """Where the mod reads the paint the game picks (see PAINT_PATTERN), for the session header."""
    return {
        "pattern": PAINT_PATTERN,
        "taskPart": f"{PAINT_TASK_PART:X}",
        "taskFile": f"{PAINT_TASK_FILE:X}",
        "taskDescriptor": f"{PAINT_TASK_DESCRIPTOR:X}",
        "partOptions": f"{PAINT_PART_OPTIONS:X}",
    }


def palette_places(address: int) -> list[list[int]]:
    """For each palette in the palettes at ``address`` (see PALETTE_ENTRY), the places in the palette of its
    five colors. Raises CaptureError if they can't be read or don't look like places in palettes."""
    raw = read_memory(address, PALETTE_COUNT * PALETTE_ENTRY) if address else None
    if raw is None:
        raise CaptureError("the palettes the paint was picked from couldn't be read")
    places = [
        list(struct.unpack_from("<5i", raw, palette * PALETTE_ENTRY + PALETTE_PLACES))
        for palette in range(PALETTE_COUNT)
    ]
    if not all(-1 <= place < 64 for row in places for place in row):
        raise CaptureError("the palettes the paint was picked from don't hold places in palettes")
    return places


def painted_task(part: int) -> str | None:
    """The model file of the task the game handed the part at ``part`` of to the function that picks paint
    (see PAINT_PATTERN), if it's a ship's or a multi-tool's (PAINT_FOLDERS), or None."""
    name = read_c_string(part - PAINT_TASK_PART + PAINT_TASK_FILE, MODEL_NAME_LENGTH)
    return name if name and is_painted_model(name) else None


class ProceduralTextures(Structure):
    """Functions of the game's procedural textures that NMS.py doesn't name, found in NMS.exe by their
    patterns (October 2026)."""

    # Picks the paint of a model the game is making (see PAINT_PATTERN), for each of its samplers: the
    # part of the task that keeps what's picked, the model's resource handle, the seed to pick with, the
    # model's palettes, a name and a color the textures may be matched against and painted with, whether
    # to paint them all with that color, and whether to keep the options already in the list instead.
    @static_function_hook(PAINT_PATTERN)
    @staticmethod
    def PickPaint(
        lpTaskPart: ctypes.c_uint64,
        lpResourceHandle: ctypes.c_uint64,
        lpSeed: ctypes.c_uint64,
        lpPalettes: ctypes.c_uint64,
        lpMatch: ctypes.c_uint64,
        lpColour: ctypes.c_uint64,
        lbUseColour: Annotated[bool, ctypes.c_bool],
        lbKeepOptions: Annotated[bool, ctypes.c_bool],
    ) -> None: ...


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


def player_state_address() -> int | None:
    """Where your player state is, or None while there's none."""
    try:
        state = gameData.player_state
    except (ValueError, AttributeError):
        return None
    return ctypes.addressof(state) if state is not None else None


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


def star_info(stars: StarCount | str | None) -> dict | str | None:
    """What the session header says of the game's star count function (see StarCount.info), or why it
    wasn't found."""
    return stars.info() if isinstance(stars, StarCount) else stars


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
        "starCount": _guarded(star_info, getattr(mod, "_stars", None)),
        # Where the mod reads your ships and their customisations, if it does (RECORD_COLORS).
        "colorLayout": _guarded(LAYOUT.color_layout) if RECORD_COLORS else None,
        # Where it reads the paint the game picks (RECORD_PAINT), and the ways it draws suns (RECORD_STARS).
        "paintLayout": paint_layout() if RECORD_PAINT else None,
        "poiLayout": _guarded(LAYOUT.poi_layout) if RECORD_STARS else None,
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
            "textureOptions": TEXTURE_OPTION_COLUMNS,
            "playerShips": PLAYER_SHIP_COLUMNS,
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


# What the mod's tab says of a system's stars, by how many.
STAR_LABELS = {1: "1", 2: "2, a binary system", 3: "3, a trinary system"}


def stars_label(record: dict) -> str:
    """How many stars a recorded system has, as the mod's tab says it."""
    stars = record.get("stars")
    if isinstance(stars, int):
        return STAR_LABELS.get(stars, str(stars))
    if record.get("starsUnknown"):
        return f"Unknown: in game mode {record.get('gameMode')} the game can count them another way"
    if not RECORD_STARS:
        return "Off (RECORD_STARS is False)"
    return "Not worked out; the log says why"


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
        "and the parts it picks for them, the items the game offers, such as multi-tools, "
        "and the colors of your own ships and multi-tool."
    )
    __version__ = MOD_VERSION
    __pymhf_required_version__ = "0.2.4"

    # Class-level defaults: pyMHF reads the GUI properties while the mod is
    # still being set up.
    _status = "Waiting for a star system to load."
    _last = "None yet."
    _stars_here = "None yet."
    _count = 0
    _query_count = 0
    _name_count = 0
    _model_count = 0
    _ship_models_seen = 0
    _tool_count = 0
    _pool_count = 0
    _offer_count = 0
    _item_count = 0
    _custom_count = 0
    _own_count = 0
    _player_count = 0

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        # Writing the capture file has a lock of its own, so no hook waits for the disk.
        self._write_lock = threading.Lock()
        self._recorded_keys: set[str] = set()
        self._session_started = False
        self._capture_file: Path | None = None  # this session's, once its first line is written
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
        # thread; the multi-tools built lately while no system was being generated, which may start the
        # next system's set (in memory only); whether a system has been generated this session; sets
        # written, by (system, their files and seeds); the systems they're of; the threads seen, numbered.
        self._generating: dict[int, dict] = {}
        self._prelude: list[dict] = []
        self._generated_once = False
        self._pool_keys: set[tuple] = set()
        self._pool_systems: set[int] = set()
        self._threads: dict[int, int] = {}
        # What the mod knows of each item the game offers, by address (see _item_updated);
        # items written, by (system, what they held); item types the log has mentioned;
        # multi-tools recorded, by seed; offers of one recorded, by (system, seed).
        self._items: dict[int, dict] = {}
        self._item_keys: set[tuple] = set()
        self._item_types_logged: set[int] = set()
        self._tools_heard: set[str] = set()
        self._offers_heard: set[tuple] = set()
        # Colors (RECORD_COLORS). Customisations written, by (address, what they held); customisations to
        # read again, by address; when each address was last read; the files of other customisations
        # written; the seeds of your ships and customisations, with what each is; seeds whose tone has
        # played; your player state: what it held when last written, how often it was, when it's next due,
        # whether you clicked the button, whether a customisation was written since; models written with
        # one of your seeds.
        self._custom_keys: set[tuple] = set()
        self._custom_watch: dict[int, dict] = {}
        self._custom_read: dict[int, float] = {}
        self._custom_calls: set[tuple[int, int]] = set()  # (thread, address) of calls read, till they return
        self._other_customs: set[str] = set()
        self._own_seeds: dict[str, str] = {}
        self._own_refreshed = -math.inf  # when the mod last looked at your ships' and customisations' seeds
        self._colors_heard: set[str] = set()
        self._player_signature: str | None = None
        self._player_count = 0
        self._player_due: float | None = None
        self._player_armed = False  # whether the first record of your ships has been made due
        self._player_requested = False
        self._custom_since_player = False
        self._own_model_keys: set[tuple] = set()
        self._texture_keys: set[tuple] = set()  # textures written, by (file, seed, parts)
        # Paint (RECORD_PAINT): written, by (file, seed, model seed, kept); waiting for a line to name their
        # seed, by the same, with when they started waiting; how many written; whether the log has said so.
        self._paint_keys: set[tuple] = set()
        self._waiting_paint: dict[tuple, dict] = {}
        self._next_paint_check = 0.0
        self._paint_count = 0
        self._paint_logged = False
        # The color variants for suns (RECORD_STARS): whether they're recorded this session, and when to look
        # for them next.
        self._suns_recorded = False
        self._next_suns = 0.0
        # Resources the game has loaded, and how many came with a descriptor, for the log.
        self._resources = 0
        self._described = 0
        self._resources_logged = 0
        self._next_resource_count = time.monotonic() + FIRST_RESOURCE_COUNT_SECONDS
        try:
            prepare_sounds()
        except Exception:
            logger.warning("Couldn't prepare the sounds.", exc_info=True)
        logger.info("Trade Depot capture %s is recording to a new file in %s", MOD_VERSION, CAPTURE_DIR)
        if RECORD_MULTITOOLS and RECORD_SHIP_PARTS:
            logger.info(
                "A system's multi-tools are recorded as you arrive. To record the one on offer, with its "
                "class and slots, go up to the space station's multi-tool case or a settlement's "
                "multi-tool rack and look at what's for sale."
            )
        # The game's star count function (see StarCount), or why it wasn't found, for the session header.
        self._stars: StarCount | str | None = None
        self._guild_requested: str | None = None
        try:
            self._stars = locate_star_count()
        except Exception:
            self._report_once("stars-find", "Couldn't look for the game's star count function.")
        if isinstance(self._stars, StarCount):
            if self._stars.why is None:
                logger.info("Found the game's star count function: each system's stars are recorded.")
            else:
                logger.info(
                    "Found the game's star count function, but its code isn't what the mod knows (%s), so "
                    "stars aren't recorded. Its code goes in the capture file, to update the mod from.",
                    self._stars.why,
                )
        elif self._stars is not None:
            logger.info(
                "Couldn't find the game's star count function (%s): stars aren't recorded.", self._stars
            )

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
    @STRING("Colors recorded")
    def colors(self):
        if not RECORD_COLORS:
            return "Off (RECORD_COLORS is False)"
        return (
            f"{self._custom_count} customisations, {self._own_count} models of yours; your ships "
            f"{self._player_count} times"
        )

    @property
    @STRING("Paint recorded")
    def paint(self):
        if not RECORD_PAINT:
            return "Off (RECORD_PAINT is False)"
        return f"{self._paint_count} ships and multi-tools"

    @property
    @STRING("Last system")
    def last_system(self):
        return self._last

    @property
    @STRING("Stars in the last system")
    def stars_here(self):
        return self._stars_here

    @property
    @STRING("Capture file")
    def capture_file(self):
        if self._capture_file is None:
            return f"None yet: this session's goes in {CAPTURE_DIR}"
        return str(self._capture_file)

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

    @gui_button("Record your ships' colors now")
    def record_colors(self):
        # The game thread does the reading, on its next frame.
        self._player_requested = True
        self._status = "Recording your ships' colors..."

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
            # The system's set: the run of multi-tools built just before (see POOL_LEAD_SECONDS), then
            # those this thread builds until Generate returns; those other threads build meanwhile are
            # only counted.
            try:
                self._generating[threading.get_ident()] = self._start_pool(time.monotonic())
            except Exception:
                self._report_once("pool", "Couldn't start a system's set of multi-tools.")
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

    if RECORD_COLORS:  # otherwise the mod leaves this function alone
        # cGcResourceCustomisation::CreateGenerationTask(handle, file, copy options) starts making a model,
        # such as one of your ships or your multi-tool, from how it's customised: read before and after.
        @nms.cGcResourceCustomisation.CreateGenerationTask.before
        def before_generation_task(self, this, lpResourceHandle, lpResourceFilename, lbCopyOptions):
            try:
                self._customisation_used(this, lpResourceHandle, lpResourceFilename, lbCopyOptions, "call")
            except Exception:
                self._report_once("colors", "Couldn't record what the game made one of yours from.")

        @nms.cGcResourceCustomisation.CreateGenerationTask.after
        def after_generation_task(self, this, lpResourceHandle, lpResourceFilename, lbCopyOptions):
            try:
                self._customisation_used(this, lpResourceHandle, lpResourceFilename, lbCopyOptions, "return")
            except Exception:
                self._report_once("colors", "Couldn't record what the game made one of yours from.")

    if RECORD_PAINT:  # otherwise the mod leaves this function alone
        # Once the game has picked the paint of a model it's making (see PAINT_PATTERN), read what it picked.
        @ProceduralTextures.PickPaint.after
        def after_pick_paint(
            self,
            lpTaskPart,
            lpResourceHandle,
            lpSeed,
            lpPalettes,
            lpMatch,
            lpColour,
            lbUseColour,
            lbKeepOptions,
        ):
            try:
                self._paint_picked(lpTaskPart, lpSeed, lpPalettes, lpColour, lbUseColour, lbKeepOptions)
            except Exception:
                self._report_once("paint", "Couldn't record the paint the game picked for a model.")

    @main_loop.after
    def on_frame(self):
        try:
            self._watch_for_game(time.monotonic())
            self._record_guild()
            self._colors(time.monotonic())
            self._resolve_paint(time.monotonic())
            self._record_suns(time.monotonic())
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
        if RECORD_COLORS and is_texture(name):
            self._texture_requested(name, resource_type, descriptor)
            return
        # One of yours? Asked without the lock, which _own_model takes: a miss now and then is harmless.
        if RECORD_COLORS and descriptor["seed"] in self._own_seeds:
            self._own_model(name, resource_type, descriptor)
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

    def _thread_index(self) -> int:
        """The calling thread's number: 1 for the first thread the mod saw this session, and so on."""
        ident = threading.get_ident()
        if (index := self._threads.get(ident)) is None:
            with self._lock:
                index = self._threads.setdefault(ident, len(self._threads) + 1)
        return index

    def _start_pool(self, now: float) -> dict:
        """A system's set, as this thread starts generating the system: the run of multi-tools the game
        built last before (see POOL_LEAD_SECONDS), unless this is the session's first generation."""
        with self._lock:
            prelude, self._prelude = self._prelude, []
            first, self._generated_once = not self._generated_once, True
        run: list[dict] = []
        last = now
        for built in reversed(prelude):
            if last - built["at"] > POOL_LEAD_SECONDS:
                break
            run.append(built)
            last = built["at"]
        run.reverse()
        tools: list[dict] = []
        files = {model_file(built["entry"]["name"]).upper() for built in run}
        if not first and all(name in files for name in POOL_SIGNATURE):
            places: dict[tuple, int] = {}
            for built in run:
                entry = built["entry"]
                if (key := model_key(entry)) not in places:  # a model built again is the same one
                    places[key] = len(tools)
                    tools.append(entry)
                entry["pool"] = places[key]  # its place in the set, which items holding it then show
        pool = {"tools": tools, "since": now, "elsewhere": 0, "thread": self._thread_index()}
        if tools:
            pool["before"], pool["lead"] = len(tools), round(now - run[0]["at"], 3)
        return pool

    def _join_pool(self, entry: dict) -> bool:
        """Add a multi-tool model to the set of the system this thread is generating, if it's generating
        one; if another thread is, count it there; if none is, keep it in case it starts the next system's
        set. Only this thread adds to its set, so no lock is needed for that; a count another thread
        misses now and then doesn't matter."""
        pool = self._generating.get(threading.get_ident())
        if pool is None:
            generating = list(self._generating.values())
            for other in generating:
                other["elsewhere"] += 1
            if not generating:
                with self._lock:
                    self._prelude.append({"at": time.monotonic(), "entry": entry})
                    del self._prelude[:-POOL_TOOLS]
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
        thread = self._thread_index()
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
                    "thread": thread,
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
            record["thread"] = pool.get("thread")  # the thread that generated the system
            if pool.get("before"):  # how many were built before, and how long before the generation
                record["before"], record["lead"] = pool["before"], pool["lead"]
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
        context: dict = {"thread": self._thread_index()}
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
        context.update(self._star_context(address))
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

    # --- Colors (RECORD_COLORS) ---

    def _colors(self, now: float) -> None:
        """On the game's main thread: read again the customisations that are due, and record your ships
        if they're due or you clicked the button."""
        if not RECORD_COLORS:
            return
        try:
            self._recheck_customisations(now)
        except Exception:
            self._report_once("colors-later", "Couldn't read a customisation again.")
        requested = self._player_requested
        try:
            self._record_player(now)
        except Exception:
            self._report_once("colors-player", "Couldn't record your ships.")
            if requested:
                self._status = "Couldn't record your ships. See the log."
                play_sound("problem")

    def _whose(self, address: int, seed: str, now: float) -> dict | None:
        """Whose the customisation at ``address`` is, if the mod may record it: {"region": offset} if it's
        one of your customisations in your player state (the offset from the first, in hex); {"own": what}
        if its seed is one of your ships' or customisations' (see own_seeds); {"system": address, "slot":
        n} for a ship of a recorded system's list, or {"tool": 1} for a multi-tool of a system's set or one
        on offer; None for anything else, such as another player's."""
        state = player_state_address()
        if state:
            offset = address - state - LAYOUT.customisations
            for stride in customisation_strides():  # where one of them may start
                if 0 <= offset < CUSTOMISATION_SLOTS * stride and offset % stride == 0:
                    return {"region": f"{offset:X}"}
        if seed == ZERO_SEED:
            return None
        if state and seed not in self._own_seeds and now - self._own_refreshed >= 1.0:
            # Perhaps one of yours the mod hasn't seen yet: look at your ships' and customisations' seeds.
            self._own_refreshed = now
            ships_raw = read_memory(state + LAYOUT.ship_resources, SHIP_RESOURCES * LAYOUT.ship_resource_size)
            self._remember_own(own_seeds(ships_raw, customisation_region(state)))
        with self._lock:
            if (what := self._own_seeds.get(seed)) is not None:
                return {"own": what}
            if (place := self._ship_place(seed)) is not None:
                return {"system": hex64(place[0]), "slot": place[1]}
            if seed in self._tools_heard:
                return {"tool": 1}
        return None

    def _remember_own(self, seeds: dict[str, str]) -> None:
        """Note the seeds of your ships and customisations (see own_seeds), so the models the game builds
        with them, and customisations it hands over with them, are recorded as yours; a ship's place says
        best what a seed is."""
        with self._lock:
            for seed, what in seeds.items():
                if what.startswith("ship ") or seed not in self._own_seeds:
                    self._own_seeds[seed] = what
            while len(self._own_seeds) > 4 * CUSTOMISATION_SLOTS * len(customisation_strides()):
                del self._own_seeds[next(iter(self._own_seeds))]

    def _customisation_used(self, this, handle_pointer, name_pointer, copy_options, via: str) -> None:
        """The game is about to make (``via`` "call") or has started making ("return") a model from the
        customisation at ``this``: record what the customisation holds if it's yours or makes one of the
        system's ships or multi-tools (see _whose), and read it again a few times after it returns."""
        address = address_of(this)
        if not address:
            return
        now = time.monotonic()
        pair = (threading.get_ident(), address)  # a call and its return come on the same thread
        with self._lock:
            if via == "return":
                if pair not in self._custom_calls:
                    return  # its call wasn't read either
                self._custom_calls.discard(pair)
            else:
                last = self._custom_read.pop(address, None)
                if last is not None and now - last < CUSTOM_MIN_SECONDS:
                    self._custom_read[address] = last
                    return  # handed over again at once: as it was a moment ago
                self._custom_read[address] = now
                while len(self._custom_read) > 4 * CUSTOM_WATCHED:
                    del self._custom_read[next(iter(self._custom_read))]
                if len(self._custom_calls) < 4 * CUSTOM_WATCHED:
                    self._custom_calls.add(pair)
        name = read_c_string(address_of(name_pointer), MODEL_NAME_LENGTH) or ""
        raw_handle = read_memory(address_of(handle_pointer), 4)
        handle = int.from_bytes(raw_handle, "little") if raw_handle is not None else None
        found, raw = customisation(address)
        whose = self._whose(address, found["seed"], now)
        if whose is None:
            self._other_customisation(name, via)
            return
        entry = {
            "t": "custom",
            "at": int(time.time()),
            "via": via,
            "file": name,
            "copy": int(bool(copy_options)),
            "handle": handle,
            **whose,
            **found,
        }
        self._write_customisation(address, entry, raw)
        if via == "return":
            with self._lock:
                self._custom_watch.pop(address, None)
                self._custom_watch[address] = {
                    "entry": {k: entry[k] for k in ("file", "copy", "handle", *whose)},
                    "seed": found["seed"],
                    "since": now,
                    "due": [now + delay for delay in CUSTOM_RECHECK_SECONDS],
                }
                while len(self._custom_watch) > CUSTOM_WATCHED:
                    del self._custom_watch[next(iter(self._custom_watch))]

    def _write_customisation(self, address: int, entry: dict, raw: bytes) -> bool:
        """Queue a customisation for the capture file, with its bytes (as ``entry["raw"]``) once your name
        and title are taken out of them, or without them if your name can't be read; unless it holds the
        same as when last written from the same place this session. Returns whether it's queued."""
        pattern, problem = player_name_pattern()
        shown = None
        if pattern is None:
            entry["nameUnread"] = problem
        else:
            shown, scrubbed = scrub(raw, pattern)
            if scrubbed:
                entry["scrubbed"] = scrubbed
        # What it holds: not when or how it was read, nor the bytes NMS.py doesn't place, which hold
        # addresses that change as the game moves the lists around, and memory past the customisation.
        held = {k: v for k, v in entry.items() if k not in ("at", "via", "after", "handle")}
        tail = (shown or b"")[LAYOUT.custom_legacy : LAYOUT.customisation_size]
        signature = hashlib.sha1(dumps(held).encode() + tail).hexdigest()
        seed = entry["seed"]
        with self._lock:
            key = (address, signature)
            if key in self._custom_keys:
                return False
            full = len(self._custom_keys) >= MAX_CUSTOM_RECORDS
            if not full:
                self._custom_keys.add(key)  # claimed, so no other thread writes it meanwhile
        if full:
            self._report_once(
                "custom-full", "Recorded %d customisations this session; no more until the next.",
                MAX_CUSTOM_RECORDS, with_traceback=False,
            )  # fmt: skip
            return False
        if shown is not None:
            entry["raw"] = packed(shown)  # only once it's to be written: compressing takes a moment
        with self._lock:
            self._pending.append(entry)
            self._custom_count += 1
            self._custom_since_player = True
            if ("region" in entry or "own" in entry) and seed != ZERO_SEED:
                self._own_seeds.setdefault(seed, entry.get("own") or f"customisation at {entry['region']}")
            first = seed not in self._colors_heard
            self._colors_heard.add(seed)
        if first:
            kind = "one of yours" if ("region" in entry or "own" in entry) else "one of the system's"
            logger.info(
                "Recorded what the game makes %s from, %s (seed %s): %d texture options, %s.",
                model_file(entry["file"]) or "something",
                kind,
                seed,
                len(entry["options"]),
                "colors" if "colors" in entry else "no colors where the mod looks",
            )
            self._status = "Recorded the colors of a ship or multi-tool."
            play_sound("colors")
        return True

    def _recheck_customisations(self, now: float) -> None:
        """Read again the customisations whose time has come (see CUSTOM_RECHECK_SECONDS), and record any
        that changed; at the last time, with what the game's resource manager holds for the handle the game
        made the model with. One that holds another seed now has been reused for something else."""
        if not self._custom_watch:
            return
        with self._lock:
            due = [
                (address, watch) for address, watch in self._custom_watch.items() if watch["due"][0] <= now
            ]
            for address, watch in due:
                while watch["due"] and watch["due"][0] <= now:  # one read for all the times passed
                    watch["due"].pop(0)
                if not watch["due"]:
                    del self._custom_watch[address]
        for address, watch in due:
            try:
                found, raw = customisation(address)
            except CaptureError:
                continue
            if found["seed"] != watch["seed"]:
                continue
            entry = {
                "t": "custom",
                "at": int(time.time()),
                "via": "later",
                "after": round(now - watch["since"], 1),
                **watch["entry"],
                **found,
            }
            if not watch["due"]:  # the last time: with what the resource manager holds for the handle
                if (resource := self._resource_of(watch["entry"]["handle"] or 0)) is not None:
                    entry["resource"] = resource
            self._write_customisation(address, entry, raw)

    def _other_customisation(self, name: str, via: str) -> None:
        """A customisation that isn't yours and doesn't make one of the system's ships or multi-tools, such
        as another player's: record only the file the game makes from it, the first few times."""
        with self._lock:
            if name in self._other_customs or len(self._other_customs) >= OTHER_CUSTOM_RECORDED:
                return
            self._other_customs.add(name)
            self._pending.append(
                {"t": "custom", "at": int(time.time()), "via": via, "file": name, "other": 1}
            )
        logger.info(
            "The game makes %s from a customisation that isn't yours nor one of the system's ships or "
            "multi-tools: only its file is recorded.",
            model_file(name) or "something",
        )

    def _paint_picked(
        self, part_pointer, seed_pointer, palettes_pointer, colour_pointer, use_colour, keep
    ) -> None:
        """Note the paint the game picked for a ship or multi-tool it's making (see PAINT_PATTERN): write it
        if it's one the mod records, else keep it waiting for a line that names its seed."""
        part = address_of(part_pointer)
        name = painted_task(part) if part else None
        if name is None:
            return
        raw = read_memory(address_of(seed_pointer), ctypes.sizeof(basic.GcSeed))
        if raw is None:
            raise CaptureError("the seed the paint was picked with couldn't be read")
        seed = basic.GcSeed.from_buffer_copy(raw)
        problems: list[str] = []
        options = read_u64(part + PAINT_PART_OPTIONS)
        rows = texture_options(options, problems) if options else []
        entry: dict = {
            "at": int(time.time()),
            "file": name,
            "seed": hex64(seed.Seed),
            "useSeed": as_int(seed.UseSeedValue),
            "options": rows,
        }
        if keep:
            entry["kept"] = 1  # the options the task was handed, as a customisation has, not picked now
        if use_colour:
            colour = read_memory(address_of(colour_pointer), 16)
            entry["useColour"] = [number(c) for c in struct.unpack("<4f", colour)] if colour else 1
        legacy = read_memory(part - PAINT_TASK_PART + PAINT_TASK_LEGACY, 1)
        if legacy is not None and legacy[0]:
            entry["legacy"] = 1
        if is_multitool_model(name):
            try:
                entry["palettes"] = palette_places(address_of(palettes_pointer))
            except CaptureError as exc:
                problems.append(str(exc))
        try:
            model = resource_descriptor(part - PAINT_TASK_PART + PAINT_TASK_DESCRIPTOR)
        except CaptureError as exc:
            problems.append(str(exc))
        else:
            if model is not None:
                entry["parts"] = model["parts"]
                if model["seed"] != entry["seed"]:
                    entry["modelSeed"] = model["seed"]
                problems.extend(model.get("errors", []))
        if problems:
            entry["errors"] = problems
        key = (name, entry["seed"], entry.get("modelSeed"), bool(keep))
        with self._lock:
            if key in self._paint_keys or key in self._waiting_paint:
                return
            place = self._paint_place(entry)
            if place is not None:
                self._write_paint(key, entry, place)
                return
            self._waiting_paint[key] = dict(entry, waited=time.monotonic())
            while len(self._waiting_paint) > PAINT_WAITING:
                del self._waiting_paint[next(iter(self._waiting_paint))]

    def _paint_place(self, entry: dict) -> dict | None:
        """What the model whose paint is in ``entry`` is, by the seed it was painted with or else the one it
        was made with, if the mod records it: one of yours (``own``), one of the multi-tools in recorded
        lines (``tool``), or a ship in a recorded system's ship list (``system`` and ``slot``); else None.
        The caller holds the lock."""
        for seed in (entry["seed"], entry.get("modelSeed")):
            if seed is None or seed == ZERO_SEED:
                continue
            if (what := self._own_seeds.get(seed)) is not None:
                return {"own": what}
            if is_multitool_model(entry["file"]):
                if seed in self._tools_heard:
                    return {"tool": 1}
            elif (place := self._ship_place(seed)) is not None:
                return {"system": hex64(place[0]), "slot": place[1]}
        return None

    def _write_paint(self, key: tuple, entry: dict, place: dict) -> None:
        """Queue a model's paint for the capture file. The caller holds the lock."""
        if key in self._paint_keys:
            return
        if len(self._paint_keys) >= PAINT_RECORDED:
            self._report_once(
                "paint-full",
                "Recorded the paint of %d ships and multi-tools this session; no more until the next.",
                PAINT_RECORDED,
                with_traceback=False,
            )
            return
        self._paint_keys.add(key)
        record = {"t": "paint", "at": entry["at"], **place}
        record.update((k, v) for k, v in entry.items() if k not in ("at", "waited"))
        self._pending.append(record)
        self._paint_count = len(self._paint_keys)
        if not self._paint_logged:
            self._paint_logged = True
            logger.info(
                "Recorded the paint the game picked for %s (seed %s): %d texture options. The paint of the "
                "ships and multi-tools the mod records is recorded from now on.",
                model_file(entry["file"]),
                entry["seed"],
                len(entry["options"]),
            )

    def _resolve_paint(self, now: float) -> None:
        """Write the paint waiting for a line that has since named its seed, and drop what has waited too
        long (see PAINT_WAIT_SECONDS)."""
        if not self._waiting_paint or now < self._next_paint_check:
            return
        self._next_paint_check = now + PAINT_CHECK_SECONDS
        with self._lock:
            for key, entry in list(self._waiting_paint.items()):
                place = self._paint_place(entry)
                if place is not None:
                    del self._waiting_paint[key]
                    self._write_paint(key, entry, place)
                elif now - entry["waited"] > PAINT_WAIT_SECONDS:
                    del self._waiting_paint[key]

    def _record_suns(self, now: float) -> None:
        """Once a session, record the game's color variants for suns (see STAR_POI_DATA)."""
        if not RECORD_STARS or self._suns_recorded or now < self._next_suns:
            return
        self._next_suns = now + SUNS_RETRY_SECONDS
        try:
            stars = star_pois()
        except CaptureError as exc:
            self._suns_recorded = True  # what's there doesn't look like the table: don't read it again
            self._report_once(
                "suns", "Couldn't read the game's space POI table: %s.", exc, with_traceback=False
            )
            return
        except Exception:
            self._suns_recorded = True
            self._report_once("suns", "Couldn't read the game's space POI table.")
            return
        if stars is None:
            return
        self._suns_recorded = True
        with self._lock:
            self._pending.append({"t": "suns", "at": int(time.time()), "stars": stars})
        named = [star for star in stars if "variants" in star]
        if named:
            logger.info("Recorded the game's color variants for suns: %s.", ", ".join(named[0]["variants"]))
        else:
            logger.info("Read the game's space POI table, but none of its stars has color variants for suns.")

    def _texture_requested(self, name: str, resource_type: int, descriptor: dict) -> None:
        """Queue a texture of a ship or multi-tool that the game loads with a descriptor, and the seed and
        parts in it, once a session per file and seed (see TEXTURES_RECORDED)."""
        key = (name, descriptor["seed"], tuple(descriptor["parts"]))
        with self._lock:
            if key in self._texture_keys or len(self._texture_keys) >= TEXTURES_RECORDED:
                return
            self._texture_keys.add(key)
            entry = {"t": "tex", "at": int(time.time()), "name": name, "type": resource_type}
            entry.update(descriptor)
            self._pending.append(entry)
        if len(self._texture_keys) == 1:
            logger.info("The game loads textures with a descriptor, as %s: they're recorded.", name)

    def _own_model(self, name: str, resource_type: int, descriptor: dict) -> None:
        """Queue a model the game builds with the seed of one of your ships or customisations, once a
        session (see OWN_MODELS_RECORDED)."""
        key = (name, descriptor["seed"], descriptor.get("seed2"), tuple(descriptor["parts"]))
        with self._lock:
            what = self._own_seeds.get(descriptor["seed"])
            full = len(self._own_model_keys) >= OWN_MODELS_RECORDED
            if what is None or key in self._own_model_keys or full:
                return
            self._own_model_keys.add(key)
            self._own_count += 1
            entry = {"t": "own", "at": int(time.time()), "whose": what, "name": name, "type": resource_type}
            entry.update(descriptor)
            self._pending.append(entry)

    def _record_player(self, now: float) -> None:
        """Record your ships and the region of your player state that holds your customisations, when
        they're due (see PLAYER_FIRST_SECONDS) or you clicked the button, unless they hold the same as when
        last recorded."""
        requested, self._player_requested = self._player_requested, False
        if not requested:
            if self._player_due is None or now < self._player_due:
                return
            if self._player_count and not self._custom_since_player:
                self._player_due = now + PLAYER_EVERY_SECONDS
                return
        if self._player_count >= PLAYER_RECORDS:
            self._player_due = None
            if requested:
                logger.info(
                    "Recorded your ships %d times this session; no more until the next.", PLAYER_RECORDS
                )
                self._status = "Your ships were recorded as often as the mod does in a session."
                play_sound("problem")
            return
        state = player_state_address()
        if not state:
            if requested:
                logger.info("Couldn't record your ships: no save is loaded yet.")
                self._status = "No save is loaded yet."
                play_sound("problem")
            return
        ships, ships_raw = player_ships(state)
        region = customisation_region(state)
        raw_primary = read_memory(state + LAYOUT.primary_ship, 4)
        self._remember_own(own_seeds(ships_raw, region))
        self._player_due = now + PLAYER_EVERY_SECONDS
        self._custom_since_player = False
        signature = hashlib.sha1(
            dumps({"ships": ships}).encode() + (ships_raw or b"") + (region or b"")
        ).hexdigest()
        if signature == self._player_signature:
            if requested:
                logger.info("Your ships hold the same as when last recorded.")
                self._status = "Your ships are recorded already; nothing has changed."
                play_sound("recorded")
            return
        primary = int.from_bytes(raw_primary, "little", signed=True) if raw_primary is not None else None
        record: dict = {
            "t": "player",
            "at": int(time.time()),
            "why": "button" if requested else "changed" if self._player_count else "loaded",
            "primaryShip": primary,
            "ships": ships,
        }
        if region is None:
            record["errors"] = ["your customisations couldn't be read"]
        pattern, problem = player_name_pattern()
        if pattern is None:
            record["nameUnread"] = problem
        else:
            scrubbed = 0
            if ships_raw is not None:
                shown, count = scrub(ships_raw, pattern)
                record["shipsRaw"] = packed(shown)
                scrubbed += count
            if region is not None:
                shown, count = scrub(region, pattern)
                record["raw"], record["rawSize"] = packed(shown), len(region)
                scrubbed += count
            if scrubbed:
                record["scrubbed"] = scrubbed
        with self._lock:
            self._pending.append(record)
            self._player_count += 1
            self._player_signature = signature
        logger.info(
            "Recorded your ships (%d of them) and what the game keeps of how your things are customised.",
            sum(1 for row in ships if row[1]),
        )
        if requested:
            self._status = "Recorded your ships' colors."
            play_sound("colors")

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
            context.update(self._star_context(named_system))
        return context

    def _star_context(self, system: int) -> dict:
        """How many stars the solar system at ``system`` has (``stars``), worked out as the game's own
        function would; or that the function would go the way the mod doesn't follow (``starsUnknown``),
        with the game mode it would go that way in."""
        stars = self._stars
        if not isinstance(stars, StarCount) or stars.why is not None:
            return {}
        try:
            count = stars.count(system)
        except CaptureError as exc:
            self._report_once("stars", "Couldn't work out a system's stars: %s.", exc, with_traceback=False)
            return {}
        except Exception:
            self._report_once("stars", "Couldn't work out a system's stars.")
            return {}
        if count is not None:
            return {"stars": count}
        return {"starsUnknown": 1, "gameMode": (stars.settings() or {}).get("gameMode")}

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
            if RECORD_COLORS and not self._player_armed:  # your ships, once your save has loaded
                self._player_armed = True
                self._player_due = time.monotonic() + PLAYER_FIRST_SECONDS
        logger.info("Recorded %s", summary)
        self._last = summary
        self._stars_here = stars_label(entry)
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
        """Write lines to the session's capture file, after the session's header the first time, which makes
        the file (see new_capture_file). The caller holds self._write_lock."""
        lines = [] if self._session_started else [dumps(session_header(self))]
        lines.extend(dumps(entry) for entry in entries)
        if self._capture_file is None:
            self._capture_file, source = new_capture_file()
            whose = {
                "steam": "your Steam ID",
                "save": "the Steam ID of the game's newest save folder, as Steam didn't say who's logged in",
                "local": f"this computer's identifier in {IDENTIFIER_FILE}, as no Steam ID could be found",
            }[source]
            logger.info("Recording this session to a new file in %s, named for %s.", CAPTURE_DIR, whose)
        self._capture_file.parent.mkdir(parents=True, exist_ok=True)
        with self._capture_file.open("a", encoding="utf-8", newline="\n") as stream:
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
