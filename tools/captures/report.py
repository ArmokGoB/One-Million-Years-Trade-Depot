#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Summarise capture files written by mods/system_capture.py.

Prints what was recorded (systems, ship pools, exotics), checks the game's
data against itself (a struct layout that doesn't match the game shows up
here first), and, given a path to nms_namegen, measures how often the
generator behind the site agrees with the game.

Usage:
    python3 tools/captures/report.py mods/captures/systems.jsonl
    python3 tools/captures/report.py --namegen ../nms_namegen mods/captures/systems.jsonl

Only the standard library is needed, plus numpy for --namegen.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_FORMATS = {1}
ZERO_SEED = "0" * 16
MASK32 = 0xFFFFFFFF

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
        return int(self.data["ua"], 16)

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

    def label(self) -> str:
        return f"{self.portal} galaxy {self.galaxy} {self.data.get('name') or '(unnamed)'}"

    def name(self, enum: str, key: str, source: dict | None = None) -> str | None:
        value = (self.data if source is None else source).get(key)
        return self.session.name(enum, value)


@dataclass
class Captures:
    sessions: list[Session] = field(default_factory=list)
    records: list[SystemRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def by_system(self) -> dict[int, list[SystemRecord]]:
        grouped: dict[int, list[SystemRecord]] = {}
        for record in self.records:
            grouped.setdefault(record.ua & ~(0xF << 52), []).append(record)
        return grouped

    def representative_by_system(self) -> dict[int, SystemRecord]:
        """One record per system: the first with a ship list, which is closest to what the
        generator produced, or else the last record."""
        chosen: dict[int, SystemRecord] = {}
        for key, records in self.by_system().items():
            with_ships = [r for r in records if r.data.get("ships")]
            chosen[key] = with_ships[0] if with_ships else records[-1]
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
                elif kind == "sys":
                    if session is None:
                        captures.skipped.append(f"{where}: system record before any session header")
                    elif not isinstance(obj.get("ua"), str):
                        captures.skipped.append(f"{where}: system record without an address")
                    else:
                        captures.records.append(SystemRecord(obj, session, number))
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


def summary_lines(captures: Captures) -> list[str]:
    systems = captures.representative_by_system()
    files = sorted({s.source for s in captures.sessions})
    lines = [
        f"{len(files)} file(s), {len(captures.sessions)} session(s), "
        f"{len(captures.records)} record(s), {len(systems)} system(s)"
    ]
    builds = Counter(
        (s.header.get("exe") or "unknown", s.header.get("nmspy") or "?") for s in captures.sessions
    )
    for (exe, nmspy), count in builds.most_common():
        lines.append(f"  game exe {exe[:12]} with NMS.py {nmspy}: {count} session(s)")
    galaxies = Counter(r.galaxy for r in systems.values())
    if galaxies:
        lines.append("  galaxies: " + ", ".join(f"{g} x{n}" for g, n in sorted(galaxies.items())))
    via = Counter(r.data.get("via", "?") for r in captures.records)
    lines.append("  recorded by: " + ", ".join(f"{k} {n}" for k, n in via.most_common()))
    errors = sum(1 for r in captures.records if r.data.get("errors"))
    unusual = sum(1 for r in captures.records if r.data.get("unusual"))
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


def _location_matches(record: SystemRecord) -> bool | None:
    loc = record.data.get("loc")
    if not isinstance(loc, list) or len(loc) < 5:
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
        "sim": Tally("address = simulation's current address"),
        "loc": Tally("address = player's location"),
        "star": Tally("star type = galaxy attributes"),
        "race": Tally("race = galaxy attributes"),
        "trade": Tally("economy = galaxy attributes"),
        "wealth": Tally("wealth = galaxy attributes"),
        "conflict": Tally("conflict = galaxy attributes"),
        "planets": Tally("planet count = galaxy attributes"),
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
        if "sim" in d:
            t["sim"].add(
                int(d["sim"], 16) & ~(0xF << 52) == r.ua & ~(0xF << 52), lambda: f"{r.label()}: {d['sim']}"
            )
        t["loc"].add(_location_matches(r), lambda: f"{r.label()}: {d.get('loc')}")
        if ga:
            for key in ("star", "race", "trade", "wealth", "conflict", "planets", "prime"):
                if key in d and key in ga:
                    t[key].add(d[key] == ga[key], lambda k=key: f"{r.label()}: {d[k]} vs {ga[k]}")
            if "bodies" in d and "seeds" in ga:
                body_seeds = [row[0] for row in d["bodies"] if row[0] != ZERO_SEED]
                t["bodies"].add(
                    body_seeds == ga["seeds"][: len(body_seeds)] and bool(body_seeds),
                    lambda: f"{r.label()}: {body_seeds} vs {ga['seeds']}",
                )
    return ["", "Self-consistency of the game's data"] + tally_lines(list(t.values()), examples)


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
    from nms_namegen.iprng import indexPrimedPRNG
    from nms_namegen.region import voxelAttributes
    from nms_namegen.system import planetSeeds, systemAttributes, systemName

    t = {
        "seed": Tally("system seed (index-primed PRNG, low 32 bits)"),
        "seed64": Tally("system seed (all 64 bits)"),
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
            ua = ((((code >> 32) & 0xFFF) << 8 | galaxy) << 32) | (code & MASK32)
            prng = indexPrimedPRNG(ua)
            va = voxelAttributes(code)
        except Exception as exc:  # the generator raises on some addresses; count it as a miss
            for tally in t.values():
                tally.add(False, lambda e=exc: f"{r.label()}: generator raised {type(e).__name__}")
            continue

        def miss(game, predicted):
            return lambda: f"{r.label()}: game {game!r}, generator {predicted!r}"

        if "seed" in d:
            game_seed = int(d["seed"], 16)
            t["seed"].add(game_seed & MASK32 == prng & MASK32, miss(d["seed"], f"{prng:016X}"))
            t["seed64"].add(game_seed == prng, miss(d["seed"], f"{prng:016X}"))
        if d.get("name"):
            t["name"].add(d["name"] == name, miss(d["name"], name))
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
                predicted_seeds = [f"{s & 0xFFFFFFFFFFFFFFFF:016X}" for s in seeds["planet_seeds"]]
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
    lines = summary_lines(captures) + consistency_lines(captures, args.examples)
    if args.namegen:
        lines += namegen_lines(captures, args.namegen, args.examples)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
