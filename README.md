# One Million Years Trade Depot

A free, open-source website for No Man's Sky explorers. Give it a portal address and it tells you what that star system holds, worked out in your browser from the address alone, the same way the game generates it.

**Site:** https://armokgob.github.io/One-Million-Years-Trade-Depot/

## What it shows

- System, region and galaxy names
- Star color, faction (or uncharted or abandoned), economy, wealth and conflict, and whether outlaws likely control it
- Which guild's envoy the region's space stations have: the Merchants, the Mercenaries or the Explorers
- How many stars the system has, and each star's color
- Whether it's a region's black hole or Atlas Interface system, or a giant planet with every other body its moon
- Planets and moons, with their names, portal addresses and seeds
- The system's ship list: 50 slots, each with its seed and type, the exotic included, plus the ship at its Sentinel crash sites. Some slots are frigates you won't meet there, such as Recon and Cursed, which are known only as expedition rewards.
- Each ship's parts, by the game's part IDs: every civilian ship, the exotic, every freighter, the Sentinels' ship and freighter, and the pirates' fighters and capital freighter. Fighters, haulers, explorers and solars also get the names the Starship Fabricator gives their parts.
- The colors the game paints those ships with, and most frigates and the swarm's frigate and drone, each color named in words
- The system's own multi-tools: 2 to 4 standard ones, a royal, a Sentinel and an Atlas one, and three more standard ones that change every day at midnight UTC, each with its seed, parts and colors
- A shareable link for every lookup

It takes a 12-digit portal address (`009A039BAE4B`) or signal booster coordinates (`064A:0082:01B9:009A`), plus the galaxy's number, from 1 (Euclid) to 256. Both examples are the Pilgrim Star, which the site shows until you look up another system.

## Accuracy

nms_namegen measured these against 1,000 hand-recorded post-Origins systems:

| Field | Agrees |
|---|---|
| Star color | 99.1% |
| Uncharted system | 99.8% |
| Dominant race | 99.1% |
| Conflict level | 99.0% |
| Economy category | 99.0% |
| Wealth tier | 98.9% |
| Planet and moon counts | 98.4% |

The rest is checked against what the [capture mod](mods/README.md) recorded in the game:

| Field | Agrees |
|---|---|
| System names | 132 of 140 |
| Region names | 178 of 179 |
| Planet names | 8,276 of 8,606 |
| Order of bodies, outlaw flag, giant planet layout | all 146 systems |
| Number of stars | all 66 systems counted |
| Ship seeds | all 146 systems |
| Which civilian ships are solar | all 2,920 |
| Parts | all 3,738 ships and multi-tools |
| Paint | all 1,564 ships, freighters, frigates and multi-tools |
| System palettes | all 140 systems |
| Guild envoy | all 43 recorded |
| Multi-tool seeds | all 69 sets, the daily three included; all 45 multi-tools on offer |

Known gaps:

- The game appears to change a letter of names with an offensive word in them, and the site doesn't. That looks like the reason for 33 of the first 80 planet names that differed.
- What decides a giant planet's biome isn't known, so the site doesn't say which kind a system has.
- Each multi-tool's class isn't known.
- The site shows the multi-tools the game makes as you arrive from space. Loading a save on a planet makes it build another set, from that planet's address, which the site doesn't show.
- The part names haven't been checked against what the game shows. About 1 hauler in 260 has wings that make a component the game doesn't name.

## How it works

`src/core` is a TypeScript library with no DOM. Its base is a line-for-line port of [nms_namegen](https://github.com/hadsh/nms_namegen): the portal address and galaxy make the game's universal address, an index-primed PRNG turns that into the system seed, and a multiply-with-carry RNG draws the system's attributes, names and body seeds in the game's order. 64-bit math uses `BigInt`, and comparisons the game makes in single precision use `Math.fround`.

The rest is this project's own. Each module ports a Python model in [`tools/captures`](tools/captures), whose docstring explains what the game does:

| Module | Model | Works out |
|---|---|---|
| `ships.ts` | `ship_model.py` | the ship list, following the generator past the space station and the planets' spawn points |
| `stars.ts` | `star_model.py` | how many stars, and each one's color |
| `guild.ts` | `guild_model.py` | the region's guild |
| `multitools.ts` | `multitool_model.py` | the seeds of the system's own multi-tools, the day's three included |
| `parts.ts` | `parts_model.py` | each ship's and multi-tool's parts, from its seed |
| `partnames.ts` | `part_names_model.py` | the Starship Fabricator's names for those parts |
| `paint.ts` | `paint_model.py` | each model's palettes and paint |

The parts, part names and paint come from tables in `src/core/data` that scripts in `tools` derive from the game's own files (see [Development](#development)). `colornames.ts` puts each color into words.

`npm test` replays nms_namegen's golden vectors and fixtures from each Python model. CI also checks that the name tables and test fixtures in the repository are the ones the scripts make, and compares 20,000 fresh cases from the Python library, across all 256 galaxies, field by field.

## Roadmap

1. Names for the parts of the other ships, from the No Man's Sky Coordinate Exchange (NMSCE) where it has them, and for the multi-tools' parts
2. Each multi-tool's class. With the parts and colors already on the site, this makes release 1.0.
3. Then pictures of each ship and multi-tool
4. After 1.0: each planet's creatures, with their colors and pattern, physical characteristics, aggression, genus, description and battle stats

The [capture mod](mods/README.md) records what the game generates in each system a player visits, to check the models against. It needs a Windows PC. Its versions are in [mods/CHANGELOG.md](mods/CHANGELOG.md).

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

The part, paint and part name tables come from the game's own files, which this repository doesn't hold. To rebuild them after a game update, extract the files from your copy of the game with [HGPAKtool](https://github.com/monkeyman192/HGPAKtool) and point the scripts at the folder it extracts them into. Build the part tables before the part names. Every filter needs a `*`: without one, HGPAKtool stops at the first pak that lacks the file.

```sh
hgpaktool -U -f="*spacecraft/*.descriptor.mbin" -f="*weapons/multitool/*.descriptor.mbin" <the game's PCBANKS folder>
python3 tools/build_part_tables.py --game EXTRACTED
hgpaktool -U -f="*.scene.mbin" -f="*.descriptor.mbin" -f="*.material.mbin" -f="*.texture.mbin" -f="*palettes.mbin" <the game's PCBANKS folder>
python3 tools/build_paint_tables.py --game EXTRACTED
hgpaktool -U -f="metadata/gamestate/playerdata/*customisation*" -f="metadata/reality/tables/*product*" -f="language/*english.mbin" <the game's PCBANKS folder>
python3 tools/build_part_names.py --game EXTRACTED
```

`tools/render_parts.py` draws what each part ID looks like, from the game's scenes and geometry: each part alone and on a whole ship. It needs numpy and Pillow, and writes into `renders/`, which git ignores, as the pictures are of the game's own models. Without `--model` it draws every model, which takes a while.

```sh
hgpaktool -U -f="*spacecraft/*.scene.mbin" -f="*spacecraft/*.geometry*" -f="*weapons/multitool/*.scene.mbin" -f="*weapons/multitool/*.geometry*" <the game's PCBANKS folder>
python3 tools/render_parts.py --game EXTRACTED --model SHUTTLE_PROC
```

The capture mod has its own tests; see [mods/README.md](mods/README.md#development). Pushes to `main` deploy the site through GitHub Actions.

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
