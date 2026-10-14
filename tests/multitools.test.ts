// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A system's first run of multi-tools against tools/captures/multitool_model.py,
// the Python model it ports, over the made-up addresses in
// tests/fixtures/multitool-vectors.json (written by
// tools/crosscheck/multitool_vectors.py). tests/crosscheck.test.ts compares
// the two over thousands more when CROSSCHECK_FILE is set.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  describeSystem,
  distinguishingParts,
  hex64,
  MULTITOOL_MODELS,
  multitoolRun,
  parsePortalCode,
  universalAddress,
} from "../src/core";

interface MultitoolVector {
  code: string;
  galaxy: number;
  /** [model file, seed] of each multi-tool, in the game's order. */
  run: [string, string][];
}

const file = JSON.parse(readFileSync(new URL("./fixtures/multitool-vectors.json", import.meta.url), "utf8")) as {
  vectors: MultitoolVector[];
};

describe("multi-tool vectors from the Python model", () => {
  it("has three systems with each number of standard multi-tools", () => {
    const standard = file.vectors.map((v) => v.run.filter(([name]) => name === "MULTITOOL").length);
    expect(standard).toEqual([2, 2, 2, 3, 3, 3, 4, 4, 4]);
  });

  for (const v of file.vectors) {
    it(`${v.code} in galaxy ${v.galaxy}: ${v.run.length} multi-tools`, () => {
      const code = parsePortalCode(v.code);
      const run = multitoolRun(universalAddress(code, v.galaxy));
      expect(run.map((tool) => [MULTITOOL_MODELS[tool.kind], hex64(tool.seed)])).toEqual(v.run);
      expect(describeSystem(code, v.galaxy).multitools).toEqual(
        run.map((tool) => ({
          kind: tool.kind,
          seed: `0x${hex64(tool.seed)}`,
          parts: distinguishingParts(MULTITOOL_MODELS[tool.kind], tool.seed),
        })),
      );
    });
  }
});

describe("a system's first run of multi-tools", () => {
  it("ends with the royal, the Sentinel and the Atlas one", () => {
    for (const v of file.vectors) {
      const kinds = multitoolRun(universalAddress(parsePortalCode(v.code), v.galaxy)).map((tool) => tool.kind);
      expect(kinds.slice(-3)).toEqual(["Royal", "Sentinel", "Atlas"]);
      expect(new Set(kinds.slice(0, -3))).toEqual(new Set(["Standard"]));
    }
  });

  it("doesn't depend on the planet digit", () => {
    const at = (code: string) => multitoolRun(universalAddress(parsePortalCode(code), 0));
    expect(at("509A039BAE4B")).toEqual(at("009A039BAE4B"));
  });
});
