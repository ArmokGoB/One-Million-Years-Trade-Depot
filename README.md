# One Million Years Trade Depot

A free, open-source website for No Man's Sky explorers. Give it a portal address and it tells you what that star system holds, worked out in your browser from the address alone, the same way the game generates it.

**Site:** https://armokgob.github.io/One-Million-Years-Trade-Depot/

## What it shows today

- System name and region name
- Star colour, faction (or uncharted / abandoned), economy, wealth and conflict
- Whether it is a region's black hole or Atlas Interface system
- Planets and moons, with their procedural names and planet seeds
- The ship list the game builds for the system: 50 slots, each with its seed and type, the exotic's included, plus the seed the game keeps for the ship at its Sentinel crash sites. Not every slot is a ship you can meet there: the list has a frigate of every class, including the Normandy, which only comes from the Beachhead expedition.
- A shareable link for every lookup

It accepts a 12-digit portal address (`003DF8F87945`) or signal-booster coordinates (`025B:0082:03FF:004A`), plus a galaxy number (0 is Euclid).

How often each field matches what players recorded in game, measured by nms_namegen against 1,000 hand-recorded post-Origins systems (2026-08-23):

| Field | Agreement |
|---|---|
| Star colour | 99.1% |
| Uncharted system | 99.8% |
| Dominant race | 99.1% |
| Conflict level | 99.0% |
| Economy category | 99.0% |
| Wealth tier | 98.9% |
| Planet and moon counts | 98.4% |

System, region and planet names, the order of bodies, and the outlaw flag aren't covered by that measurement. The [capture mod](mods/README.md)'s records check them on a smaller sample: so far 23 of 24 system names, all 28 region names and 1,109 of 1,141 planet names agree with the game, as do the order of bodies and the outlaw flag in all 31 systems recorded. Most of the planet names that differ (26 of 32) look like the work of a filter for offensive words, which changes one letter; the site doesn't model it yet.

The ships come from this project's own model of the game's generator (roadmap step 3). It was worked out from the same 31 systems and gets all 50 ship seeds and the crash-site seed right in 30 of them. The site flags systems with a planet that has two moons, the layout behind the one miss, and doesn't predict ships for gas giant systems, whose layout the model doesn't cover. Every recorded system lists its ships in the same 50 slots; only the first 20, the civilian ships, change with the dominant race, and the game picks between a shuttle and a solar ship in a way not worked out yet.

## Roadmap

1. **System lookup.** Done: this site.
2. **Capture mod.** In progress: [`mods/system_capture.py`](mods/system_capture.py), an [NMS.py](https://github.com/monkeyman192/NMS.py) mod that records, for every system a player enters, its address and the ship pool the game generates for it (`SystemShips` in the game's solar system data: each ship's seed and type). Needs a Windows PC; [how to run it](mods/README.md).
3. **Address → ship pool.** On the site now. Every system captured so far has a 50-slot ship list with the same layout, with its one exotic in slot 20. [`tools/captures/ship_model.py`](tools/captures/ship_model.py) predicts all 50 ship seeds from the portal address alone, building on nms_namegen like the site does, and [`src/core/ships.ts`](src/core/ships.ts) is its port. It matched every ship and the Sentinel crash-site ship in 30 of the 31 systems captured so far. The ships come last in a system's generation, after the space station and the "attractor" spawn points around each planet, and those decide where in the random-number stream the ships' seeds start. The one miss has a planet with two moons, which the game lays out in a way not worked out yet. Still open: that layout, gas giant systems, and how the game picks between a shuttle and a solar ship.
4. **Seed → appearance.** Decode each ship seed into parts and colours, starting with squid versus ball-cockpit exotics, then every ship type.
5. **Multi-tools and freighters**, then pictures.

## How it works

`src/core` is a pure TypeScript library with no DOM, so other projects can use it too. It is a line-for-line port of [nms_namegen](https://github.com/hadsh/nms_namegen):

- the portal address and galaxy form the game's universal address;
- an index-primed PRNG (Threefish-style 64-bit mixing) turns that into the system seed;
- a 32-bit multiply-with-carry RNG then draws the system's attributes, names and body seeds in the game's order.

All 64-bit maths uses `BigInt`, and float comparisons use `Math.fround` where the game compares in single precision.

The ships are this project's addition: `src/core/ships.ts` follows the same generator on, from the system's universal address through the space station and the planets' attractor spawn points to the ships, as `tools/captures/ship_model.py` does in Python.

Parity is checked two ways. `npm test` replays nms_namegen's 443 golden vectors through the port, and the ship model's output for a set of addresses that covers every body layout it treats differently. CI also generates 20,000 fresh cases with the Python library, pinned to a known commit, covering all 256 galaxies, every planet digit and the system indices where the generator branches, and compares every field, ships included.

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
python3 tools/crosscheck/generate.py --namegen ../nms_namegen --count 20000 > crosscheck.jsonl
CROSSCHECK_FILE=crosscheck.jsonl npm test
```

The capture mod has its own Python tests, which run on any OS; see [mods/README.md](mods/README.md#development).

Pushes to `main` deploy the site through GitHub Actions.

## Ground rules

- Free and non-commercial.
- No game models, textures or other art in this repository. The only game-derived data is the name-generation tables, taken from nms_namegen.
- Fan-made and not affiliated with or endorsed by Hello Games. No Man's Sky is a trademark of Hello Games Ltd.

## Credits

- [nms_namegen](https://github.com/hadsh/nms_namegen) by Stuart Coyle, had.sh and GoodGuysFree (MIT): the generator this site ports, and the ground truth behind the accuracy figures.
- [NMS.py](https://github.com/monkeyman192/NMS.py), [pyMHF](https://github.com/monkeyman192/pyMHF), [HGPAKtool](https://github.com/monkeyman192/HGPAKtool) and [MBINCompiler](https://github.com/monkeyman192/MBINCompiler) by monkeyman192 and contributors: the tools the next milestones build on.
- Fonts: Big Shoulders Stencil Display and Atkinson Hyperlegible Next, both under the SIL Open Font License 1.1.

## License

GNU Affero General Public License v3.0 or later; see [LICENSE](LICENSE). If you run a modified version as a public website, you must offer its source code to the people who use it.

Code and data ported from nms_namegen stay under its MIT license; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
