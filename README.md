# One Million Years Trade Depot

A free, open-source website for No Man's Sky explorers. Give it a portal address and it tells you what that star system holds, worked out in your browser from the address alone, the same way the game generates it.

**Site:** https://armokgob.github.io/One-Million-Years-Trade-Depot/

## What it shows today

- System name and region name
- Star colour, faction (or uncharted / abandoned), economy, wealth and conflict
- How many stars it has: whether it's a binary or trinary system
- Whether it is a region's black hole or Atlas Interface system
- Planets and moons, with their procedural names and planet seeds
- The ship list the game builds for the system: 50 slots, each with its seed and type, the exotic's included, plus the seed the game keeps for the ship at its Sentinel crash sites. Not every slot is a ship you can meet there: the list has a frigate of every type, including Recon and Cursed, whose only known frigates (the SSV Normandy SR1 and the Ship of the Damned) are expedition rewards.
- Whether the system's exotic is a squid
- A shareable link for every lookup

It accepts a 12-digit portal address (`009A039BAE4B`) or signal-booster coordinates (`064A:0082:01B9:009A`), plus a galaxy number (0 is Euclid). Both examples are the Pilgrim Star, which the site shows until you look up another system.

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

System, region and planet names, the order of bodies, and the outlaw flag aren't covered by that measurement. The [capture mod](mods/README.md)'s records check them on a smaller sample: so far 87 of 93 system names, 104 of 105 region names and 5,755 of 5,971 planet names agree with the game, as do the order of bodies and the outlaw flag in all 99 systems recorded, 11 of them outlaw systems. Of the first 80 planet names that differed, 33 looked like the work of a filter for offensive words, which changes one letter; the site doesn't model it yet.

How many stars a system has comes from the way the game counts them, which the capture mod's records showed: one star, a second when the system's `NebulaSeed`, a number between 0 and 1, is above 1 minus the game's binary star chance, 0.2, and a third when it's also above 1 minus its ternary star chance, 0.05. `NebulaSeed` is the 9th number the game draws from the system's address, as it was in all 93 systems recorded with their raw data, so about 1 system in 5 has a second star and 1 in 20 a third. Worked out from the address, the count matched the one the capture mod worked out from the game's own values in all 19 systems it has counted, 2 of them with more than one star, and screenshots of those two show their two and three stars.

The ships come from this project's own model of the game's generator (roadmap step 3). It was worked out from the first 66 systems recorded and has held for the 33 recorded since: it gets all 50 ship seeds and the crash-site seed right in 94 of the 99. The other 5 each have a planet with two moons, which the game arranges in one of two ways, and match with the moons the other way round. The model can't yet tell which way a system has, so for those systems the site flags its prediction and also gives the exotic and crash-site seeds for the other way.

Every recorded system lists its ships in the same 50 slots; only the first 20, the civilian ships, change: how many haulers, fighters and explorers depends on the dominant race, and the game makes some of them solar ships in a way not worked out yet. Outside outlaw systems, 66 of 588 shuttle slots held a solar ship and no other slot did; in outlaw systems, 66 of 77 shuttle slots did, and so did 13 of 143 other civilian slots.

Whether the exotic is a squid comes from the exotic's own seed. As far as the captures show, the first number the game draws from a ship's seed picks the first part of the ship's model, each option getting one unbroken stretch of that number's range: that held for all 1,193 models the capture mod has recorded of the seven kinds of ship whose first part varies. For an exotic, the top of the range gives `_SCLASSSHIP_SQU` and the rest `_SCLASSSHIP_ROY`. The 40 exotics recorded split cleanly: the 9 with `_SCLASSSHIP_SQU` drew between 0.9531 and 0.9965 of the range, and the 31 with `_SCLASSSHIP_ROY` between 0.0023 and 0.9519. Of the first 12, five of the six squids were in systems where players had posted squids, and the one other exotic seen landing wasn't a squid; the 28 recorded since the site drew its line all fell on the side it predicted. The site draws the line at 20/21 (0.9524), where it would be if the game weighted the squid 0.05 against the others' 1, so about 1 exotic in 21 is a squid. For the 1 exotic in 800 or so whose draw falls in the gap between 0.9519 and 0.9531, the site says "probably".

## Roadmap

1. **System lookup.** Done: this site.
2. **Capture mod.** In progress: [`mods/system_capture.py`](mods/system_capture.py), an [NMS.py](https://github.com/monkeyman192/NMS.py) mod that records, for every system a player enters, its address and the ship pool the game generates for it (`SystemShips` in the game's solar system data: each ship's seed and type). Version 0.10.0 added, when the player clicks a button, the guild of the region's space stations, and 0.11.0 how many stars a system has, worked out as the game's own star count function would, which the site now shows; 0.11.1 shows it on the mod's tab too. Needs a Windows PC; [how to run it](mods/README.md).
3. **Address → ship pool.** On the site now. Every system captured so far has a 50-slot ship list with the same layout, with its one exotic in slot 20. [`tools/captures/ship_model.py`](tools/captures/ship_model.py) predicts all 50 ship seeds from the portal address alone, building on nms_namegen like the site does, and [`src/core/ships.ts`](src/core/ships.ts) is its port. It matched every ship and the Sentinel crash-site ship in 94 of the 99 systems captured so far, gas giant systems included, and the other 5 with a planet's two moons the other way round. The ships come last in a system's generation, after the space station and the "attractor" spawn points around each planet, and those decide where in the random-number stream the ships' seeds start. Still open: which way round the game puts a planet's two moons, and which civilian ships it makes solar.
4. **Seed → appearance.** In progress: decode each ship seed into parts and colours. Squid versus other exotics is on the site now. Version 0.7.0 of the capture mod records the parts the game picks for each ship in a system's list as it builds the ship, which showed that the first draw from a ship's seed picks the first part of its model. Next: the rest of the exotic's parts, then every ship type.
5. **Multi-tools and freighters**, then pictures. The game builds each system's own multi-tools as you arrive, 8 to 10 per system in the captures so far. Version 0.11.0 of the capture mod records them, with each one's seed and parts, and did for all 19 systems of its first run; since 0.9.0 it has recorded the one a space station offers, with its seed, parts, class and inventory. So the data builds up before this step starts. With the starships' parts and colours from step 4, this makes release 1.0: look up a system and scout the starships, freighters and multi-tools it generates without going there.
6. **Creatures**, after 1.0: the creatures each planet generates, with their colours and pattern, physical characteristics, aggression, genus, description and battle stats.

## How it works

`src/core` is a pure TypeScript library with no DOM, so other projects can use it too. It is a line-for-line port of [nms_namegen](https://github.com/hadsh/nms_namegen):

- the portal address and galaxy form the game's universal address;
- an index-primed PRNG (Threefish-style 64-bit mixing) turns that into the system seed;
- a 32-bit multiply-with-carry RNG then draws the system's attributes, names and body seeds in the game's order.

All 64-bit maths uses `BigInt`, and float comparisons use `Math.fround` where the game compares in single precision.

The ships and the stars are this project's additions: `src/core/ships.ts` follows the same generator on, from the system's universal address through the space station and the planets' attractor spawn points to the ships, and tells from the exotic's seed whether it's a squid, as `tools/captures/ship_model.py` does in Python; `src/core/stars.ts` draws the system's `NebulaSeed` from its universal address and counts its stars the way the game does, as `tools/captures/star_model.py` does.

Parity is checked two ways. `npm test` replays nms_namegen's 443 golden vectors through the port, the ship model's output for a set of addresses that covers every body layout it treats differently, and the star model's for systems with one, two and three stars. CI also generates 20,000 fresh cases with the Python library, pinned to a known commit, covering all 256 galaxies, every planet digit and the system indices where the generator branches, and compares every field, ships and stars included.

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
- Fonts: [MatrixType](https://ggbot.itch.io/matrixtype-font-family) by GGBotNet (CC0 1.0) and [Façade](https://velvetyne.fr/fonts/facade/) by Éléonore Fines, published by the Velvetyne Type Foundry (SIL Open Font License 1.1). The logo's lettering is [Butovo Mono](https://fontesk.com/butovo-mono-font/) by Okunkir.

## License

GNU Affero General Public License v3.0 or later; see [LICENSE](LICENSE). If you run a modified version as a public website, you must offer its source code to the people who use it.

Code and data ported from nms_namegen stay under its MIT license; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
