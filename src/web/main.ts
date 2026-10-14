// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The lookup page. All generation happens in ../core; this file only reads
// the form, renders the description and keeps the URL shareable.

import "./styles.css";

import {
  AddressError,
  describeSystem,
  GALAXY_COUNT,
  galaxyLabel,
  galaxyName,
  formatPortalCode,
  parseAnyAddress,
  parseGalaxyNumber,
  type PartsInfo,
  type ShipGroup,
  type ShipsInfo,
  type SystemDescription,
} from "../core";

const form = document.querySelector<HTMLFormElement>("#lookup")!;
const addressInput = document.querySelector<HTMLInputElement>("#address")!;
const galaxyInput = document.querySelector<HTMLInputElement>("#galaxy")!;
const galaxyHint = document.querySelector<HTMLParagraphElement>("#galaxy-hint")!;
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

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * The address of this page with a system in it, which opens the site on that system. Its galaxy
 * parameter is the galaxy's index, counting from 0 like the game, as in the links the site gave
 * before it numbered galaxies from 1, so that those still open the same system.
 */
function systemLink(portalCode: string, galaxy: number): URL {
  const url = new URL(window.location.href);
  url.searchParams.set("address", portalCode);
  url.searchParams.set("galaxy", String(galaxy));
  return url;
}

/** The galaxy number the form shows for a link's galaxy parameter (see systemLink). */
function galaxyNumberText(parameter: string | null): string {
  const index = (parameter ?? "0").trim();
  return /^[0-9]+$/.test(index) ? String(Number(index) + 1) : index;
}

/** Under the galaxy field, the name of the galaxy whose number is in it. */
function showGalaxyName(): void {
  try {
    galaxyHint.textContent = galaxyName(parseGalaxyNumber(galaxyInput.value));
  } catch {
    galaxyHint.textContent = `From 1 (Euclid) to ${GALAXY_COUNT}.`;
  }
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

/** Only the system's star color is known, so a system with more than one star says so of the others. */
const OTHER_STARS: Record<number, string> = {
  2: "The other star's color isn't worked out yet.",
  3: "The other two stars' colors aren't worked out yet.",
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

/** Parts as the game names them, less the leading underscore. */
function partsText(parts: readonly string[]): string {
  return parts.map((part) => part.replace(/^_/, "")).join(", ");
}

/** A ship's parts, one line per model it could be built from, each said which where there are two. */
function partsLines(models: readonly PartsInfo[], className: string): HTMLElement[] {
  return models.map(({ model, parts }) => {
    const which = models.length > 1 ? `As a ${model.toLowerCase()}: ` : "";
    return el("dd", className, which + partsText(parts));
  });
}

/** The full ship list: each group's ships, every one a type with its seed and parts. */
function shipList(ships: ShipsInfo): HTMLElement {
  const groups = el("div", "ships");
  for (const [group, heading] of SHIP_GROUPS) {
    const members = ships.ships.filter((s) => s.group === group);
    if (!members.length) continue;
    const list = el("dl", "ships__list");
    for (const s of members) {
      const row = el("div", "ships__row", el("dt", "ships__type", s.type), el("dd", "ships__seed", s.seed));
      row.append(...partsLines(s.parts, "ships__parts"));
      if (s.note) row.append(el("dd", "ships__note", s.note));
      list.append(row);
    }
    groups.append(el("section", "ships__group", el("h4", "ships__heading", heading), list));
  }
  return groups;
}

/**
 * A ship's seed and parts in the key, then the seed and parts it would have
 * if the system's two-moon planets had their moons the other way round.
 */
function keyShip(seed: string, parts: readonly string[], others: { seed: string; parts: readonly string[] }[]): Node[] {
  return [
    el("span", "manifest__note", `Seed ${seed}`),
    el("span", "manifest__note", partsText(parts)),
    ...others.flatMap((other) => [
      el("span", "manifest__note", `Or seed ${other.seed}, with the moons the other way round`),
      el("span", "manifest__note", partsText(other.parts)),
    ]),
  ];
}

/** Whether an exotic is a squid, as running text reads it. */
function squidPhrase(squid: boolean): string {
  return squid ? "a squid" : "not a squid";
}

/**
 * The exotic in the key: whether it's a squid, for each way the system's
 * two-moon planets can have their moons arranged, then its seed and parts.
 */
function exoticEntry(ships: ShipsInfo): HTMLElement {
  const calls = [ships.exoticSquid, ...ships.alternatives.map((a) => a.exoticSquid)];
  const [first, ...others] = calls.map(squidPhrase);
  let verdict = first === "a squid" ? "Squid" : "Not a squid";
  if (others.length) {
    const different = [...new Set(others)].filter((phrase) => phrase !== first);
    verdict += different.length
      ? `, or ${different.join(" or ")} with the moons ${others.length > 1 ? "another" : "the other"} way round`
      : ", whichever way round the moons are";
  }

  const arranged = ships.alternatives.map((a) => ({ seed: a.exotic, parts: a.exoticParts }));
  return el("dd", undefined, verdict, ...keyShip(ships.exotic, ships.exoticParts, arranged));
}

function shipsSection(d: SystemDescription): HTMLElement {
  const ships = d.ships;
  const warning = ships.uncertain
    ? [
        el(
          "p",
          "result__warning",
          `Less certain here: this system has ${ships.uncertain}, and every seed depends on which. The exotic and ` +
            `crash-site ship for ${ships.alternatives.length > 1 ? "the other ways" : "the other way"} are given too.`,
        ),
      ]
    : [];

  const key = el("dl", "manifest");
  key.append(
    el("dt", undefined, "Exotic"),
    exoticEntry(ships),
    el("dt", undefined, "Sentinel crash-site ship"),
    el(
      "dd",
      undefined,
      ...keyShip(
        ships.crashSite,
        ships.crashSiteParts,
        ships.alternatives.map((a) => ({ seed: a.crashSite, parts: a.crashSiteParts })),
      ),
    ),
  );
  const all = el(
    "details",
    "ships-all",
    el("summary", "ships-all__summary", `The game's full list (${ships.ships.length} slots)`),
    shipList(ships),
  );

  return el("section", "result__section", el("h3", "result__heading", "Ships"), ...warning, key, all);
}

/** The system's own multi-tools: the first run of its set, each with its seed and parts. */
function multitoolsSection(d: SystemDescription): HTMLElement {
  const key = el("dl", "manifest");
  let standard = 0;
  for (const tool of d.multitools) {
    const term = tool.kind === "Standard" ? `Standard ${++standard}` : tool.kind;
    const parts = el("span", "manifest__note", partsText(tool.parts));
    key.append(el("dt", undefined, term), el("dd", undefined, tool.seed, parts));
  }
  const sale = d.uncharted || d.abandoned ? "" : "The space station sells one of the standard ones, most often the first. ";
  const intro = el("p", "result__aside", `${sale}Three more standard ones aren't worked out yet.`);
  return el("section", "result__section", el("h3", "result__heading", "Multi-tools"), key, intro);
}

function render(d: SystemDescription): void {
  document.documentElement.dataset.star = d.starColor;

  const name = el("h2", "result__name result__name--fresh", d.name);
  const region = el("p", "result__region", `${d.region}, ${galaxyLabel(d.galaxy)}`);

  const flags: string[] = [];
  if (d.stars > 1) flags.push(`${MULTIPLE_STARS[d.stars]} star system`);
  if (d.blackHole) flags.push("Black hole system");
  if (d.atlasInterface) flags.push("Atlas Interface system");
  if (d.gasGiant) flags.push("Giant planet system");
  const flagList = el("ul", "result__flags");
  for (const f of flags) flagList.append(el("li", "result__flag", f));

  const manifest = el("dl", "manifest");
  const row = (term: string, value: Node | string, note?: string) => {
    const dd = el("dd", undefined, value);
    if (note) dd.append(el("span", "manifest__note", note));
    manifest.append(el("dt", undefined, term), dd);
  };

  row("Star color", el("span", undefined, el("span", "swatch"), d.starColor));
  row("Stars", String(d.stars), OTHER_STARS[d.stars]);
  row("Faction", d.faction);
  if (!d.uncharted) {
    row("Economy", d.economy);
    row("Wealth", d.wealth);
    row("Conflict", d.conflict);
  }
  if (d.pirate) row("Outlaws", "Likely outlaw-controlled");
  if (d.uncharted || d.abandoned) row("Guild envoy", `${d.guild} (the region's)`);
  else row("Guild envoy", d.guild, "The same in every space station of the region.");
  row("Bodies", `${plural(d.planetCount, "planet", "planets")}, ${plural(d.moonCount, "moon", "moons")}`);
  row("Portal address", d.portalCode);
  row("Galactic coordinates", d.galacticCoordinates);

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
    el("p", undefined, "The colors of every ship and multi-tool. ", roadmap, "."),
  );

  const header = el("header", "result__header", name, region, ...(flags.length ? [flagList] : []), actions);
  const facts = el("div", "result__facts", manifest);

  result.replaceChildren(
    header,
    el("div", "result__columns", facts, bodiesSection),
    shipsSection(d),
    multitoolsSection(d),
    next,
  );
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
    galaxy = parseGalaxyNumber(galaxyText);
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
galaxyInput.addEventListener("input", showGalaxyName);

// Restore a shared link, or start on the Pilgrim Star (064A:0082:01B9:009A on a signal booster) in Euclid.
// The site shows generated names, not the ones players give, so an intro says which system this is.
const DEFAULT_ADDRESS = "009A039BAE4B";
const params = new URLSearchParams(window.location.search);
const sharedAddress = params.get("address");
if (sharedAddress) {
  galaxyInput.value = galaxyNumberText(params.get("galaxy"));
  showGalaxyName();
  addressInput.value = sharedAddress;
  lookup(sharedAddress, galaxyInput.value, false);
} else {
  galaxyInput.value = "1";
  showGalaxyName();
  lookup(DEFAULT_ADDRESS, galaxyInput.value, false);
  result.prepend(
    el(
      "p",
      "result__intro",
      "An example to start with: the system its discoverer named the Pilgrim Star. Enter any other address above.",
    ),
  );
}
