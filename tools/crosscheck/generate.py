#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Differential test data: runs nms_namegen over many addresses, one JSON per line.

tests/crosscheck.test.ts replays the file against the TypeScript port when
CROSSCHECK_FILE points at it. Unlike the 443 golden vectors, this covers
every planet digit, all 256 galaxies, and the system indices where the
generator branches (guide stars, black hole, Atlas Interface, the purple
window, the ends of the range). Each case also carries the ship pool that
tools/captures/ship_model.py predicts, which builds on nms_namegen, with
which planets have their two moons the other way round, whether its exotic
is a squid and which civilian ships the game makes solar; how many stars
tools/captures/star_model.py gives the system, and the color of each, from
nms_namegen's star type; the guild and the first run of multi-tools that
guild_model.py and multitool_model.py give it; the parts parts_model.py
picks for one model with the system's first ship seed, each model in turn,
case by case; the paint paint_model.py gives one model with that seed, its
palettes from the system's address or the seed as the model's are, each
model in turn too; and the names part_names_model.py gives the parts of a
fighter, hauler, explorer or solar with that seed, each in turn.

Usage:
    python3 tools/crosscheck/generate.py --namegen /path/to/nms_namegen --count 20000 > crosscheck.jsonl
"""

import argparse
import json
import random
import sys
from pathlib import Path

EDGE_SYSTEM_IDS = [
    0x000, 0x001, 0x002, 0x008, 0x009, 0x00A, 0x010, 0x077, 0x078, 0x079, 0x07A, 0x07B, 0x07C,
    0x0FF, 0x100, 0x2FF, 0x3E7, 0x3E8, 0x3E9, 0x3EA, 0x428, 0x429, 0x42A, 0x7FF, 0xFFE, 0xFFF,
]
EDGE_COORDS = [0x000, 0x001, 0x7FE, 0x7FF, 0x800, 0x801, 0xFFE, 0xFFF]
EDGE_Y = [0x00, 0x01, 0x7E, 0x7F, 0x80, 0x81, 0xFE, 0xFF]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--namegen", required=True, type=Path)
    parser.add_argument("--count", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()

    sys.path.insert(0, str(args.namegen.resolve()))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "captures"))
    import guild_model  # noqa: E402
    import multitool_model  # noqa: E402
    import paint_model  # noqa: E402
    import part_names_model  # noqa: E402
    import parts_model  # noqa: E402
    import ship_model  # noqa: E402
    import star_model  # noqa: E402
    from nms_namegen.planet import planetName  # noqa: E402
    from nms_namegen.region import regionName, voxelAttributes  # noqa: E402
    from nms_namegen.system import planetSeeds, systemAttributes, systemName  # noqa: E402

    rnd = random.Random(args.seed)

    def random_case():
        roll = rnd.random()
        planet = rnd.randrange(16)
        galaxy = rnd.randrange(256)
        x, z, y = rnd.randrange(0x1000), rnd.randrange(0x1000), rnd.randrange(0x100)
        system = rnd.randrange(0x1000)
        if roll < 0.25:
            system = rnd.choice(EDGE_SYSTEM_IDS)
        elif roll < 0.35:
            x, z, y = rnd.choice(EDGE_COORDS), rnd.choice(EDGE_COORDS), rnd.choice(EDGE_Y)
        elif roll < 0.45:
            # near the galactic center, where voxel attributes change shape
            x = (rnd.randrange(-12, 13)) & 0xFFF
            z = (rnd.randrange(-12, 13)) & 0xFFF
            y = (rnd.randrange(-12, 13)) & 0xFF
        elif roll < 0.6:
            system = rnd.randrange(1, 0x2FF)  # the range real systems mostly occupy
        code = (planet << 44) | (system << 32) | (y << 24) | (z << 12) | x
        return code, galaxy

    def guarded(fn, *a):
        try:
            return fn(*a)
        except Exception as exc:  # the port must fail on exactly the same inputs
            return f"ERR:{type(exc).__name__}"

    def ships(code, galaxy):
        """The predicted ship pool, compactly: enough to pin every seed (they are consecutive draws), the
        planets whose two moons are the other way round, and the slots of the civilian ships the game makes
        solar."""
        ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)
        system = ship_model.bodies(ua) or []
        prediction = ship_model.predict(ua)
        attributes = systemAttributes(code & 0x0FFFFFFFFFFF, galaxy)
        civilian = ship_model.civilian_types(
            ua, prediction.ships[:20], attributes["dominant_race"], attributes["pirate"]
        )
        return {
            "bodies": [[b.size, b.parent, b.prime] for b in system],
            "swapped": sorted(ship_model.swapped_moons(ua, system)),
            "start": prediction.start,
            "first": f"{prediction.ships[0]:016X}",
            "exotic": f"{prediction.ships[20]:016X}",
            "squid": ship_model.exotic_squid(prediction.ships[20]),
            "crash": f"{prediction.crash:016X}",
            "last": f"{prediction.ships[-1]:016X}",
            "solar": [slot for slot, kind in enumerate(civilian) if kind == "Solar"],
        }

    def paint(case: int, model: str, seed: int, ua: int) -> list:
        """One model's paint, compactly: each pass's layers as option:palette:alternative:color, the color
        as hex, empty for none and for a layer that isn't painted. The Sentinel ship with the hint POLICE
        every other time."""
        source = paint_model.palette_source(model)
        if source == paint_model.LEGACY:
            palettes = paint_model.legacy_palettes(seed)
        else:
            palettes = paint_model.palettes(ua if source == paint_model.SYSTEM else seed)
        parts = parts_model.parts(model, seed) if model in models else []
        hint = "POLICE" if model == "SENTINELSHIP_PROC" and case % 2 else ""

        def hex_color(layer) -> str:
            if not layer.painted or layer.color is None:
                return ""
            # Rounded half up, as JavaScript's Math.round does.
            return "".join(f"{int(min(1.0, max(0.0, c)) * 255 + 0.5):02x}" for c in layer.color)

        passes = paint_model.paint(model, parts, seed, palettes, hint)
        layers = [[f"{p.option}:{p.palette}:{p.alt}:{hex_color(p)}" for p in passes[k]] for k in sorted(passes)]
        return [model, hint, layers]

    models = parts_model.models()
    paint_models = paint_model.models()
    named_models = part_names_model.models()
    out = sys.stdout
    for case in range(args.count):
        code, galaxy = random_case()
        seeds = guarded(planetSeeds, code, galaxy)
        ua = (((code >> 32) & 0xFFF) << 40) | (galaxy << 32) | (code & 0xFFFFFFFF)  # the system's
        rec = {
            "code": f"{code:012X}",
            "galaxy": galaxy,
            "region": guarded(regionName, code, galaxy),
            "system": guarded(systemName, code, galaxy),
            "planet": guarded(planetName, code, galaxy),
            "sysattr": guarded(systemAttributes, code, galaxy),
            "voxel": guarded(voxelAttributes, code),
            "ships": guarded(ships, code, galaxy),
            # tools/captures/star_model.py's count, from the system's universal address
            "stars": star_model.stars(ua),
            "guild": guild_model.guild(ua),
            "multitools": [[name, f"{seed:016X}"] for name, seed in multitool_model.first_run(ua)],
        }
        if isinstance(rec["sysattr"], dict):
            # the color of each star, from nms_namegen's star type
            rec["suns"] = star_model.star_colors(rec["sysattr"]["star_type"], rec["stars"])
        if isinstance(rec["ships"], dict):
            # the parts of one model, in turn, with the system's first ship seed
            model = models[case % len(models)]
            rec["parts"] = [model, parts_model.parts(model, int(rec["ships"]["first"], 16))]
            # the paint of one model, in turn, with that seed
            rec["paint"] = paint(case, paint_models[case % len(paint_models)], int(rec["ships"]["first"], 16), ua)
            # and the names of one named model's parts, in turn, with that seed: [model, [side, name, parts]]
            model = named_models[case % len(named_models)]
            names = part_names_model.names(model, int(rec["ships"]["first"], 16))
            rec["names"] = [model, [[n.side, n.name, list(n.parts)] for n in names]]
        if isinstance(seeds, dict):
            rec["seeds"] = [f"{s & 0xFFFFFFFFFFFFFFFF:016X}" for s in seeds["planet_seeds"]]
            rec["planet_count"] = seeds["planet_count"]
            rec["moon_count"] = seeds["moon_count"]
            rec["sizes"] = seeds["sizes"]
            # names of every body, in generation order
            rec["body_names"] = [guarded(planetName, s) for s in seeds["planet_seeds"]]
        else:
            rec["seeds"] = seeds
        out.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
