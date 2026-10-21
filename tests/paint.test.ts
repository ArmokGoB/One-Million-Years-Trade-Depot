// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Palettes and paint against tools/captures/paint_model.py, the Python model
// they port, over the made-up seeds in tests/fixtures/paint-vectors.json
// (written by tools/crosscheck/paint_vectors.py).

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  basePalettes,
  legacyPalettes,
  PAINT_MODELS,
  paint,
  paintColors,
  paletteSource,
  PART_MODELS,
  partsFor,
  type PaintModel,
  type PartModel,
  type RGB,
} from "../src/core";

type Colors = number[][] | null;

interface PaletteVector {
  seed: string;
  base: Colors[];
  legacy: Colors[];
}

/** [group, layer, option, palette, color alternative, color (null for none), painted]. */
type Row = [string, string, string, number, number, number[] | null, number];

interface PaintVector {
  model: PaintModel;
  seed: string;
  palettes: string;
  hint: string;
  passes: Row[][];
}

const file = JSON.parse(readFileSync(new URL("./fixtures/paint-vectors.json", import.meta.url), "utf8")) as {
  palettes: PaletteVector[];
  paints: PaintVector[];
};

const single = (colors: Colors) => colors && colors.map((color) => color.map(Math.fround));
const seed = (hex: string) => BigInt(`0x${hex}`);

describe("palette vectors from the Python model", () => {
  for (const v of file.palettes) {
    it(`base palettes of ${v.seed}`, () => {
      expect(basePalettes(seed(v.seed)).map((p) => p && p.map((c) => [...c]))).toEqual(v.base.map(single));
    });
    it(`older palettes of ${v.seed}`, () => {
      expect(legacyPalettes(seed(v.seed)).map((p) => p && p.map((c) => [...c]))).toEqual(v.legacy.map(single));
    });
  }
});

describe("paint vectors from the Python model", () => {
  it("cover every model the tables paint, two seeds each and the Sentinel ship once more with its hint", () => {
    const expected = PAINT_MODELS.flatMap((model) =>
      model === "SENTINELSHIP_PROC" ? [model, model, model] : [model, model],
    );
    expect(file.paints.map((v) => v.model)).toEqual(expected);
    expect(file.paints.filter((v) => v.hint).map((v) => [v.model, v.hint])).toEqual([["SENTINELSHIP_PROC", "POLICE"]]);
  });

  for (const v of file.paints) {
    it(`${v.model} with seed ${v.seed}${v.hint ? ` and hint ${v.hint}` : ""}`, () => {
      const source = paletteSource(v.model);
      const palettes = source === "legacy" ? legacyPalettes(seed(v.palettes)) : basePalettes(seed(v.palettes));
      const parts = (PART_MODELS as string[]).includes(v.model) ? partsFor(v.model as PartModel, seed(v.seed)) : [];
      const passes = paint(v.model, parts, seed(v.seed), palettes, v.hint);
      const rows = passes.map((layers) =>
        layers.map((l) => [l.group, l.layer, l.option, l.palette, l.alt, l.color && [...l.color], l.painted ? 1 : 0]),
      );
      const expected = v.passes.map((layers) =>
        layers.map(([group, layer, option, palette, alt, color, painted]) => [
          group,
          layer,
          option,
          palette,
          alt,
          color ? color.map(Math.fround) : null,
          painted,
        ]),
      );
      expect(rows).toEqual(expected);
    });
  }
});

describe("palettes", () => {
  it("come from the model's own seed for starships, the system's for fleets, the older way for multi-tools", () => {
    expect(paletteSource("FIGHTER_PROC")).toBe("own");
    expect(paletteSource("SENTINELSHIP_PROC")).toBe("own");
    expect(paletteSource("SWARM")).toBe("own");
    expect(paletteSource("CAPITALFREIGHTER_PROC")).toBe("system");
    expect(paletteSource("COMBATFRIGATELOD0")).toBe("system");
    expect(paletteSource("PIRATECRUISERLOD0")).toBe("system");
    expect(paletteSource("MULTITOOL")).toBe("legacy");
  });
});

describe("paint colors", () => {
  it("are each painted color once, the hull's before the decals'", () => {
    const red: RGB = [1, 0, 0];
    const blue: RGB = [0, 0, 1];
    const white: RGB = [1, 1, 1];
    const layer = (group: string, color: RGB | null, painted = true) => ({
      group,
      layer: "BASE",
      option: "",
      palette: 10,
      alt: 0,
      color,
      painted,
    });
    expect(
      paintColors([
        [layer("DECALLOGO", blue), layer("", red), layer("", white, false), layer("", null), layer("", red)],
      ]),
    ).toEqual([red, blue]);
  });

  it("are the same every time for the same seed", () => {
    const palettes = basePalettes(42n);
    const parts = partsFor("FIGHTER_PROC", 42n);
    expect(paint("FIGHTER_PROC", parts, 42n, palettes)).toEqual(paint("FIGHTER_PROC", parts, 42n, palettes));
  });
});
