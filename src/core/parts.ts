// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A model's parts from its seed: a port of tools/captures/parts_model.py,
// which the capture report checks against every model the capture mod
// records. tests/parts.test.ts holds this port to it.
//
// The game picks a ship's or multi-tool's parts from its model's descriptor,
// with the generator seeded with its seed, going through the descriptor's
// lists in order. A list one of whose options is already among the parts is
// skipped without a draw, so a part two scenes share, such as a wing and its
// mirror image, is picked once. Otherwise one draw picks an option, as the
// game's code does it: each option weighs 20, one whose name has xRARE in it
// 1 and one with xNEVER 0, and the draw scaled to the total weight falls on
// one of them in turn (a list of xNEVER options only is skipped). The part is
// listed without any LOD suffix, and only once. If the option has child
// lists, two more draws make a seed (mixed as a ship's seed is) for picking
// from them; then two more draws make a seed for each scene the option brings
// in, for picking from that scene's descriptor if it has one. Child lists, or
// a scene's descriptor, that offer xNEVER options only take no draws. The
// parts come out in that order.
//
// The descriptors are reduced to what picking needs in
// data/part-tables.json, by tools/build_part_tables.py.

import rawTables from "./data/part-tables.json";
import { type PRNG, seededPRNG } from "./prng";
import { mix64 } from "./u64";

/** An option: its ID, or [ID, weight class, the trees of the scenes it brings in (-1: none), child lists]. */
type Option = string | [string, number?, number[]?, PartList[]?];
/** A list of options: [type ID, options]. */
type PartList = [string, Option[]];

interface PartTablesFile {
  models: Record<string, number>;
  trees: PartList[][];
}

const TABLES = rawTables as PartTablesFile;

/** The models with parts, by the key of their descriptor. */
export type PartModel =
  | "FIGHTER_PROC"
  | "DROPSHIP_PROC"
  | "SCIENTIFIC_PROC"
  | "SHUTTLE_PROC"
  | "SAILSHIP_PROC"
  | "S-CLASS_PROC"
  | "SENTINELSHIP_PROC"
  | "FREIGHTER_PROC"
  | "CAPITALFREIGHTER_PROC"
  | "MULTITOOL"
  | "ROYALMULTITOOL"
  | "SENTINELMULTITOOL"
  | "ATLASMULTITOOL"
  | "FREIGHTERSMALL_PROC"
  | "FREIGHTERTINY_PROC"
  | "POLICEFREIGHTER"
  | "PIRATEFREIGHTER";

/** How much an option weighs in a pick, by weight class: normal, xRARE, xNEVER. */
const WEIGHTS = [20, 1, 0] as const;

interface Unpacked {
  part: string;
  weight: number;
  refs: readonly number[];
  children: readonly PartList[];
}

function unpack(option: Option): Unpacked {
  if (typeof option === "string") return { part: option, weight: WEIGHTS[0], refs: [], children: [] };
  const [part, cls = 0, refs = [], children = []] = option;
  return { part, weight: WEIGHTS[cls as 0 | 1 | 2] ?? WEIGHTS[0], refs, children };
}

/** The option one draw picks, by weight; none, without a draw, from options that all weigh nothing. */
function pick(rng: PRNG, options: readonly Option[]): Unpacked | null {
  const unpacked = options.map(unpack);
  const total = unpacked.reduce((sum, o) => sum + o.weight, 0);
  if (total === 0) return null;
  let r = rng.random(total);
  for (const o of unpacked) {
    if (r < o.weight) return o;
    r -= o.weight;
  }
  throw new Error("a draw below the total weight falls on an option");
}

/**
 * Whether every one of these lists offers options, and only xNEVER ones: the
 * game goes through no such child lists or scene descriptor, nor draws a seed
 * for them.
 */
function neverOnly(lists: readonly PartList[]): boolean {
  return lists.length > 0 && lists.every(([, options]) => options.length && options.every((o) => !unpack(o).weight));
}

/** A seed made of the next two draws, the first the low half, mixed. */
function subSeed(rng: PRNG): bigint {
  const low = BigInt(rng.randi());
  const high = BigInt(rng.randi());
  return mix64((high << 32n) | low);
}

/** A level-of-detail suffix, which the game drops from the IDs it lists. */
const LOD_SUFFIX = /LOD\d+$/;

interface Picked {
  part: string;
  /** Whether the list it came from offered another option the game could have picked. */
  choice: boolean;
}

/**
 * The parts picked so far, in order, and their IDs, for telling which lists
 * are decided already; and every option of every list gone through, picked or
 * not, less any LOD suffix.
 */
interface Listing {
  picked: Picked[];
  ids: Set<string>;
  offered: Set<string>;
}

/** Note the options of these lists as offered, less any LOD suffix. */
function offer(lists: readonly PartList[], out: Listing): void {
  for (const [, options] of lists) {
    for (const option of options) out.offered.add(unpack(option).part.replace(LOD_SUFFIX, ""));
  }
}

function walk(lists: readonly PartList[], rng: PRNG, out: Listing): void {
  for (const list of lists) {
    const options = list[1];
    offer([list], out);
    if (options.some((option) => out.ids.has(unpack(option).part))) continue; // decided already
    const picked = pick(rng, options);
    if (!picked) continue;
    const part = picked.part.replace(LOD_SUFFIX, "");
    if (!out.ids.has(part)) {
      out.ids.add(part);
      out.picked.push({ part, choice: options.filter((option) => unpack(option).weight > 0).length > 1 });
    }
    // Lists of xNEVER options only, which the game doesn't go through, still count as offering them.
    if (neverOnly(picked.children)) offer(picked.children, out);
    else if (picked.children.length) walk(picked.children, seededPRNG(subSeed(rng)), out);
    for (const ref of picked.refs) {
      if (ref >= 0 && neverOnly(TABLES.trees[ref]!)) {
        offer(TABLES.trees[ref]!, out);
        continue;
      }
      const seed = subSeed(rng);
      if (ref >= 0) walk(TABLES.trees[ref]!, seededPRNG(seed), out);
    }
  }
}

function listing(model: PartModel, seed: bigint): Listing {
  const out: Listing = { picked: [], ids: new Set(), offered: new Set() };
  walk(TABLES.trees[TABLES.models[model]!]!, seededPRNG(seed), out);
  return out;
}

function picks(model: PartModel, seed: bigint): Picked[] {
  return listing(model, seed).picked;
}

/** The parts the game picks for `model` with `seed`, in the order it lists them. */
export function partsFor(model: PartModel, seed: bigint): string[] {
  return picks(model, seed).map((p) => p.part);
}

/**
 * The parts the game picks for `model` with `seed`, in order, and every option
 * of every list it goes through on the way, picked or not, less any LOD
 * suffix: the parts it could have picked instead. The options of the
 * xNEVER-only lists a picked part brings, which the game passes over, count too.
 */
export function partsAndOptions(model: PartModel, seed: bigint): { parts: string[]; offered: ReadonlySet<string> } {
  const out = listing(model, seed);
  return { parts: out.picked.map((p) => p.part), offered: out.offered };
}

/**
 * The parts that tell this one apart from others of its model: those picked
 * from a list offering more than one option. A list with one option gives
 * every model that reaches it the same part, such as the joints a solar ship
 * is built on.
 */
export function distinguishingParts(model: PartModel, seed: bigint): string[] {
  return picks(model, seed).flatMap((p) => (p.choice ? [p.part] : []));
}

/** Every model the parts tables have. */
export const PART_MODELS = Object.keys(TABLES.models) as PartModel[];
