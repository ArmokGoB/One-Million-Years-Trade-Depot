// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A ship's parts by the names the game gives them: a port of
// tools/captures/part_names_model.py. tests/partnames.test.ts holds this port
// to it.
//
// The game names the parts of the ships a player can build at a space
// station's Starship Fabricator: fighters, haulers, explorers and solars.
// Each slot of such a ship (fuselage or cockpit, wings, thruster, sail) takes
// components, each named and made of groups of part IDs (reduced to what
// naming needs in data/part-names.json, by tools/build_part_names.py). A slot
// is named for the component that fits the parts the game picks for the ship:
//
// - a group fits when the descriptor went through a list that offers at least
//   one of its parts, and the ship has every one of its parts that such a list
//   offers (parts of lists never gone through for this ship don't count);
// - a component fits when all its groups fit, or, if its rule is 1, any one;
// - a slot is named when exactly one component fits and that one has a name;
// - an explorer with a matched pair of wings (the first part of one of the
//   tables' pairs) is named as if it had the pair's second part, its right
//   wing its left one; a part named for having the second is made of the
//   first.

import rawNames from "./data/part-names.json";
import { partsAndOptions, type PartModel } from "./parts";

/** Which of a pair of slots, for the explorer's wings: "left" or "right"; "" for any other slot. */
export type Side = "" | "left" | "right";

/** A component: [its name ("" for none), 0 if all its groups must fit or 1 if any one, its groups]. */
type Component = [string, number, string[][]];
/** A slot: [its side, the components it takes]. */
type Slot = [Side, Component[]];

interface PartNamesFile {
  pairs: Record<string, [string, string][]>;
  models: Record<string, Slot[]>;
}

const NAMES = rawNames as unknown as PartNamesFile;

/** A slot of a ship named. */
export interface NamedPart {
  side: Side;
  /** As the game names it, in its English, e.g. "Omega Fuselage". */
  name: string;
  /** The ship's parts that make it, in the order the ship has them. */
  parts: string[];
}

/** The models the game names parts of: the ones its Starship Fabricator builds. */
export const NAMED_MODELS = Object.keys(NAMES.models) as PartModel[];

/** The named slots of `model` with `seed`, in the Fabricator's order; none for a model the game doesn't name. */
export function namedParts(model: PartModel, seed: bigint): NamedPart[] {
  const slots = NAMES.models[model];
  if (!slots) return [];
  const { parts, offered } = partsAndOptions(model, seed);
  const have = new Set(parts);
  const standsFor = new Map<string, string>(); // a pair's second part, by the first, which the ship has instead
  for (const [first, second] of NAMES.pairs[model] ?? []) {
    if (have.has(first)) {
      have.delete(first);
      have.add(second);
      standsFor.set(second, first);
    }
  }

  const fits = (group: readonly string[]) => {
    const inList = group.filter((part) => offered.has(part));
    return inList.length > 0 && inList.every((part) => have.has(part));
  };

  const found = slots.map(([side, components]): NamedPart | null => {
    const fitting = components.flatMap(([name, rule, groups]) => {
      const fit = groups.filter(fits);
      return fit.length && (rule === 1 || fit.length === groups.length) ? [{ name, fit }] : [];
    });
    if (fitting.length !== 1 || !fitting[0]!.name) return null;
    const made = new Set(fitting[0]!.fit.flat().map((part) => standsFor.get(part) ?? part));
    return { side, name: fitting[0]!.name, parts: parts.filter((part) => made.has(part)) };
  });
  const sides = slots.map(([side]) => side);
  const [left, right] = [sides.indexOf("left"), sides.indexOf("right")];
  if (standsFor.size && left >= 0 && right >= 0) {
    const named = found[left];
    found[right] = named ? { ...named, side: "right" } : null;
  }
  return found.filter((named): named is NamedPart => named !== null);
}
