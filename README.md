# One Million Years Trade Depot

A free, open-source website for No Man's Sky explorers. Give it a portal address and it tells you what that star system holds, worked out in your browser from the address alone, the same way the game generates it.

**Site:** https://armokgob.github.io/One-Million-Years-Trade-Depot/

## What it shows today

- System name, region name and the galaxy's name
- Star color, faction (or uncharted / abandoned), economy, wealth and conflict
- Which guild's envoy the region's space stations have: the Merchants, the Mercenaries or the Explorers
- How many stars it has, whether it's a binary or trinary system, and each star's color
- Whether it is a region's black hole or Atlas Interface system, or a system of one giant planet and its moons
- Planets and moons, with their procedural names and planet seeds
- The ship list the game builds for the system: 50 slots, each with its seed and type, the exotic's included, plus the seed the game keeps for the ship at its Sentinel crash sites. Not every slot is a ship you can meet there: the list has a frigate of every type, including Recon and Cursed, whose only known frigates (the SSV Normandy SR1 and the Ship of the Damned) are expedition rewards.
- The parts of each fighter, hauler, explorer and solar by the names the game gives them at a space station's Starship Fabricator, each with the part IDs it's made of
- The parts that set each ship apart, by the game's IDs for them: those of every civilian ship, the exotic, every freighter, the Sentinels' ship and freighter, and the pirates' fighters and capital freighter
- The colors the game paints each of those ships with, and most frigates and the swarm's frigate and drone, every color named in words
- The system's own multi-tools: the seeds, parts and colors of its 2 to 4 standard ones, and of its royal, Sentinel and Atlas one
- A shareable link for every lookup

It accepts a 12-digit portal address (`009A039BAE4B`) or signal-booster coordinates (`064A:0082:01B9:009A`), plus the galaxy's number, from 1 (Euclid) to 256. Both examples are the Pilgrim Star, which the site shows until you look up another system.

How often each field matches what players recorded in game, measured by nms_namegen against 1,000 hand-recorded post-Origins systems (2026-08-23):

| Field | Agreement |
|---|---|
| Star color | 99.1% |
| Uncharted system | 99.8% |
| Dominant race | 99.1% |
| Conflict level | 99.0% |
| Economy category | 99.0% |
| Wealth tier | 98.9% |
| Planet and moon counts | 98.4% |

System, region and planet names, the order of bodies, and the outlaw flag aren't covered by that measurement. The [capture mod](mods/README.md)'s records check them on a smaller sample: so far 109 of 117 system names, 147 of 148 region names and 7,139 of 7,414 planet names agree with the game, as do the order of bodies and the outlaw flag in all 123 systems recorded, 11 of them outlaw systems. Of the first 80 planet names that differed, 33 looked like the work of a filter for offensive words, which changes one letter; the site doesn't model it yet.

Some purple systems have a single giant planet, every other body its moon. nms_namegen predicts this layout, and it matched the game in all 123 systems recorded, 19 of them giant planet systems. Most giants are gas giants, but not all: of those 19, 17 were gas giants, 1 a lush giant and 1 a barren giant, and players report giants of other biomes too. What decides a giant's biome isn't known yet, so the site doesn't say which kind a system has.

How many stars a system has comes from the way the game counts them, which the capture mod's records showed: one star, a second when the system's `NebulaSeed`, a number between 0 and 1, is above 1 minus the game's binary star chance, 0.2, and a third when it's also above 1 minus its ternary star chance, 0.05. `NebulaSeed` is the 9th number the game draws from the system's address, as it was in all 139 systems recorded with their raw data, so about 1 system in 5 has a second star and 1 in 20 a third. Worked out from the address, the count matched the one the capture mod worked out from the game's own values in all 66 systems it counted, 15 of them with more than one star, and screenshots of 4 of those show as many stars as the site gives them. In the game's code, each sun has a color of its own: the main sun the system's star color, and each other sun the next of the game's five, yellow, green, blue, red and purple, in that order, going round; a binary and a trinary system's suns had those colors in the game. The site gives each star its color that way.

The ships come from this project's own model of the game's generator (roadmap step 3). It was worked out from the first 66 systems recorded and has held for the 80 recorded since: it gets all 50 ship seeds and the crash-site seed right in all 146. Where the seeds start in the game's random-number stream depends on where the planets' moons are, and a planet's two moons can sit either way round: the first at an azimuth of 0 and the second at 137.5 degrees, or the other way. The game decides as it places the planets: from a random-number stream seeded with the system's address, it draws the numbers that place the planets, then one for each of those planets with moons, and an even one puts the first moon at 137.5 degrees. Worked out that way, the moons of all 222 two-moon planets with attractors whose positions the capture mod recorded are where the game put them.

Every recorded system lists its ships in the same 50 slots; only the first 20, the civilian ships, change. How many haulers, fighters and explorers come first depends on the dominant race, and shuttles make up the rest. Then the game decides for each of them whether to make it a solar ship instead, as its code shows: it hashes the ship's seed with the system's address, seeds its random-number generator with the hash, and makes the ship solar if the first number it draws, as a fraction between 0 and 1, is below a chance the game sets. For a shuttle that chance is 0.1, or 0.85 in an outlaw system; for a hauler, fighter or explorer it's 0.1 in an outlaw system, and outside one the game never makes them solar. Worked out that way, all 2,920 civilian ships of the 146 systems recorded with their ships came out as the game made them, 174 of them solar.

Each ship's and multi-tool's parts come from its seed and from its model's descriptor, the game's lists of options for its parts, and the descriptors of the scenes those parts bring in. The game goes through the lists in order and picks one option from each with the next number it draws from the seed. In its code, each option weighs 20, one whose name has xRARE in it 1 and one with xNEVER 0, and the number scaled to the total weight falls on one of them, so a rare option is exactly a twentieth as likely as another, and one with xNEVER is never picked. A part with lists of its own, and each scene a part brings in, get seeds of their own from the next numbers, unless all they offer is options with xNEVER. A list that offers a part already picked is skipped: a shuttle's left wing offers the same options as its right wing, so only the right wing's are picked. Worked out that way, the parts matched those recorded, every one of them, for all 3,738 ships and multi-tools of these models the capture mod recorded.

The parts' names are the ones the game gives the parts of the ships a player can build at a space station's Starship Fabricator: fighters, haulers, explorers and solars. The game's tables list, for each slot of such a ship (its fuselage or cockpit, wings, thruster and sail), the components it takes, each named and made of a few of the parts a ship's descriptor picks; a ship's part is named for the component made of the parts it has. That names every slot of all 1,652 fighters, haulers, explorers and solars the capture mod recorded, but for the wings of 2 haulers, whose parts make a component the game has no name for; about 1 hauler in 260 has it. Explorers took more than the tables say. About half the explorers the game generates have a matched pair of wings, one wing for both sides, where an explorer built at the Fabricator has a wing for each side; such an explorer is named as one with the same wing on both sides. The Fabricator builds an explorer's right wing from copies of the generator's right-wing scenes, which let its subwings differ from the left wing's, and a copy has its original's nodes and materials, so a generated right wing is named for the copy it matches. And a generated explorer with separate wings never has the extra subwing some of the Fabricator's wings can have, so its wings are named for the versions without it. The capture mod doesn't record names, so they haven't been checked against what the game shows yet.

Their colors are the paint the game picks for them. The game makes 66 palettes of five colors from a seed: a starship's from its own seed, a freighter's, a frigate's and the rest of a fleet's from its system's address, and a multi-tool's from its own seed, the older way, from older palettes. Then each material of the model as built, with the parts it was given, brings in its texture lists: layers of options, each a texture tinted with a color of a palette. The game merges the layers of every material's lists, and a stream of numbers drawn from the model's seed decides which layers are painted and with which option. A texture hint picks some options out: the Sentinel ship of each system's list has the hint POLICE, the other ships none. Worked out that way, the paint matched every layer's texture and color for all 1,564 ships, freighters, frigates and multi-tools of these models whose paint versions 0.13.0 to 0.15.0 of the capture mod recorded. A frigate is painted at each level of detail; the site gives the closest one's colors.

That settles which exotics are squids: an exotic's first part is its body, and the squid's, `_SCLASSSHIP_SQU`, is a rare option against the other exotics' body, so the first number drawn from an exotic's seed makes it a squid in the top 1/21 of its range, about 1 exotic in 21, with no margin either way. All 87 exotics recorded agree, 11 of them squids.

Which guild's envoy a region's space stations have comes from the address too. The first number the game draws from a system's address, scaled to three, picks the Merchants, the Mercenaries or the Explorers, the order the game lists its Trade, Warrior and Explorer guilds in. That number hardly depends on anything but the region's part of the address, so the guild is the same throughout a region. It matched all 43 guild envoys recorded with the capture mod, in 31 regions of three galaxies. A seed of the region's part alone fits those as well; it would give another guild in about 1 system in 20,000.

A system's own multi-tools come from its address as well. The game builds them just before it generates the system, in two runs. The first comes from a random-number stream seeded the way nms_namegen seeds the planets' seeds: its first number picks how many standard multi-tools there are, 2, 3 or 4, and the next numbers give each one's seed, then the royal one's, the Sentinel one's and the Atlas one's. Worked out that way, the first run matched all 43 systems' sets the capture mod recorded, and all 32 multi-tools it recorded for sale, at space stations and the Nexus, were standard ones from it, 20 of them the first. The second run, three more standard multi-tools, comes from a seed not worked out yet. NMS.py names a kind of multi-tool pool SettlementRotational, so they are probably settlements' stock, which may change over time.

## Roadmap

1. **System lookup.** Done: this site.
2. **Capture mod.** In progress: [`mods/system_capture.py`](mods/system_capture.py), an [NMS.py](https://github.com/monkeyman192/NMS.py) mod that records, for every system a player enters, its address and the ship pool the game generates for it (`SystemShips` in the game's solar system data: each ship's seed and type). Version 0.10.0 added, when the player clicks a button, the guild of the region's space stations, which the site now works out from the address, and 0.11.0 how many stars a system has, worked out as the game's own star count function would, which the site now shows; 0.11.1 shows it on the mod's tab too. Version 0.12.0 records what the game makes the player's own ships and multi-tools from, to work out how it colors them, and 0.13.0 the paint the game picks for every ship of a system's list and the system's multi-tools, and the color variants the game draws a system's stars with. Since 0.14.0 it writes each session to a file of its own, named for the player's Steam ID and the time, and since 0.15.0 it no longer records what those records have settled: stars, the colors of suns, guilds, and ships' parts apart from their paint. Needs a Windows PC; [how to run it](mods/README.md).
3. **Address → ship pool.** Done: on the site. Every system captured so far has a 50-slot ship list with the same layout, with its one exotic in slot 20. [`tools/captures/ship_model.py`](tools/captures/ship_model.py) predicts all 50 ship seeds from the portal address alone, building on nms_namegen like the site does, and [`src/core/ships.ts`](src/core/ships.ts) is its port. It matched every ship and the Sentinel crash-site ship, and made the same civilian ships solar as the game did, in all 146 systems captured so far, giant planet systems included. The ships come last in a system's generation, after the space station and the "attractor" spawn points around each planet, and those, with the moons in their way, decide where in the random-number stream the ships' seeds start.
4. **Seed → appearance.** Done: each ship's parts and colors are on the site. The parts are picked as the game picks them from tables that [`tools/build_part_tables.py`](tools/build_part_tables.py) derives from the game's model descriptors, and checked against the parts version 0.7.0 of the capture mod and later record for each ship the game builds. The colors are the paint the game picks, worked out from tables that [`tools/build_paint_tables.py`](tools/build_paint_tables.py) derives from the game's palettes, scenes, materials and texture lists, and checked against the paint versions 0.13.0 and later record. A system's own colors, which the capture mod has recorded since version 0.2.0 with the rest of the system's data, come from the same palette generator with the system's address, and match all 139 systems recorded with their data; they show on the site as its freighters' and frigates' colors. The fighters', haulers', explorers' and solars' parts have the names the game's Starship Fabricator gives them, from tables that [`tools/build_part_names.py`](tools/build_part_names.py) derives from the game's own. Next: names for the other ships' and the multi-tools' parts.
5. **Multi-tools and freighters**, then pictures. The game builds each system's own multi-tools as you arrive, 8 to 10 per system in the captures so far. Version 0.11.0 of the capture mod records them, with each one's seed and parts, and it has for 43 systems so far. Since 0.9.0 it has also recorded the one a space station offers, with its seed, parts, class and inventory. The seeds of all but three of each system's multi-tools come from its address, and the site shows them with their parts and colors, as it does the freighters in each system's ship list. Next: the other three multi-tools, then each one's class. With the starships' parts and colors from step 4, this makes release 1.0: look up a system and scout the starships, freighters and multi-tools it generates without going there.
6. **Creatures**, after 1.0: the creatures each planet generates, with their colors and pattern, physical characteristics, aggression, genus, description and battle stats.

## How it works

`src/core` is a pure TypeScript library with no DOM, so other projects can use it too. It is a line-for-line port of [nms_namegen](https://github.com/hadsh/nms_namegen):

- the portal address and galaxy form the game's universal address;
- an index-primed PRNG (Threefish-style 64-bit mixing) turns that into the system seed;
- a 32-bit multiply-with-carry RNG then draws the system's attributes, names and body seeds in the game's order.

All 64-bit math uses `BigInt`, and float comparisons use `Math.fround` where the game compares in single precision.

The ships and the stars are this project's additions: `src/core/ships.ts` follows the same generator on, from the system's universal address through the space station and the planets' attractor spawn points to the ships, as `tools/captures/ship_model.py` does in Python; `src/core/parts.ts` picks each ship's and multi-tool's parts from its seed, as `tools/captures/parts_model.py` does, from `src/core/data/part-tables.json`, which `tools/build_part_tables.py` derives from the model descriptors in a player's own copy of the game; `src/core/partnames.ts` names a fighter's, hauler's, explorer's or solar's parts, as `tools/captures/part_names_model.py` does, from `src/core/data/part-names.json`, which `tools/build_part_names.py` derives from the Starship Fabricator's tables, the item tables and the English text in a player's copy of the game; `src/core/paint.ts` works out each one's palettes and paint, as `tools/captures/paint_model.py` does, from `src/core/data/paint-tables.json`, which `tools/build_paint_tables.py` derives from the palettes, scenes, materials and texture lists in a player's copy of the game, and `src/core/colornames.ts` names each color; `src/core/stars.ts` draws the system's `NebulaSeed` from its universal address and counts its stars the way the game does, and gives each its color, as `tools/captures/star_model.py` does.

Parity is checked two ways. `npm test` replays nms_namegen's 443 golden vectors through the port, the ship model's output for a set of addresses that covers every body layout it treats differently, the star model's for systems with one, two and three stars and for each star color, the guild model's for each guild, the multi-tool model's for each number of standard multi-tools, the parts and paint models' for made-up seeds of every model, and the part name model's for made-up seeds of each ship type it names. CI also generates 20,000 fresh cases with the Python library, pinned to a known commit, covering all 256 galaxies, every planet digit and the system indices where the generator branches, and compares every field, ships, stars, guilds, multi-tools, parts, paint and part names included.

## Development

```sh
npm install
npm run dev        # local site with hot reload
npm test           # golden vectors and unit tests
npm run build      # static site in dist/
```

Regenerate the data files and run the full cross-check (Python 3.13+ with numpy):

```sh
git clone https://github.com/hadsh/nms_namegen ../nms_namegen
python3 tools/build_name_tables.py --namegen ../nms_namegen
python3 tools/convert_golden_vectors.py --namegen ../nms_namegen
python3 tools/crosscheck/ship_vectors.py --namegen ../nms_namegen
python3 tools/crosscheck/star_vectors.py
python3 tools/crosscheck/guild_vectors.py
python3 tools/crosscheck/multitool_vectors.py
python3 tools/crosscheck/parts_vectors.py
python3 tools/crosscheck/paint_vectors.py
python3 tools/crosscheck/part_names_vectors.py
python3 tools/crosscheck/generate.py --namegen ../nms_namegen --count 20000 > crosscheck.jsonl
CROSSCHECK_FILE=crosscheck.jsonl npm test
```

The part, paint and part name tables come from the game's own files, which this repository doesn't hold. To rebuild them after a game update, extract the files from your copy of the game with [HGPAKtool](https://github.com/monkeyman192/HGPAKtool) and point the scripts at the folder it extracts them into: the model descriptors for the part tables; the scenes, descriptors, materials, texture lists and palettes for the paint tables; and the Starship Fabricator's tables, the item tables and the English text for the part name tables, which need the part tables built first. Every filter needs a `*`: HGPAKtool looks for a filter without one in every pak, and stops at the first pak that lacks it.

```sh
hgpaktool -U -f="*spacecraft/*.descriptor.mbin" -f="*weapons/multitool/*.descriptor.mbin" <the game's PCBANKS folder>
python3 tools/build_part_tables.py --game EXTRACTED
hgpaktool -U -f="*.scene.mbin" -f="*.descriptor.mbin" -f="*.material.mbin" -f="*.texture.mbin" -f="*palettes.mbin" <the game's PCBANKS folder>
python3 tools/build_paint_tables.py --game EXTRACTED
hgpaktool -U -f="metadata/gamestate/playerdata/*customisation*" -f="metadata/reality/tables/*product*" -f="language/*english.mbin" <the game's PCBANKS folder>
python3 tools/build_part_names.py --game EXTRACTED
```

To see what a part ID looks like, `tools/render_parts.py` draws a model's parts from its scenes and geometry: each part on a whole ship and alone, and whole ships with each part in its own color. It needs numpy and Pillow, and writes into `renders/`, which git ignores: the pictures are of the game's own models, so they don't go in the repository. Without `--model`, it draws every model, which takes a while.

```sh
hgpaktool -U -f="*spacecraft/*.scene.mbin" -f="*spacecraft/*.geometry*" -f="*weapons/multitool/*.scene.mbin" -f="*weapons/multitool/*.geometry*" <the game's PCBANKS folder>
python3 tools/render_parts.py --game EXTRACTED --model SHUTTLE_PROC
```

The capture mod has its own Python tests, which run on any OS; see [mods/README.md](mods/README.md#development).

Pushes to `main` deploy the site through GitHub Actions.

## Ground rules

- Free and non-commercial.
- No files distributed with the game, nor copies of them, are in this repository.
- Fan-made and not affiliated with or endorsed by Hello Games. No Man's Sky is a trademark of Hello Games Ltd.

## Credits

- [nms_namegen](https://github.com/hadsh/nms_namegen) by Stuart Coyle, had.sh and GoodGuysFree (MIT): the generator this site ports, and the ground truth behind the accuracy figures.
- [NMS.py](https://github.com/monkeyman192/NMS.py), [pyMHF](https://github.com/monkeyman192/pyMHF), [HGPAKtool](https://github.com/monkeyman192/HGPAKtool) and [MBINCompiler](https://github.com/monkeyman192/MBINCompiler) by monkeyman192 and contributors: the tools the capture mod and the part tables build on.
- Fonts: [MatrixType](https://ggbot.itch.io/matrixtype-font-family) by GGBotNet (CC0 1.0) and [Façade](https://velvetyne.fr/fonts/facade/) by Éléonore Fines, published by the Velvetyne Type Foundry (SIL Open Font License 1.1). The logo's lettering is [Butovo Mono](https://fontesk.com/butovo-mono-font/) by Okunkir.

## License

GNU Affero General Public License v3.0 or later; see [LICENSE](LICENSE). If you run a modified version as a public website, you must offer its source code to the people who use it.

Code and data ported from nms_namegen stay under its MIT license; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
