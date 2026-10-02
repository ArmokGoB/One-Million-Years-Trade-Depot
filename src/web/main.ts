// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The lookup page. All generation happens in ../core; this file only reads
// the form, renders the description and keeps the URL shareable.

import "@fontsource/big-shoulders-stencil-display/800";
import "@fontsource/big-shoulders-stencil-display/900";
import "@fontsource-variable/atkinson-hyperlegible-next";
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
  type ShipGroup,
  type ShipsInfo,
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

function shipTable(ships: ShipsInfo): HTMLTableElement {
  const table = el("table", "ships");
  const head = el("thead", "visually-hidden", el("tr", undefined, el("th", undefined, "Ship"), el("th", undefined, "Seed")));
  for (const th of head.querySelectorAll("th")) th.scope = "col";
  table.append(head);
  for (const [group, heading] of SHIP_GROUPS) {
    const members = ships.ships.filter((s) => s.group === group);
    if (!members.length) continue;
    const title = el("th", "ships__group", heading);
    title.scope = "rowgroup";
    title.colSpan = 2;
    const body = el("tbody", undefined, el("tr", undefined, title));
    for (const s of members) {
      const type = el("td", "ships__type", s.type);
      if (s.note) type.append(el("span", "ships__note", s.note));
      body.append(el("tr", undefined, type, el("td", "ships__seed seed", s.seed)));
    }
    table.append(body);
  }
  return table;
}

function shipsSection(d: SystemDescription): HTMLElement {
  const heading = el("h3", "result__heading", "Ships");
  if (!d.ships) {
    return el(
      "section",
      "result__section",
      heading,
      el(
        "p",
        "result__aside",
        "Not predicted for gas giant systems yet: the model doesn't cover how the game lays out " +
          "their planets, which decides where the ship seeds fall in its random numbers.",
      ),
    );
  }
  const ships = d.ships;
  const intro = el(
    "p",
    "result__aside",
    `Predicted from the address alone, by a model of the game's generator worked out from ` +
      `${SHIP_ACCURACY.recorded} systems recorded in game. It gets every ship's seed right in ` +
      `${SHIP_ACCURACY.matched} of them.`,
  );
  const { matched, recorded } = SHIP_ACCURACY.twoMoons;
  const warning = ships.uncertain
    ? [
        el(
          "p",
          "result__warning",
          `Less certain here: this system has ${ships.uncertain}. ` +
            `Of the ${count(recorded)} recorded systems with one, the model gets ${count(matched)} right.`,
        ),
      ]
    : [];

  const key = el("dl", "manifest manifest--ships");
  key.append(
    el("dt", undefined, "Exotic"),
    el("dd", "seed", ships.exotic),
    el("dt", undefined, "Sentinel crash-site ship"),
    el("dd", "seed", ships.crashSite),
  );

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
        "and the game picks between a shuttle and a solar ship in a way not worked out yet.",
    ),
    shipTable(ships),
  );

  return el("section", "result__section", heading, intro, ...warning, key, all);
}

function render(d: SystemDescription): void {
  document.documentElement.dataset.star = d.starColour;

  const name = el("h2", "result__name result__name--fresh", d.name);
  const region = el("p", "result__region", `${d.region}, galaxy ${galaxyLabel(d.galaxy)}`);

  const flags: string[] = [];
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

  row("Star", el("span", undefined, el("span", "swatch"), d.starColour));
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
    "result__aside manifest__accuracy",
    `Star colour, faction, economy, wealth, conflict and body counts each match at least ${pct(lowest)} ` +
      `of 1,000 systems players recorded in game ` +
      `(star colour and faction ${pct(a.starColour)}, economy ${pct(a.economy)}, ` +
      `wealth ${pct(a.wealth)}, conflict ${pct(a.conflict)}, planet and moon counts ${pct(a.planetAndMoonCounts)}).`,
  );

  const bodies = el("ol", "bodies");
  for (const b of d.bodies) {
    bodies.append(
      el(
        "li",
        "bodies__item",
        el("span", "bodies__number", String(b.index)),
        el("span", "bodies__name", b.name),
        el("span", "bodies__meta", `Portal ${b.portalCode}, seed ${b.seed}`),
      ),
    );
  }
  const bodiesSection = el(
    "section",
    "result__section",
    el("h3", "result__heading", "Planets and moons"),
    el(
      "p",
      "result__aside",
      `Names and order come straight from the generator. Checked against the game so far: the order in all ` +
        `${checks.systems} systems recorded, and ${checks.planetNames.matched.toLocaleString("en")} of ` +
        `${checks.planetNames.checked.toLocaleString("en")} planet names. ` +
        "The seed is what a save editor calls the planet seed.",
    ),
    bodies,
  );

  const status = el("span", "result__status");
  status.setAttribute("role", "status");
  const copy = el("button", "button-secondary", "Copy link to this system");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      status.textContent = "Link copied.";
    } catch {
      status.textContent = "Couldn't copy. Use the address bar instead.";
    }
  });
  const actions = el("div", "result__actions", copy, status);

  const roadmap = el("a", undefined, "Follow the roadmap");
  roadmap.href = "https://github.com/ArmokGoB/One-Million-Years-Trade-Depot#roadmap";
  const next = el(
    "section",
    "result__section result__next",
    el("h3", "result__heading", "Coming next"),
    el("p", undefined, "What each ship looks like, starting with the exotic, then multi-tools. ", roadmap, "."),
  );

  result.replaceChildren(
    name,
    region,
    ...(flags.length ? [flagList] : []),
    manifest,
    accuracy,
    bodiesSection,
    shipsSection(d),
    actions,
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
    galaxy = parseGalaxy(galaxyText);
  } catch (e) {
    showError(e instanceof AddressError ? e.message : "That galaxy number couldn't be read.", galaxyInput);
    return;
  }

  const description = describeSystem(code, galaxy);
  addressInput.value = formatPortalCode(code);
  render(description);

  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("address", description.portalCode);
    url.searchParams.set("galaxy", String(galaxy));
    window.history.replaceState(null, "", url);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  lookup(addressInput.value, galaxyInput.value, true);
});

// Restore a shared link.
const params = new URLSearchParams(window.location.search);
const sharedAddress = params.get("address");
if (sharedAddress) {
  galaxyInput.value = params.get("galaxy") ?? "0";
  addressInput.value = sharedAddress;
  lookup(sharedAddress, galaxyInput.value, false);
}
