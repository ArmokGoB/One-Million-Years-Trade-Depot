#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Summarise capture files written by mods/system_capture.py.

Prints what was recorded (systems, ship pools, exotics, the parts the game
picked for the ships it built, each exotic's against ship_model.py's squid
rule, each system's own multi-tools, and the items the game offered, such as
multi-tools); checks the game's
data against itself, which is where a struct layout that no longer matches
the game shows up first; and finds each system's ship seeds in the game's
random-number stream seeded by the system seed. Given a path to nms_namegen,
it also measures how often the generator behind the site agrees with the game.

Usage:
    python3 tools/captures/report.py mods/captures/systems.jsonl
    python3 tools/captures/report.py --namegen ../nms_namegen mods/captures/systems.jsonl

Only the standard library is needed, plus numpy for --namegen.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import statistics
import struct
import sys
import zlib
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# mix is re-exported for the tests.
from game_rng import MASK32, MASK64, MIX_A, MIX_B, mix, seeded_state, stream_states, unmix  # noqa: E402, F401
import ship_model  # noqa: E402  (nms_namegen is only needed for its bodies(), which --namegen uses)
from star_model import float32, nebula_seed, star_count  # noqa: E402, F401

SUPPORTED_FORMATS = {1, 2}
ZERO_SEED = "0" * 16
PLANET_BITS = 0xF << 52
# How far into a system's stream to look for its ships.
STREAM_LIMIT = 100_000
# A multi-tool's model file is in this folder, but not in these (as in the capture mod since 0.9.0).
MULTITOOL_DIR = "/WEAPONS/MULTITOOL/"
NOT_MULTITOOL_DIRS = ("/MULTITOOLPARTS/",)
# What an item record can say of the item, or of how it was recorded: 0 or 1, or why (nameUnread
# since 0.9.0 says why the player's name couldn't be read).
ITEM_FLAGS = ("free", "gift", "reward", "extra", "unsettled", "nameUnread")

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

# Game enum member names -> nms_namegen's numbering (see src/core/system.ts).
# The generator's draw index is the game's enum value for economy and race.
NAMEGEN_STAR = {"Yellow": 0, "Green": 1, "Blue": 2, "Red": 3, "Purple": 4}
NAMEGEN_RACE = {"None_": 0, "Traders": 1, "Explorers": 2, "Warriors": 3}
NAMEGEN_ECONOMY = {
    "Trading": 1,
    "Fusion": 2,
    "Scientific": 3,
    "Mining": 4,
    "Manufacturing": 5,
    "HighTech": 6,
    "PowerGeneration": 7,
}
NAMEGEN_WEALTH = {"Poor": 1, "Average": 2, "Wealthy": 3}
NAMEGEN_CONFLICT = {"Low": 1, "Default": 2, "High": 3}


class CaptureFormatError(ValueError):
    pass


# --- Records ---


@dataclass
class Session:
    header: dict
    source: str

    def name(self, enum: str, value: int | None) -> str | None:
        table = self.header.get("enums", {}).get(enum)
        if table is None or value is None or not 0 <= value < len(table):
            return None
        return table[value]


@dataclass
class SystemRecord:
    data: dict
    session: Session
    line: int

    @property
    def ua(self) -> int:
        """The universal address. While a system is being generated its address isn't set
        yet, but its seed holds the same value (observed in every capture so far)."""
        value = int(self.data["ua"], 16)
        if value == 0 and isinstance(self.data.get("seed"), str):
            value = int(self.data["seed"], 16)
        return value

    @property
    def portal(self) -> str:
        ua = self.ua
        return f"{(ua >> 52) & 0xF:X}{(ua >> 40) & 0xFFF:03X}{ua & MASK32:08X}"

    @property
    def system_code(self) -> int:
        """Portal code with planet digit 0, as nms_namegen takes it."""
        return (((self.ua >> 40) & 0xFFF) << 32) | (self.ua & MASK32)

    @property
    def galaxy(self) -> int:
        return (self.ua >> 32) & 0xFF

    @property
    def display_name(self) -> str:
        return self.data.get("displayName") or self.data.get("name") or ""

    def label(self) -> str:
        return f"{self.portal} galaxy {self.galaxy} {self.display_name or '(unnamed)'}"

    def name(self, enum: str, key: str, source: dict | None = None) -> str | None:
        value = (self.data if source is None else source).get(key)
        return self.session.name(enum, value)


@dataclass
class Captures:
    sessions: list[Session] = field(default_factory=list)
    records: list[SystemRecord] = field(default_factory=list)
    queries: list[dict] = field(default_factory=list)
    names: list[dict] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    # Items the game offered (multi-tools on racks and at merchants, gifts, rewards), with their session.
    items: list[tuple[dict, Session]] = field(default_factory=list)
    # Multi-tool models the game built, and the first build of other model files: no seeds or parts.
    built: list[tuple[dict, Session]] = field(default_factory=list)
    # The multi-tools the game built while it generated a system: the system's own set.
    pools: list[tuple[dict, Session]] = field(default_factory=list)
    # The guilds whose envoys the player said they saw, with the system they were in.
    guilds: list[tuple[dict, Session]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def by_system(self) -> dict[int, list[SystemRecord]]:
        grouped: dict[int, list[SystemRecord]] = {}
        for record in self.records:
            grouped.setdefault(record.ua & ~PLANET_BITS, []).append(record)
        return grouped

    def representative_by_system(self) -> dict[int, SystemRecord]:
        """One record per system: the first with a ship list, which is closest to what the
        generator produced, or else the last record. A name the game only showed later is
        carried over."""
        chosen: dict[int, SystemRecord] = {}
        for key, records in self.by_system().items():
            with_ships = [r for r in records if r.data.get("ships")]
            best = with_ships[0] if with_ships else records[-1]
            if not best.data.get("displayName"):
                named = next((r for r in records if r.data.get("displayName")), None)
                if named is not None:
                    best = SystemRecord(
                        dict(best.data, displayName=named.data["displayName"]), best.session, best.line
                    )
            chosen[key] = best
        return chosen


def read_captures(paths: Iterable[Path]) -> Captures:
    captures = Captures()
    for path in paths:
        session: Session | None = None
        with open(path, encoding="utf-8") as stream:
            for number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                where = f"{path}:{number}"
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    captures.skipped.append(f"{where}: not JSON ({exc.msg})")
                    continue
                if not isinstance(obj, dict):
                    captures.skipped.append(f"{where}: not a record")
                    continue
                kind = obj.get("t")
                if kind == "session":
                    if obj.get("format") not in SUPPORTED_FORMATS:
                        raise CaptureFormatError(
                            f"{where}: capture format {obj.get('format')!r} isn't supported by this report"
                        )
                    session = Session(obj, str(path))
                    captures.sessions.append(session)
                elif session is None:
                    captures.skipped.append(f"{where}: record before any session header")
                elif kind == "sys":
                    if not isinstance(obj.get("ua"), str):
                        captures.skipped.append(f"{where}: system record without an address")
                    else:
                        captures.records.append(SystemRecord(obj, session, number))
                elif kind == "query":
                    captures.queries.append(obj)
                elif kind == "name":
                    captures.names.append(obj)
                elif kind == "model":
                    captures.models.append(obj)
                elif kind == "item":
                    captures.items.append((obj, session))
                elif kind == "built":
                    captures.built.append((obj, session))
                elif kind == "pool":
                    captures.pools.append((obj, session))
                elif kind == "guild":
                    captures.guilds.append((obj, session))
                else:
                    captures.skipped.append(f"{where}: unknown record type {kind!r}")
    return captures


def percent(hits: int, total: int) -> str:
    return f"{100 * hits / total:5.1f}%" if total else "    -"


@dataclass
class Tally:
    label: str
    hits: int = 0
    total: int = 0
    misses: list[str] = field(default_factory=list)

    def add(self, ok: bool | None, describe: Callable[[], str]) -> None:
        if ok is None:
            return
        self.total += 1
        if ok:
            self.hits += 1
        else:
            self.misses.append(describe())

    def line(self, width: int) -> str:
        return f"  {self.label:<{width}} {self.hits:>5}/{self.total:<5} {percent(self.hits, self.total)}"


def tally_lines(tallies: list[Tally], examples: int) -> list[str]:
    width = max(len(t.label) for t in tallies)
    lines = [t.line(width) for t in tallies if t.total]
    for t in tallies:
        for miss in t.misses[:examples]:
            lines.append(f"    {t.label}: {miss}")
        if len(t.misses) > examples:
            lines.append(f"    {t.label}: ... {len(t.misses) - examples} more")
    return lines


# --- Report sections ---


def summary_lines(captures: Captures) -> list[str]:
    systems = captures.representative_by_system()
    files = sorted({s.source for s in captures.sessions})
    sets = sum(1 for pool, _ in captures.pools if pool.get("tools"))
    lines = [
        f"{len(files)} file(s), {len(captures.sessions)} session(s), "
        f"{len(captures.records)} record(s), {len(systems)} system(s), {len(captures.queries)} lookup(s), "
        f"{len(captures.names)} name(s), "
        f"{len(captures.models)} ship model(s), {sets} system multi-tool set(s), "
        f"{len(captures.items)} offered item(s), {len(captures.built)} model build note(s), "
        f"{len(captures.guilds)} guild(s)"
    ]
    builds = Counter(
        (s.header.get("exe") or "unknown", s.header.get("steamBuild") or "?", s.header.get("nmspy") or "?")
        for s in captures.sessions
    )
    for (exe, build, nmspy), count in builds.most_common():
        lines.append(f"  game exe {exe[:12]} (Steam build {build}) with NMS.py {nmspy}: {count} session(s)")
    unattached = Counter(
        f"{hook} {state}"
        for s in captures.sessions
        if isinstance(s.header.get("hooks"), dict)
        for hook, state in s.header["hooks"].items()
        if state != "enabled"
    )
    if unattached:
        lines.append(
            "  hooks not attached: " + ", ".join(f"{k} ({n} session(s))" for k, n in unattached.items())
        )
    galaxies = Counter(r.galaxy for r in systems.values())
    if galaxies:
        lines.append("  galaxies: " + ", ".join(f"{g} x{n}" for g, n in sorted(galaxies.items())))
    via = Counter(r.data.get("via", "?") for r in captures.records)
    lines.append("  recorded by: " + ", ".join(f"{k} {n}" for k, n in via.most_common()))
    errors = sum(1 for r in captures.records if r.data.get("errors"))
    unusual = sum(1 for r in captures.records if _unusual(r))
    lines.append(f"  records with read errors: {errors}; with unusual values: {unusual}")
    for problem in captures.skipped[:10]:
        lines.append(f"  skipped {problem}")
    if len(captures.skipped) > 10:
        lines.append(f"  skipped ... {len(captures.skipped) - 10} more lines")

    pools = [r for r in systems.values() if isinstance(r.data.get("ships"), list)]
    lines.append("")
    lines.append(f"Ship pools ({len(pools)} systems; each system's first record with a ship list)")
    if not pools:
        lines.append("  none recorded")
        return lines
    changed = sum(
        1
        for records in captures.by_system().values()
        if len({json.dumps(r.data["ships"]) for r in records if r.data.get("ships")}) > 1
    )
    lines.append(f"  systems whose ship list changed between records: {changed}")
    sizes = [len(r.data["ships"]) for r in pools]
    lines.append(
        f"  {sum(sizes)} ships, {min(sizes)}-{max(sizes)} per system (median {statistics.median(sizes):g})"
    )
    columns = [("class", "shipClass", 2), ("role", "role", 3), ("faction", "faction", 4)]
    for title, enum, index in columns:
        counts: Counter[str] = Counter()
        for r in pools:
            for row in r.data["ships"]:
                name = r.session.name(enum, row[index]) or f"#{row[index]}"
                counts[SHIP_LABELS.get(name, name) if enum == "shipClass" else name] += 1
        lines.append(f"  by {title}: " + ", ".join(f"{k} {n}" for k, n in counts.most_common()))
    hints = Counter(row[6] or "(none)" for r in pools for row in r.data["ships"])
    lines.append("  texture hints: " + ", ".join(f"{k} {n}" for k, n in hints.most_common()))
    use_seed = Counter(row[1] for r in pools for row in r.data["ships"])
    lines.append("  useSeed flags: " + ", ".join(f"{k}: {n}" for k, n in sorted(use_seed.items())))
    shared = Counter(row[0] for r in pools for row in r.data["ships"])
    repeated = sum(1 for n in shared.values() if n > 1)
    lines.append(f"  ship seeds seen in more than one system: {repeated}")

    exotic = []
    for r in sorted(pools, key=lambda r: (r.galaxy, r.portal)):
        seeds = [row[0] for row in r.data["ships"] if r.session.name("shipClass", row[2]) == "Royal"]
        if seeds:
            exotic.append(f"  {r.label()}: {len(seeds)} exotic ({', '.join(seeds)})")
    lines.append("")
    lines.append(f"Systems with an exotic in the pool: {len(exotic)}")
    lines.extend(exotic)
    return lines


def _unusual(record: SystemRecord) -> list[str]:
    """The record's implausible-looking fields. Format 1 also flagged an address of 0 during
    generation, which is normal, so that flag is dropped."""
    flags = record.data.get("unusual") or []
    if record.session.header.get("format") == 1:
        flags = [flag for flag in flags if flag != "ua"]
    return flags


def _location_matches(record: SystemRecord) -> bool | None:
    loc = record.data.get("loc")
    if not isinstance(loc, list) or len(loc) < 5 or int(record.data["ua"], 16) == 0:
        return None
    galaxy, x, y, z, system = loc[:5]
    ua = record.ua
    return (
        galaxy == record.galaxy
        and system == (ua >> 40) & 0xFFF
        and (x & 0xFFF) == ua & 0xFFF
        and (z & 0xFFF) == (ua >> 12) & 0xFFF
        and (y & 0xFF) == (ua >> 24) & 0xFF
    )


def consistency_lines(captures: Captures, examples: int) -> list[str]:
    """Agreement between fields the game holds twice.

    A struct layout that no longer matches the game shows up here as low
    agreement across the board. Individual counts can differ by design.
    """
    t = {
        "arg": Tally("Generate's seed argument = system seed"),
        "active": Tally("generated system is the loaded one"),
        "seed": Tally("system seed = universal address"),
        "loc": Tally("address = player's location"),
        "star": Tally("star type = galaxy attributes"),
        "race": Tally("race = galaxy attributes"),
        "trade": Tally("economy = galaxy attributes"),
        "wealth": Tally("wealth = galaxy attributes"),
        "conflict": Tally("conflict = galaxy attributes"),
        "planets": Tally("planet count = galaxy attributes' planets + prime planets"),
        "prime": Tally("prime planet count = galaxy attributes"),
        "bodies": Tally("planet input seeds = galaxy attribute seeds"),
    }
    for r in captures.records:
        d = r.data
        ga = d.get("galaxy") if isinstance(d.get("galaxy"), dict) else None
        if "arg" in d and "seed" in d:
            t["arg"].add(d["arg"] == d["seed"], lambda: f"{r.label()}: {d['arg']} vs {d['seed']}")
        if "active" in d:
            t["active"].add(bool(d["active"]), lambda: r.label())
        if "seed" in d and int(d["ua"], 16):
            t["seed"].add(
                int(d["seed"], 16) & ~PLANET_BITS == int(d["ua"], 16) & ~PLANET_BITS,
                lambda: f"{r.label()}: seed {d['seed']}, address {d['ua']}",
            )
        t["loc"].add(_location_matches(r), lambda: f"{r.label()}: {d.get('loc')}")
        if ga:
            for key in ("star", "race", "trade", "wealth", "conflict", "prime"):
                if key in d and key in ga:
                    t[key].add(d[key] == ga[key], lambda k=key: f"{r.label()}: {d[k]} vs {ga[k]}")
            if "planets" in d and "planets" in ga and "prime" in ga:
                expected = ga["planets"] + (ga["prime"] if d.get("primeInCount") else 0)
                t["planets"].add(
                    d["planets"] == expected,
                    lambda: f"{r.label()}: {d['planets']} vs {ga['planets']}+{ga['prime']}",
                )
            if "bodies" in d and "seeds" in ga:
                body_seeds = [row[0] for row in d["bodies"] if row[0] != ZERO_SEED]
                t["bodies"].add(
                    body_seeds == ga["seeds"][: len(body_seeds)] and bool(body_seeds),
                    lambda: f"{r.label()}: {body_seeds} vs {ga['seeds']}",
                )
    return ["", "Self-consistency of the game's data"] + tally_lines(list(t.values()), examples)


@dataclass
class ShipStream:
    """Where a system's ship seeds sit in the stream seeded by its system seed."""

    offset: int | None  # draws made before slot 0's first draw
    found: int = 0  # ship seeds found in sequence
    layout: list[str] = field(default_factory=list)


def locate_ship_stream(seed: int, ship_seeds: list[str], crash_seed: str | None, limit: int) -> ShipStream:
    outputs = [state & MASK32 for state in stream_states(seed, limit)]

    def pair(seed_hex: str) -> tuple[int, int]:
        draws = unmix(int(seed_hex, 16))
        return draws & MASK32, draws >> 32

    def at(position: int, words: tuple[int, int]) -> bool:
        return position + 1 < len(outputs) and (outputs[position], outputs[position + 1]) == words

    pairs = [pair(s) for s in ship_seeds]
    crash = pair(crash_seed) if crash_seed and crash_seed != ZERO_SEED else None
    offset = next((i for i in range(len(outputs) - 1) if at(i, pairs[0])), None) if pairs else None
    result = ShipStream(offset)
    if offset is None:
        return result

    position, run_start = offset, 0

    def close_run(end: int) -> None:
        if end >= run_start:
            result.layout.append(f"ships {run_start}-{end}" if end > run_start else f"ship {run_start}")

    for slot, words in enumerate(pairs):
        if at(position, words):
            result.found += 1
            position += 2
            continue
        close_run(slot - 1)
        run_start = slot
        if crash is not None and at(position, crash):
            result.layout.append("crash ship")
            position += 2
        else:
            skip = next((k for k in range(1, 65) if at(position + k, words)), None)
            if skip is None:
                result.layout.append("lost")
                return result
            result.layout.append(f"{skip} other draw{'s' if skip > 1 else ''}")
            position += skip
        if not at(position, words):
            result.layout.append("lost")
            return result
        result.found += 1
        position += 2
    close_run(len(pairs) - 1)
    if crash is not None and "crash ship" not in result.layout and at(position, crash):
        result.layout.append("crash ship")
    return result


def ship_stream_lines(captures: Captures, limit: int = STREAM_LIMIT) -> list[str]:
    lines = ["", "Ship seeds in the system seed's random-number stream"]
    layouts: Counter[str] = Counter()
    offsets = []
    for r in sorted(captures.representative_by_system().values(), key=lambda r: (r.galaxy, r.portal)):
        ships = r.data.get("ships")
        if not ships or "seed" not in r.data:
            continue
        found = locate_ship_stream(
            int(r.data["seed"], 16), [row[0] for row in ships], r.data.get("crashShip"), limit
        )
        if found.offset is None:
            lines.append(f"  {r.label()}: not in the first {limit:,} draws")
            continue
        layout = ", ".join(found.layout)
        layouts[layout] += 1
        offsets.append(found.offset)
        lines.append(
            f"  {r.label()}: after {found.offset} draws; {found.found}/{len(ships)} in sequence: {layout}"
        )
    if offsets:
        lines.append(
            f"  {len(offsets)} system(s); ships begin after {min(offsets)}-{max(offsets)} draws; "
            f"{layouts.most_common(1)[0][1]} share the layout: {layouts.most_common(1)[0][0]}"
        )
    return lines


def _draw_index(states: dict[int, int], seed: int, value: str | None) -> str:
    """How many draws the generator had made when it held ``value``."""
    if value is None:
        return "?"
    state = int(value, 16)
    if state == seeded_state(seed):
        return "0"
    for candidate, note in ((state, ""), (((state & MASK32) << 32) | (state >> 32), " (halves swapped)")):
        if candidate in states:
            return f"{states[candidate] + 1}{note}"
    return "-"


def trace_lines(captures: Captures, limit: int = STREAM_LIMIT) -> list[str]:
    """Generator state at each traced step, as a count of draws from the system seed."""
    traced = [r for r in captures.records if r.data.get("trace") and "seed" in r.data]
    traced_queries = [q for q in captures.queries if q.get("trace") and q.get("seed")]
    if not traced and not traced_queries:
        return []
    named = captures.representative_by_system()
    lines = ["", "Generation traces (draws made from the system seed at each step; - = not in this stream)"]
    placements = []
    for r in traced:
        seed = int(r.data["seed"], 16)
        states = {state: i for i, state in enumerate(stream_states(seed, limit))}
        steps = " ".join(f"{label}{_draw_index(states, seed, value)}" for label, value in r.data["trace"])
        label = named.get(r.ua & ~PLANET_BITS, r).label()
        lines.append(f"  {label}: {steps}")
        if r.data.get("via") == "gen" and (placed := _ship_placement(r, states, seed, limit)) is not None:
            placements.append((label, *placed))
    for q in traced_queries[:20]:
        seed = int(q["seed"], 16)
        states = {state: i for i, state in enumerate(stream_states(seed, limit))}
        steps = " ".join(f"{label}{_draw_index(states, seed, value)}" for label, value in q["trace"])
        lines.append(f"  lookup {q['seed']}: {steps}")
    if len(traced_queries) > 20:
        lines.append(f"  ... {len(traced_queries) - 20} more lookups")
    if placements:
        lines.append("  Where the ships come in each traced generation:")
        tails: Counter[int] = Counter()
        for label, biomes, ships_start, end, locators in placements:
            between = ships_start - biomes
            text = (
                f"    {label}: biomes done after {biomes} draws, ships start after {ships_start}, "
                f"Generate done after {end}; {between} draws between biomes and ships"
            )
            if locators:
                text += f", {locators} locators ({between / locators:.2f} draws each)"
            lines.append(text)
            tails[end - ships_start] += 1
        tail, count = tails.most_common(1)[0]
        lines.append(
            f"    Generate ended {tail} draws after the ships started in {count} of {len(placements)} "
            "generation(s)"
        )
    return lines


def _ship_placement(
    record: SystemRecord, states: dict[int, int], seed: int, limit: int
) -> tuple[int, int, int, int | None] | None:
    """(draws made when the biomes were done, when the ships started and when Generate returned,
    and the locator count) for a traced generation, or None if any draw count is unknown."""

    def draws(label: str) -> int | None:
        value = next((v for step, v in record.data["trace"] if step == label), None)
        if value is None:
            return None
        state = int(value, 16)
        return 0 if state == seeded_state(seed) else (states[state] + 1 if state in states else None)

    ships = record.data.get("ships")
    biomes, end = draws("biomes<"), draws("generate<")
    if not ships or biomes is None or end is None:
        return None
    found = locate_ship_stream(seed, [row[0] for row in ships], record.data.get("crashShip"), limit)
    if found.offset is None:
        return None
    locators = record.data.get("locators")
    count = locators.get("count") if isinstance(locators, dict) else None
    return biomes, found.offset, end, count


def lookup_lines(captures: Captures) -> list[str]:
    if not captures.queries:
        return []
    with_ships = sum(1 for q in captures.queries if q.get("ships"))
    errors = sum(1 for q in captures.queries if q.get("errors"))
    return [
        "",
        f"Lookups (systems the game described without loading them): {len(captures.queries)}",
        f"  with a ship list: {with_ships}; with read errors: {errors}",
    ]


def _portal_label(ua: int) -> str:
    return f"{(ua >> 52) & 0xF:X}{(ua >> 40) & 0xFFF:03X}{ua & MASK32:08X} galaxy {(ua >> 32) & 0xFF}"


def _model_file(name: str) -> str:
    """A model's file name without its folders and extensions: FIGHTER_PROC."""
    return name.replace("\\", "/").rsplit("/", 1)[-1].split(".", 1)[0] or "(unnamed)"


def model_lines(captures: Captures) -> list[str]:
    """Ship models the game built, with the parts it picked, against their systems' ship lists."""
    if not captures.models:
        return []
    systems = captures.representative_by_system()
    files = Counter(_model_file(model.get("name") or "") for model in captures.models)
    shown = ", ".join(f"{name} {n}" for name, n in files.most_common(8))
    if len(files) > 8:
        shown += f", and {len(files) - 8} other model files"
    lines = ["", f"Ship models recorded with their parts: {len(captures.models)} ({shown})"]
    if errors := sum(1 for model in captures.models if model.get("errors")):
        lines.append(f"  with read errors: {errors}")
    kinds: Counter = Counter()
    unmatched = 0
    exotics: list[tuple[SystemRecord, dict]] = []
    for model in captures.models:
        record = systems.get(int(model.get("system") or "0", 16) & ~PLANET_BITS)
        slot = model.get("slot")
        ships = (record.data.get("ships") or []) if record is not None else []
        if record is not None and slot == "crash" and record.data.get("crashShip") == model.get("seed"):
            kinds["Sentinel crash-site ship"] += 1
            continue
        if not isinstance(slot, int) or not 0 <= slot < len(ships) or ships[slot][0] != model.get("seed"):
            unmatched += 1
            continue
        name = record.session.name("shipClass", ships[slot][2])
        kinds[SHIP_LABELS.get(name or "", name or f"class {ships[slot][2]}")] += 1
        if name == "Royal":
            exotics.append((record, model))
    if kinds:
        lines.append("  by ship type: " + ", ".join(f"{kind} {n}" for kind, n in kinds.most_common()))
    if unmatched:
        lines.append(f"  not found in a recorded system's ship list: {unmatched}")
    lines.append(f"  exotics: {len(exotics)}")
    for record, model in exotics:
        parts = " ".join(model.get("parts") or []) or "(no parts)"
        seed = _hex_or_none(model.get("seed"))
        draw = f" (first draw {ship_model.first_draw(seed) / 2**32:.6f})" if seed is not None else ""
        lines.append(f"    {record.label()}: {model.get('seed')}{draw} {parts}")
    return lines + squid_lines(exotics)


def part_group(part: str) -> str:
    """The group a part ID is one of the options of, by the game's naming: _COCKPIT_C is an option of
    _COCKPIT_, and _COCKPITA_0NEW of _COCKPITA_; an ID without a leading underscore, such as
    TEXTURE_TEMP, of its first word's group."""
    if part.startswith("_"):
        end = part.find("_", 1)
        return part[: end + 1] if end > 0 else part
    return part.split("_", 1)[0]


def unseen_options(counts: Counter) -> float:
    """About how many options of a group no capture has shown yet, from how many showed up once and how
    many twice (Chao1, bias-corrected). A lower bound: options the game rarely picks are easily missed."""
    once = sum(1 for n in counts.values() if n == 1)
    twice = sum(1 for n in counts.values() if n == 2)
    return once * (once - 1) / (2 * (twice + 1))


def part_coverage_lines(captures: Captures, groups_shown: int = 6) -> list[str]:
    """For each ship model the game picks parts for (the *_PROC files, but for their lower-detail
    copies), the parts recorded so far: how many options each group has shown, and about how many more
    it probably has, so the ship types that need more captures stand out. The game's own option lists
    aren't in the captures, so the totals are estimates."""
    systems = captures.representative_by_system()
    by_file: dict[str, dict[tuple, dict]] = {}
    kinds: dict[str, set[str]] = {}
    for model in captures.models:
        file = _model_file(model.get("name") or "")
        if not model.get("parts") or "_PROC" not in file or "_LOD" in file:
            continue
        record = systems.get(int(model.get("system") or "0", 16) & ~PLANET_BITS)
        slot = model.get("slot")
        ships = (record.data.get("ships") or []) if record is not None else []
        if record is not None and isinstance(slot, int) and 0 <= slot < len(ships):
            name = record.session.name("shipClass", ships[slot][2])
            kinds.setdefault(file, set()).add(SHIP_LABELS.get(name or "", name or f"class {ships[slot][2]}"))
        elif slot == "crash":
            kinds.setdefault(file, set()).add("Sentinel crash-site ship")
        by_file.setdefault(file, {})[(model.get("name"), model.get("seed"))] = model  # each model once
    if not by_file:
        return []
    lines = [
        "",
        "Ship parts recorded, by model: the options seen in each group of its parts, and about how many more "
        "the game probably has, from how many options showed up only once or twice (a lower bound; the "
        "game's own lists of options would give the totals)",
    ]
    for file, models in sorted(by_file.items(), key=lambda item: -len(item[1])):
        groups: dict[str, Counter] = {}
        for model in models.values():
            for part in model["parts"]:
                groups.setdefault(part_group(part), Counter())[part] += 1
        seen = sum(len(counts) for counts in groups.values())
        more = {group: unseen_options(counts) for group, counts in groups.items()}
        used_by = f" ({', '.join(sorted(kinds[file]))})" if file in kinds else ""
        lines.append(
            f"  {file}{used_by}: {len(models)} models, {len(groups)} groups, {seen} options seen, "
            f"about {round(sum(more.values()))} more"
        )
        open_groups = sorted((group for group in groups if round(more[group]) >= 1), key=lambda g: -more[g])
        if open_groups:
            said = ", ".join(
                f"{group} {len(groups[group])} seen in {sum(groups[group].values())} picks "
                f"(about {round(more[group])} more)"
                for group in open_groups[:groups_shown]
            )
            others = len(open_groups) - groups_shown
            lines.append(
                f"    likely to have more: {said}" + (f", and {others} more groups" if others > 0 else "")
            )
    return lines


def _is_multitool(name: str | None) -> bool:
    """As the capture mod tells a multi-tool's model file since 0.9.0. Before, it took effects in
    weapon folders for multi-tools too, which this leaves out of what those versions recorded."""
    path = "/" + (name or "").replace("\\", "/").upper()
    return (
        MULTITOOL_DIR in path
        and not any(folder in path for folder in NOT_MULTITOOL_DIRS)
        and "/SPACECRAFT/" not in path
    )


def _set_key(pool: dict) -> list:
    """What tells one of a system's multi-tool sets from another: each tool's file, seed and parts, in order."""
    return [[tool.get("name"), tool.get("seed"), tool.get("parts")] for tool in pool.get("tools") or []]


def _region(ua: int) -> tuple[int, int]:
    """A system's region: its galaxy and voxel, the address bits other than the planet and system."""
    return (ua >> 32) & 0xFF, ua & MASK32


def _region_label(region: tuple[int, int]) -> str:
    galaxy, voxel = region
    signed = lambda value, bits: value - (1 << bits) if value >= 1 << (bits - 1) else value  # noqa: E731
    x, z, y = signed(voxel & 0xFFF, 12), signed((voxel >> 12) & 0xFFF, 12), signed(voxel >> 24, 8)
    return f"galaxy {galaxy} region X {x}, Y {y}, Z {z}"


# Where cGcSolarSystemData keeps the system's NebulaSeed (its Sky's), as NMS.py 180383 places it: the
# value the game's star count compares with its sky globals' chances (see the mod's StarCount).
NEBULA_SEED_AT = 0x2080


def _star_function(info: object) -> str:
    """What a session header says of the game's star count function (see the mod's StarCount)."""
    if info is None:
        return "not looked for (RECORD_STARS off)"
    if not isinstance(info, dict):
        return f"not found: {info}"
    text = f"found at +{info.get('offset')}"
    if "shape" in info:  # 0.11.0 on: the mod works the count out from what the function reads
        if not info["shape"]:
            return f"{text}; its code isn't what the mod knows: {info.get('why')}"
        if "binary" not in info:
            return f"{text}; the values it reads couldn't be read"
        text += f"; binary star chance {info['binary']:g}, ternary {info['ternary']:g}"
        if info.get("one") != 1.0:
            text += f", taken from {info.get('one')} rather than 1"
        forced = [name for name in ("forceBinary", "forceTernary") if info.get(name)]
        text += f"; {', '.join(forced)} on" if forced else ""
        return f"{text}; game mode {info.get('gameMode')}, boot mode {info.get('bootMode')}"
    return f"{text}; not called: {info.get('why')}"  # 0.10.0 tried to call it


def star_guild_lines(captures: Captures, examples: int = 20) -> list[str]:
    """How many stars each system has, as the game said and as worked out from its address, and the
    guild seen in each region, with what else the captures say of the region, to find what decides it."""
    lines: list[str] = []
    headers = [s.header["starCount"] for s in captures.sessions if "starCount" in s.header]  # 0.10.0 on
    found = Counter(_star_function(info) for info in headers)
    systems = captures.representative_by_system()
    stars: dict[int, int] = {}
    nebulas: dict[int, float] = {}
    for record in captures.records:
        system = record.ua & ~PLANET_BITS
        if isinstance(record.data.get("stars"), int):
            stars[system] = record.data["stars"]
        raw = record.data.get("raw")
        if isinstance(raw, str) and len(data := zlib.decompress(base64.b64decode(raw))) >= NEBULA_SEED_AT + 4:
            nebulas[record.ua] = struct.unpack_from("<f", data, NEBULA_SEED_AT)[0]
    chances = next(
        (info for info in reversed(headers) if isinstance(info, dict) and "binary" in info), None
    )  # the game's, from the newest session that read them
    if found or stars or nebulas:
        counts = Counter(stars.values())
        lines += [
            "",
            "Stars: systems by how many stars the game counts: "
            + (", ".join(f"{n} x{c}" for n, c in sorted(counts.items())) or "none recorded"),
        ]
        lines += [
            f"  the game's star count function: {text} ({n} session(s))" for text, n in found.most_common()
        ]
        drawn = sum(1 for seed, value in nebulas.items() if nebula_seed(seed) == value)
        lines.append(
            f"  NebulaSeed, which it counts by, is the 9th draw of the system seed's stream: {drawn}/{len(nebulas)}"
            " systems with raw data"
        )
        if chances is None:
            lines.append(
                "  the game's star chances aren't recorded yet, so counts can't be worked out from addresses"
            )
        else:
            worked = {
                system: star_count(nebula_seed(system), chances["binary"], chances["ternary"], chances["one"])
                for system in systems
            }
            agree = sum(1 for system, n in stars.items() if worked.get(system) == n)
            lines.append(
                "  worked out from the address with the game's chances: "
                + ", ".join(f"{n} x{c}" for n, c in sorted(Counter(worked.values()).items()))
                + f" over {len(worked)} systems; the same as the game counted: {agree}/{len(stars)}"
            )
            several = [system for system, n in worked.items() if n != 1]
            for system in several[:examples]:
                counted = f" (the game counted {stars[system]})" if system in stars else ""
                lines.append(f"    {systems[system].label()}: {worked[system]} stars{counted}")
    if captures.guilds:
        by_region: dict[tuple[int, int], list[dict]] = {}
        for entry, _ in captures.guilds:
            by_region.setdefault(_region(int(entry.get("system") or "0", 16)), []).append(entry)
        regions_of: dict[tuple[int, int], list[SystemRecord]] = {}
        for system, record in systems.items():
            regions_of.setdefault(_region(system), []).append(record)
        colours_of: dict[tuple[int, int], set[float]] = {}  # from every record: 0.10.0 on record it
        for record in captures.records:
            if (colour := (record.data.get("galaxy") or {}).get("regionColour")) is not None:
                colours_of.setdefault(_region(record.ua), set()).add(colour)
        lines += ["", f"Guilds recorded: {len(captures.guilds)} for {len(by_region)} region(s)"]
        mixed = 0
        for region, entries in by_region.items():  # in the order first recorded
            guilds = Counter(entry.get("guild") for entry in entries)
            mixed += len(guilds) > 1
            records = regions_of.get(region, [])
            races = Counter(record.name("race", "race") or "?" for record in records)
            colours = sorted(colours_of.get(region, ()))
            said = ", ".join(f"{guild} x{n}" for guild, n in guilds.most_common())
            said += f"; systems recorded there: {len(records)}"
            if races:
                said += ", by race: " + ", ".join(f"{race} {n}" for race, n in races.most_common())
            if colours:
                said += f"; region colour value {', '.join(f'{c:g}' for c in colours)}"
            lines.append(f"  {_region_label(region)}: {said}")
        lines.append(f"  regions recorded with more than one guild: {mixed}")
    return lines


def pool_lines(captures: Captures, limit: int = 100) -> list[str]:
    """Each system's own multi-tools, which the game builds as it generates the system: their files,
    seeds and parts; how many it built just before the generation; whether a system's set came out the
    same each time it was recorded; and any seed in more than one system's set, which wouldn't be a
    system's own."""
    if not captures.pools:
        return []
    systems = captures.representative_by_system()
    sets = [pool for pool, _ in captures.pools if pool.get("tools")]
    by_system: dict[int, list[dict]] = {}
    for pool in sets:
        by_system.setdefault(int(pool.get("system") or "0", 16) & ~PLANET_BITS, []).append(pool)
    tools = [tool for pool in sets for tool in pool["tools"]]
    files = Counter(_model_file(tool.get("name") or "") for tool in tools)
    sizes = Counter(len(pool["tools"]) for pool in sets)
    lines = [
        "",
        f"Systems' own multi-tools: {len(sets)} set(s) for {len(by_system)} system(s), "
        f"{len(tools)} multi-tools ({', '.join(f'{name} {n}' for name, n in files.most_common())})",
        "  multi-tools per set: " + ", ".join(f"{size} x{n}" for size, n in sorted(sizes.items())),
    ]
    if before := [pool for pool in sets if pool.get("before")]:  # 0.11.0 on
        leads = [pool.get("lead") or 0 for pool in before]
        lines.append(
            f"  sets started by the run of multi-tools built just before the generation: {len(before)} "
            f"({sum(pool['before'] for pool in before)} multi-tools, {min(leads):g} to {max(leads):g} s before it)"
        )
    elsewhere = [pool for pool, _ in captures.pools if pool.get("elsewhere")]
    if elsewhere:
        lines.append(
            f"  generations during which other threads built multi-tools: {len(elsewhere)} "
            f"({sum(pool['elsewhere'] for pool in elsewhere)} multi-tools; "
            f"{sum(1 for pool in elsewhere if not pool.get('tools'))} of them with none on the generating thread)"
        )
    again = [pools for pools in by_system.values() if len(pools) > 1]
    same = sum(1 for pools in again if len({json.dumps(_set_key(pool)) for pool in pools}) == 1)
    lines.append(f"  systems recorded more than once: {len(again)}; with the same set each time: {same}")
    systems_of: dict[str, set[int]] = {}
    for system, pools in by_system.items():
        for pool in pools:
            for tool in pool.get("tools") or []:
                systems_of.setdefault(str(tool.get("seed")), set()).add(system)
    shared = sorted(seed for seed, where in systems_of.items() if len(where) > 1)
    examples = f" ({', '.join(shared[:5])})" if shared else ""
    lines.append(f"  seeds in more than one system's set: {len(shared)}{examples}")
    if late := sum(1 for pool, _ in captures.pools if pool.get("late")):
        lines.append(f"  sets of generations that took longer than the mod waited: {late}")
    if errors := sum(1 for tool in tools if tool.get("errors")):
        lines.append(f"  multi-tools with read errors: {errors}")
    described = []
    for system, pools in sorted(by_system.items(), key=lambda item: ((item[0] >> 32) & 0xFF, item[0])):
        record = systems.get(system)
        label = record.label() if record is not None else _portal_label(system)
        said = ", ".join(
            f"{_model_file(tool.get('name') or '')} {tool.get('seed')} ({len(tool.get('parts') or [])} parts)"
            for tool in pools[-1].get("tools") or []
        )
        described.append(f"  {label}: {said}")
    lines += described[:limit]
    if len(described) > limit:
        lines.append(f"  ... {len(described) - limit} more")
    return lines


def _resource_summary(resource: dict, model: dict | None) -> str:
    """What the game's resource manager held for an item's handle, against the model the mod paired."""
    if "error" in resource:
        return f"resource manager: {resource['error']}"
    said = f"resource {_model_file(resource.get('name') or '')}, {resource.get('refs')} holding it"
    if "seed" not in resource:
        return said + (f", {len(resource['errors'])} read error(s)" if resource.get("errors") else "")
    if model is not None:
        same = all(resource.get(key) == model.get(key) for key in ("name", "seed", "parts"))
        return said + (", the same model" if same else f", another model: {resource.get('seed')}")
    parts = " ".join(resource.get("parts") or []) or "(no parts)"
    return said + f", seed {resource.get('seed')}: {parts}"


def _store_summary(store: dict, session: Session) -> str:
    """One of an item's inventories: [index] size, slots, class, layout seed, contents and stats."""
    if store.get("implausible"):
        return f"[{store.get('i')}] not an inventory"
    width, height, slots = (store.get("size") or [0, 0, 0])[:3]
    grade = session.name("inventoryClass", store.get("class")) or store.get("class")
    said = f"[{store.get('i')}] {width}x{height}, {slots} slots, class {grade}"
    layout = store.get("layout") or []
    if layout and (_hex_or_none(layout[0]) or 0) > 1:
        said += f", layout seed {layout[0]}"
    for key, label in (("entries", "in it"), ("history", "in its history"), ("special", "special slots")):
        if rows := store.get(key):
            said += f", {len(rows)} {label}"
    if stats := store.get("stats"):
        said += ", stats " + " ".join(f"{stat[0]}={stat[1]}" for stat in stats)
    if store.get("errors"):
        said += f", {len(store['errors'])} read error(s)"
    return said


def item_lines(captures: Captures, limit: int = 100) -> list[str]:
    """Items the game offered (multi-tools on racks and at merchants, gifts, rewards): their
    inventories, the models they held and the text in them; and the multi-tool models the game built."""
    lines: list[str] = []
    systems = captures.representative_by_system()

    def place(entry: dict) -> tuple[int, str]:
        ua = int(entry.get("system") or "0", 16)
        record = systems.get(ua & ~PLANET_BITS)
        return ua, record.label() if record is not None else (_portal_label(ua) if ua else "(no system)")

    # The systems' own multi-tools by (session, system, resource handle), for items the mod didn't pair.
    pooled = {
        (id(session), int(pool.get("system") or "0", 16) & ~PLANET_BITS, tool.get("handle")): number
        for pool, session in captures.pools
        for number, tool in enumerate(pool.get("tools") or [], start=1)
    }
    if captures.items:
        types = Counter(str(item.get("itemType")) for item, _ in captures.items)
        described: list[str] = []
        tool_systems: dict[str, set[int]] = {}
        with_tool = 0
        for item, session in captures.items:
            ua, label = place(item)
            models = [item["model"]] if item.get("model") else []
            models += item.get("tools") or []
            tools = [model for model in models if _is_multitool(model.get("name"))]
            with_tool += bool(tools)
            for tool in tools:
                tool_systems.setdefault(tool["seed"], set()).add(ua)
            where = session.name("where", item.get("where")) or f"place {item.get('where')}"
            flags = "".join(
                f", {flag}" if item[flag] in (1, True) else f", {flag} ({item[flag]})"
                for flag in ITEM_FLAGS
                if item.get(flag)
            )
            said = []
            if "stores" in item or "handle" in item:  # 0.8.2 on
                stores = item.get("stores") or []
                summary = "; ".join(_store_summary(store, session) for store in stores)
                said.append(f"inventories {summary}" if stores else "no inventories")
            elif "raw" in item:
                said.append("bytes only")
            if model := item.get("model"):
                parts = " ".join(model.get("parts") or []) or "(no parts)"
                number = f" (number {model['pool'] + 1} of the system's set)" if "pool" in model else ""
                file = _model_file(model.get("name") or "")
                said.append(f"model {file} {model.get('seed')}{number}: {parts}")
            elif item.get("handle") not in (None, 0, 0xFFFFFFFF):
                number = pooled.get((id(session), ua & ~PLANET_BITS, item["handle"]))
                in_set = f", number {number} of the system's set by its handle" if number else ""
                said.append(f"model handle {item['handle']}, not paired{in_set}")
            if resource := item.get("resource"):
                said.append(_resource_summary(resource, model or None))
            for tool in item.get("tools") or []:
                parts = " ".join(tool.get("parts") or []) or "(no parts)"
                said.append(
                    f"seed of {_model_file(tool.get('name') or '')} {tool.get('seed')} at byte "
                    f"{tool.get('offset', 0):#x}: {parts}"
                )
            if texts := item.get("texts"):
                said.append("text " + "; ".join(repr(text) for _, text in texts))
            described.append(
                f"  {label}, {where}, nearest planet {item.get('planet')}, item type {item.get('itemType')}"
                f"{flags}, state {item.get('state')}: {', '.join(said)}"
            )
        lines += [
            "",
            f"Items the game offered: {len(captures.items)} record(s), {with_tool} with a multi-tool's model "
            f"(item types: {', '.join(f'{t} x{n}' for t, n in sorted(types.items()))})",
            *described[:limit],
        ]
        if len(described) > limit:
            lines.append(f"  ... {len(described) - limit} more")
        repeated = sum(1 for seen in tool_systems.values() if len(seen) > 1)
        lines.append(f"  multi-tools: {len(tool_systems)}; offered in more than one system: {repeated}")
    if captures.built:
        tool_builds = [(b, session) for b, session in captures.built if _is_multitool(b.get("name"))]
        files = Counter(_model_file(b.get("name") or "") for b, _ in tool_builds)
        shown = ", ".join(f"{name} {n}" for name, n in files.most_common()) or "none"
        lines += [
            "",
            f"Multi-tool models the game built (seeds and parts not recorded): {len(tool_builds)} ({shown})",
            f"  other model files with parts: {len(captures.built) - len(tool_builds)}",
        ]
        for built, session in tool_builds[:limit]:
            where = session.name("where", built.get("where")) or f"place {built.get('where')}"
            lines.append(
                f"    {place(built)[1]}, {where}: {_model_file(built.get('name') or '')}, "
                f"{built.get('parts')} parts, handle {built.get('handle')}"
            )
        if len(tool_builds) > limit:
            lines.append(f"    ... {len(tool_builds) - limit} more")
    return lines


def _hex_or_none(text: object) -> int | None:
    try:
        return int(str(text), 16)
    except ValueError:
        return None


def squid_lines(exotics: list[tuple[SystemRecord, dict]]) -> list[str]:
    """Each exotic's body, from its first part, against the squid rule in ship_model.py."""
    bodies: dict[int, tuple[str, str | None]] = {}
    known = (ship_model.SQUID_PART, ship_model.OTHER_EXOTIC_PART)
    for record, model in exotics:
        seed = _hex_or_none(model.get("seed"))
        if seed is not None:
            parts = model.get("parts") or []
            # The game builds an exotic again later with only its texture; that build says nothing of its body.
            if seed not in bodies or bodies[seed][1] not in known:
                bodies[seed] = (record.label(), parts[0] if parts else None)
    checked, disagree, other = 0, [], 0
    highest_not_squid = lowest_squid = None
    for seed, (label, first) in bodies.items():
        if first not in known:
            other += 1
            continue
        checked += 1
        squid, draw = first == ship_model.SQUID_PART, ship_model.first_draw(seed)
        if squid:
            lowest_squid = draw if lowest_squid is None else min(lowest_squid, draw)
        else:
            highest_not_squid = draw if highest_not_squid is None else max(highest_not_squid, draw)
        if ship_model.exotic_squid(seed).squid != squid:
            disagree.append(f"    disagrees: {label}: {seed:016X}, first draw {draw / 2**32:.6f}, {first}")
    if not checked and not other:
        return []
    lines = [
        f"  squid rule (a squid when the seed's first draw is at least 20/21 of its range): "
        f"{checked - len(disagree)} of {checked} exotic seeds agree"
    ]
    lines += disagree
    if other:
        neither = f"neither {ship_model.SQUID_PART} nor {ship_model.OTHER_EXOTIC_PART}"
        lines.append(f"    first part {neither}: {other}")
    if highest_not_squid is not None and lowest_squid is not None:
        closest = (
            f"    closest to the line: not a squid at {highest_not_squid / 2**32:.6f} ({highest_not_squid}), "
            f"a squid at {lowest_squid / 2**32:.6f} ({lowest_squid})"
        )
        if highest_not_squid >= lowest_squid:
            closest += "; they overlap, so no line fits them all"
        elif highest_not_squid > ship_model.NOT_SQUID_HIGHEST or lowest_squid < ship_model.SQUID_LOWEST:
            closest += "; closer than ship_model.py's edges: update them and SQUID_EDGES in src/core/ships.ts"
        lines.append(closest)
    return lines


def _region_name_candidates(seed: int) -> dict[str, str | None]:
    """The region name nms_namegen would make if the game's seed were each stage of its regionName()."""
    from nms_namegen.generator import generateName
    from nms_namegen.prng import PRNG
    from nms_namegen.region import region_name_adornments

    def named(prng_seed: int) -> str | None:
        try:
            rng = PRNG(prng_seed)
            max_length = rng.random(4) + 6
            name = generateName(rng, 0, 6, max_length).capitalize()
            if rng.random(0x64) < 0x50:
                name = region_name_adornments[rng.random(0x14)].format(name)
            return name
        except Exception:  # some seeds make the generator raise
            return None

    # regionName() starts from (galaxy >> 1) ^ ((galaxy << 32) | the portal code's low 32 bits): the
    # game's seed holds the galaxy where regionName() puts it, so the first term comes from it too.
    register = (((((seed >> 32) & 0xFF) >> 1) ^ seed) * MIX_A) & MASK64
    register = (((register >> 33) ^ register) * MIX_B) & MASK64
    register ^= register >> 33
    return {
        "before mixing": named(seeded_state(register)),
        "after mixing": named(seeded_state(seed)),
        "as the generator's seed": named(seed),
    }


def name_lines(captures: Captures, namegen: Path, examples: int) -> list[str]:
    """Planet and region names the game generated, against nms_namegen for the same seeds."""
    if not captures.names:
        return []
    sys.path.insert(0, str(namegen.resolve()))
    from nms_namegen.planet import planetName
    from nms_namegen.region import regionName

    systems = captures.representative_by_system()
    t = {
        "planet": Tally("planet name = generator's name for the same seed"),
        "planet seed": Tally("planet name seeds that are the loaded system's planet seeds"),
    }
    stages = ["before mixing", "after mixing", "as the generator's seed"]
    for stage in stages:
        t[stage] = Tally(f"region name = generator's, taking the seed {stage}")
    t["region here"] = Tally("region names that are the loaded system's region")

    for entry in captures.names:
        seed, name = int(entry["seed"], 16), entry.get("name")
        system = int(entry.get("system") or "0", 16) & ~PLANET_BITS

        def miss(predicted, entry=entry):
            return lambda: f"seed {entry['seed']}: game {entry.get('name')!r}, generator {predicted!r}"

        if entry.get("kind") == "planet":
            try:
                predicted = planetName(seed)
            except Exception as exc:
                predicted = f"error: {type(exc).__name__}"
            t["planet"].add(name == predicted, miss(predicted))
            record = systems.get(system)
            seeds = (record.data.get("galaxy") or {}).get("seeds") if record else None
            if seeds:
                t["planet seed"].add(
                    entry["seed"] in seeds, lambda: f"seed {entry['seed']} isn't one of {seeds}"
                )
        elif entry.get("kind") == "region":
            for stage, predicted in _region_name_candidates(seed).items():
                t[stage].add(name == predicted, miss(predicted))
            if system:
                code = (((system >> 40) & 0xFFF) << 32) | (system & MASK32)
                predicted = regionName(code, (system >> 32) & 0xFF)
                t["region here"].add(name == predicted, miss(predicted))
    counts = Counter(entry.get("kind") for entry in captures.names)
    return [
        "",
        "Names the game generated ("
        + ", ".join(f"{k} {n}" for k, n in counts.most_common())
        + "; names for places other than where you were count as misses on the 'loaded system' lines)",
    ] + tally_lines(list(t.values()), examples)


def _namegen_anomaly(va: dict, system_id: int) -> int:
    """0 none, 1 Atlas Interface, 2 black hole: src/core/system.ts systemAttributesDetailed()."""
    system_id -= 1
    if system_id < va["guide_star_count"]:
        return 0
    diff = system_id - va["guide_star_count"]
    if va["black_hole_count"] > 0 and 0 <= diff < va["black_hole_count"]:
        return 2
    diff -= va["black_hole_count"]
    if va["atlas_station_count"] > 0 and 0 <= diff < va["atlas_station_count"]:
        return 1
    return 0


def _game_anomaly(name: str | None) -> int | None:
    if name is None:
        return None
    return {"None_": 0, "AtlasStation": 1, "AtlasStationFinal": 1, "BlackHole": 2}.get(name, -1)


def namegen_lines(captures: Captures, namegen: Path, examples: int) -> list[str]:
    """How often nms_namegen (and so the site) predicts what the game generated."""
    sys.path.insert(0, str(namegen.resolve()))
    from nms_namegen.region import voxelAttributes
    from nms_namegen.system import planetSeeds, systemAttributes, systemName

    t = {
        "name": Tally("system name"),
        "star": Tally("star colour"),
        "race": Tally("dominant race / uncharted"),
        "economy": Tally("economy (charted systems)"),
        "wealth": Tally("wealth (charted systems)"),
        "conflict": Tally("conflict (charted systems)"),
        "abandoned": Tally("abandoned"),
        "pirate": Tally("outlaw (pirate) system"),
        "gas": Tally("gas giant layout"),
        "planets": Tally("planet count"),
        "prime": Tally("prime planet count"),
        "seeds": Tally("planet seeds, every body in order"),
        "anomaly": Tally("black hole / Atlas Interface"),
        "voxel": Tally("region attributes (guide stars, renegades, anomalies)"),
        "key planets": Tally("key attributes: planet count"),
        "key prime": Tally("key attributes: prime planet count"),
        "key safe start": Tally("key attributes: safe start planet"),
        "key abandoned": Tally("key attributes: abandoned"),
        "key pirate": Tally("key attributes: outlaw (pirate)"),
    }
    for r in captures.representative_by_system().values():
        d = r.data
        code, galaxy = r.system_code, r.galaxy
        ga = d.get("galaxy") if isinstance(d.get("galaxy"), dict) else {}
        flags = set(ga.get("flags", []))
        try:
            attrs = systemAttributes(code, galaxy)
            name = systemName(code, galaxy)
            seeds = planetSeeds(code, galaxy)
            va = voxelAttributes(code)
        except Exception as exc:  # the generator raises on some addresses; count it as a miss
            for tally in t.values():
                tally.add(False, lambda e=exc: f"{r.label()}: generator raised {type(e).__name__}")
            continue

        def miss(game, predicted):
            return lambda: f"{r.label()}: game {game!r}, generator {predicted!r}"

        if r.display_name:
            t["name"].add(r.display_name == name, miss(r.display_name, name))
        keys = d.get("keyAttributes")
        if isinstance(keys, dict):
            for tally, key, predicted in (
                ("key planets", "planets", attrs["planet_count"]),
                ("key prime", "prime", attrs["prime_planet_count"]),
                ("key safe start", "safeStart", attrs["safe_start_planet"]),
                ("key abandoned", "abandoned", attrs["abandoned"]),
                ("key pirate", "pirate", attrs["pirate"]),
            ):
                if key in keys:
                    t[tally].add(keys[key] == predicted, miss(keys[key], predicted))
        star = NAMEGEN_STAR.get(r.name("star", "star") or "")
        t["star"].add(None if star is None else star == attrs["star_type"], miss(star, attrs["star_type"]))
        race_name = r.name("race", "race")
        race = NAMEGEN_RACE.get(race_name or "")
        t["race"].add(
            None if race_name is None else race == attrs["dominant_race"],
            miss(race_name, attrs["dominant_race"]),
        )
        charted = race_name not in (None, "None_")
        if charted:
            for key, enum, table, predicted in (
                ("economy", "trade", NAMEGEN_ECONOMY, attrs["economy_type"]),
                ("wealth", "wealth", NAMEGEN_WEALTH, attrs["wealth"]),
                ("conflict", "conflict", NAMEGEN_CONFLICT, attrs["conflict_level"]),
            ):
                game_name = r.name(enum, enum)
                if game_name is not None:
                    t[key].add(table.get(game_name) == predicted, miss(game_name, predicted))
        if ga:
            t["abandoned"].add(
                ("AbandonedSystem" in flags) == attrs["abandoned"], miss(sorted(flags), attrs["abandoned"])
            )
            t["pirate"].add(
                ("IsPirateSystem" in flags) == attrs["pirate"], miss(sorted(flags), attrs["pirate"])
            )
            t["gas"].add(
                ("IsGasGiantSystem" in flags) == attrs["gas_giant"], miss(sorted(flags), attrs["gas_giant"])
            )
            if "planets" in ga:
                t["planets"].add(
                    ga["planets"] == attrs["planet_count"], miss(ga["planets"], attrs["planet_count"])
                )
            if "prime" in ga:
                t["prime"].add(
                    ga["prime"] == attrs["prime_planet_count"], miss(ga["prime"], attrs["prime_planet_count"])
                )
            if "seeds" in ga:
                predicted_seeds = [f"{s & MASK64:016X}" for s in seeds["planet_seeds"]]
                t["seeds"].add(ga["seeds"] == predicted_seeds, miss(ga["seeds"], predicted_seeds))
            game_anomaly = _game_anomaly(r.name("anomaly", "anomaly", ga))
            predicted_anomaly = _namegen_anomaly(va, (code >> 32) & 0xFFF)
            t["anomaly"].add(
                None if game_anomaly is None else game_anomaly == predicted_anomaly,
                miss(r.name("anomaly", "anomaly", ga), predicted_anomaly),
            )
            voxel = ga.get("voxel")
            if isinstance(voxel, list) and len(voxel) >= 7:
                game_voxel = [voxel[0], voxel[1], voxel[2], voxel[3], voxel[6]]
                predicted_voxel = [
                    va["atlas_station_count"],
                    va["black_hole_count"],
                    va["guide_star_count"],
                    va["guide_star_renegade_count"],
                    va["inside_gap"],
                ]
                t["voxel"].add(game_voxel == predicted_voxel, miss(game_voxel, predicted_voxel))
    return ["", f"nms_namegen against the game ({namegen})"] + tally_lines(list(t.values()), examples)


def ship_model_lines(captures: Captures, namegen: Path) -> list[str]:
    """Each system's ship seeds as ship_model.py predicts them from the address, against the game's."""
    sys.path.insert(0, str(namegen.resolve()))

    lines = ["", "Ship seeds predicted from the address alone (tools/captures/ship_model.py)"]
    matched = other = checked = 0
    misses: Counter[str] = Counter()
    for r in sorted(captures.representative_by_system().values(), key=lambda r: (r.galaxy, r.portal)):
        ships, crash = r.data.get("ships"), r.data.get("crashShip")
        if not ships or not crash:
            continue
        checked += 1
        game = [int(row[0], 16) for row in ships]
        predictions = ship_model.predictions(r.ua & ~PLANET_BITS)
        hits = [i for i, p in enumerate(predictions) if p.ships == game and p.crash == int(crash, 16)]
        prediction = predictions[0]
        if hits == [0]:
            matched += 1
            note = f" (flagged: {prediction.uncertain})" if prediction.uncertain else ""
            lines.append(f"  {r.label()}: all {len(game)} ships and the crashed ship match{note}")
            continue
        if hits:
            other += 1
            lines.append(
                f"  {r.label()}: all {len(game)} ships and the crashed ship match the other moon arrangement"
            )
            continue
        same = sum(a == b for a, b in zip(prediction.ships, game))
        found = locate_ship_stream(r.ua, [row[0] for row in ships], crash, STREAM_LIMIT)
        where = f"after {found.offset} draws" if found.offset is not None else "elsewhere"
        reason = prediction.uncertain or "not explained by the model"
        misses[reason] += 1
        lines.append(
            f"  {r.label()}: {same}/{len(game)} ships match; predicted the ships after {prediction.start} "
            f"draws, the game drew them {where} ({reason})"
        )
    if checked:
        summary = f"  {matched} of {checked} systems: every ship seed and the crashed ship's match the model's first guess"
        if other:
            summary += f"; {other} more match the other way of arranging a planet's two moons"
        if misses:
            summary += "; misses: " + ", ".join(f"{n} with {reason}" for reason, n in misses.most_common())
        lines.append(summary)
    return lines


def moon_layout_lines(captures: Captures, namegen: Path, examples: int) -> list[str]:
    """Which way round each two-moon planet's moons are, wherever a record holds the bodies' positions."""
    sys.path.insert(0, str(namegen.resolve()))

    sources = [(r.ua & ~PLANET_BITS, r.data.get("positions")) for r in captures.records]
    sources += [
        (int(q["seed"], 16) & ~PLANET_BITS, q.get("positions")) for q in captures.queries if q.get("seed")
    ]
    ways: Counter[str] = Counter()
    odd: list[str] = []
    seen: set[int] = set()
    for ua, positions in sources:
        if not positions or ua in seen:
            continue
        seen.add(ua)
        system = ship_model.bodies(ua)
        if not system or len(positions) < len(system):
            continue
        for planet in ship_model.two_moon_planets(system):
            first = next(k for k, body in enumerate(system) if body.parent == planet)
            x, _, z = (a - b for a, b in zip(positions[first], positions[planet]))
            azimuth = math.degrees(math.atan2(z, x)) % 360
            if min(azimuth, 360 - azimuth) < 1:
                ways["first moon at azimuth 0 (the model's first guess)"] += 1
            elif abs(azimuth - math.degrees(ship_model.GOLDEN_ANGLE)) < 1:
                ways["first moon at 137.5 degrees"] += 1
            else:
                ways["neither"] += 1
                odd.append(f"{ua:016X} planet {planet}: first moon at azimuth {azimuth:.2f}")
    lines = ["", f"Two-moon planets whose moons' positions were recorded: {sum(ways.values())}"]
    lines += [f"  {way}: {n}" for way, n in ways.most_common()]
    lines += [f"    {line}" for line in odd[:examples]]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "captures", nargs="+", type=Path, help="systems.jsonl files written by the capture mod"
    )
    parser.add_argument("--namegen", type=Path, help="path to a clone of nms_namegen, to score the generator")
    parser.add_argument("--examples", type=int, default=5, help="mismatches to list per field (default 5)")
    args = parser.parse_args(argv)

    try:
        captures = read_captures(args.captures)
    except (OSError, CaptureFormatError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    lines = (
        summary_lines(captures)
        + consistency_lines(captures, args.examples)
        + ship_stream_lines(captures)
        + trace_lines(captures)
        + lookup_lines(captures)
        + model_lines(captures)
        + part_coverage_lines(captures)
        + star_guild_lines(captures)
        + pool_lines(captures)
        + item_lines(captures)
    )
    if args.namegen:
        lines += namegen_lines(captures, args.namegen, args.examples)
        lines += name_lines(captures, args.namegen, args.examples)
        lines += ship_model_lines(captures, args.namegen)
        lines += moon_layout_lines(captures, args.namegen, args.examples)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
