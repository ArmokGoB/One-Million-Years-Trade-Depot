// SPDX-License-Identifier: AGPL-3.0-or-later
//
// What the game paints a ship, freighter, frigate or multi-tool with: a port
// of tools/captures/paint_model.py, which the capture report checks against
// every paint the capture mod records. tests/paint.test.ts holds this port to
// it.
//
// Palettes. The game makes a model's 66 palettes of five colors from a seed:
// a starship's and a swarm drone's from its own seed; a freighter's, a
// frigate's and the rest of a system's fleet's from the system's universal
// address; a multi-tool's from its own seed, the older way, from the older
// palettes. Each color is picked with two draws from a palette of up to 64 in
// the game's files.
//
// Textures. Each material of the model as built, with only the parts its
// descriptor picked, has two samplers the paint is picked for, each with a
// texture list: layers of options, each option a texture tinted with one of
// the colors of a palette. For each sampler in turn, the layers of every
// material's list are merged by name and group; one random stream, seeded
// with the model's seed, decides for each merged layer whether it's painted
// and with which option; each material's base layer gets an option of its
// own unless the pick already is one of its options; and layers that match
// their base take its option. An option for a texture hint counts only with
// that hint (a Sentinel ship has POLICE), one for no hint only without one.
//
// The palettes, texture lists, materials and scenes, cut down to what painting
// needs, are in data/paint-tables.json, by tools/build_paint_tables.py.

import rawTables from "./data/paint-tables.json";
import type { PartModel } from "./parts";
import { PRNG } from "./prng";
import { MASK32, mix64, swap16 } from "./u64";

/** A color's red, green and blue, from 0 to 1. */
export type RGB = readonly [number, number, number];

/** An option: [name, color alternative, palette, weight, use]. */
type OptionRow = [string, number, number, number, number];
/** A layer: [group, name, probability, whether it matches its base, options]. */
type LayerRow = [string, string, number, number, OptionRow[]];
/**
 * What a scene brings in, in order: a material (its index), a scene (-1 minus
 * its index), or what's built only with a part ([the part, ...items]).
 */
type SceneItem = number | [string, ...SceneItem[]];

interface PaintTablesFile {
  models: Record<string, number>;
  palettes: { base: (number[] | null)[]; legacy: number[][] };
  lists: [number, LayerRow[]][];
  materials: [number, number][];
  scenes: SceneItem[][];
}

const TABLES = rawTables as PaintTablesFile;

/**
 * The models the site paints, by the key of their scene: those whose parts
 * parts.ts picks, and the closest level of detail of the frigates, the swarm
 * drone and the pirates' frigates, which have no parts to pick.
 */
export type PaintModel =
  | PartModel
  | "COMBATFRIGATELOD0"
  | "SCIENCEFRIGATELOD0"
  | "INDUSTRIALFRIGATELOD0"
  | "DIPLOMATICFRIGATELOD0"
  | "SUPPORTFRIGATELOD0"
  | "GHOSTSHIPFRIGATELOD0"
  | "PIRATECRUISERLOD0"
  | "SWARMFRIGATE"
  | "SWARM";

/** Every model the paint tables have. */
export const PAINT_MODELS = Object.keys(TABLES.models) as PaintModel[];

// --- Tables, rounded to single precision again ---

interface Palette {
  /** How many of its colors the game uses: 0 none, 1 one, 2 four, 3 eight, 4 sixteen, 5 all. */
  kind: number;
  colors: RGB[];
}

interface TextureOption {
  name: string;
  alt: number;
  palette: number;
  weight: number;
  use: number;
}

interface TextureLayer {
  group: string;
  name: string;
  probability: number;
  matchBase: boolean;
  options: TextureOption[];
}

interface TextureList {
  keepApart: boolean;
  layers: TextureLayer[];
}

function palette(entry: number[] | null): Palette | null {
  if (!entry) return null;
  const values = entry.slice(1).map(Math.fround);
  return {
    kind: entry[0]!,
    colors: Array.from({ length: 64 }, (_, i) => [values[3 * i]!, values[3 * i + 1]!, values[3 * i + 2]!] as const),
  };
}

const BASE_PALETTES = TABLES.palettes.base.map(palette);
const LEGACY_PALETTES = TABLES.palettes.legacy.map((entry) => palette(entry)!);
const LISTS: TextureList[] = TABLES.lists.map(([keep, layers]) => ({
  keepApart: keep !== 0,
  layers: layers.map(([group, name, probability, match, options]) => ({
    group,
    name,
    probability: Math.fround(probability),
    matchBase: match !== 0,
    options: options.map(([option, alt, palette, weight, use]) => ({
      name: option,
      alt,
      palette,
      weight: Math.fround(weight),
      use,
    })),
  })),
}));

// --- The generator ---

/** The game turns a draw into a fraction with this, then rounds it to single precision. */
const UNIT = 1 / 4294967295;

/**
 * The generator the paint and the palettes draw from: the game's
 * multiply-with-carry generator (see prng.ts), seeded from a 64-bit seed
 * slightly differently from seededPRNG: a zero low word counts as one, and
 * the carry isn't made non-zero.
 */
class Stream {
  private rng: PRNG;

  constructor(state: bigint) {
    this.rng = new PRNG(state);
  }

  static seeded(seed: bigint): Stream {
    const low = seed & MASK32;
    const high = (seed >> 32n) & MASK32;
    const carry = swap16(low) ^ high ^ low;
    return new Stream((carry << 32n) | (low === 0n ? 1n : low));
  }

  next(): number {
    return this.rng.randi();
  }

  fraction(): number {
    return Math.fround(this.next() * UNIT);
  }

  copy(): Stream {
    return new Stream(this.rng.seed);
  }

  /** A stream seeded with the next two draws, mixed as a ship's seed is; this one doesn't advance. */
  derive(): Stream {
    const ahead = this.copy();
    const low = BigInt(ahead.next());
    const high = BigInt(ahead.next());
    return Stream.seeded(mix64((high << 32n) | low));
  }
}

// --- Palettes ---

/** A model's palettes: each one's five colors, or null where the tables have none (no paint uses it). */
export type Palettes = readonly (readonly RGB[] | null)[];

/** Where in a palette a color is picked from, by how many colors the palette uses. */
function placeFor(kind: number, x1: number, x2: number): number {
  const top = x1 >>> 29;
  if (kind === 1) return 0;
  if (kind === 2) return ((top >>> 2) * 8 + (x2 >>> 31)) * 4;
  if (kind === 3) return x2 >>> 29;
  if (kind === 4) return ((x2 >>> 30) + (top >>> 1) * 8) * 2;
  return (x2 >>> 29) + top * 8;
}

/** The color a place stands for, by how many colors the palette uses. */
function colorAt(kind: number, place: number): number {
  const low = place & 7;
  if (kind === 1) return 0;
  if (kind === 2) return ((low >>> 2) + (place >>> 5) * 8) * 4;
  if (kind === 3) return low;
  if (kind === 4) return ((low >>> 1) + (place >>> 4) * 8) * 2;
  return place;
}

/** Base palettes: a color less than this (squared) from one picked already is the same color. */
const CLOSE = 2 ** -32;

/**
 * Five colors of a base palette: two draws each, and the next place in the
 * palette for a color the same as one picked already (64 places at most). A
 * palette the tables leave out is drawn for all the same.
 */
function pick(table: Palette | null, stream: Stream): RGB[] | null {
  const picked: RGB[] = [];
  for (let k = 0; k < 5; k++) {
    const x1 = stream.next();
    const x2 = stream.next();
    if (!table) continue;
    let place = placeFor(table.kind, x1, x2);
    let color = table.colors[colorAt(table.kind, place)]!;
    for (let tries = 0; tries < 64; tries++) {
      const c = color;
      const same = picked.some(
        (other) => (other[0] - c[0]) ** 2 + (other[1] - c[1]) ** 2 + (other[2] - c[2]) ** 2 < CLOSE,
      );
      if (!same) break;
      place = (place + 1) & 63;
      color = table.colors[colorAt(table.kind, place)]!;
    }
    picked.push(color);
  }
  return table ? picked : null;
}

/** The six faction palettes (Warrior to TraderAlt), in the order the game makes them again. */
const FACTIONS = [0x20, 0x23, 0x22, 0x25, 0x21, 0x24] as const;

/**
 * The palettes the game makes from a seed: in turn up to the 52nd; the
 * Freighter one from the stream as it was at the Paint one; the six faction
 * palettes from a stream derived after them, the Grass ones from another
 * derived after two more draws, and the rest from one derived from that.
 */
export function basePalettes(seed: bigint): Palettes {
  const out: (RGB[] | null)[] = Array<RGB[] | null>(66).fill(null);
  const stream = Stream.seeded(seed);
  let atPaint = stream;
  for (let p = 0; p < 52; p++) {
    if (p === 10) atPaint = stream.copy();
    out[p] = pick(BASE_PALETTES[p] ?? null, stream);
  }
  const factions = stream.derive();
  stream.next();
  stream.next();
  const grass = stream.derive();
  for (const p of FACTIONS) out[p] = pick(BASE_PALETTES[p] ?? null, factions.copy());
  out[0] = pick(BASE_PALETTES[0] ?? null, grass.copy());
  out[0x33] = pick(BASE_PALETTES[0x33] ?? null, grass);
  const rest = grass.derive();
  for (let p = 0x34; p < 0x42; p++) out[p] = pick(BASE_PALETTES[p] ?? null, p === 0x38 ? atPaint : rest);
  return out;
}

/** Whether two colors are too close for the older palettes, in single precision as the game measures. */
function tooClose(a: RGB, b: RGB, threshold: number): boolean {
  const dr = Math.fround(a[0] - b[0]);
  const dg = Math.fround(a[1] - b[1]);
  const db = Math.fround(a[2] - b[2]);
  const total = Math.fround(Math.fround(Math.fround(dr * dr) + Math.fround(dg * dg)) + Math.fround(db * db));
  return Math.fround(threshold) > Math.fround(Math.sqrt(total));
}

/** Five colors of an older palette: two draws a try, up to 64 tries for a color at least 1 from those picked. */
function pickLegacy(table: Palette, stream: Stream): RGB[] {
  const picked: RGB[] = [];
  for (let k = 0; k < 5; k++) {
    let color = table.colors[0]!;
    for (let tries = 0; tries < 64; tries++) {
      const x1 = stream.next();
      const x2 = stream.next();
      color = table.colors[table.kind === 3 ? x2 >>> 29 : (x2 >>> 29) + (x1 >>> 29) * 8]!;
      const c = color;
      if (!picked.some((other) => tooClose(other, c, 1))) break;
    }
    picked.push(color);
  }
  return picked;
}

/**
 * The palettes the game makes the older way, as for multi-tools: each in
 * turn, up to the last one the tables have; the six faction palettes made
 * again at the end if the tables have all 66.
 */
export function legacyPalettes(seed: bigint): Palettes {
  const out: (RGB[] | null)[] = Array<RGB[] | null>(66).fill(null);
  const stream = Stream.seeded(seed);
  LEGACY_PALETTES.forEach((table, p) => {
    out[p] = pickLegacy(table, stream);
  });
  if (LEGACY_PALETTES.length === 66) {
    const factions = stream.derive();
    for (const p of FACTIONS) out[p] = pickLegacy(LEGACY_PALETTES[p]!, factions.copy());
  }
  return out;
}

/** Where a model's palettes come from: its own seed, its system's address, or its own seed the older way. */
export type PaletteSource = "own" | "system" | "legacy";

const OWN_PALETTES = new Set<string>([
  "FIGHTER_PROC",
  "DROPSHIP_PROC",
  "SCIENTIFIC_PROC",
  "SHUTTLE_PROC",
  "SAILSHIP_PROC",
  "S-CLASS_PROC",
  "SENTINELSHIP_PROC",
  "SWARM",
]);
const LEGACY_PALETTES_MODELS = new Set<string>(["MULTITOOL", "ROYALMULTITOOL", "SENTINELMULTITOOL", "ATLASMULTITOOL"]);

/** Whose seed a model's palettes come from, as the captures show. */
export function paletteSource(model: PaintModel): PaletteSource {
  if (LEGACY_PALETTES_MODELS.has(model)) return "legacy";
  return OWN_PALETTES.has(model) ? "own" : "system";
}

// --- The paint ---

/** One layer of a pass and what it was painted with. */
export interface PaintedLayer {
  group: string;
  layer: string;
  /** The texture option, "" for a layer that isn't painted (or an option without a name). */
  option: string;
  palette: number;
  /** The color alternative: 0 Primary, 1-3 Alternative1-3, 4 Alternative4, 5 Unique, 7 None. */
  alt: number;
  /** Null for an option of no color; white for a layer that isn't painted. */
  color: RGB | null;
  painted: boolean;
}

const BASE = "BASE";
const UNNAMED = "";
const NO_COLOR = 7;
const WHITE: RGB = [1, 1, 1];

interface MergedOption {
  name: string;
  alt: number;
  palette: number;
  count: number;
  weight: number;
}

interface MergedLayer {
  name: string;
  group: string;
  count: number;
  probability: number;
  matchBase: boolean;
  options: MergedOption[];
}

function usable(option: TextureOption, hint: string): boolean {
  if (option.use === 1) return hint === option.name;
  if (option.use === 2) return hint === "";
  return true;
}

function merge(merged: MergedLayer[], layer: TextureLayer, hint: string, keepApart: boolean): void {
  const apart = keepApart && layer.options.length < 2 && layer.group === UNNAMED;
  const found = apart ? undefined : merged.find((m) => m.name === layer.name && m.group === layer.group);
  if (!found) {
    const options = layer.options
      .filter((o) => usable(o, hint))
      .map((o) => ({ name: o.name, alt: o.alt, palette: o.palette, count: 1, weight: o.weight }));
    if (options.length) {
      merged.push({
        name: layer.name,
        group: layer.group,
        count: 1,
        probability: layer.probability,
        matchBase: layer.matchBase,
        options,
      });
    }
    return;
  }
  found.count += 1;
  found.probability = Math.fround(layer.probability + found.probability);
  found.matchBase ||= layer.matchBase;
  for (const o of layer.options) {
    const same = found.options.find((m) => m.name === o.name && m.palette === o.palette && m.alt === o.alt);
    if (same) {
      same.count += 1;
      same.weight = Math.fround(o.weight + same.weight);
    } else if (usable(o, hint)) {
      found.options.push({ name: o.name, alt: o.alt, palette: o.palette, count: 1, weight: o.weight });
    }
  }
}

function colorOf(alt: number, palette: number, palettes: Palettes): RGB | null {
  if (alt === NO_COLOR) return null;
  const colors = palettes[palette];
  if (!colors) throw new Error(`palette ${palette} isn't in the paint tables`);
  return colors[Math.min(alt, 3)]!;
}

function paintPass(
  lists: readonly (TextureList | null)[],
  seed: bigint,
  hint: string,
  palettes: Palettes,
): PaintedLayer[] {
  const merged: MergedLayer[] = [];
  for (const list of lists) {
    if (list) for (const layer of list.layers) merge(merged, layer, hint, list.keepApart);
  }
  const stream = Stream.seeded(seed);
  const rows: PaintedLayer[] = [];
  const painted = (group: string, layer: string, o: { name: string; palette: number; alt: number }): PaintedLayer => ({
    group,
    layer,
    option: o.name,
    palette: o.palette,
    alt: o.alt,
    color: colorOf(o.alt, o.palette, palettes),
    painted: true,
  });

  // Whether each merged layer is painted, and with which option.
  for (const m of merged) {
    m.probability = Math.fround(m.probability / Math.fround(m.count));
    let row: PaintedLayer = {
      group: m.group,
      layer: m.name,
      option: "",
      palette: 4,
      alt: 0,
      color: WHITE,
      painted: false,
    };
    if (m.probability > 0 && stream.fraction() < m.probability && !m.matchBase) {
      let total = 0;
      for (const o of m.options) {
        o.weight = Math.fround(o.weight / Math.fround(o.count));
        total = Math.fround(total + o.weight);
      }
      const target = Math.fround(stream.fraction() * total);
      let running = 0;
      for (const o of m.options) {
        running = Math.fround(running + o.weight);
        if (target < running) {
          row = painted(m.group, m.name, o);
          break;
        }
      }
    }
    rows.push(row);
  }

  // Each material's first base layer, unless the pick for it is one of its options already.
  for (const list of lists) {
    const layer = list?.layers.find((l) => l.name === BASE || l.name === UNNAMED);
    if (!layer) continue;
    let exact = false;
    let named = -1;
    for (const r of [...rows]) {
      if (r.layer !== layer.name || r.group !== layer.group) continue;
      for (let j = 0; j < layer.options.length; j++) {
        const o = layer.options[j]!;
        if (o.name !== r.option) continue;
        named = j;
        if (o.palette === r.palette && o.alt === r.alt) {
          exact = true;
          break;
        }
      }
    }
    if (exact) continue;
    if (named < 0 || !usable(layer.options[named]!, hint)) {
      named = layer.options.findIndex((o) => usable(o, hint));
      // The game would read an option from outside the list here.
      if (named < 0) throw new Error(`no option of a base layer can be used with the hint "${hint}"`);
    }
    rows.push(painted(layer.group, layer.name, layer.options[named]!));
  }

  // Layers that match their base, when painted, take the option their group's base got.
  merged.forEach((m, i) => {
    if (!(stream.fraction() < m.probability && m.matchBase)) return;
    for (const b of [...rows]) {
      if ((b.layer !== BASE && b.layer !== UNNAMED) || b.group !== m.group) continue;
      const o = m.options.find((option) => option.name === b.option);
      if (o) {
        rows[i] = {
          ...rows[i]!,
          option: b.option,
          palette: o.palette,
          alt: o.alt,
          color: colorOf(o.alt, o.palette, palettes),
          painted: true,
        };
        break;
      }
    }
  });
  return rows;
}

/** A level-of-detail suffix, which the game drops from the IDs of the parts it picks. */
const LOD_SUFFIX = /LOD\d+$/;

/**
 * The painted materials of a model built with these parts, in the game's
 * order: a node's materials, then its children, then the scenes it brings in;
 * each material once, where it first comes. A part's node is built only if the
 * part is among them.
 */
function materials(model: PaintModel, parts: readonly string[]): number[] {
  const chosen = new Set(parts.map((part) => part.toUpperCase().replace(LOD_SUFFIX, "")));
  const out: number[] = [];
  const seen = new Set<number>();
  const visit = (items: readonly SceneItem[], depth: number): void => {
    for (const item of items) {
      if (Array.isArray(item)) {
        const [part, ...built] = item;
        if (chosen.has(part)) visit(built, depth);
      } else if (item < 0) {
        if (depth < 32) visit(TABLES.scenes[-1 - item]!, depth + 1);
      } else if (!seen.has(item)) {
        seen.add(item);
        out.push(item);
      }
    }
  };
  const root = TABLES.models[model];
  if (root !== undefined && root >= 0) visit(TABLES.scenes[root]!, 0);
  return out;
}

/**
 * What the game paints `model` with: each pass's layers, the first for its
 * materials' gDiffuseMap, the second, if any material has one, for their
 * gDiffuse2Map. `parts` are those its descriptor picked (partsFor), `palettes`
 * those it takes its colors from (see paletteSource), `hint` its texture hint.
 */
export function paint(
  model: PaintModel,
  parts: readonly string[],
  seed: bigint,
  palettes: Palettes,
  hint = "",
): PaintedLayer[][] {
  const perMaterial = materials(model, parts).map((m) => TABLES.materials[m]!.map((k) => (k >= 0 ? LISTS[k]! : null)));
  let passes = 0;
  for (const [first, second] of perMaterial) {
    passes = Math.max(passes, second ? (first ? 1 : 0) + 1 : first ? 1 : 0);
  }
  return Array.from({ length: passes }, (_, k) =>
    paintPass(
      perMaterial.map((lists) => lists[k] ?? null),
      seed,
      hint,
      palettes,
    ),
  );
}

/**
 * The colors a paint shows, each once: those of the layers painted with a
 * color, the hull's (layers of no group) before the decals', each in the
 * game's order.
 */
export function paintColors(passes: readonly (readonly PaintedLayer[])[]): RGB[] {
  const layers = passes.flat().filter((l) => l.painted && l.color);
  const ordered = [...layers.filter((l) => l.group === ""), ...layers.filter((l) => l.group !== "")];
  const out: RGB[] = [];
  for (const { color } of ordered) {
    if (!out.some((c) => c[0] === color![0] && c[1] === color![1] && c[2] === color![2])) out.push(color!);
  }
  return out;
}
