// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The lookup page. All generation happens in ../core; this file only reads
// the form, renders the description and keeps the URL shareable.

import "./styles.css";

import {
  AddressError,
  CAPTURE_CHECKS,
  describeSystem,
  formatPortalCode,
  MEASURED_ACCURACY,
  parseAnyAddress,
  parseGalaxy,
  SHIP_ACCURACY,
  SOLAR_COUNTS,
  SQUID_CHECKS,
  SQUID_EDGES,
  STAR_CHECKS,
  type ShipGroup,
  type ShipsInfo,
  type SquidCall,
  type SystemDescription,
} from "../core";

const form = document.querySelector<HTMLFormElement>("#lookup")!;
const addressInput = document.querySelector<HTMLInputElement>("#address")!;
const galaxyInput = document.querySelector<HTMLInputElement>("#galaxy")!;
const errorBox = document.querySelector<HTMLParagraphElement>("#lookup-error")!;
const result = document.querySelector<HTMLElement>("#result")!;

/** Small DOM helper: element with optional class and children. */
function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  ...children: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children);
  return node;
}

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Small counts in words, as running text reads them. */
function count(n: number): string {
  return ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"][n] ?? String(n);
}

/** The address of this page with a system in it, which opens the site on that system. */
function systemLink(portalCode: string, galaxy: number): URL {
  const url = new URL(window.location.href);
  url.searchParams.set("address", portalCode);
  url.searchParams.set("galaxy", String(galaxy));
  return url;
}

function galaxyLabel(galaxy: number): string {
  return galaxy === 0 ? "0 (Euclid)" : String(galaxy);
}

function showError(message: string, field: HTMLInputElement): void {
  errorBox.textContent = message;
  errorBox.hidden = false;
  field.setAttribute("aria-invalid", "true");
  field.focus();
}

function clearError(): void {
  errorBox.hidden = true;
  errorBox.textContent = "";
  addressInput.removeAttribute("aria-invalid");
  galaxyInput.removeAttribute("aria-invalid");
}

/** What a system with more than one star is called, by how many. */
const MULTIPLE_STARS: Record<number, string> = { 2: "Binary", 3: "Trinary" };

/** Only the system's star colour is known, so a system with more than one star says so of the others. */
const OTHER_STARS: Record<number, string> = {
  2: "The other star's colour isn't worked out yet.",
  3: "The other two stars' colours aren't worked out yet.",
};

/** The order and headings of the full ship list. */
const SHIP_GROUPS: readonly (readonly [ShipGroup, string])[] = [
  ["civilian", "Civilian ships"],
  ["exotic", "Exotic"],
  ["freighter", "Freighters"],
  ["frigate", "Frigates"],
  ["sentinel", "Sentinels"],
  ["pirate", "Pirates"],
  ["swarm", "Swarm"],
  ["corvette", "Corvette"],
];

/** The full ship list: each group's ships, every one a type with its seed. */
function shipList(ships: ShipsInfo): HTMLElement {
  const groups = el("div", "ships");
  for (const [group, heading] of SHIP_GROUPS) {
    const members = ships.ships.filter((s) => s.group === group);
    if (!members.length) continue;
    const list = el("dl", "ships__list");
    for (const s of members) {
      const row = el("div", "ships__row", el("dt", "ships__type", s.type), el("dd", "ships__seed", s.seed));
      if (s.note) row.append(el("dd", "ships__note", s.note));
      list.append(row);
    }
    groups.append(el("section", "ships__group", el("h4", "ships__heading", heading), list));
  }
  return groups;
}

/** A seed in the key, with the seeds it would be if the system's two-moon planets were arranged otherwise. */
function keySeed(seed: string, others: string[]): HTMLElement {
  const dd = el("dd", undefined, seed);
  if (others.length) dd.append(el("span", "manifest__note", `or ${others.join(" or ")}, with the moons the other way round`));
  return dd;
}

/** Whether an exotic is a squid, as running text reads it: "probably" where its seed is too close to call. */
function squidPhrase(call: SquidCall): string {
  const verdict = call.squid ? "a squid" : "not a squid";
  return call.close ? `probably ${verdict}` : verdict;
}

/** How many exotics in one fall where the line between squids and the rest could still be, roughly. */
const closeOdds = Math.round(2 ** 32 / (SQUID_EDGES.squid - SQUID_EDGES.notSquid - 1) / 100) * 100;

/**
 * The exotic in the key: whether it's a squid, then its seed, for each way
 * the system's two-moon planets can have their moons arranged.
 */
function exoticEntry(ships: ShipsInfo): HTMLElement {
  const calls = [ships.exoticSquid, ...ships.alternatives.map((a) => a.exoticSquid)];
  const [first, ...others] = calls.map(squidPhrase);
  let verdict = first === "a squid" ? "Squid" : first!.charAt(0).toUpperCase() + first!.slice(1);
  if (others.length) {
    const different = [...new Set(others)].filter((phrase) => phrase !== first);
    verdict += different.length
      ? `, or ${different.join(" or ")} with the moons ${others.length > 1 ? "another" : "the other"} way round`
      : ", whichever way round the moons are";
  }

  const seeds = el("span", "manifest__note", `Seed ${ships.exotic}`);
  if (ships.alternatives.length) {
    seeds.append(`, or ${ships.alternatives.map((a) => a.exotic).join(" or ")} with the moons the other way round`);
  }
  const dd = el("dd", undefined, verdict, seeds);

  const close = calls.filter((call) => call.close).length;
  if (close) {
    const which =
      close === calls.length
        ? calls.length === 1
          ? "Its seed falls"
          : "These seeds fall"
        : close === 1
          ? "One of these seeds falls"
          : "Some of these seeds fall";
    dd.append(
      el(
        "span",
        "manifest__note",
        `${which} in the narrow stretch, about 1 exotic in ${closeOdds}, where the line between squids and ` +
          `other exotics hasn't been pinned down.`,
      ),
    );
  }
  return dd;
}

function shipsSection(d: SystemDescription): HTMLElement {
  const ships = d.ships;
  const { matched, recorded } = SHIP_ACCURACY;
  const intro = el(
    "p",
    "result__aside",
    `Predicted from the address alone, by a model of the game's generator worked out from ` +
      `${recorded} systems recorded in game. It gets every ship's seed right in ${matched} of them. ` +
      `The other ${count(recorded - matched)} each have a planet with two moons, which the game arranges in one ` +
      `of two ways, and match once they're the other way round.`,
  );
  const { firstGuess, recorded: twoMoonSystems } = SHIP_ACCURACY.twoMoons;
  const warning = ships.uncertain
    ? [
        el(
          "p",
          "result__warning",
          `Less certain here: this system has ${ships.uncertain}, and every seed depends on which. ` +
            `The model can't tell yet. The list assumes the way that was right in ${count(firstGuess)} of the ` +
            `${count(twoMoonSystems)} such systems recorded; the exotic and crash-site seeds for ` +
            `${ships.alternatives.length > 1 ? "the other ways" : "the other way"} are given too.`,
        ),
      ]
    : [];

  const key = el("dl", "manifest");
  key.append(
    el("dt", undefined, "Exotic"),
    exoticEntry(ships),
    el("dt", undefined, "Sentinel crash-site ship"),
    keySeed(
      ships.crashSite,
      ships.alternatives.map((a) => a.crashSite),
    ),
  );
  const squids = el(
    "p",
    "result__aside",
    `Whether the exotic is a squid follows from its seed: the game picks the exotic's body with the first ` +
      `number it draws from that seed, and makes about 1 exotic in 21 a squid. That held for all ` +
      `${SQUID_CHECKS.recorded} exotics recorded in game, ${count(SQUID_CHECKS.squids)} of them squids.`,
  );

  const [shuttleSolar, shuttleSlots] = SOLAR_COUNTS.shuttle;
  const [outlawSolar, outlawSlots] = SOLAR_COUNTS.outlawShuttle;
  const [otherSolar, otherSlots] = SOLAR_COUNTS.outlawOther;
  const solar = d.pirate
    ? `In outlaw systems like this one, ${outlawSolar} of the ${outlawSlots} shuttle slots recorded held a solar ` +
      `ship, and so did ${otherSolar} of the ${otherSlots} other civilian slots.`
    : `Outside outlaw systems, ${shuttleSolar} of the ${shuttleSlots} shuttle slots recorded held a solar ship, ` +
      `and no other slot did.`;
  const all = el(
    "details",
    "ships-all",
    el("summary", "ships-all__summary", `The game's full list (${ships.ships.length} slots)`),
    el(
      "p",
      "result__aside",
      "This is the list the game builds for the system, laid out the same way in every system recorded so far. " +
        "Not every slot is a ship you can meet there: it holds a frigate of every type, including types " +
        "whose only known frigates are expedition rewards. " +
        "Only the civilian slots vary: how many haulers, fighters and explorers depends on the dominant race, " +
        "and the game makes some of them solar ships in a way not worked out yet. " +
        solar,
    ),
    shipList(ships),
  );

  return el("section", "result__section", el("h3", "result__heading", "Ships"), ...warning, key, intro, squids, all);
}

function render(d: SystemDescription): void {
  document.documentElement.dataset.star = d.starColour;

  const name = el("h2", "result__name result__name--fresh", d.name);
  const region = el("p", "result__region", `${d.region}, galaxy ${galaxyLabel(d.galaxy)}`);

  const flags: string[] = [];
  if (d.stars > 1) flags.push(`${MULTIPLE_STARS[d.stars]} star system`);
  if (d.blackHole) flags.push("Black hole system");
  if (d.atlasInterface) flags.push("Atlas Interface system");
  if (d.gasGiant) flags.push("Gas giant layout");
  const flagList = el("ul", "result__flags");
  for (const f of flags) flagList.append(el("li", "result__flag", f));

  const manifest = el("dl", "manifest");
  const row = (term: string, value: Node | string, note?: string) => {
    const dd = el("dd", undefined, value);
    if (note) dd.append(el("span", "manifest__note", note));
    manifest.append(el("dt", undefined, term), dd);
  };

  row("Star colour", el("span", undefined, el("span", "swatch"), d.starColour));
  row("Stars", String(d.stars), OTHER_STARS[d.stars]);
  row("Faction", d.faction);
  if (!d.uncharted) {
    row("Economy", d.economy);
    row("Wealth", d.wealth);
    row("Conflict", d.conflict);
  }
  const checks = CAPTURE_CHECKS;
  if (d.pirate) {
    row(
      "Outlaws",
      "Likely outlaw-controlled",
      `Matched the game in all ${checks.systems} systems recorded so far, ` +
        `${count(checks.outlawSystems)} of them outlaw systems.`,
    );
  }
  row("Bodies", `${plural(d.planetCount, "planet", "planets")}, ${plural(d.moonCount, "moon", "moons")}`);
  row("Portal address", d.portalCode);
  row("Galactic coordinates", d.galacticCoordinates);

  const a = MEASURED_ACCURACY;
  const lowest = Math.min(a.starColour, a.dominantRace, a.economy, a.wealth, a.conflict, a.planetAndMoonCounts);
  const accuracy = el(
    "p",
    "result__aside",
    `Star colour, faction, economy, wealth, conflict and body counts each match at least ${pct(lowest)} ` +
      `of 1,000 systems players recorded in game ` +
      `(star colour and faction ${pct(a.starColour)}, economy ${pct(a.economy)}, ` +
      `wealth ${pct(a.wealth)}, conflict ${pct(a.conflict)}, planet and moon counts ${pct(a.planetAndMoonCounts)}). ` +
      `The number of stars is worked out the way the game counts them, with its chances of a second star ` +
      `(1 in 5) and a third (1 in 20), and matched the game in all ${STAR_CHECKS.counted} systems whose stars ` +
      `the capture mod counted, ${count(STAR_CHECKS.several)} of them with more than one.`,
  );

  const bodies = el("ol", "bodies");
  for (const b of d.bodies) {
    bodies.append(
      el(
        "li",
        "bodies__item",
        el("span", "bodies__number", String(b.index)),
        el("span", "bodies__name", b.name),
        el("span", "bodies__meta", `Portal ${b.portalCode}`),
        el("span", "bodies__meta", `Seed ${b.seed}`),
      ),
    );
  }
  const bodiesSection = el(
    "section",
    "result__section result__bodies",
    el("h3", "result__heading", "Planets and moons"),
    bodies,
    el(
      "p",
      "result__aside",
      `Names and order come straight from the generator. Checked against the game so far: the order in all ` +
        `${checks.systems} systems recorded, and ${checks.planetNames.matched.toLocaleString("en")} of ` +
        `${checks.planetNames.checked.toLocaleString("en")} planet names. ` +
        "The seed is what a save editor calls the planet seed.",
    ),
  );

  const status = el("span", "result__status");
  status.setAttribute("role", "status");
  const copy = el("button", "button-secondary", "Copy link to this system");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    // Built from the system shown, since the page's own address has none on the default system.
    const link = systemLink(d.portalCode, d.galaxy).href;
    try {
      await navigator.clipboard.writeText(link);
      status.textContent = "Link copied.";
    } catch {
      const anchor = el("a", undefined, link);
      anchor.href = link;
      status.replaceChildren("Couldn't copy. Here is the link: ", anchor);
    }
  });
  const actions = el("div", "result__actions", copy, status);

  const roadmap = el("a", undefined, "Follow the roadmap");
  roadmap.href = "https://github.com/ArmokGoB/One-Million-Years-Trade-Depot#roadmap";
  const next = el(
    "section",
    "result__section result__next",
    el("h3", "result__heading", "Coming next"),
    el("p", undefined, "The rest of what each ship looks like, then multi-tools. ", roadmap, "."),
  );

  const header = el("header", "result__header", name, region, ...(flags.length ? [flagList] : []), actions);
  const facts = el("div", "result__facts", manifest, accuracy);

  result.replaceChildren(header, el("div", "result__columns", facts, bodiesSection), shipsSection(d), next);
  result.hidden = false;
}

function lookup(addressText: string, galaxyText: string, updateUrl: boolean): void {
  clearError();
  let code: bigint;
  let galaxy: number;
  try {
    code = parseAnyAddress(addressText);
  } catch (e) {
    showError(e instanceof AddressError ? e.message : "That address couldn't be read.", addressInput);
    return;
  }
  try {
    galaxy = parseGalaxy(galaxyText);
  } catch (e) {
    showError(e instanceof AddressError ? e.message : "That galaxy number couldn't be read.", galaxyInput);
    return;
  }

  const description = describeSystem(code, galaxy);
  addressInput.value = formatPortalCode(code);
  render(description);

  if (updateUrl) window.history.replaceState(null, "", systemLink(description.portalCode, galaxy));
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  lookup(addressInput.value, galaxyInput.value, true);
});

// Restore a shared link, or start on the Pilgrim Star (064A:0082:01B9:009A on a signal booster) in Euclid.
// The site shows generated names, not the ones players give, so an intro says which system this is.
const DEFAULT_ADDRESS = "009A039BAE4B";
const params = new URLSearchParams(window.location.search);
const sharedAddress = params.get("address");
if (sharedAddress) {
  galaxyInput.value = params.get("galaxy") ?? "0";
  addressInput.value = sharedAddress;
  lookup(sharedAddress, galaxyInput.value, false);
} else {
  galaxyInput.value = "0";
  lookup(DEFAULT_ADDRESS, galaxyInput.value, false);
  result.prepend(
    el(
      "p",
      "result__intro",
      "An example to start with: the system its discoverer named the Pilgrim Star. Enter any other address above.",
    ),
  );
}
