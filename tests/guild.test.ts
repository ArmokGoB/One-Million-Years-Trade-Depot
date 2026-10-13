// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The guild against tools/captures/guild_model.py, the Python model it ports,
// over the made-up addresses in tests/fixtures/guild-vectors.json (written by
// tools/crosscheck/guild_vectors.py). tests/crosscheck.test.ts compares the
// two over thousands more when CROSSCHECK_FILE is set.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { describeSystem, guildFor, GUILDS, parsePortalCode, seededPRNG, universalAddress } from "../src/core";

interface GuildVector {
  code: string;
  galaxy: number;
  /** The first draw of the generator seeded with the system's universal address, in hex. */
  firstDraw: string;
  guild: string;
}

const file = JSON.parse(readFileSync(new URL("./fixtures/guild-vectors.json", import.meta.url), "utf8")) as {
  vectors: GuildVector[];
};

describe("guild vectors from the Python model", () => {
  it("has four systems with each guild", () => {
    expect(file.vectors.map((v) => v.guild)).toEqual(GUILDS.flatMap((guild) => [guild, guild, guild, guild]));
  });

  for (const v of file.vectors) {
    it(`${v.code} in galaxy ${v.galaxy}: ${v.guild}`, () => {
      const code = parsePortalCode(v.code);
      const ua = universalAddress(code, v.galaxy);
      expect(seededPRNG(ua).randi().toString(16).toUpperCase().padStart(8, "0")).toBe(v.firstDraw);
      expect(guildFor(ua)).toBe(v.guild);
      expect(describeSystem(code, v.galaxy).guild).toBe(v.guild);
    });
  }
});

describe("guilds", () => {
  it("are in the game's order, a third of the first draw's range each", () => {
    expect(GUILDS).toEqual(["Merchants", "Mercenaries", "Explorers"]);
  });

  it("are the same for every system of a region", () => {
    const region = parsePortalCode("00000089ABCD");
    const systems = [0x001, 0x02a, 0x3e9, 0xfff].map((system) => region | (BigInt(system) << 32n));
    const guilds = new Set(systems.map((code) => guildFor(universalAddress(code, 5))));
    expect([...guilds]).toEqual(["Mercenaries"]);
  });
});
