// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A color in words, for every swatch the site shows: the site says each color
// it shows, never only shows it. The name is a plain color word, from the
// color's lightness, chroma and hue in OKLab (Björn Ottosson's perceptual
// color space, 2020): a gray by its lightness, "grayish", "pale" or a word of
// its own (beige, tan, khaki, olive) for a color of little chroma, and for the
// rest its hue's word, with "dark" or "light" where its lightness is far from
// the hue's own (a dark orange is brown, a dark yellow mustard or olive).

import type { RGB } from "./paint";

/** An sRGB channel, 0 to 1, made linear. */
function linear(channel: number): number {
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

/** A color's lightness (0 to 1), chroma and hue (degrees) in OKLab. */
export function oklch([r, g, b]: RGB): { lightness: number; chroma: number; hue: number } {
  const lr = linear(r);
  const lg = linear(g);
  const lb = linear(b);
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  const lightness = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const hue = ((Math.atan2(bb, a) * 180) / Math.PI + 360) % 360;
  return { lightness, chroma: Math.hypot(a, bb), hue };
}

/** Below this chroma a color is a gray (below the second if it's very light); below the third, a grayish one. */
const GRAY = 0.035;
const PALE_GRAY = 0.025;
const GRAYISH = 0.07;

/** Grays by lightness: below each bound, its name. */
const GRAYS: readonly (readonly [number, string])[] = [
  [0.28, "black"],
  [0.48, "dark gray"],
  [0.68, "gray"],
  [0.88, "light gray"],
  [Infinity, "white"],
];

type Hue = "pink" | "red" | "orange" | "yellow" | "yellow-green" | "green" | "teal" | "blue" | "purple";

/** Hues by angle: from each angle up to the next, its word. */
const HUES: readonly (readonly [number, Hue])[] = [
  [0, "pink"],
  [15, "red"],
  [38, "orange"],
  [72, "yellow"],
  [112, "yellow-green"],
  [132, "green"],
  [172, "teal"],
  [222, "blue"],
  [280, "purple"],
  [345, "pink"],
];

function hueOf(angle: number): Hue {
  let found: Hue = "pink";
  for (const [from, hue] of HUES) if (angle >= from) found = hue;
  return found;
}

/** A color of little chroma. */
function grayish(hue: Hue, lightness: number, angle: number): string {
  if (lightness >= 0.85) {
    if (hue === "orange" || (hue === "yellow" && angle < 88)) return "beige";
    return `pale ${hue === "red" ? "pink" : hue === "yellow-green" ? "green" : hue}`;
  }
  switch (hue) {
    case "pink":
      return lightness < 0.62 ? "grayish red" : "grayish pink";
    case "red":
    case "orange":
      if (angle < 30) return lightness < 0.62 ? "grayish red" : "grayish pink";
      return lightness < 0.4 ? "dark brown" : lightness < 0.62 ? "grayish brown" : "tan";
    case "yellow":
      if (lightness < 0.55) return angle < 88 ? "grayish brown" : "olive";
      return angle < 88 && lightness >= 0.7 ? "beige" : "khaki";
    case "yellow-green":
      return lightness < 0.55 ? "olive" : "grayish green";
    default:
      return `grayish ${hue}`;
  }
}

/** A color of more chroma. */
function vivid(hue: Hue, lightness: number, chroma: number, angle: number): string {
  switch (hue) {
    case "pink":
      return lightness >= 0.62 ? "pink" : lightness < 0.45 ? "dark red" : "rose";
    case "red":
      return lightness >= 0.74 ? "pink" : lightness < 0.45 ? "dark red" : "red";
    case "orange":
      if (lightness < 0.6) return chroma >= 0.13 ? "dark orange" : lightness < 0.42 ? "dark brown" : "brown";
      if (lightness >= 0.75 && chroma < 0.09) return "beige";
      return lightness >= 0.86 ? "light orange" : "orange";
    case "yellow":
      if (lightness < 0.55) return angle < 88 ? "brown" : "olive";
      if (lightness < 0.75) return angle < 100 ? "mustard" : "olive";
      if (chroma < 0.1) return angle < 88 ? "beige" : lightness < 0.85 ? "khaki" : "pale yellow";
      return lightness >= 0.92 && chroma < 0.13 ? "light yellow" : "yellow";
    case "yellow-green":
      if (lightness < 0.55) return chroma < 0.12 ? "olive" : "dark green";
      return lightness >= 0.88 ? "light green" : "yellow-green";
    case "purple":
      if (angle >= 325 && lightness >= 0.65) return "pink";
      if (angle >= 315 && chroma >= 0.15) return lightness < 0.45 ? "purple" : "magenta";
      return lightness < 0.4 ? "dark purple" : lightness >= 0.74 ? "light purple" : "purple";
    default: {
      // Green, teal and blue: dark below about where their deep shades end, light above their pastels.
      const dark = hue === "blue" ? 0.42 : 0.45;
      const light = hue === "blue" ? 0.74 : 0.82;
      return lightness < dark ? `dark ${hue}` : lightness >= light ? `light ${hue}` : hue;
    }
  }
}

/** The color in a few plain words. */
export function colorName(color: RGB): string {
  const { lightness, chroma, hue: angle } = oklch(color);
  if (chroma < GRAY && !(lightness >= 0.85 && chroma >= PALE_GRAY)) {
    return GRAYS.find(([below]) => lightness < below)![1];
  }
  const hue = hueOf(angle);
  return chroma < GRAYISH ? grayish(hue, lightness, angle) : vivid(hue, lightness, chroma, angle);
}

/** A color as a CSS hex color: #rrggbb. */
export function hexColor([r, g, b]: RGB): string {
  const byte = (channel: number) =>
    Math.round(Math.min(1, Math.max(0, channel)) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${byte(r)}${byte(g)}${byte(b)}`;
}
