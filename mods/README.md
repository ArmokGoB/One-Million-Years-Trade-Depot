# Capture mod

`system_capture.py` records every star system you visit in No Man's Sky, together with `SystemShips`: the list of ships the game prepares for that system (each ship's seed, type, role and faction). The project used these records to work out how the game picks a system's ship seeds from its address, which the site now shows, and uses them to check that model. When the game builds one of those ships, the mod also records the parts the game picked for it. Those records showed which exotics are squids, which the site now predicts, and are how the project means to work out the rest of what a seed looks like: the next step on the [roadmap](../README.md#roadmap). Ahead of a later step, it also records the multi-tools the game offers: each tool's seed and parts, and where you were when it was offered.

The mod only reads. It changes nothing in the game or your save, and it runs on top of [NMS.py](https://github.com/monkeyman192/NMS.py).

**Status:** version 0.1 recorded the first systems in the game, with NMS.py 180383.0. Versions 0.4.0, 0.5.0, 0.5.2 and 0.7.0 have run in the game too: all of their hooks attached, the generation traces, names and locators they recorded check out, and the arrival tone plays. Version 0.5.1 crashed the game when a save loaded or when it attached to a running game; 0.5.2 took out the change that did it. In its first run, 0.7.0 recorded where each planet is, and the parts of every ship in the system's list, the exotic's included, while the system was still loading; the parts it read match the raw bytes it kept. Not yet tried in the game: the hotkeys, and finding a game that was already running when the mod attached. To record ship parts, 0.7.0 watches a function the game calls for everything it loads. If the game crashes or loads slowly with it, set `RECORD_SHIP_PARTS = False` near the top of `system_capture.py` and the mod leaves that function alone. Version 0.8.0 adds recording multi-tools, which hasn't run in the game yet (see [Record multi-tools](#record-multi-tools)). If the mod misbehaves, the log file (see below) is the most useful thing to send.

## What you need

- A Windows PC with No Man's Sky on Steam.
- Python 3.13, 64-bit, from python.org: the [3.13.16 release page](https://www.python.org/downloads/release/python-31316/) has a "Windows installer (64-bit)". NMS.py doesn't support Python 3.14 yet.
- **Not** the Microsoft Store version of Python. The game can't load it; pyMHF stops with `DLL load failed while importing _socket: Access is denied`, and the mod refuses to start with it.
- NMS.py for your game version. After a game update the mod stops working until NMS.py catches up; update it with `py -3.13 -m pip install --upgrade nmspy`.

## Install (once)

1. If you have Python 3.13 from the Microsoft Store, uninstall it first: Settings → Apps → Installed apps → Python 3.13 → Uninstall.
2. Run the python.org installer with its default options, which include the `py` launcher.
3. In a terminal (Windows Terminal or Command Prompt):

   ```bat
   py -0p
   py -3.13 -m pip install nmspy
   ```

   `py -0p` lists the Pythons the launcher can see. The 3.13 entry should point to a folder like `AppData\Local\Programs\Python\Python313`, not to anything under `WindowsApps`.

Then download [`system_capture.py`](system_capture.py) into a folder of its own, or clone this repository.

## Record systems

1. Start Steam. No Man's Sky can be closed or already running.
2. In a terminal, in the folder with the mod:

   ```bat
   py -3.13 system_capture.py
   ```

   This starts the game through Steam with the mod attached, or attaches the mod to the game if it's already running. Two extra windows open: a log console and the pyMHF panel, which has a **TradeDepotCapture** tab.

   Starting the game this way is better: the mod then sees how the system you load into is generated. A system that was generated before the mod attached gets recorded without those details.

   Attached to a game that's already running, the mod can't see the game until the game next changes state. Opening the galaxy map should do it. The log says "Found the game" when it has.
3. Load your save and play as usual. A few seconds after you arrive in a system, the mod plays two short rising notes, and the log shows a line like:

   ```text
   Recorded <system name> (<portal code>, galaxy <number>): 50 ships (Freighter 21, Fighter 9, Shuttle 6, ...)
   ```

   As a system loads, the game builds every ship in its ship list, and the mod records the parts the game picked for each. When it gets to the exotic, three high notes play, often before the loading screen ends, and the log says `Recorded the parts of the exotic (seed ...)`, with its parts. You don't need to wait for the exotic to land. If its first part is `_SCLASSSHIP_SQU`, it's a squid.
4. Save and quit the game normally when you're done. Pressing Ctrl+C in the terminal closes the game too.

   If you close the terminal window instead while the game keeps running, pyMHF stays inside the game until you quit it, and the mod can't attach again until then. It says so if you try.

The records go to `captures\systems.jsonl` and the logs to `logs\`, both next to `system_capture.py`. Each session adds to the same file.

If you arrive somewhere and don't hear the notes, press F6 (see below). If the log says that some values look wrong for every system, NMS.py probably doesn't match your game version yet.

You don't need to label exotics any more: the parts tell which are squids. If you'd like to note what you saw anyway, press F7 when an exotic that lands is a squid or F8 if it isn't, while you're still in that system. In every system recorded so far the ship list holds exactly one exotic, so the mod pairs your label with that exotic's seed. Only label exotics flown by the game, not other players' ships. If you press the wrong key, press the right one: the report keeps your last label for each system in a session.

## Record multi-tools

Multi-tools aren't in a system's ship list, so the mod records them where the game offers one: at a space station's multi-tool merchant, on a minor settlement's multi-tool rack, or as a gift or a reward. Stand near one for about 20 seconds. The mod looks at each item the game offers once a second, and two quick very high notes mean it recorded the multi-tool in it; the log says `Recorded a multi-tool the game offers (seed ...)`, with its parts. According to the [No Man's Sky wiki](https://nomanssky.fandom.com/wiki/Multi-Tool), each planet and moon has its own pool of 2 to 4 multi-tools, found in its minor settlements, and the space station has its own, so each place you visit can add different ones.

This is new in 0.8.0 and hasn't run in the game yet. The mod pairs an item with the multi-tool model whose seed it holds, and how the game stores an item on offer isn't known yet, so it may not find the pairing at first. Either way, it keeps the raw bytes of the first few items of each kind in a session. Those should show where the game keeps an offered multi-tool's class and number of slots. Screenshots of the multi-tools you saw, with their class, type and slots, would help match them up.

If the game misbehaves near a multi-tool rack, set `RECORD_MULTITOOLS = False` near the top of `system_capture.py`. Multi-tools also need `RECORD_SHIP_PARTS`, because their parts come through the same function.

## Hotkeys and sounds

You don't need to switch away from the game. While its window has focus, these keys do what the buttons on the TradeDepotCapture tab do, and a short tone tells you how it went:

| Key | What it does | Tone when it worked |
|---|---|---|
| F6 | Record the current system now | Two rising notes |
| F7 | Note that the exotic you just saw here is a squid | Three rising notes |
| F8 | Note that the exotic you just saw here isn't a squid | Three falling notes |

Two low notes mean it didn't work: no system was loaded yet, the system couldn't be read or written, or for F7 and F8, the system's ship list has no exotic to pair the label with. The log says which.

Three high notes, the last one higher, mean the mod has recorded the parts of the system's exotic. They play once per exotic. Two quick very high notes mean it has recorded a multi-tool the game offers, once per multi-tool.

The keys act when you let go of them. The game's default controls don't appear to use F6 to F8. If one clashes with your own key bindings or another program, change `HOTKEYS` near the top of `system_capture.py`; pyMHF can bind single keys only, not combinations like Ctrl+F6. In the same place, `PLAY_SOUNDS`, `CHIME_ON_ARRIVAL` (the notes after you arrive) and `SOUND_VOLUME` turn the tones off or change their volume, and `RECORD_SHIP_PARTS` and `RECORD_MULTITOOLS` turn off recording ship parts and multi-tools.

## Send captures

Zip `captures\systems.jsonl` and attach it to an [issue](https://github.com/ArmokGoB/One-Million-Years-Trade-Depot/issues). If something went wrong, attach the newest file in `logs\` too.

A capture file holds the address of every system you recorded and when you got there, so anyone you share it with can see where you've been. It holds nothing else about you: no player name, account or save data, and nothing about other players. Ship parts are recorded only for ships in the system's own ship list, never for your ships or other players'. Multi-tools are recorded only when the game offers one as an item. The game also builds the multi-tools you and other players carry, but the mod keeps every multi-tool's seed in memory only, and writes one to the file only when an item on offer holds that seed. Items are recorded with whether you were in a space station or on foot, and which planet was nearest, but not your position. The first line of each session names the game's executable by its SHA-1 hash and Steam build ID, says which of the mod's hooks attached, and lists the NMS.py, pyMHF and Python versions.

For the hotkeys, pyMHF watches the keyboard while the game runs. The mod reacts only to its three keys, and only while the game has focus; it records nothing you type.

## What a record holds

One JSON object per line. A `"t": "session"` line starts each run of the game and carries the column names for the compact rows below and the game's enum names, since game updates can renumber enums. Each `"t": "sys"` line is one system:

| Field | Meaning |
|---|---|
| `via` | What triggered the record: `gen` (the game generated the system), `poll` (the mod noticed it while you were there), `btn` (you asked, with F6 or the button) |
| `at` | Unix time, in seconds |
| `ua` | Universal address, 16 hex digits; the portal code and galaxy are packed into it. Still zero while the game is generating the system, so `gen` records have `ua` 0 |
| `seed` | The system seed, which holds the same value as the universal address |
| `displayName` | The name the game shows for the system (`poll` and `btn` records) |
| `name`, `star`, `race`, `trade`, `wealth`, `conflict`, `planets`, `prime` | The game's own description of the system |
| `ships` | `SystemShips`, one row per ship: seed, use-seed flag, class, role, faction, frigate class, texture hint |
| `bodies` | Planet generation inputs: seed, biome, size, resources and flags per planet |
| `positions` | Where each planet and moon is in the system, as x, y, z; in lookups too, if the game has placed them by the end of the lookup. They show which way round the game put a planet's two moons, which decides where the system's ship seeds fall |
| `galaxy` | The galaxy generator's view of the same system: planet seeds, star attributes and region data |
| `trace` | `gen` records: the generator's random-number state at the start and end of each generation step |
| `keyAttributes` | The galaxy generator's summary that generation starts from: planet counts, the safe start planet, flags, and four bytes (`anomaly`) not yet understood. Only when the game runs that step for the system, which it hasn't for any generated or looked-up system so far |
| `locators` | `gen` records: the system's locators, spawn points the generator places: `count`, and the whole array, compressed and base64-encoded, in `raw`. Most of the random numbers drawn between the planet biomes and the ships seem to go to these |
| `raw`, `rawGalaxy` | `gen` records: all of the generated system data and of the galaxy attributes, zlib-compressed and base64-encoded, for offline analysis |
| `arg`, `active`, `sim`, `loc` | Cross-checks: the seed the game passed in, whether the system was the loaded one, the simulation's address and the player's location |
| `errors`, `unusual` | Present only when part of the system couldn't be read or looked implausible |

Five other kinds of line:

- `"t": "query"`: a lookup, a system the game described without loading it. It has the system's seed, the random-number states around the lookup and around any generation steps inside it, its key attributes if that step ran, and whatever the lookup filled in, perhaps including where its planets are. Each seed is recorded once per session.
- `"t": "name"`: a planet or region name the game generated, with the seed it was generated from (`kind`, `seed`, `name`; `local` if the shown text differs), and the system you were in at the time. Each seed is recorded once per session.
- `"t": "label"`: an exotic sighting you labelled with F7, F8 or the buttons, with the system and its exotic's seed.
- `"t": "model"`: a ship of a system's ship list that the game built: the system and the ship's `slot` in its list (`"crash"` for the Sentinel crash-site ship), the model file (`name`) and resource `type`, the ship's `seed` (and a second seed, `seed2`, if the game gave one), and the IDs of the parts the game picked (`parts`). The first records of a session also keep the descriptor the game passed, as `raw`, to check the mod reads it right. Each model of each ship is recorded once per session.
- `"t": "item"`: an item the game offered: the loaded `system`; where you were (`where`, a value of the game's EnvironmentLocation, such as SpaceStation or PlanetOnFoot; the nearest `planet`'s index; and `loc`, your location as in a system line); the item's kind (`itemType`, not yet matched to names), `state`, and whether it was `free`, a `gift` or a `reward`; and `tools`, the multi-tool models whose seed the item holds, each with its file (`name`), `seed`, `parts` and the byte `offset` in the item where the seed is. The first few items of each kind in a session keep the item's bytes, as `raw`. Each multi-tool offered is recorded once per system per session. An item that holds none after 20 seconds is recorded only if it's one of the first few of its kind, for its bytes.

[`tools/captures/report.py`](../tools/captures/report.py) reads these files. It summarises the ship pools and checks the game's data against itself. It also finds each system's ship seeds in the random-number stream seeded by the system seed, turns the traces into draw counts, lists the exotic labels, lists the parts recorded for each exotic, checking whether it's a squid against what the site predicts from its seed, and lists the multi-tools the game offered. Given a clone of nms_namegen, it scores the site's generator against the game, including the names the game generated, and checks the ship seeds that [`ship_model.py`](../tools/captures/ship_model.py) predicts from each system's address.

```sh
python3 tools/captures/report.py mods/captures/systems.jsonl
python3 tools/captures/report.py --namegen ../nms_namegen mods/captures/systems.jsonl
```

## Development

The tests run anywhere, not only on Windows: [`tests/harness.py`](tests/harness.py) stubs the Windows-only packages so NMS.py's real struct definitions and pyMHF's hook decorators load, and the tests build fake game memory from those structs.

```sh
python3 -m pip install --no-deps nmspy==180383.0 pymhf==0.2.4
python3 -m pip install typing_extensions packaging tomlkit
python3 -m unittest discover -s mods/tests -v
NMS_NAMEGEN=../nms_namegen python3 -m unittest discover -s mods/tests -v   # plus the generator comparison (needs numpy)
```
