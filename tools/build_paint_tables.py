#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builds src/core/data/paint-tables.json from the game's palettes, scenes, materials and texture lists.

What the game paints a ship, freighter, frigate or multi-tool with comes from:

- its palettes: the game makes 66 palettes of five colors from a seed, each picked from a palette of up to
  64 colors in METADATA/SIMULATION/SOLARSYSTEM/COLOURS/BASECOLOURPALETTES.MBIN, or, for a multi-tool, in
  LEGACYBASECOLOURPALETTES.MBIN, the older palettes;
- its scene as built, with only the parts its descriptor picked: the materials of its nodes, in order;
- each material's two samplers the paint is picked for, gDiffuseMap and gDiffuse2Map, and the procedural
  texture list beside each one's texture (its file name with the extensions dropped and .TEXTURE.MBIN
  added): up to eight layers, each with options, each option a texture tinted with a color of a palette.

This script keeps what painting needs and nothing else: each palette's colors and how many of them it uses;
each texture list's layers that have options, with their options; each material's two lists; and each
model's scene cut down to the nodes that lead to a material with a list, with the part each node is built
for, if any. tools/captures/paint_model.py and src/core/paint.ts paint from the result.

The files are the game's own, which this repository doesn't hold. Extract them from the game's PCBANKS
folder with HGPAKtool (https://github.com/monkeyman192/HGPAKtool), for instance:

    hgpaktool -U -f="*.scene.mbin" -f="*.descriptor.mbin" -f="*.material.mbin" -f="*.texture.mbin" \\
        -f="*palettes.mbin" <PCBANKS folder>

and point this script at the folder it extracts them into:

    python3 tools/build_paint_tables.py --game EXTRACTED

A scene or material that a model brings in and that isn't among the extracted files is an error: the
paint would come out wrong without it.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

from build_part_tables import HEADER_SIZE, MAGIC, MBIN_VERSION, Descriptor, DescriptorError, descriptor_path

OUT_DEFAULT = Path(__file__).resolve().parent.parent / "src" / "core" / "data" / "paint-tables.json"

# The models the site paints, by the key the code uses for them, and their scenes: the models whose parts
# the site picks (see build_part_tables.py), and, of the frigates, the swarm and the pirates' frigates,
# the closest level of detail, which has no parts to pick.
MODELS = {
    "FIGHTER_PROC": "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN",
    "DROPSHIP_PROC": "MODELS/COMMON/SPACECRAFT/DROPSHIPS/DROPSHIP_PROC.SCENE.MBIN",
    "SCIENTIFIC_PROC": "MODELS/COMMON/SPACECRAFT/SCIENTIFIC/SCIENTIFIC_PROC.SCENE.MBIN",
    "SHUTTLE_PROC": "MODELS/COMMON/SPACECRAFT/SHUTTLE/SHUTTLE_PROC.SCENE.MBIN",
    "SAILSHIP_PROC": "MODELS/COMMON/SPACECRAFT/SAILSHIP/SAILSHIP_PROC.SCENE.MBIN",
    "S-CLASS_PROC": "MODELS/COMMON/SPACECRAFT/S-CLASS/S-CLASS_PROC.SCENE.MBIN",
    "SENTINELSHIP_PROC": "MODELS/COMMON/SPACECRAFT/SENTINELSHIP/SENTINELSHIP_PROC.SCENE.MBIN",
    "FREIGHTER_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/FREIGHTER_PROC.SCENE.MBIN",
    "CAPITALFREIGHTER_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/CAPITALFREIGHTER_PROC.SCENE.MBIN",
    "MULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/MULTITOOL.SCENE.MBIN",
    "ROYALMULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/ROYALMULTITOOL.SCENE.MBIN",
    "SENTINELMULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/SENTINELMULTITOOL.SCENE.MBIN",
    "ATLASMULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/ATLASMULTITOOL.SCENE.MBIN",
    "FREIGHTERSMALL_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/FREIGHTERSMALL_PROC.SCENE.MBIN",
    "FREIGHTERTINY_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/FREIGHTERTINY_PROC.SCENE.MBIN",
    "POLICEFREIGHTER": "MODELS/COMMON/SPACECRAFT/POLICE/POLICEFREIGHTER.SCENE.MBIN",
    "PIRATEFREIGHTER": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/PIRATEFREIGHTER.SCENE.MBIN",
    "COMBATFRIGATELOD0": "MODELS/COMMON/SPACECRAFT/FRIGATES/COMBATFRIGATELOD0.SCENE.MBIN",
    "SCIENCEFRIGATELOD0": "MODELS/COMMON/SPACECRAFT/FRIGATES/SCIENCEFRIGATELOD0.SCENE.MBIN",
    "INDUSTRIALFRIGATELOD0": "MODELS/COMMON/SPACECRAFT/FRIGATES/INDUSTRIALFRIGATELOD0.SCENE.MBIN",
    "DIPLOMATICFRIGATELOD0": "MODELS/COMMON/SPACECRAFT/FRIGATES/DIPLOMATICFRIGATELOD0.SCENE.MBIN",
    "SUPPORTFRIGATELOD0": "MODELS/COMMON/SPACECRAFT/FRIGATES/SUPPORTFRIGATELOD0.SCENE.MBIN",
    "GHOSTSHIPFRIGATELOD0": "MODELS/COMMON/SPACECRAFT/FRIGATES/GHOSTSHIPFRIGATELOD0.SCENE.MBIN",
    "PIRATECRUISERLOD0": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/PIRATECRUISERLOD0.SCENE.MBIN",
    "SWARMFRIGATE": "MODELS/COMMON/SPACECRAFT/SWARM/SWARMFRIGATE.SCENE.MBIN",
    "SWARM": "MODELS/COMMON/SPACECRAFT/SWARM/SWARM.SCENE.MBIN",
}

PALETTE_FILES = {
    "base": "METADATA/SIMULATION/SOLARSYSTEM/COLOURS/BASECOLOURPALETTES.MBIN",
    "legacy": "METADATA/SIMULATION/SOLARSYSTEM/COLOURS/LEGACYBASECOLOURPALETTES.MBIN",
}
# The models whose colors come from the older palettes: the multi-tools.
LEGACY_MODELS = {"MULTITOOL", "ROYALMULTITOOL", "SENTINELMULTITOOL", "ATLASMULTITOOL"}
# A color alternative that takes no color from a palette, and one that takes the color the paint is handed.
NO_COLOR, MATCH_GROUND = 7, 6

# The two samplers of a material the game picks paint for: pass 0 and pass 1.
SAMPLERS = ("gDiffuseMap", "gDiffuse2Map")

# --- Reading the files (.MBIN) ---
#
# Laid out as build_part_tables.py says, the templates as in NMS.py and MBINCompiler.

SCENE_HASH = 0x3DB87E47  # cTkSceneNodeData
MATERIAL_HASH = 0x4737D48A  # cTkMaterialData
TEXTURE_LIST_HASH = 0x4CF0C331  # cTkProceduralTextureList
PALETTE_LIST_HASH = 0x2DF7C5B6  # cGcPaletteList
ARRAY_FLAGS = 0xAAAAAA01

PALETTE_COUNT = 66  # cGcPaletteList: 66 cGcPaletteData of 0x410 bytes: 64 colors, then how many it uses
PALETTE_SIZE = 0x410
LAYER_COUNT = 8  # cTkProceduralTextureList: 8 cTkProceduralTextureLayer of 0x48 bytes, then a flag
LAYER_SIZE = 0x48
OPTION_SIZE = 0x60  # cTkProceduralTexture

# A level-of-detail suffix, which the game drops from a part's ID.
LOD_SUFFIX = re.compile(r"LOD\d+$")
# A node the game builds only with the part it's named for: an underscore, a type, an underscore and at
# least one more character (_ENGINE_B, _LETTERL_ALOD0). Other nodes, _SmallSignL2_ among them, are always
# built.
PART_NODE = re.compile(r"_[^_]+_.")


class TableError(ValueError):
    pass


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def short(value: float) -> float:
    """The shortest decimal that is the same single-precision number, as a float: the game's values are
    single precision, and readers round each number of the tables to single precision again."""
    for digits in range(1, 10):
        text = f"{value:.{digits}g}"
        if f32(float(text)) == value:
            return float(text)
    raise TableError(f"{value!r} isn't a single-precision number")


class Files:
    """The extracted files, by their path in the game, upper-cased; in the first folder that has each."""

    def __init__(self, roots: list[Path]):
        self.paths: dict[str, Path] = {}
        for root in roots:
            for p in root.rglob("*"):
                if p.is_file():
                    self.paths.setdefault(p.relative_to(root).as_posix().upper(), p)

    @staticmethod
    def norm(path: str) -> str:
        """A path as the game writes it in a file, as the index has it: forward slashes, upper case, without
        a {1}-style suffix."""
        return re.sub(r"\{\d+\}$", "", path.replace("\\", "/").upper())

    def has(self, path: str) -> bool:
        return self.norm(path) in self.paths

    def read(self, path: str, template_hash: int) -> bytes:
        data = self.paths[self.norm(path)].read_bytes()
        magic, version, _, name_hash = struct.unpack_from("<QHHI", data, 0)
        if magic != MAGIC or version != MBIN_VERSION or name_hash != template_hash:
            raise TableError(f"{path}: not a file this script can read")
        return data


def text(data: bytes, at: int, size: int) -> str:
    """A fixed-size name (TkID), which must hold nothing after its end: the game compares all of its bytes."""
    raw = data[at : at + size]
    name, _, rest = raw.partition(b"\0")
    if rest.strip(b"\0"):
        raise TableError(f"a name at {at:#x} has bytes after its end: {raw!r}")
    return name.decode("ascii")


def array(data: bytes, at: int, size: int) -> list[int]:
    """Where each element of the cTkDynamicArray at ``at`` lies."""
    offset, count, flags = struct.unpack_from("<QII", data, at)
    if count and flags != ARRAY_FLAGS:
        raise TableError(f"no array at {at:#x}")
    return [at + offset + i * size for i in range(count)]


def string(data: bytes, at: int) -> str:
    """A VariableSizeString: laid out like an array of its characters, the last one a zero."""
    offset, count, flags = struct.unpack_from("<QII", data, at)
    if not count:
        return ""
    if flags != ARRAY_FLAGS:
        raise TableError(f"no string at {at:#x}")
    return data[at + offset : at + offset + count].split(b"\0", 1)[0].decode("ascii")


def scene_node(data: bytes, at: int) -> dict:
    """A cTkSceneNodeData: attributes at 0x00 (name, value), children at 0x10, name at 0x30, type at 0x40."""
    attributes: dict[str, list[str]] = {}
    for a in array(data, at, 0x20):
        attributes.setdefault(text(data, a, 0x10), []).append(string(data, a + 0x10))
    return {
        "name": string(data, at + 0x30),
        "type": text(data, at + 0x40, 0x10),
        "attributes": attributes,
        "children": [scene_node(data, c) for c in array(data, at + 0x10, 0x80)],
    }


def palette_list(data: bytes) -> list[list[float]]:
    """Each palette: how many colors it uses (an enum: 0 none, 1 one, 2 four, 3 eight, 4 sixteen, 5 all),
    then the red, green and blue of its 64 colors. Every color's alpha is 1, which the tables leave out."""
    out = []
    for p in range(PALETTE_COUNT):
        at = HEADER_SIZE + p * PALETTE_SIZE
        entry: list[float] = [struct.unpack_from("<i", data, at + 0x400)[0]]
        for i in range(64):
            r, g, b, a = struct.unpack_from("<4f", data, at + 16 * i)
            if a != 1.0:
                raise TableError(f"palette {p}, color {i}: an alpha of {a}")
            entry += [short(r), short(g), short(b)]
        out.append(entry)
    return out


def texture_list(data: bytes) -> list:
    """[whether it keeps unnamed layers apart (its AlwaysEnableUnnamedTextureLayers), its layers that have
    options]; a layer is [group, name, probability, whether it matches its base (SelectToMatchBase),
    options], an option [name, color alternative, palette, weight, use (TextureGameplayUse)]."""
    layers = []
    for k in range(LAYER_COUNT):
        at = HEADER_SIZE + k * LAYER_SIZE
        options = []
        for o in array(data, at + 0x30, OPTION_SIZE):
            alt, _index, palette = struct.unpack_from("<IiI", data, o + 0x40)
            weight, use = struct.unpack_from("<fI", data, o + 0x4C)
            options.append([text(data, o + 0x10, 0x20), alt, palette, short(weight), use])
        if options:
            probability = struct.unpack_from("<f", data, at + 0x40)[0]
            match_base = data[at + 0x44]
            layers.append([text(data, at, 0x10), text(data, at + 0x20, 0x10), short(probability), match_base, options])
    return [data[HEADER_SIZE + LAYER_COUNT * LAYER_SIZE], layers]


def list_path(texture: str) -> str:
    """The texture list beside a texture: its file name without its extensions (up to four) and with
    .TEXTURE.MBIN."""
    folder, _, name = Files.norm(texture).rpartition("/")
    for _ in range(4):
        if "." in name:
            name = name.rsplit(".", 1)[0]
    return f"{folder}/{name}.TEXTURE.MBIN"


# --- The tables ---


class Builder:
    def __init__(self, files: Files):
        self.files = files
        self.lists: list = []
        self.list_index: dict[str, int] = {}
        self.materials: list[list[int]] = []
        self.material_index: dict[str, int | None] = {}
        self.scenes: list = []
        self.scene_index: dict[str, int] = {}
        self.visiting: set[str] = set()
        self.missing: set[str] = set()

    def texture_list(self, texture: str) -> int:
        """The index of the texture's list, or -1 if it has none: the game doesn't paint that texture."""
        path = list_path(texture)
        if path not in self.list_index:
            if not self.files.has(path):
                return -1
            self.list_index[path] = len(self.lists)
            self.lists.append(texture_list(self.files.read(path, TEXTURE_LIST_HASH)))
        return self.list_index[path]

    def material(self, path: str) -> int | None:
        """The index of a material with a list for either sampler, or None for one without."""
        path = Files.norm(path)
        if path not in self.material_index:
            if not self.files.has(path):
                self.missing.add(path)
                return None
            data = self.files.read(path, MATERIAL_HASH)
            maps: dict[str, str] = {}
            for s in array(data, HEADER_SIZE + 0x50, 0x50):  # cTkMaterialSampler: map at 0x20, name at 0x30
                maps.setdefault(string(data, s + 0x30), string(data, s + 0x20))
            lists = [self.texture_list(maps[s]) if s in maps else -1 for s in SAMPLERS]
            if lists == [-1, -1]:
                self.material_index[path] = None
            else:
                self.material_index[path] = len(self.materials)
                self.materials.append(lists)
        return self.material_index[path]

    def part_names(self, scene: str) -> dict[str, str]:
        """{node name: part ID}, both in capitals, for each option of the scene's descriptor, if it has one:
        the part a node of that name is built for."""
        path = descriptor_path(scene)
        if not self.files.has(path):
            return {}
        names: dict[str, str] = {}

        def walk(lists: list[dict]) -> None:
            for lst in lists:
                for option in lst["options"]:
                    names[option["name"].upper()] = option["id"].upper()
                    walk(option["children"])

        try:
            walk(Descriptor(self.files.paths[Files.norm(path)]).lists(HEADER_SIZE))
        except DescriptorError as exc:
            raise TableError(str(exc)) from exc
        return names

    def scene(self, path: str) -> int:
        """The index of the scene's items, or -1 if nothing in it is painted."""
        path = Files.norm(path)
        if path in self.scene_index:
            return self.scene_index[path]
        if path in self.visiting:
            raise TableError(f"{path} brings itself in")
        if not self.files.has(path):
            self.missing.add(path)
            return -1
        self.visiting.add(path)
        data = self.files.read(path, SCENE_HASH)
        items = self.node(scene_node(data, HEADER_SIZE), self.part_names(path))
        self.visiting.discard(path)
        self.scene_index[path] = len(self.scenes) if items else -1
        if items:
            self.scenes.append(items)
        return self.scene_index[path]

    def node(self, node: dict, names: dict[str, str]) -> list:
        """What a node brings in, in the order the game takes it: its painted materials, then what its children
        bring in, then the scenes it brings in (as -1 - their index). A node built for a part is a list of the
        part and its items; any other is its items, in its parent's. A node the scene's descriptor names is
        built for the part it names it for, and any other named as parts are, for the part of its name;
        either without a level-of-detail suffix."""
        name = node["name"].upper()
        bare = LOD_SUFFIX.sub("", name)
        part = names.get(name, names.get(bare))
        if part is not None:
            part = LOD_SUFFIX.sub("", part)
        elif PART_NODE.match(name):
            part = bare
        items: list = [
            m for m in (self.material(path) for path in node["attributes"].get("MATERIAL", [])) if m is not None
        ]
        for child in node["children"]:
            items += self.node(child, names)
        if node["type"] == "REFERENCE":
            items += [-1 - s for s in (self.scene(path) for path in node["attributes"].get("SCENEGRAPH", [])) if s >= 0]
        return [[part, *items]] if part and items else items

    def palettes_used(self, scene: int) -> set[int]:
        """The palettes the options of every list a scene can bring in take colors from, whichever parts are
        built."""
        used: set[int] = set()
        seen: set[int] = set()

        def walk(items: list) -> None:
            for item in items:
                if isinstance(item, list):
                    walk(item[1:])
                elif item < 0:
                    if -1 - item not in seen:
                        seen.add(-1 - item)
                        walk(self.scenes[-1 - item])
                else:
                    for k in self.materials[item]:
                        if k < 0:
                            continue
                        for _group, _name, _probability, _match, options in self.lists[k][1]:
                            for _option, alt, palette, _weight, _use in options:
                                if alt == MATCH_GROUND:
                                    raise TableError("an option takes the color the paint is handed (MatchGround)")
                                if alt != NO_COLOR:
                                    used.add(palette)

        if scene >= 0:
            seen.add(scene)
            walk(self.scenes[scene])
        return used


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--game", required=True, type=Path, action="append", help="folder HGPAKtool extracted the files into"
    )
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    files = Files(args.game)
    builder = Builder(files)
    palettes = {}
    try:
        for key, path in PALETTE_FILES.items():
            if not files.has(path):
                print(f"No {path} in {', '.join(map(str, args.game))}", file=sys.stderr)
                return 1
            palettes[key] = palette_list(files.read(path, PALETTE_LIST_HASH))
        models = {}
        for key, scene in MODELS.items():
            if not files.has(scene):
                print(f"No scene for {key} ({scene}) in {', '.join(map(str, args.game))}", file=sys.stderr)
                return 1
            models[key] = builder.scene(scene)
    except TableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if builder.missing:
        print(
            f"{len(builder.missing)} scenes and materials the models bring in aren't in "
            f"{', '.join(map(str, args.game))}, such as:",
            *sorted(builder.missing)[:5],
            sep="\n  ",
            file=sys.stderr,
        )
        return 1

    # Only the palettes the paint takes colors from. The game draws the same number of times for every base
    # palette, so each can be made without the others; but it draws for each older palette in turn as many
    # times as its colors make it, so the older ones are kept up to the last one used, and all of them if
    # one of the six it makes again at the end is used (Warrior to TraderAlt, 0x20 to 0x25).
    try:
        used = {key: set() for key in palettes}
        for key, scene in models.items():
            used["legacy" if key in LEGACY_MODELS else "base"] |= builder.palettes_used(scene)
    except TableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    palettes["base"] = [entry if p in used["base"] else None for p, entry in enumerate(palettes["base"])]
    if used["legacy"]:
        last = PALETTE_COUNT if used["legacy"] & set(range(0x20, 0x26)) else max(used["legacy"]) + 1
        palettes["legacy"] = palettes["legacy"][:last]
    else:
        palettes["legacy"] = []

    about = (
        "Derived from the game's palettes, scenes, materials and texture lists by tools/build_paint_tables.py. "
        "Numbers are single precision: round each to it again. Palettes: base (66, null where unused) and legacy "
        "(the first ones, up to the last used), each how many colors it uses (0 none, 1 one, 2 four, 3 eight, "
        "4 sixteen, 5 all) and the red, green and blue of its 64 colors. Lists: [whether unnamed layers are kept "
        "apart, layers], a layer [group, name, probability, whether it matches its base, options], an option "
        "[name, color alternative, palette, weight, use]. Materials: each one's lists for its two samplers "
        "(-1: none). Scenes: what each brings in, in order: a material (its index), a scene (-1 - its index), "
        "or what's built only with a part ([the part, items]). Models: the scene each one is (-1: nothing painted)."
    )

    def compact(value) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)

    def block(items: list) -> str:
        return "[\n" + ",\n".join(compact(item) for item in items) + "\n]"

    # One item a line, so that a change to one shows as a change to its line.
    lines = [
        "{",
        f'"about":{compact(about)},',
        f'"models":{compact(models)},',
        f'"palettes":{{"base":{block(palettes["base"])},',
        f'"legacy":{block(palettes["legacy"])}}},',
        f'"lists":{block(builder.lists)},',
        f'"materials":{compact(builder.materials)},',
        f'"scenes":{block(builder.scenes)}',
        "}",
    ]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.loads(args.out.read_text(encoding="utf-8"))  # still valid JSON
    print(
        f"Wrote {args.out}: {len(models)} models, {len(builder.scenes)} scenes, {len(builder.materials)} "
        f"materials, {len(builder.lists)} texture lists, {args.out.stat().st_size:,} bytes."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
