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
  describeSystem,
  formatPortalCode,
  MEASURED_ACCURACY,
  parseAnyAddress,
  parseGalaxy,
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
  if (d.pirate) row("Outlaws", "Likely outlaw-controlled", "Not yet checked against the game.");
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
      "Names and order come straight from the generator and haven't been checked against the game yet. " +
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
    el("h3", "result__heading", "Ships and multi-tools"),
    el(
      "p",
      undefined,
      "Not yet. The next step records the real ship pool of systems as players visit them, " +
        "then works out the formula the game uses. ",
      roadmap,
      ".",
    ),
  );

  result.replaceChildren(name, region, ...(flags.length ? [flagList] : []), manifest, accuracy, bodiesSection, actions, next);
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
