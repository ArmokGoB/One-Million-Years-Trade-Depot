// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Which guild's envoy a system's space station has, from its address alone:
// a port of tools/captures/guild_model.py, which the capture report checks
// against every guild the capture mod records. tests/guild.test.ts holds
// this port to it.
//
// The first draw of the generator seeded with the system's universal
// address, scaled to three, picks the guild, in the order the game lists
// them: its Trade, Warrior and Explorer guilds. That draw hardly depends on
// anything but the address's low 32 bits, the region's coordinates, so a
// region's stations all have the same guild.

import { seededPRNG } from "./prng";

/** The three guilds, in the game's order. */
export const GUILDS = ["Merchants", "Mercenaries", "Explorers"] as const;
export type Guild = (typeof GUILDS)[number];

/** The guild whose envoy the space station of the system at universal address `ua` has. */
export function guildFor(ua: bigint): Guild {
  return GUILDS[seededPRNG(ua).random(GUILDS.length)] as Guild;
}
