#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pictures of the parts of the game's procedural ships and multi-tools, one for each part ID, drawn from the
game's own scenes and geometry: for working out what each ID looks like.

For each model (FIGHTER_PROC, SHUTTLE_PROC, MULTITOOL, ...), it writes into the output folder:

- <MODEL>-parts-NN.png: every part ID the model's tables offer (src/core/data/part-tables.json), in the tables'
  order, each three times: in orange over the rest of a whole model built around it, in gray (from a made-up
  seed, every list on the way to the part picking the option that leads to it); then alone, from the front left
  and from the back right, the left one only of a pair either side of the middle. A part with no geometry of its
  own is drawn with the parts it brings; one with none of those either, or that no model built around it has, is
  listed on the last sheet.
- <MODEL>-ships-NN.png: whole models built from made-up seeds as the game builds them, each part in its own
  color, with a key of the part IDs.
- <MODEL>-parts.json: for each part ID it drew, the scenes it brings in and the size and middle of what's drawn
  of it, in the model's own units (+X its left, +Y up, +Z its front); no geometry.

It reads the scenes and geometry as HGPAKtool extracts them from the game's PCBANKS folder:

    hgpaktool -U -f="*spacecraft/*.scene.mbin" -f="*spacecraft/*.geometry*" \\
        -f="*weapons/multitool/*.scene.mbin" -f="*weapons/multitool/*.geometry*" <the game's PCBANKS folder>

It needs numpy and Pillow (pip install numpy pillow). From the repository's root:

    python3 tools/render_parts.py --game EXTRACTED --model SHUTTLE_PROC
    python3 tools/render_parts.py --game EXTRACTED          # every model

The pictures are of the game's own models: like the game's files, they don't go in the repository.
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import os
import random
import struct
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent / "captures"))
import parts_model  # noqa: E402  (how the game picks a model's parts)
from game_rng import Stream, mix  # noqa: E402

MODELS = {  # each model of the tables, by the scene it's built from
    "FIGHTER_PROC": "MODELS/COMMON/SPACECRAFT/FIGHTERS/FIGHTER_PROC.SCENE.MBIN",
    "DROPSHIP_PROC": "MODELS/COMMON/SPACECRAFT/DROPSHIPS/DROPSHIP_PROC.SCENE.MBIN",
    "SCIENTIFIC_PROC": "MODELS/COMMON/SPACECRAFT/SCIENTIFIC/SCIENTIFIC_PROC.SCENE.MBIN",
    "SHUTTLE_PROC": "MODELS/COMMON/SPACECRAFT/SHUTTLE/SHUTTLE_PROC.SCENE.MBIN",
    "SAILSHIP_PROC": "MODELS/COMMON/SPACECRAFT/SAILSHIP/SAILSHIP_PROC.SCENE.MBIN",
    "S-CLASS_PROC": "MODELS/COMMON/SPACECRAFT/S-CLASS/S-CLASS_PROC.SCENE.MBIN",
    "SENTINELSHIP_PROC": "MODELS/COMMON/SPACECRAFT/SENTINELSHIP/SENTINELSHIP_PROC.SCENE.MBIN",
    "FREIGHTER_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/FREIGHTER_PROC.SCENE.MBIN",
    "CAPITALFREIGHTER_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/CAPITALFREIGHTER_PROC.SCENE.MBIN",
    "FREIGHTERSMALL_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/FREIGHTERSMALL_PROC.SCENE.MBIN",
    "FREIGHTERTINY_PROC": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/FREIGHTERTINY_PROC.SCENE.MBIN",
    "POLICEFREIGHTER": "MODELS/COMMON/SPACECRAFT/POLICE/POLICEFREIGHTER.SCENE.MBIN",
    "PIRATEFREIGHTER": "MODELS/COMMON/SPACECRAFT/INDUSTRIAL/PIRATEFREIGHTER.SCENE.MBIN",
    "MULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/MULTITOOL.SCENE.MBIN",
    "ROYALMULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/ROYALMULTITOOL.SCENE.MBIN",
    "SENTINELMULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/SENTINELMULTITOOL.SCENE.MBIN",
    "ATLASMULTITOOL": "MODELS/COMMON/WEAPONS/MULTITOOL/ATLASMULTITOOL.SCENE.MBIN",
}

HEADER = 0x20  # an MBIN's header, before its data
ARRAY_FLAGS = (0xAAAAAA01, 0x101)  # how scenes, and geometry files, mark an array
GL_HALF_FLOAT, GL_FLOAT = 0x140B, 0x1406  # the component types of a vertex layout
# Scenes inside a model that aren't parts of it: a cockpit's interior.
SKIPPED_SCENES = ("INTERIOR",)
# Materials of effects rather than solid parts: engine jets and glows, scan planes.
EFFECTS = ("ENGINEJET", "GLOW", "SCANPLANE", "TRAIL", "FLAME")
MAX_DEPTH = 60
ATTEMPTS = 40  # seeds to try for a ship with a part on it

HIGHLIGHT = np.array([0.95, 0.45, 0.1])  # orange
GRAY = np.array([0.8, 0.8, 0.83])
LIGHT = np.array([0.3, 0.8, 0.5]) / np.linalg.norm([0.3, 0.8, 0.5])


class FormatError(ValueError):
    pass


# --- Reading the game's files ---


class Files:
    """The extracted files by their path in the game (from MODELS/ on, upper-cased, with / for separators)."""

    def __init__(self, roots: list[Path]):
        self.paths: dict[str, Path] = {}
        for root in roots:
            for dirpath, _, names in os.walk(root):
                for name in names:
                    path = Path(dirpath) / name
                    key = path.relative_to(root).as_posix().upper()
                    at = key.find("MODELS/")
                    self.paths.setdefault(key[at:] if at >= 0 else key, path)

    def read(self, game_path: str) -> bytes | None:
        key = game_path.replace("\\", "/").upper()
        path = self.paths.get(key) or self.paths.get(key + ".PC")
        return path.read_bytes() if path else None


def array(data: bytes, at: int, size: int) -> list[int]:
    """Where each item of the array at ``at`` is, for items of ``size`` bytes."""
    offset, count, flags = struct.unpack_from("<QII", data, at)
    if count and flags not in ARRAY_FLAGS:
        raise FormatError(f"no array at {at:#x}")
    return [at + offset + i * size for i in range(count)]


def text(data: bytes, at: int, size: int) -> str:
    return data[at : at + size].split(b"\0", 1)[0].decode("utf-8", "replace")


def vstring(data: bytes, at: int) -> str:
    offset, count, flags = struct.unpack_from("<QII", data, at)
    if not count:
        return ""
    if flags not in ARRAY_FLAGS:
        raise FormatError(f"no string at {at:#x}")
    return data[at + offset : at + offset + count].split(b"\0", 1)[0].decode("utf-8", "replace")


def scene_node(data: bytes, at: int) -> dict:
    """A cTkSceneNodeData: name, type, attributes, transform (rotation in degrees, scale, translation), children."""
    attributes: dict[str, str] = {}
    for a in array(data, at, 0x20):
        attributes.setdefault(text(data, a, 0x10), vstring(data, a + 0x10))
    rot, scale, trans = (struct.unpack_from("<3f", data, at + 0x50 + k) for k in (0, 0xC, 0x18))
    return {
        "name": vstring(data, at + 0x30),
        "type": text(data, at + 0x40, 0x10),
        "attributes": attributes,
        "rot": rot,
        "scale": scale,
        "trans": trans,
        "children": [scene_node(data, c) for c in array(data, at + 0x10, 0x80)],
    }


def matrix(node: dict) -> np.ndarray:
    """The node's transform as a 4x4 matrix: scale, then rotation about X, Y and Z, then translation."""
    rx, ry, rz = (math.radians(a) for a in node["rot"])
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = mz @ my @ mx @ np.diag(node["scale"])
    m[:3, 3] = node["trans"]
    return m


class Geometry:
    """A scene's cTkGeometryData (.GEOMETRY.MBIN.PC) and cTkGeometryStreamData (.GEOMETRY.DATA.MBIN.PC): a stream
    for each mesh, its vertex data then its indices, and its positions apart."""

    def __init__(self, meta: bytes, stream: bytes | None):
        self.meta, self.stream = meta, stream
        self.position_layout = self.layout(HEADER)
        (self.indices16,) = struct.unpack_from("<i", meta, HEADER + 0x158)
        self.by_hash: dict[int, dict] = {}
        self.by_name: dict[str, dict] = {}
        if stream is None:
            return
        for at in array(stream, HEADER, 0x48):  # cTkMeshData
            data_at, _ = self._bytes(at + 0x10)
            pos_at, pos_len = self._bytes(at + 0x20)
            mesh_hash, index_size, vertex_size, _ = struct.unpack_from("<QIII", stream, at + 0x30)
            mesh = {"data": data_at, "pos": (pos_at, pos_len), "isize": index_size, "vsize": vertex_size}
            self.by_hash[mesh_hash & 0xFFFFFFFF] = mesh
            self.by_name[vstring(stream, at).upper()] = mesh

    def _bytes(self, at: int) -> tuple[int, int]:
        offset, count, _ = struct.unpack_from("<QII", self.stream, at)
        return at + offset, count

    def layout(self, at: int) -> dict:
        elements = []
        for e in array(self.meta, at, 0xC):
            _instancing, gl_type = struct.unpack_from("<Ii", self.meta, e)
            _normalise, offset, semantic, size = struct.unpack_from("<4B", self.meta, e + 8)
            elements.append({"type": gl_type, "offset": offset, "semantic": semantic, "size": size})
        (stride,) = struct.unpack_from("<i", self.meta, at + 0x1C)
        return {"elements": elements, "stride": stride}

    def triangles(self, name: str, mesh_hash: int | None, count: int | None) -> np.ndarray | None:
        """The mesh's triangles, as (n, 3, 3) positions in its own space. ``count`` is how many indices its scene
        node draws (BATCHCOUNT), which with the size of its index data says how wide each is, 2 or 4 bytes, as
        NMSDK reads them; the geometry file's own flag is only for a mesh without one that fits."""
        mesh = self.by_hash.get(mesh_hash & 0xFFFFFFFF) if mesh_hash is not None else None
        mesh = mesh or self.by_name.get(name.upper())
        if mesh is None:
            return None
        layout = self.position_layout
        pos_at, pos_len = mesh["pos"]
        pos = positions(self.stream[pos_at : pos_at + pos_len], layout, pos_len // layout["stride"])
        size = mesh["isize"]
        if count and size // count in (2, 4):  # any padding after them is under a whole index
            width = size // count
        else:
            width = 2 if self.indices16 or size % 4 else 4
            count = size // width
        start = mesh["data"] + mesh["vsize"]
        data = self.stream[start : start + count * width]
        dtype = np.uint16 if width == 2 else np.uint32
        idx = np.frombuffer(data, dtype=dtype, count=len(data) // width).astype(np.int64)
        idx = idx[: len(idx) // 3 * 3].reshape(-1, 3)
        return pos[idx[(idx < len(pos)).all(1)]]


def positions(data: bytes, layout: dict, count: int) -> np.ndarray:
    """Each vertex's position (semantic 0) as float32, from interleaved vertex data."""
    e = next((e for e in layout["elements"] if e["semantic"] == 0), None)
    if e is None:
        raise FormatError("no positions in the layout")
    stride = layout["stride"]
    raw = np.frombuffer(data, dtype=np.uint8, count=count * stride).reshape(count, stride)[:, e["offset"] :]
    if e["type"] == GL_HALF_FLOAT:
        return np.ascontiguousarray(raw[:, : 2 * e["size"]]).view(np.float16).astype(np.float32)[:, :3]
    if e["type"] == GL_FLOAT:
        return np.ascontiguousarray(raw[:, : 4 * e["size"]]).view(np.float32)[:, :3]
    raise FormatError(f"positions of type {e['type']:#x}")


class Game:
    """The scenes and geometry of the extracted files, read as they're needed."""

    def __init__(self, roots: list[Path]):
        self.files = Files(roots)
        self.clear()

    def clear(self) -> None:
        self.scenes: dict[str, dict | None] = {}
        self.geometry: dict[str, Geometry | None] = {}
        self.missing: set[str] = set()  # the files asked for that weren't there
        self.unreadable: dict[str, str] = {}  # what couldn't be read, and why

    def scene(self, path: str) -> dict | None:
        key = path.replace("\\", "/").upper()
        key = key if key.endswith(".MBIN") else key + ".MBIN"
        if key not in self.scenes:
            data = self.files.read(key)
            self.scenes[key] = None
            if data is None:
                self.missing.add(key)
            else:
                try:
                    self.scenes[key] = scene_node(data, HEADER)
                except (FormatError, ValueError, struct.error, IndexError) as e:
                    self.unreadable[key] = str(e) or type(e).__name__
        return self.scenes[key]

    def triangles(self, scene_path: str, node: dict) -> np.ndarray | None:
        """A mesh node's triangles, from its scene's geometry."""
        root = self.scene(scene_path)
        path = root and root["attributes"].get("GEOMETRY")
        if not path:
            return None
        key = path.replace("\\", "/").upper()
        try:
            if key not in self.geometry:
                self.geometry[key] = None
                meta = self.files.read(key)
                stream_key = key.replace(".GEOMETRY.MBIN", ".GEOMETRY.DATA.MBIN")
                stream = self.files.read(stream_key)
                self.missing.update(k for k, data in ((key, meta), (stream_key, stream)) if data is None)
                self.geometry[key] = Geometry(meta, stream) if meta else None
            geometry = self.geometry[key]
            if geometry is None:
                return None
            attributes = node["attributes"]
            mesh_hash, count = attributes.get("HASH", ""), attributes.get("BATCHCOUNT", "")
            return geometry.triangles(
                node["name"], int(mesh_hash) if mesh_hash.isdigit() else None, int(count) if count.isdigit() else None
            )
        except (FormatError, ValueError, struct.error, IndexError) as e:
            self.unreadable[f"{key} {node['name']}"] = str(e) or type(e).__name__
            return None


def short(scene_path: str) -> str:
    """A scene's path without MODELS/COMMON/ and the like before the model's folder, nor .SCENE.MBIN."""
    p = scene_path.replace("\\", "/").upper().removesuffix(".MBIN").removesuffix(".SCENE")
    for prefix in ("MODELS/COMMON/SPACECRAFT/", "MODELS/COMMON/WEAPONS/", "MODELS/COMMON/"):
        p = p.removeprefix(prefix)
    return p


def model_triangles(
    game: Game, model: str, picked: set[str], options: set[str], chains: bool = False
) -> tuple[list[tuple], dict[str, list[str]]]:
    """The model's triangles, with LOD 0 meshes only, by the picked part they belong to (the nearest picked
    option above them; '' for none), and the scenes each picked part brings in. ``picked`` holds part IDs as the
    game lists them, ``options`` every option ID of the model's tables as its descriptors have them; a scene
    node that stands for an option that isn't picked (option_of()) is left out, with everything under it. With
    ``chains``, each batch is with every picked part above it, nearest last, instead."""
    out: list[tuple] = []
    brought: dict[str, list[str]] = {}

    def walk(path: str, node: dict, world: np.ndarray, base: np.ndarray, chain: tuple, jointed: bool, depth: int):
        option = option_of(node["name"], options)
        if option is not None:
            listed = parts_model.LOD_SUFFIX.sub("", option)
            if listed not in picked:
                return
            chain = (*chain, listed)
        owner = chain[-1] if chain else ""
        m = world @ matrix(node)
        if node["type"] == "MESH" and node["attributes"].get("LODLEVEL", "0") == "0" and not effect(node):
            t = game.triangles(path, node)
            if t is not None and len(t):
                # A mesh under a joint is skinned to it: its vertices are where they rest, in its scene's space.
                place = base if jointed else m
                pts = np.c_[t.reshape(-1, 3), np.ones(len(t) * 3)] @ place.T
                out.append((chain if chains else owner, pts[:, :3].reshape(-1, 3, 3)))
        if node["type"] == "REFERENCE" and depth < MAX_DEPTH:
            ref = node["attributes"].get("SCENEGRAPH", "")
            root = game.scene(ref) if ref and not any(s in ref.upper() for s in SKIPPED_SCENES) else None
            if root is not None:
                scenes = brought.setdefault(owner, [])
                if short(ref) not in scenes:
                    scenes.append(short(ref))
                for c in root["children"]:
                    walk(ref, c, m, m, chain, False, depth + 1)
        if depth < MAX_DEPTH:
            for c in node["children"]:
                walk(path, c, m, base, chain, jointed or node["type"] == "JOINT", depth + 1)

    root = game.scene(MODELS[model])
    if root is not None:
        walk(MODELS[model], root, np.eye(4), np.eye(4), (), False, 0)
    return out, brought


def option_of(name: str, options: set[str]) -> str | None:
    """The option ID a scene node stands for, if any: its name upper-cased, or else cut to 15 or 31 characters, as
    the IDs of a few long names are (_SClassShip_Royal is _SCLASSSHIP_ROY)."""
    name = name.upper()
    return next((key for key in (name, name[:15], name[:31]) if key in options), None)


def effect(node: dict) -> bool:
    material = node["attributes"].get("MATERIAL", "").upper().replace("\\", "/").rsplit("/", 1)[-1]
    return any(word in material for word in EFFECTS)


# --- Picking parts ---


def picked_with(model: str, seed: int, force: dict[int, str] | None = None) -> tuple[list[str], dict[str, str]]:
    """The parts the game picks for ``model`` with ``seed``, as parts_model.parts() has them, except that the
    lists ``force`` names (by the id() of their options in the tables) pick the option it gives them; and the part
    each part came with (the option whose child lists or scenes it was picked from; '' for the model's own)."""
    force = force or {}
    trees = parts_model.tables()["trees"]
    unpack = parts_model.unpack
    out: list[str] = []
    parent: dict[str, str] = {}

    def forced(lists: list) -> bool:
        return any(id(options) in force for _, options in lists)

    def walk(lists: list, stream: Stream, above: str) -> None:
        for _type_id, options in lists:
            if any(unpack(o)[0] in out for o in options):
                continue  # decided already
            chosen = parts_model._pick(stream, options)  # drawn even when forced, so later draws stay the same
            if id(options) in force:
                chosen = next(unpack(o) for o in options if unpack(o)[0] == force[id(options)])
            if chosen is None:
                continue
            part, _, refs, children = chosen
            listed = parts_model.LOD_SUFFIX.sub("", part)
            if listed not in out:
                out.append(listed)
                parent.setdefault(listed, above)
            if children and (not parts_model.never_only(children) or forced(children)):
                low, high = stream.word(), stream.word()
                walk(children, Stream(mix((high << 32) | low)), listed)
            for ref in refs:
                if ref >= 0 and parts_model.never_only(trees[ref]) and not forced(trees[ref]):
                    continue
                low, high = stream.word(), stream.word()
                if ref >= 0:
                    walk(trees[ref], Stream(mix((high << 32) | low)), listed)

    walk(trees[parts_model.tables()["models"][model]], Stream(seed), "")
    return out, parent


def offered(model: str) -> dict[str, tuple[str, int, int, dict[int, str]]]:
    """Every option the model's tables offer, in their order: the type ID of the first list that offers it, its
    weight class (0 normal, 1 rare, 2 never), how many lists offer it, and the picks that lead to it from the
    model's own lists, as picked_with() takes them."""
    t = parts_model.tables()
    found: dict[str, tuple[str, int, int, dict[int, str]]] = {}
    seen: set[int] = set()

    def walk(lists: list, above: tuple[tuple[int, str], ...]) -> None:
        for type_id, options in lists:
            for option in options:
                part, cls, refs, children = parts_model.unpack(option)
                path = (*above, (id(options), part))
                first = found.get(part)
                found[part] = (type_id, cls, 1, dict(path)) if first is None else (*first[:2], first[2] + 1, first[3])
                walk(children, path)
                for ref in refs:
                    if ref >= 0 and ref not in seen:
                        seen.add(ref)
                        walk(t["trees"][ref], path)

    walk(t["trees"][t["models"][model]], ())
    return found


# --- Drawing ---


def view(camera: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    """The (right, up) axes of a view from the given direction, with +Y up."""
    c = np.array(camera, float) / np.linalg.norm(camera)
    world_up = np.array([0.0, 1.0, 0.0]) if abs(c[1]) < 0.99 else np.array([0.0, 0.0, 1.0])
    right = np.cross(world_up, c)
    right /= np.linalg.norm(right)
    return right, np.cross(c, right)


VIEWS = {  # +Z is a model's front and +X its left
    "front left": view((1, 0.8, 1)),
    "back right": view((-1, 0.8, -1)),
    "left": view((1, 0, 0)),
}


def picture(
    tris: np.ndarray, colors: np.ndarray, view_name: str, size: int, on_top: np.ndarray | None = None
) -> Image.Image:
    """The triangles from one side, filling the picture, each flat-shaded in its color, the farthest drawn first;
    those ``on_top`` marks, if any, drawn after all the others, so they show through them."""
    img = Image.new("RGB", (size, size), "white")
    if not len(tris):
        return img
    right, up = VIEWS[view_name]
    toward = np.cross(right, up)  # toward the viewer
    flat = tris.reshape(-1, 3)
    u, v = flat @ right, flat @ up
    scale = (size - 8) / max(u.max() - u.min(), v.max() - v.min(), 1e-6)
    cu, cv = (u.max() + u.min()) / 2, (v.max() + v.min()) / 2
    px = ((u - cu) * scale + size / 2).reshape(-1, 3)
    py = (size / 2 - (v - cv) * scale).reshape(-1, 3)
    depth = (flat @ toward).reshape(-1, 3).mean(1)
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    keep = lengths > 1e-12
    shade = np.zeros(len(tris))
    shade[keep] = np.abs(normals[keep] @ LIGHT) / lengths[keep]
    fills = (colors * (0.35 + 0.65 * shade)[:, None] * 255).astype(int).tolist()
    order = np.argsort(depth, kind="stable")
    order = order[keep[order]]
    if on_top is not None:
        order = np.concatenate([order[~on_top[order]], order[on_top[order]]])
    corners = np.stack([px, py], axis=2).tolist()
    d = ImageDraw.Draw(img)
    for k in order.tolist():
        d.polygon([tuple(p) for p in corners[k]], fill=tuple(fills[k]))
    return img


def bounds_of(tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    flat = tris.reshape(-1, 3)
    return flat.min(0), flat.max(0)


def left_side(tris: np.ndarray) -> np.ndarray | None:
    """The left half of a part made of two mirror images either side of the middle, such as a pair of wings,
    or None for any other part."""
    x = tris[:, :, 0]
    left, right = (x > 0).all(1), (x < 0).all(1)
    if not left.any() or not right.any() or not (left | right).all():
        return None
    (llo, lhi), (rlo, rhi) = bounds_of(tris[left]), bounds_of(tris[right])
    mirrored_lo, mirrored_hi = np.array([-rhi[0], rlo[1], rlo[2]]), np.array([-rlo[0], rhi[1], rhi[2]])
    tolerance = 0.05 * (lhi - llo).max()
    if (abs(llo - mirrored_lo) > tolerance).any() or (abs(lhi - mirrored_hi) > tolerance).any():
        return None
    return tris[left]


def font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before 10.1
        return ImageFont.load_default()


def fit(d: ImageDraw.ImageDraw, label: str, width: int, f: ImageFont.ImageFont) -> str:
    """The label, cut short with an ellipsis to fit the width."""
    if d.textlength(label, font=f) <= width:
        return label
    while label and d.textlength(label + "…", font=f) > width:
        label = label[:-1]
    return label + "…"


def save_sheets(tiles: list[Image.Image], cols: int, rows: int, stem: Path) -> list[Path]:
    """The tiles, in order, on sheets of ``cols`` by ``rows``, saved as <stem>-01.png and on."""
    written = []
    per = cols * rows
    for k in range(0, len(tiles), per):
        chunk = tiles[k : k + per]
        w, h = chunk[0].size
        sheet = Image.new("RGB", (cols * w, ((len(chunk) + cols - 1) // cols) * h), "white")
        d = ImageDraw.Draw(sheet)
        for i, tile in enumerate(chunk):
            x, y = (i % cols) * w, (i // cols) * h
            sheet.paste(tile, (x, y))
            d.rectangle([x, y, x + w - 1, y + h - 1], outline=(190, 190, 190))
        path = stem.parent / f"{stem.name}-{k // per + 1:02d}.png"
        sheet.save(path, optimize=True)
        written.append(path)
    return written


# --- The sheets ---


def part_sheets(game: Game, model: str, out: Path, size: int) -> list[Path]:
    """<MODEL>-parts-NN.png and <MODEL>-parts.json."""
    options = {k.upper() for k in parts_model.reachable(model)}
    seed = random.Random(f"{model} parts").getrandbits(64)
    head, small = font(13), font(11)
    tiles: list[Image.Image] = []
    facts: dict[str, dict] = {}
    empty: list[str] = []
    for part, (type_id, cls, lists, force) in offered(model).items():
        listed = parts_model.LOD_SUFFIX.sub("", part)
        if listed in facts or listed in empty:
            continue
        # A part picked first from another list can keep the way to this one closed: then try other seeds.
        rnd = random.Random(f"{model} {part}")
        for attempt in range(ATTEMPTS):
            picked, parent = picked_with(model, seed if attempt == 0 else rnd.getrandbits(64), force)
            if listed in picked:
                break
        batches, brought = model_triangles(game, model, {p.upper() for p in picked}, options)

        def under(p: str) -> bool:
            while p:
                p = parent.get(p, "")
                if p == listed:
                    return True
            return False

        mine = {listed} if any(o == listed for o, _ in batches) else {o for o, _ in batches if under(o)}
        if listed not in picked or not mine:
            empty.append(listed)
            continue
        tris = np.concatenate([t for _, t in batches])
        own = np.concatenate([np.full(len(t), o in mine) for o, t in batches])
        colors = np.where(own[:, None], HIGHLIGHT, GRAY)
        alone = tris[own]
        lo, hi = bounds_of(alone)
        facts[listed] = (
            {
                "size": [round(float(v), 2) for v in hi - lo],
                "middle": [round(float(v), 2) for v in (hi + lo) / 2],
                "scenes": brought.get(listed, []),
            }
            | ({"with": sorted(mine)} if mine != {listed} else {})
            | ({"lists": lists} if lists > 1 else {})
        )

        tile = Image.new("RGB", (3 * size + 8, size + 34), "white")
        d = ImageDraw.Draw(tile)
        tag = {1: "  rare", 2: "  never picked"}.get(cls, "")
        d.text((4, 2), f"{listed}{tag}", fill=(0, 0, 0), font=head)
        note = f"in {type_id}" + (f" and {lists - 1} more lists" if lists > 1 else "")
        note += f", with {', '.join(sorted(mine - {listed}))}" if mine != {listed} else ""
        if facts[listed]["scenes"]:
            note += "; brings " + ", ".join(facts[listed]["scenes"])
        half = left_side(alone)
        if half is not None:  # a pair: the left one alone is bigger
            alone, note = half, f"{note}; alone, the left one of the pair"
        d.text((4, 18), fit(d, note, 3 * size, small), fill=(90, 90, 90), font=small)
        tile.paste(picture(tris, colors, "front left", size, on_top=own), (2, 32))
        alone_colors = np.repeat(HIGHLIGHT[None], len(alone), 0)
        for j, name in enumerate(("front left", "back right"), start=1):
            tile.paste(picture(alone, alone_colors, name, size), (2 + j * (size + 2), 32))
        tiles.append(tile)

    if empty:  # a last tile, listing the parts with nothing to draw
        tile = Image.new("RGB", (3 * size + 8, size + 34), "white")
        d = ImageDraw.Draw(tile)
        d.text((4, 2), "Nothing to draw", fill=(0, 0, 0), font=head)
        line, y = "", 20
        for name in empty:
            if d.textlength(f"{line}, {name}", font=small) > 3 * size and line:
                d.text((4, y), line, fill=(90, 90, 90), font=small)
                line, y = name, y + 14
            else:
                line = f"{line}, {name}" if line else name
        d.text((4, y), line, fill=(90, 90, 90), font=small)
        tiles.append(tile)

    (out / f"{model}-parts.json").write_text(
        json.dumps({"model": model, "parts": facts, "empty": empty}, separators=(",", ":")), encoding="utf-8"
    )
    return save_sheets(tiles, 2, 7, out / f"{model}-parts") + [out / f"{model}-parts.json"]


def part_color(part: str) -> np.ndarray:
    hue = int(hashlib.md5(part.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    return np.array(colorsys.hsv_to_rgb(hue, 0.55, 1.0)) if part else GRAY


def ship_sheets(game: Game, model: str, out: Path, count: int, size: int) -> list[Path]:
    """<MODEL>-ships-NN.png."""
    options = {k.upper() for k in parts_model.reachable(model)}
    rnd = random.Random(f"{model} ships")
    small = font(11)
    tiles = []
    for _ in range(count):
        seed = rnd.getrandbits(64)
        picked, _ = picked_with(model, seed)
        batches, _ = model_triangles(game, model, {p.upper() for p in picked}, options)
        tile = Image.new("RGB", (3 * size + 8, size + 76), "white")
        d = ImageDraw.Draw(tile)
        d.text((4, 2), f"{model} {seed:016X}", fill=(90, 90, 90), font=small)
        if batches:
            tris = np.concatenate([t for _, t in batches])
            colors = np.concatenate([np.repeat(part_color(o)[None], len(t), 0) for o, t in batches])
            for j, name in enumerate(("front left", "back right", "left")):
                tile.paste(picture(tris, colors, name, size), (2 + j * (size + 2), 18))
        x, y = 4, size + 22
        for part in dict.fromkeys(o for o, _ in batches if o):
            w = 16 + d.textlength(part, font=small)
            if x + w > 3 * size and x > 4:
                x, y = 4, y + 14
            d.rectangle([x, y + 2, x + 10, y + 12], fill=tuple(int(v * 255) for v in part_color(part)))
            d.text((x + 14, y), part, fill=(0, 0, 0), font=small)
            x += w + 10
        tiles.append(tile)
    return save_sheets(tiles, 2, 4, out / f"{model}-ships")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", required=True, type=Path, nargs="+", help="the folder(s) HGPAKtool extracted to")
    parser.add_argument("--model", action="append", choices=list(MODELS), help="a model (default: every one)")
    parser.add_argument("--out", type=Path, default=Path("renders"), help="where to write (default: renders)")
    parser.add_argument("--ships", type=int, default=8, help="whole models to draw of each (default: 8)")
    parser.add_argument("--size", type=int, default=170, help="each picture's width in pixels (default: 170)")
    args = parser.parse_args()

    game = Game(args.game)
    args.out.mkdir(parents=True, exist_ok=True)
    for model in args.model or list(MODELS):
        if game.scene(MODELS[model]) is None:
            print(f"{model}: no {MODELS[model]} in {', '.join(map(str, args.game))}", file=sys.stderr)
            game.clear()
            continue
        began = time.monotonic()
        written = part_sheets(game, model, args.out, args.size)
        written += ship_sheets(game, model, args.out, args.ships, 2 * args.size)
        print(f"{model}: {len(written)} files in {time.monotonic() - began:.0f} s")
        if game.missing:
            some = ", ".join(sorted(game.missing)[:3])
            print(f"  {len(game.missing)} files it brings in weren't there, so it's drawn without them: {some}")
        if game.unreadable:
            some = "; ".join(f"{what}: {why}" for what, why in sorted(game.unreadable.items())[:3])
            print(f"  {len(game.unreadable)} scenes or meshes couldn't be read, so it's drawn without them: {some}")
        game.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
