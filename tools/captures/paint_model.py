# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the game paints a ship, freighter, frigate or multi-tool with: each layer's texture and color.

Worked out from the game's code and checked against every paint the capture mod recorded (0.13.0 on): for
the models the site paints, each layer's texture option, palette, color alternative and color came out as
the game picked them, every one. tools/build_paint_tables.py keeps what painting needs in
src/core/data/paint-tables.json; src/core/paint.ts is the site's port.

Palettes. The game makes a model's 66 palettes of five colors from a seed (palettes()): a starship's and a
swarm drone's from its own seed; a freighter's, a frigate's and the rest of a system's fleet's from the
system's, its universal address; a multi-tool's from its own seed, the older way, from the older palettes
(legacy_palettes()). Each color comes from a palette of up to 64 in the game's files, picked with two
draws; a color too close to one picked already gives way to the next in the palette.

Textures. Each material of the model as built, with only the parts its descriptor picked, has two samplers
the paint is picked for, gDiffuseMap (pass 0) and gDiffuse2Map (pass 1), each with a texture list: layers
of options, each option a texture tinted with one of the five colors of a palette. There are two passes if
any material has a list for gDiffuse2Map, else one. For each pass:

1. The layers of every material's list, in material order, are merged by name and group: a merged layer's
   probability is the mean of the layers', an option's weight the mean of its own over the lists that have
   it (the same name, palette and color alternative). An option for a hint counts only if the model has
   that texture hint (a Sentinel ship has POLICE), one for no hint only if it has none.
2. One random stream, seeded with the model's seed, then decides for each merged layer whose probability is
   above 0 whether it's painted (a draw below the probability); if it is, and it isn't marked to match its
   base, which option (a second draw times the sum of the weights, against the running sum).
3. Each material's first layer named BASE or unnamed gets its own record unless the pick for its group is
   one of its options already: the option of that name, if it can be used, or else its first option that
   can.
4. One more draw per merged layer: a layer marked to match its base that's painted takes the option its
   group's base got, by name.

An option's color is its palette's color for its alternative: Primary and Alternative1 to 3 as they are,
Alternative4 and Unique the fourth color, None no color. A layer that isn't painted is white.

The materials come in the order of the model's scene: a node's materials, then its own children, then the
scenes it brings in, each in turn the same way; each material once, where it first comes. A part's node is
built only if the descriptor picked the part (see tools/build_paint_tables.py).
"""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from game_rng import MASK32, MASK64, MULTIPLIER, mix, swap16

TABLES = Path(__file__).resolve().parents[2] / "src" / "core" / "data" / "paint-tables.json"

PALETTES = [
    "Grass", "Plant", "Leaf", "Wood", "Rock", "Stone", "Crystal", "Sand", "Dirt", "Metal", "Paint", "Plastic", "Fur",
    "Scale", "Feather", "Water", "Cloud", "Sky", "Space", "Underbelly", "Undercoat", "Snow", "SkyHorizon", "SkyFog",
    "SkyHeightFog", "SkySunset", "SkyNight", "WaterNear", "SpaceCloud", "SpaceBottom", "SpaceSolar", "SpaceLight",
    "Warrior", "Scientific", "Trader", "WarriorAlt", "ScientificAlt", "TraderAlt", "RockSaturated", "RockLight",
    "RockDark", "PlanetRing", "Custom_Head", "Custom_Torso", "Custom_Chest_Armour", "Custom_Backpack", "Custom_Arms",
    "Custom_Hands", "Custom_Legs", "Custom_Feet", "Cave", "GrassAlt", "BioShip_Body", "BioShip_Underbelly",
    "BioShip_Cockpit", "SailShip_Sails", "Freighter", "FreighterPaint", "PirateBase", "PirateAlt", "SpaceStationBase",
    "SpaceStationAlt", "SpaceStationLights", "DeepWaterBioLum", "Slime", "Hulk",
]  # fmt: skip
ALTS = ["Primary", "Alternative1", "Alternative2", "Alternative3", "Alternative4", "Unique", "MatchGround", "None"]

# Where each model's palettes come from: its own seed, its system's or, the older way, its own.
OWN, SYSTEM, LEGACY = "own", "system", "legacy"
PALETTE_SOURCES = {
    **dict.fromkeys(
        ["FIGHTER_PROC", "DROPSHIP_PROC", "SCIENTIFIC_PROC", "SHUTTLE_PROC", "SAILSHIP_PROC", "S-CLASS_PROC"], OWN
    ),
    **dict.fromkeys(["SENTINELSHIP_PROC", "SWARM"], OWN),
    **dict.fromkeys(["MULTITOOL", "ROYALMULTITOOL", "SENTINELMULTITOOL", "ATLASMULTITOOL"], LEGACY),
}


def palette_source(model: str) -> str:
    """Whose seed ``model``'s palettes come from: OWN, SYSTEM or LEGACY (its own, the older way)."""
    return PALETTE_SOURCES.get(model, SYSTEM)


# --- Numbers ---

UNIT = 1.0 / 4294967295.0  # the game turns a draw into a fraction with this, then rounds it to single precision
CLOSE = 2.0**-32  # base palettes: a color less than this (squared) from one picked already is the same color


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


class Stream:
    """The generator the paint and the palettes draw from: the same multiply-with-carry generator as
    game_rng's, seeded from a 64-bit seed slightly differently (a zero low word is one, and the carry isn't
    made non-zero), or with (1, 0) when told not to use the seed."""

    def __init__(self, seed: int, use: bool = True):
        if use:
            low, high = seed & MASK32, (seed >> 32) & MASK32
            self.word, self.carry = low or 1, swap16(low) ^ high ^ low
        else:
            self.word, self.carry = 1, 0

    def next(self) -> int:
        value = self.word * MULTIPLIER + self.carry
        self.word, self.carry = value & MASK32, value >> 32
        return self.word

    def fraction(self) -> float:
        return f32(self.next() * UNIT)

    def copy(self) -> Stream:
        other = Stream(0, False)
        other.word, other.carry = self.word, self.carry
        return other

    def derive(self) -> Stream:
        """A stream seeded with the next two draws, mixed as a ship's seed is; this one doesn't advance."""
        ahead = self.copy()
        low = ahead.next()
        high = ahead.next()
        return Stream(mix(((high << 32) | low) & MASK64))


# --- Tables ---


@dataclass
class Option:
    name: str
    alt: int
    palette: int
    weight: float
    use: int


@dataclass
class Layer:
    group: str
    name: str
    probability: float
    match_base: int
    options: list[Option]


@dataclass
class TextureList:
    keep_apart: int
    layers: list[Layer]


@lru_cache(maxsize=1)
def tables() -> dict:
    """The paint tables, with every number rounded to single precision again."""
    with open(TABLES, encoding="utf-8") as f:
        t = json.load(f)

    def palette(entry: list | None):
        if entry is None:
            return None
        values = [f32(x) for x in entry[1:]]
        return int(entry[0]), [tuple(values[3 * i : 3 * i + 3]) for i in range(64)]

    t["palettes"] = {key: [palette(entry) for entry in entries] for key, entries in t["palettes"].items()}
    t["lists"] = [
        TextureList(
            keep,
            [
                Layer(group, name, f32(probability), match, [Option(o, a, p, f32(w), u) for o, a, p, w, u in options])
                for group, name, probability, match, options in layers
            ],
        )
        for keep, layers in t["lists"]
    ]
    return t


def models() -> list[str]:
    """The models the tables can paint, by key (FIGHTER_PROC, COMBATFRIGATELOD0, ...)."""
    return list(tables()["models"])


# --- Palettes ---


def _index(count_kind: int, x1: int, x2: int) -> int:
    """Where in a palette a color is picked from, by how many colors the palette uses."""
    top = x1 >> 29
    if count_kind == 1:
        return 0
    if count_kind == 2:
        return ((top >> 2) * 8 + (x2 >> 31)) * 4
    if count_kind == 3:
        return x2 >> 29
    if count_kind == 4:
        return ((x2 >> 30) + (top >> 1) * 8) * 2
    return (x2 >> 29) + top * 8


def _place(count_kind: int, index: int) -> int:
    """The color a place stands for, by how many colors the palette uses."""
    low = index & 7
    if count_kind == 1:
        return 0
    if count_kind == 2:
        return ((low >> 2) + (index >> 5) * 8) * 4
    if count_kind == 3:
        return low
    if count_kind == 4:
        return ((low >> 1) + (index >> 4) * 8) * 2
    return index


def _pick(table, stream: Stream) -> list[tuple[float, float, float]] | None:
    """Five colors of a base palette: two draws each, the next place in the palette for a color the same as
    one picked already (64 places at most). A palette the tables leave out is drawn for all the same."""
    picked: list[tuple[float, float, float]] = []
    for _ in range(5):
        x1, x2 = stream.next(), stream.next()
        if table is None:
            continue
        count_kind, colors = table
        index = _index(count_kind, x1, x2)
        color = colors[_place(count_kind, index)]
        for _ in range(64):
            if not any(sum((a - b) ** 2 for a, b in zip(other, color)) < CLOSE for other in picked):
                break
            index = (index + 1) & 63
            color = colors[_place(count_kind, index)]
        picked.append(color)
    return picked if table is not None else None


def palettes(seed: int, use: bool = True) -> list[list[tuple[float, float, float]] | None]:
    """The 66 palettes the game makes from a seed, five colors each (None for those the tables leave out):
    in turn up to the 52nd; the Freighter one from the stream as it was at the Paint one; then the six
    faction palettes from a stream derived after them, the Grass ones from another derived after two more
    draws, and the rest from one derived from that."""
    tables_ = tables()["palettes"]["base"]
    out: list = [None] * 66
    stream = Stream(seed, use)
    at_paint = None
    for p in range(52):
        if p == 10:
            at_paint = stream.copy()
        out[p] = _pick(tables_[p], stream)
    factions = stream.derive()
    stream.next(), stream.next()
    grass = stream.derive()
    for p in (0x20, 0x23, 0x22, 0x25, 0x21, 0x24):
        out[p] = _pick(tables_[p], factions.copy())
    out[0] = _pick(tables_[0], grass.copy())
    out[0x33] = _pick(tables_[0x33], grass)
    rest = grass.derive()
    for p in range(0x34, 0x42):
        out[p] = _pick(tables_[p], at_paint if p == 0x38 else rest)
    return out


def _too_close(a: tuple, b: tuple, threshold: float) -> bool:
    dr, dg, db = f32(a[0] - b[0]), f32(a[1] - b[1]), f32(a[2] - b[2])
    total = f32(f32(f32(dr * dr) + f32(dg * dg)) + f32(db * db))
    return f32(threshold) > f32(math.sqrt(total))


def _pick_legacy(table, stream: Stream, threshold: float) -> list[tuple[float, float, float]]:
    """Five colors of an older palette: two draws for each try, up to 64 tries for a color at least
    ``threshold`` from those picked already."""
    count_kind, colors = table
    picked: list[tuple[float, float, float]] = []
    for _ in range(5):
        for _ in range(64):
            x1, x2 = stream.next(), stream.next()
            color = colors[(x2 >> 29) if count_kind == 3 else (x2 >> 29) + (x1 >> 29) * 8]
            if not any(_too_close(other, color, threshold) for other in picked):
                break
        picked.append(color)
    return picked


def legacy_palettes(seed: int, use: bool = True, threshold: float = 1.0) -> list:
    """The palettes the game makes the older way, as for multi-tools: each in turn, up to the last one the
    tables have (None for the rest), the six faction palettes made again at the end if the tables have all."""
    tables_ = tables()["palettes"]["legacy"]
    out: list = [None] * 66
    stream = Stream(seed, use)
    for p, table in enumerate(tables_):
        out[p] = _pick_legacy(table, stream, threshold)
    if len(tables_) == 66:
        factions = stream.derive()
        for p in (0x20, 0x23, 0x22, 0x25, 0x21, 0x24):
            out[p] = _pick_legacy(tables_[p], factions.copy(), threshold)
    return out


# --- The paint ---

BASE, UNNAMED = "BASE", ""
NO_COLOR = 7
WHITE = (1.0, 1.0, 1.0)
# A level-of-detail suffix, which the game drops from the IDs of the parts it picks.
LOD_SUFFIX = re.compile(r"LOD\d+$")


@dataclass
class Painted:
    """One layer of a pass and what it was painted with: a row of a capture's paint line, but for its
    sampler and color's place. ``color`` is None for an option of no color; a layer that isn't painted has
    an empty option, Rock, Primary and white."""

    group: str
    layer: str
    option: str
    palette: int
    alt: int
    color: tuple[float, float, float] | None
    painted: bool


@dataclass
class _MergedOption:
    name: str
    alt: int
    palette: int
    count: int
    weight: float


@dataclass
class _Merged:
    name: str
    group: str
    count: int
    probability: float
    match_base: int
    options: list[_MergedOption] = field(default_factory=list)


def _usable(option: Option, hint: str) -> bool:
    if option.use == 1:
        return hint == option.name
    if option.use == 2:
        return hint == ""
    return True


def _merge(merged: list[_Merged], layer: Layer, hint: str, keep_apart: int) -> None:
    found = None
    if not (keep_apart and len(layer.options) < 2 and layer.group == UNNAMED):
        found = next((m for m in merged if m.name == layer.name and m.group == layer.group), None)
    if found is None:
        m = _Merged(layer.name, layer.group, 1, layer.probability, layer.match_base)
        m.options = [_MergedOption(o.name, o.alt, o.palette, 1, o.weight) for o in layer.options if _usable(o, hint)]
        if m.options:
            merged.append(m)
        return
    found.count += 1
    found.probability = f32(layer.probability + found.probability)
    found.match_base |= layer.match_base
    for o in layer.options:
        same = next((mo for mo in found.options if (mo.name, mo.palette, mo.alt) == (o.name, o.palette, o.alt)), None)
        if same is not None:
            same.count += 1
            same.weight = f32(o.weight + same.weight)
        elif _usable(o, hint):
            found.options.append(_MergedOption(o.name, o.alt, o.palette, 1, o.weight))


def _color(alt: int, palette: int, pals: list) -> tuple[float, float, float] | None:
    if alt == NO_COLOR:
        return None
    return pals[palette][min(alt, 3)]


def _pass(lists: list[TextureList | None], seed: int, use: bool, hint: str, pals: list) -> list[Painted]:
    merged: list[_Merged] = []
    for tl in lists:
        if tl is not None:
            for layer in tl.layers:
                _merge(merged, layer, hint, tl.keep_apart)
    stream = Stream(seed, use)
    rows: list[list] = []  # [group, layer, option, palette, alt, color, painted]
    for m in merged:
        m.probability = f32(m.probability / f32(m.count))
        row = [m.group, m.name, "", 4, 0, WHITE, False]  # not painted: Rock, Primary, white
        if m.probability > 0.0 and stream.fraction() < m.probability and not m.match_base:
            total = 0.0
            for o in m.options:
                o.weight = f32(o.weight / f32(o.count))
                total = f32(total + o.weight)
            target = f32(stream.fraction() * total)
            running = 0.0
            for o in m.options:
                running = f32(running + o.weight)
                if target < running:
                    row = [m.group, m.name, o.name, o.palette, o.alt, _color(o.alt, o.palette, pals), True]
                    break
        rows.append(row)
    for tl in lists:
        if tl is None:
            continue
        layer = next((ly for ly in tl.layers if ly.name in (BASE, UNNAMED)), None)
        if layer is None:
            continue
        exact, named = False, -1
        for r in list(rows):
            if r[1] == layer.name and r[0] == layer.group:
                for j, o in enumerate(layer.options):
                    if o.name == r[2]:
                        named = j
                        if (o.palette, o.alt) == (r[3], r[4]):
                            exact = True
                            break
        if exact:
            continue
        if named < 0 or not _usable(layer.options[named], hint):
            named = next((j for j, o in enumerate(layer.options) if _usable(o, hint)), -1)
            if named < 0:  # the game would read an option from outside the list here
                raise ValueError(f"no option of a base layer can be used with the hint {hint!r}")
        o = layer.options[named]
        rows.append([layer.group, layer.name, o.name, o.palette, o.alt, _color(o.alt, o.palette, pals), True])
    for i, m in enumerate(merged):
        if stream.fraction() < m.probability and m.match_base:
            for b in list(rows):
                if b[1] in (BASE, UNNAMED) and b[0] == m.group:
                    o = next((o for o in m.options if o.name == b[2]), None)
                    if o is not None:
                        rows[i][2:7] = [b[2], o.palette, o.alt, _color(o.alt, o.palette, pals), True]
                        break
    return [Painted(*row) for row in rows]


def materials(model: str, parts) -> list[int]:
    """The painted materials of ``model`` built with these parts, in the order the game lists them."""
    t = tables()
    chosen = {LOD_SUFFIX.sub("", part.upper()) for part in parts}
    out: list[int] = []
    seen: set[int] = set()

    def visit(items: list, depth: int) -> None:
        for item in items:
            if isinstance(item, list):  # [part, items]: built only with the part
                if item[0] in chosen:
                    visit(item[1:], depth)
            elif item < 0:  # a scene it brings in
                if depth < 32:
                    visit(t["scenes"][-1 - item], depth + 1)
            elif item not in seen:  # a material
                seen.add(item)
                out.append(item)

    root = t["models"][model]
    if root >= 0:
        visit(t["scenes"][root], 0)
    return out


def paint(model: str, parts, seed: int, pals: list, hint: str = "", use: bool = True) -> dict[int, list[Painted]]:
    """What the game paints ``model`` with: {pass: [Painted]}, pass 0 for gDiffuseMap, 1 for gDiffuse2Map.
    ``parts`` are the parts its descriptor picked (parts_model.parts), ``pals`` the palettes it takes its
    colors from (palettes() or legacy_palettes() of the seed palette_source() says), ``hint`` its texture
    hint ("" for none)."""
    t = tables()
    per_material = [[t["lists"][k] if k >= 0 else None for k in t["materials"][m]] for m in materials(model, parts)]
    passes = 0
    for first, second in per_material:
        passes = max(passes, (first is not None) + 1 if second is not None else int(first is not None))
    return {k: _pass([lists[k] for lists in per_material], seed, use, hint, pals) for k in range(passes)}
