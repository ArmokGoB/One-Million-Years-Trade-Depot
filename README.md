# One Million Years Trade Depot

A free, open-source website for No Man's Sky explorers. Give it a portal address and it tells you what that star system holds, worked out in your browser from the address alone, the same way the game generates it.

**Site:** https://armokgob.github.io/One-Million-Years-Trade-Depot/

## What it shows today

- System name and region name
- Star colour, faction (or uncharted / abandoned), economy, wealth and conflict
- Whether it is a region's black hole or Atlas Interface system
- Planets and moons, with their procedural names and planet seeds
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

System, region and planet names, the order of bodies, and the outlaw flag aren't covered by that measurement yet. The site says so where it shows them.

## Roadmap

1. **System lookup.** Done: this site.
2. **Capture mod.** An [NMS.py](https://github.com/monkeyman192/NMS.py) mod that logs, for every system a player enters, its address and the ship pool the game generates for it (`SystemShips` in the game's solar system data: each ship's seed and type). Needs a Windows PC.
3. **Address → ship pool.** Work out how the game derives those ships from the address, using the captures as ground truth, and publish the measured accuracy.
4. **Seed → appearance.** Decode each ship seed into parts and colours, starting with squid versus ball-cockpit exotics, then every ship type.
5. **Multi-tools and freighters**, then pictures.

## How it works

`src/core` is a pure TypeScript library with no DOM, so other projects can use it too. It is a line-for-line port of [nms_namegen](https://github.com/hadsh/nms_namegen):

- the portal address and galaxy form the game's universal address;
- an index-primed PRNG (Threefish-style 64-bit mixing) turns that into the system seed;
- a 32-bit multiply-with-carry RNG then draws the system's attributes, names and body seeds in the game's order.

All 64-bit maths uses `BigInt`, and float comparisons use `Math.fround` where the game compares in single precision.

Parity is checked two ways. `npm test` replays nms_namegen's 443 golden vectors through the port. CI also generates 20,000 fresh cases with the Python library, pinned to a known commit, covering all 256 galaxies, every planet digit and the system indices where the generator branches, and compares every field.

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
python3 tools/crosscheck/generate.py --namegen ../nms_namegen --count 20000 > crosscheck.jsonl
CROSSCHECK_FILE=crosscheck.jsonl npm test
```

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
