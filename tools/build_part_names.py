#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builds src/core/data/part-names.json from the game's Starship Fabricator tables.

The game names the parts of the ships a player can build at a space station's Starship Fabricator: fighters,
haulers, explorers and solars (its tables have shuttles too, switched off and unnamed). Its modular
customisation table (cGcModularCustomisationDataTable) gives each of those ship types its slots (fuselage or
cockpit, wings, thruster, sail, and the reactor, which isn't a part) and the components a slot takes. A
component is an item, named in the game's product tables, and descriptor groups
(cGcCustomisationDescriptorGroups): each group a set of the part IDs a ship's descriptor lists, and the
component's rule for its groups, all of them or any one. Salvaging a ship at Starship Outfitting gives its
components.

This script keeps each ship type's slots that hold parts, each with its components: the component's name,
in the game's English as its developers spell it, its rule, and its groups' part IDs, upper-cased as the
parts tables have them, less those the ship type's descriptors don't have (see build_part_tables.py, which
must have built src/core/data/part-tables.json first). tools/captures/part_names_model.py and
src/core/partnames.ts name a ship's parts from the result.

Some of the Fabricator's explorer parts are ones the game's generator never picks (xNEVER), and so never
fit a generated explorer as they are. This script names them as the generated parts they look like:

- The Fabricator builds an explorer's right wing from copies of the generator's right-wing scenes, which let
  its subwings differ from the left wing's. A copy has the original's nodes, with the same mesh ranges, and
  its materials, byte for byte, but for the names of the subwings (_SubWingR_A for _SubWingL_A, and so on).
  A part that brings in such a copy stands for the generator's part that brings in the original, in the
  same list (LOOKALIKES).
- In a list whose options the generator never picks, it picks nothing; an option of such a list named
  NULL, which brings in nothing, stands for that, and isn't required.

And it adds one rule the tables don't say. About half the explorers the game generates have a matched pair
of wings: their descriptor picks _WINGS_SYM (or _WINGS_SYM1), and one wing for both sides, where an explorer
built at the Fabricator has _WINGS_ASYM (_WINGS_ASYM1) and a wing for each side, which may be the same one.
Such an explorer is named as the Fabricator's explorer with the same wing on both sides: as if it had
_WINGS_ASYM (_WINGS_ASYM1), its right wing its left one (PAIRS).

The tables are the game's own, which this repository doesn't hold. Extract them from the game's PCBANKS
folder with HGPAKtool (https://github.com/monkeyman192/HGPAKtool), for instance:

    hgpaktool -U -f="metadata/gamestate/playerdata/*customisation*" -f="metadata/reality/tables/*product*" \\
        -f="language/*english.mbin" <PCBANKS folder>

and point this script at the folder it extracts them into:

    python3 tools/build_part_names.py --game EXTRACTED
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

from build_paint_tables import Files, TableError, array, text
from build_part_tables import ARRAY_FLAGS, HEADER_SIZE, MAGIC, MBIN_VERSION

OUT_DEFAULT = Path(__file__).resolve().parent.parent / "src" / "core" / "data" / "part-names.json"

MODULAR_TABLE = "METADATA/GAMESTATE/PLAYERDATA/MODULARCUSTOMISATIONDATATABLE.MBIN"
DESCRIPTOR_GROUPS = "METADATA/GAMESTATE/PLAYERDATA/CHARACTERCUSTOMISATIONDESCRIPTORGROUPSDATA.MBIN"
PRODUCT_TABLES = re.compile(r"METADATA/REALITY/TABLES/[^/]*PRODUCT[^/]*\.MBIN")
# The game's English, as its developers spell it; US English is a translation of it, in *_USENGLISH.MBIN.
ENGLISH = re.compile(r"LANGUAGE/[^/]*_ENGLISH\.MBIN")

MODULAR_TABLE_HASH = 0x54887B8D  # cGcModularCustomisationDataTable
DESCRIPTOR_GROUPS_HASH = 0xF28D85CB  # cGcCustomisationDescriptorGroups
PRODUCT_TABLE_HASH = 0x06EDC332  # cGcProductTable
LOCALISATION_HASH = 0xF8DBEB64  # cTkLocalisationTable

# Layouts as in NMS.py (nmspy/data/exported_types.py).
CONFIG_COUNT = 12  # cGcModularCustomisationConfig, one for each cGcModularCustomisationResourceType
CONFIG_SIZE = 0x290  # BaseResource (cGcExactResource) at 0x180, Slots at 0x250, IsEnabled at 0x280
SLOT_SIZE = 0x128  # cGcModularCustomisationSlotConfig: SlotID at 0xC0, SlottableItems at 0xD0
ITEM_SIZE = 0x40  # cGcModularCustomisationSlotItemData: groups at 0, ItemID at 0x10, salvage rule at 0x34
GROUP_SET_SIZE = 0x38  # cGcCustomisationDescriptorGroupSet: DescriptorGroups at 0
GROUP_SIZE = 0x108  # cGcCustomisationDescriptorGroup: Descriptors at 0x40, GroupID at 0x50
PRODUCT_SIZE = 0x300  # cGcProductData: ID at 0x150, NameLower at 0x270
ENTRY_SIZE = 0x130  # cTkLocalisationEntry: Id at 0, English at 0x40

# The ship types the site names parts of, by the scene the Fabricator builds them from, and the key the
# parts tables have for it.
MODELS = {
    "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN": "FIGHTER_PROC",
    "MODELS/COMMON/SPACECRAFT/DROPSHIPS/DROPSHIP_PROC.SCENE.MBIN": "DROPSHIP_PROC",
    "MODELS/COMMON/SPACECRAFT/SCIENTIFIC/SCIENTIFIC_PROC.SCENE.MBIN": "SCIENTIFIC_PROC",
    "MODELS/COMMON/SPACECRAFT/SAILSHIP/SAILSHIP_PROC.SCENE.MBIN": "SAILSHIP_PROC",
}
# The explorer's wing slots, by slot ID: the sides the site tells apart.
SIDES = {"SCI_L_WING": "left", "SCI_R_WING": "right"}
# A matched pair of wings, and what an explorer built at the Fabricator has instead (see above).
PAIRS = {"SCIENTIFIC_PROC": [["_WINGS_SYM", "_WINGS_ASYM"], ["_WINGS_SYM1", "_WINGS_ASYM1"]]}
# The Fabricator's explorer parts that bring in copies of the generator's right-wing scenes, and the
# generator's parts that bring in the originals (see above): WINGSBRIGHT_XNEVER.SCENE.MBIN for
# WINGSBRIGHT.SCENE.MBIN, SUBWINGSA_RIGHTXNEVER.SCENE.MBIN for SUBWINGSA_RIGHT.SCENE.MBIN, and so on.
LOOKALIKES = {
    "SCIENTIFIC_PROC": {
        "_WINGSR_B5XNEVER": "_WINGSR_B4",
        "_WINGSR_D4XNEVER": "_WINGSR_D4",
        "_WINGSR_H6XNEVER": "_WINGSR_H4",
        "_WINGSR_K3XNEVER": "_WINGSR_K3",
        "_WINGSRIGHT_B6XNEVER": "_WINGSRIGHT_B5",
        "_WINGSRIGHT_D5XNEVER": "_WINGSRIGHT_D5",
        "_WINGSRIGHT_H7XNEVER": "_WINGSRIGHT_H5",
        "_WINGSRIGHT_K4XNEVER": "_WINGSRIGHT_K4",
        "_SUBWINGR_AXNEVER": "_SUBWINGL_A",
        "_SUBWINGR_BXNEVER": "_SUBWINGL_B",
        "_SUBWINGR_CXNEVER": "_SUBWINGL_C",
        "_SUBWINGR_DXNEVER": "_SUBWINGL_D",
    }
}
PART_TABLES = OUT_DEFAULT.parent / "part-tables.json"
NEVER = 2  # the weight class of an option the generator never picks, in the parts tables


def options(tables: dict, model: str) -> tuple[dict[str, int], set[str]]:
    """Every option ``model``'s descriptors offer, by ID, with its weight class (0 normal, 1 rare, 2 never),
    and the options named NULL of the lists whose every option is never picked."""
    found: dict[str, int] = {}
    empty: set[str] = set()
    seen: set[int] = set()

    def walk(lists: list) -> None:
        for _type, opts in lists:
            unpacked = [o if isinstance(o, list) else [o] for o in opts]
            if all(len(o) > 1 and o[1] == NEVER for o in unpacked):
                empty.update(re.sub(r"LOD\d+$", "", o[0]) for o in unpacked if "NULL" in o[0])
            for o in unpacked:
                part = re.sub(r"LOD\d+$", "", o[0])
                found[part] = min(found.get(part, NEVER), o[1] if len(o) > 1 else 0)
                if len(o) > 3 and o[3]:
                    walk(o[3])
                for ref in o[2] if len(o) > 2 and o[2] else []:
                    if ref >= 0 and ref not in seen:
                        seen.add(ref)
                        walk(tables["trees"][ref])

    walk(tables["trees"][tables["models"][model]])
    return found, empty


def read(files: Files, path: str, template_hash: int) -> bytes:
    if not files.has(path):
        raise TableError(f"no {path}")
    return files.read(path, template_hash)


def string(data: bytes, at: int) -> str:
    """A VariableSizeString: laid out like an array of its characters, the last one a zero."""
    offset, count, flags = struct.unpack_from("<QII", data, at)
    if not count:
        return ""
    if flags != ARRAY_FLAGS:
        raise TableError(f"no string at {at:#x}")
    return data[at + offset : at + offset + count].split(b"\0", 1)[0].decode("utf-8")


def descriptor_groups(data: bytes) -> dict[str, list[str]]:
    """Each descriptor group's part IDs, upper-cased, by group ID."""
    groups: dict[str, list[str]] = {}
    for s in array(data, HEADER_SIZE + 0x30, GROUP_SET_SIZE):
        for g in array(data, s, GROUP_SIZE):
            group = text(data, g + 0x50, 0x10)
            if group in groups:
                raise TableError(f"descriptor group {group} twice")
            groups[group] = [text(data, d, 0x20).upper() for d in array(data, g + 0x40, 0x20)]
    return groups


def product_names(files: Files) -> dict[str, str]:
    """Each product's lower-case name (its text ID, NameLower), by product ID."""
    names: dict[str, str] = {}
    for path in sorted(p for p in files.paths if PRODUCT_TABLES.fullmatch(p)):
        data = files.paths[path].read_bytes()
        magic, version, _, name_hash = struct.unpack_from("<QHHI", data, 0)
        if (magic, version, name_hash) != (MAGIC, MBIN_VERSION, PRODUCT_TABLE_HASH):
            continue  # another kind of table, such as the procedural products'
        for p in array(data, HEADER_SIZE, PRODUCT_SIZE):
            product, name = text(data, p + 0x150, 0x10), text(data, p + 0x270, 0x80)
            if names.setdefault(product, name) != name:
                raise TableError(f"product {product} named both {names[product]} and {name}")
    return names


def english(files: Files, wanted: set[str]) -> dict[str, str]:
    """The game's English for each text ID in ``wanted`` that it has."""
    found: dict[str, str] = {}
    paths = sorted(p for p in files.paths if ENGLISH.fullmatch(p))
    if not paths:
        raise TableError("no LANGUAGE/*_ENGLISH.MBIN")
    for path in paths:
        data = files.read(path, LOCALISATION_HASH)
        for e in array(data, HEADER_SIZE, ENTRY_SIZE):
            # Read leniently: a few of the game's text IDs aren't ASCII, and none of those is wanted.
            key = data[e : e + 0x20].partition(b"\0")[0].decode("utf-8", "replace")
            if key in wanted:
                value = string(data, e + 0x40)
                if found.setdefault(key, value) != value:
                    raise TableError(f"{key} is both {found[key]!r} and {value!r}")
    return found


def configs(data: bytes) -> dict[str, list[tuple[str, list[tuple[str, int, list[str]]]]]]:
    """The Fabricator's slots of each ship type the site names parts of, by model: each slot's ID and its
    components, each its item, its salvage rule (0 all groups, 1 any one) and its descriptor groups."""
    out = {}
    for i in range(CONFIG_COUNT):
        c = HEADER_SIZE + i * CONFIG_SIZE
        model = MODELS.get(string(data, c + 0x180).upper())
        if model is None:
            continue
        if not data[c + 0x280]:
            raise TableError(f"the Fabricator has {model} switched off")
        slots = []
        for s in array(data, c + 0x250, SLOT_SIZE):
            items = []
            for it in array(data, s + 0xD0, ITEM_SIZE):
                rule = struct.unpack_from("<I", data, it + 0x34)[0]
                if rule not in (0, 1):
                    raise TableError(f"{model}: a salvage rule of {rule}")
                items.append((text(data, it + 0x10, 0x10), rule, [text(data, g, 0x10) for g in array(data, it, 0x10)]))
            slots.append((text(data, s + 0xC0, 0x10), items))
        out[model] = slots
    if set(out) != set(MODELS.values()):
        raise TableError(f"the Fabricator has no {', '.join(sorted(set(MODELS.values()) - set(out)))}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--game", required=True, type=Path, action="append", help="folder HGPAKtool extracted the files into"
    )
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()

    files = Files(args.game)
    part_tables = json.loads(PART_TABLES.read_text(encoding="utf-8"))
    try:
        slots_of = configs(read(files, MODULAR_TABLE, MODULAR_TABLE_HASH))
        groups = descriptor_groups(read(files, DESCRIPTOR_GROUPS, DESCRIPTOR_GROUPS_HASH))
        products = product_names(files)
        items = {item for slots in slots_of.values() for _, its in slots for item, _, _ in its}
        texts = english(files, {products[i] for i in items if i in products})

        models: dict[str, list] = {}
        unnamed: list[str] = []
        for model, slots in slots_of.items():
            offered, empty = options(part_tables, model)
            lookalikes = LOOKALIKES.get(model, {})
            for copy, original in lookalikes.items():
                if offered.get(copy) != NEVER or offered.get(original, NEVER) == NEVER:
                    raise TableError(f"{model}: {copy} no longer a copy the generator never picks of {original}")

            def parts(group: list[str]) -> list[str]:
                """The group's part IDs, a copy's as its original's, less empty ones and those the descriptors
                don't offer."""
                out: list[str] = []
                for part in (lookalikes.get(p, p) for p in group):
                    if part in offered and part not in empty and part not in out:
                        out.append(part)
                return out

            out = []
            for slot, its in slots:
                if not any(gs for _, _, gs in its):
                    continue  # the reactor: no parts, only the ship's class
                components = []
                for item, rule, gs in its:
                    missing = [g for g in gs if g not in groups]
                    if not gs or missing:
                        raise TableError(f"{model} {slot} {item}: no descriptor group {', '.join(missing) or ''}")
                    # A component without a name in the game still takes its parts from the others.
                    name = texts.get(products.get(item, ""), "")
                    if not name:
                        unnamed.append(f"{model} {slot} {item}")
                    components.append([name, rule, [parts(groups[g]) for g in gs]])
                out.append([SIDES.get(slot, ""), components])
            models[model] = out
        found = {slot for slots in slots_of.values() for slot, _ in slots}
        if not set(SIDES) <= found:
            raise TableError(f"no slot {', '.join(sorted(set(SIDES) - found))}")
    except TableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    about = (
        "Derived from the game's Starship Fabricator tables by tools/build_part_names.py. For each ship type, its "
        "slots that hold parts, each [side ('left', 'right' or none), components], a component [its name in the "
        "game's English ('' for none), 0 if all its groups must fit or 1 if any one, its groups: each a list "
        "of part IDs, those of the explorer's copied parts as the originals', empty options and those the "
        "descriptors don't offer left out]. Pairs: an explorer with the first part of a pair has a matched pair "
        "of wings, and is named as if it had the second, its right wing its left one."
    )

    def compact(value) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    # One slot per line, so that a change to one shows as a change to its line.
    lines = ["{", f'"about":{compact(about)},', f'"pairs":{compact(PAIRS)},', '"models":{']
    for k, (model, slots) in enumerate(models.items()):
        lines.append(f'"{model}":[')
        lines.append(",\n".join(compact(slot) for slot in slots))
        lines.append("]" + ("," if k + 1 < len(models) else ""))
    lines.append("}}")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.loads(args.out.read_text(encoding="utf-8"))  # still valid JSON
    count = sum(len(c) for slots in models.values() for _, c in slots)
    print(f"Wrote {args.out}: {count} components of {len(models)} ship types, {len(unnamed)} without a name:")
    for u in unnamed:
        print(f"  {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
