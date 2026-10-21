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
// mirror image, is picked once. Otherwise one draw picks an option, each as
// likely as the next, except that one whose name has xRARE in it weighs 0.05
// against the others' 1 and one with xNEVER weighs nothing (a list of those
// only is skipped). The part is listed without any LOD suffix, and only once.
// If the option has child lists, two more draws make a seed (mixed as a
// ship's seed is) for picking from them; then two more draws make a seed for
// each scene the option brings in, for picking from that scene's descriptor
// if it has one. The parts come out in that order.
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
const WEIGHTS = [1, 0.05, 0] as const;

interface Unpacked {
  part: string;
  weight: number;
  refs: readonly number[];
  children: readonly PartList[];
}

function unpack(option: Option): Unpacked {
  if (typeof option === "string") return { part: option, weight: 1, refs: [], children: [] };
  const [part, cls = 0, refs = [], children = []] = option;
  return { part, weight: WEIGHTS[cls as 0 | 1 | 2] ?? 1, refs, children };
}

function pick(rng: PRNG, options: readonly Option[]): Unpacked | null {
  const unpacked = options.map(unpack);
  if (unpacked.every((o) => o.weight === 1)) return unpacked[rng.random(unpacked.length)]!;
  const total = unpacked.reduce((sum, o) => sum + o.weight, 0);
  if (total === 0) return null;
  const r = (rng.randi() / 4294967296) * total;
  let acc = 0;
  let last: Unpacked | null = null;
  for (const o of unpacked) {
    if (o.weight === 0) continue;
    acc += o.weight;
    last = o;
    if (r < acc) return o;
  }
  return last; // only if rounding put r at the very top
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

/** The parts picked so far, in order, and their IDs, for telling which lists are decided already. */
interface Listing {
  picked: Picked[];
  ids: Set<string>;
}

function walk(lists: readonly PartList[], rng: PRNG, out: Listing): void {
  for (const [, options] of lists) {
    if (options.some((option) => out.ids.has(unpack(option).part))) continue; // decided already
    const picked = pick(rng, options);
    if (!picked) continue;
    const part = picked.part.replace(LOD_SUFFIX, "");
    if (!out.ids.has(part)) {
      out.ids.add(part);
      out.picked.push({ part, choice: options.filter((option) => unpack(option).weight > 0).length > 1 });
    }
    if (picked.children.length) walk(picked.children, seededPRNG(subSeed(rng)), out);
    for (const ref of picked.refs) {
      const seed = subSeed(rng);
      if (ref >= 0) walk(TABLES.trees[ref]!, seededPRNG(seed), out);
    }
  }
}

function picks(model: PartModel, seed: bigint): Picked[] {
  const out: Listing = { picked: [], ids: new Set() };
  walk(TABLES.trees[TABLES.models[model]!]!, seededPRNG(seed), out);
  return out.picked;
}

/** The parts the game picks for `model` with `seed`, in the order it lists them. */
export function partsFor(model: PartModel, seed: bigint): string[] {
  return picks(model, seed).map((p) => p.part);
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
