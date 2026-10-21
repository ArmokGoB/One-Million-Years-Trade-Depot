// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Color names: what the site calls the colors it shows, next to each swatch.

import { describe, expect, it } from "vitest";
import { colorName, hexColor, oklch, type RGB } from "../src/core";

const rgb = (hex: string): RGB => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as unknown as RGB;

describe("color names", () => {
  // Familiar colors, by their CSS or common names, and what the site calls them.
  const named: [string, string][] = [
    ["#000000", "black"],
    ["#3a3a3a", "dark gray"],
    ["#808080", "gray"],
    ["#c0c0c0", "light gray"],
    ["#ffffff", "white"],
    ["#bcebff", "pale blue"], // pale sky
    ["#f5deb3", "beige"], // wheat
    ["#c5a085", "tan"],
    ["#bdb76b", "khaki"], // dark khaki
    ["#808000", "olive"],
    ["#875858", "grayish red"],
    ["#8b4513", "brown"], // saddle brown
    ["#4a2f1b", "dark brown"],
    ["#b5420f", "dark orange"], // rust
    ["#ff8c00", "orange"],
    ["#c9a227", "mustard"],
    ["#ffd700", "yellow"], // gold
    ["#fff59d", "light yellow"],
    ["#9acd32", "yellow-green"],
    ["#2e8b57", "green"], // sea green
    ["#1b5e20", "dark green"],
    ["#a5d6a7", "light green"],
    ["#008080", "teal"],
    ["#40e0d0", "light teal"], // turquoise
    ["#4169e1", "blue"], // royal blue
    ["#000080", "dark blue"], // navy
    ["#87cefa", "light blue"], // light sky blue
    ["#3b1a5a", "dark purple"],
    ["#800080", "purple"],
    ["#d7b4f3", "light purple"],
    ["#c000c0", "magenta"],
    ["#ff69b4", "pink"], // hot pink
    ["#ffc0cb", "pink"],
    ["#c2185b", "rose"],
    ["#d32f2f", "red"],
    ["#7b1414", "dark red"],
  ];
  for (const [hex, name] of named) {
    it(`calls ${hex} ${name}`, () => {
      expect(colorName(rgb(hex))).toBe(name);
    });
  }

  it("takes the lightness, chroma and hue of OKLab", () => {
    const white = oklch([1, 1, 1]);
    expect(white.lightness).toBeCloseTo(1, 6);
    expect(white.chroma).toBeCloseTo(0, 6);
    // Ottosson's reference: sRGB red is L 0.628, C 0.258, h 29.2 degrees.
    const red = oklch([1, 0, 0]);
    expect(red.lightness).toBeCloseTo(0.628, 3);
    expect(red.chroma).toBeCloseTo(0.2577, 3);
    expect(red.hue).toBeCloseTo(29.23, 1);
  });
});

describe("hex colors", () => {
  it("are each channel as two hex digits, rounded and kept within 0 and 1", () => {
    expect(hexColor([1, 0, 0])).toBe("#ff0000");
    expect(hexColor([0.5, 0.25, 0.75])).toBe("#8040bf");
    expect(hexColor([1.2, -0.1, 0.004])).toBe("#ff0001");
  });
});
