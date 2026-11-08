// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A ship's parts by name: a port of tools/captures/part_names_model.py.
// tests/partnames.test.ts holds this port to it.
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
//
// Players name the parts of the other ships: shuttles, exotics, Sentinel
// ships, freighters and capital freighters. tools/community_part_names.tsv has
// their names, the No Man's Sky Coordinate Exchange's (NMSCE) and this
// project's own for parts NMSCE has no name for, each with groups of part IDs
// (in data/community-part-names.json, by tools/build_community_part_names.py).
// A ship has each name it has every part of a group of, made of the parts of
// every such group, in the order their first parts come on the ship; a name
// with no parts, which every ship of its model has, comes first.

import rawCommunityNames from "./data/community-part-names.json";
import rawNames from "./data/part-names.json";
import { partsAndOptions, partsFor, type PartModel } from "./parts";

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

/** A name players use for a part, and the groups of part IDs a ship has it with. */
type CommunityName = [string, string[][]];

interface CommunityNamesFile {
  models: Record<string, CommunityName[]>;
}

const NAMES = rawNames as unknown as PartNamesFile;
const COMMUNITY_NAMES = rawCommunityNames as unknown as CommunityNamesFile;

/** A named part of a ship. */
export interface NamedPart {
  side: Side;
  /**
   * As the game names it, in its English, e.g. "Omega Fuselage", or for a
   * ship it doesn't name, as players do, e.g. "Magnatreme Ring".
   */
  name: string;
  /** The ship's parts that make it, in the order the ship has them; none for a part every ship of its model has. */
  parts: string[];
}

/**
 * The models whose parts have names: those the game's Starship Fabricator
 * builds, then those players name the parts of.
 */
export const NAMED_MODELS = [...Object.keys(NAMES.models), ...Object.keys(COMMUNITY_NAMES.models)] as PartModel[];

/**
 * The named parts of `model` with `seed`: a Fabricator ship's named slots, in
 * the Fabricator's order, or the names players give the parts of another ship
 * (see communityNames); none for a model whose parts have no names.
 */
export function namedParts(model: PartModel, seed: bigint): NamedPart[] {
  const slots = NAMES.models[model];
  if (!slots) return communityNames(model, seed);
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

/**
 * The names players give the parts of `model` with `seed`, in the order their
 * first parts come on the ship, a name with no parts first; none for a model
 * they don't name the parts of.
 */
function communityNames(model: PartModel, seed: bigint): NamedPart[] {
  const entries = COMMUNITY_NAMES.models[model];
  if (!entries) return [];
  const parts = partsFor(model, seed);
  const have = new Set(parts);
  const found = entries.flatMap(([name, groups], index) => {
    const fit = groups.filter((group) => group.every((part) => have.has(part)));
    if (!fit.length) return [];
    const made = new Set(fit.flat());
    const ordered = parts.filter((part) => made.has(part));
    const first = ordered.length ? parts.indexOf(ordered[0]!) : -1;
    return [{ first, index, named: { side: "" as Side, name, parts: ordered } }];
  });
  found.sort((a, b) => a.first - b.first || a.index - b.index);
  return found.map(({ named }) => named);
}
