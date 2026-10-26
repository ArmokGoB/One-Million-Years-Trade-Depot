#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builds src/core/data/part-tables.json from the game's model descriptors.

A procedural model, a ship's or a multi-tool's, has a descriptor next to its
scene (FIGHTER_PROC.DESCRIPTOR.MBIN next to FIGHTER_PROC.SCENE.MBIN, say), a
cTkModelDescriptorList: lists of options for the game to pick one from, each
option with an ID, child lists, and the scenes it brings in, which have
descriptors of their own if they have parts to pick. This script keeps what
picking needs and nothing else: each list's options in order, each option's
ID, whether its name marks it rare (xRARE) or never picked (xNEVER), its
child lists and the scenes it brings in. tools/captures/parts_model.py and
src/core/parts.ts pick parts from the result.

The descriptors are the game's own files, which this repository doesn't hold.
Extract them from the game's PCBANKS folder with HGPAKtool
(https://github.com/monkeyman192/HGPAKtool), for instance:

    hgpaktool -U -f="*spacecraft/*.descriptor.mbin" -f="*weapons/multitool/*.descriptor.mbin" <PCBANKS folder>

and point this script at the folder it extracts them into:

    python3 tools/build_part_tables.py --game EXTRACTED

A scene that an option brings in without a descriptor among the extracted
files is taken to have no parts; the script says how many it met.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

OUT_DEFAULT = Path(__file__).resolve().parent.parent / "src" / "core" / "data" / "part-tables.json"

# The models whose parts the site shows, by the key the code uses for them, and their scenes.
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
}

# --- Reading a descriptor (.MBIN) ---
#
# An .MBIN file is a 0x20-byte header, then the template's data as it lies in
# memory, with every pointer stored as an offset from where the pointer is.
# Layouts as in MBINCompiler (libMBIN) and NMS.py.

MAGIC = 0xCCCCCCCCCCCCCCCC
MBIN_VERSION = 3300
DESCRIPTOR_LIST_HASH = 0x4026294F  # cTkModelDescriptorList
HEADER_SIZE = 0x20
ARRAY_FLAGS = 0xAAAAAA01  # cTkDynamicArray: 8-byte offset, 4-byte count, these flags
LINK_MARKER = 0xEEEEEE01  # an NMSTemplate link: 8-byte offset, 4-byte template name hash, this marker
LIST_SIZE = 0x20  # cTkResourceDescriptorList: Descriptors (array), TypeId (0x10 chars)
DATA_SIZE = 0xC8  # cTkResourceDescriptorData: Id (0x20 chars), Children, ReferencePaths, Chance, Name (0x80 chars)


class DescriptorError(ValueError):
    pass


class Descriptor:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        magic, version, _, name_hash = struct.unpack_from("<QHHI", self.data, 0)
        if magic != MAGIC or version != MBIN_VERSION or name_hash != DESCRIPTOR_LIST_HASH:
            raise DescriptorError(f"{path}: not a model descriptor this script can read")

    def text(self, at: int, size: int) -> str:
        return self.data[at : at + size].split(b"\0", 1)[0].decode("ascii")

    def array(self, at: int, size: int) -> list[int]:
        """Where each element of the cTkDynamicArray at ``at`` lies."""
        offset, count, flags = struct.unpack_from("<QII", self.data, at)
        if flags != ARRAY_FLAGS:
            raise DescriptorError(f"{self.path}: no array at {at:#x}")
        return [at + offset + i * size for i in range(count)]

    def lists(self, at: int) -> list[dict]:
        """The cTkModelDescriptorList at ``at``: its lists of options."""
        return [
            {"type": self.text(item + 0x10, 0x10), "options": [self.option(o) for o in self.array(item, DATA_SIZE)]}
            for item in self.array(at, LIST_SIZE)
        ]

    def option(self, at: int) -> dict:
        children = []
        for link in self.array(at + 0x20, 0x10):
            offset, name_hash, marker = struct.unpack_from("<QII", self.data, link)
            if marker != LINK_MARKER or name_hash != DESCRIPTOR_LIST_HASH:
                raise DescriptorError(f"{self.path}: child at {link:#x} isn't a descriptor list")
            children.extend(self.lists(link + offset))
        refs = []
        for item in self.array(at + 0x30, 0x10):
            # A VariableSizeString: laid out like an array of its characters, the last one a zero.
            offset, count, flags = struct.unpack_from("<QII", self.data, item)
            if flags != ARRAY_FLAGS:
                raise DescriptorError(f"{self.path}: no path at {item:#x}")
            refs.append(self.text(item + offset, count))
        return {
            "id": self.text(at, 0x20),
            "name": self.text(at + 0x44, 0x80),
            "chance": struct.unpack_from("<f", self.data, at + 0x40)[0],
            "children": children,
            "refs": refs,
        }


# --- The table ---

NORMAL, RARE, NEVER = 0, 1, 2


def weight_class(name: str) -> int:
    """What an option's name says about how often it's picked: one whose name has xRARE in it is rare, one
    with xNEVER is never picked. Case matters: the game's lists have a _SubWings_ContxRare, which it picks as
    often as the options next to it."""
    if "xNEVER" in name:
        return NEVER
    if "xRARE" in name:
        return RARE
    return NORMAL


# A part's level-of-detail copy carries a suffix, which the game drops from the ID it lists.
LOD_SUFFIX = re.compile(r"LOD\d+$")


def descriptor_path(scene: str) -> str:
    """The descriptor of a scene: FOO.SCENE.MBIN -> FOO.DESCRIPTOR.MBIN (a few paths carry a {1} suffix)."""
    scene = re.sub(r"\{\d+\}$", "", scene.upper())
    if not scene.endswith(".SCENE.MBIN"):
        raise DescriptorError(f"not a scene: {scene}")
    return scene[: -len(".SCENE.MBIN")] + ".DESCRIPTOR.MBIN"


class Builder:
    def __init__(self, game: Path):
        # The extracted files by their path in the game, upper-cased: HGPAKtool writes them lower-case by default.
        self.files = {p.relative_to(game).as_posix().upper(): p for p in game.rglob("*") if p.is_file()}
        self.trees: list[list] = []
        self.index: dict[str, int] = {}
        self.missing: set[str] = set()

    def tree(self, scene: str) -> int:
        """The index in ``trees`` of the scene's descriptor, or -1 if there's none."""
        path = descriptor_path(scene)
        if path in self.index:
            return self.index[path]
        if path not in self.files:
            self.missing.add(path)
            return -1
        self.index[path] = len(self.trees)
        self.trees.append([])  # reserve the index: a descriptor could bring in a scene that brings it in again
        d = Descriptor(self.files[path])
        self.trees[self.index[path]] = self.convert(d.lists(HEADER_SIZE))
        return self.index[path]

    def convert(self, lists: list[dict]) -> list:
        out = []
        for lst in lists:
            options = []
            for o in lst["options"]:
                if o["chance"]:
                    raise DescriptorError(f"{o['id']}: a Chance of {o['chance']}; picking doesn't model it")
                refs = [self.tree(r) for r in o["refs"]]
                children = self.convert(o["children"]) if o["children"] else None
                entry: list = [o["id"], weight_class(o["name"]), refs, children]
                while len(entry) > 1 and entry[-1] in (None, [], NORMAL):
                    entry.pop()
                options.append(entry[0] if len(entry) == 1 else entry)
            listed = [LOD_SUFFIX.sub("", o["id"]) for o in lst["options"]]
            if len(set(listed)) < len(listed):
                # Several detail levels of one part as options of one list, as a living ship has: how the game
                # picks among those isn't modeled.
                raise DescriptorError(f"{lst['type']}: options that are the same part: {listed}")
            out.append([lst["type"], options])
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", required=True, type=Path, help="folder HGPAKtool extracted the descriptors into")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    builder = Builder(args.game)
    models = {}
    for key, scene in MODELS.items():
        index = builder.tree(scene)
        if index < 0:
            print(f"No descriptor for {key} ({descriptor_path(scene)}) in {args.game}", file=sys.stderr)
            return 1
        models[key] = index

    about = (
        "Derived from the game's model descriptors by tools/build_part_tables.py. Each tree is a model's lists of "
        "options, [type ID, options]; an option is its ID as the descriptor has it, or [ID, weight class (0 normal, "
        "1 rare, 2 never), the scenes it brings in (the index of their tree, or -1 for a scene without parts), its "
        "child lists]."
    )

    def compact(value) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)

    # One tree per line, so that a change to one model shows as a change to its line.
    lines = [
        "{",
        f'"about":{compact(about)},',
        f'"models":{compact(models)},',
        '"trees":[',
        ",\n".join(compact(tree) for tree in builder.trees),
        "]}",
    ]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.loads(args.out.read_text(encoding="utf-8"))  # still valid JSON
    print(
        f"Wrote {args.out}: {len(models)} models from {len(builder.trees)} descriptors; "
        f"{len(builder.missing)} scenes they bring in have no descriptor here."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
