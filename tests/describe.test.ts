// SPDX-License-Identifier: AGPL-3.0-or-later
//
// What the description says of a system's faction, economy, wealth and
// conflict: what the game's galaxy map shows. The addresses are made up, one
// of each kind of system, as nms_namegen's attributes make them.

import { describe, expect, it } from "vitest";
import { describeSystem, OUTLAW_CONFLICT, OUTLAW_WEALTH, parsePortalCode, systemAttributes } from "../src/core";

const at = (code: string) => {
  const portal = parsePortalCode(code);
  return { attributes: systemAttributes(portal, 0), description: describeSystem(portal, 0, 20_000) };
};

describe("a system's faction, economy, wealth and conflict", () => {
  it("are the generator's for a charted system", () => {
    const { attributes, description } = at("02BD21C11519");
    expect([attributes.uncharted, attributes.abandoned, attributes.pirate]).toEqual([false, false, false]);
    expect(description).toMatchObject({ faction: "Gek", economy: "Manufacturing", wealth: "Medium", conflict: "High" });
  });

  it("are the game's words for an outlaw system's wealth and conflict", () => {
    const { attributes, description } = at("03A75FD09E28");
    expect(attributes.pirate).toBe(true);
    expect(description).toMatchObject({
      faction: "Vy'keen",
      economy: "Scientific",
      wealth: OUTLAW_WEALTH,
      conflict: OUTLAW_CONFLICT,
      pirate: true,
    });
    expect([OUTLAW_WEALTH, OUTLAW_CONFLICT]).toEqual(["Black Market", "Pirate Controlled"]);
  });

  it("are unavailable in an abandoned system, whose race comes first", () => {
    const { attributes, description } = at("02B9DF3FA92A");
    expect(attributes.abandoned).toBe(true);
    expect(description).toMatchObject({
      faction: "Gek (Abandoned)",
      economy: "None",
      wealth: "None",
      conflict: "None",
    });
  });

  it("are unavailable in an uncharted system", () => {
    const { attributes, description } = at("038DCFEF062B");
    expect(attributes.uncharted).toBe(true);
    expect(description).toMatchObject({ faction: "Uncharted", economy: "None", wealth: "None", conflict: "None" });
  });
});
