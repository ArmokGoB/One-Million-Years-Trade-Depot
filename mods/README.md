# Capture mod

`system_capture.py` records every star system you visit in No Man's Sky, together with `SystemShips`: the list of ships the game prepares for that system (each ship's seed, type, role and faction). The project uses these records to work out how the game picks a system's ships from its address, the next step on the [roadmap](../README.md#roadmap).

The mod only reads. It changes nothing in the game or your save, and it runs on top of [NMS.py](https://github.com/monkeyman192/NMS.py).

**Status:** version 0.1 recorded the first systems in the game, with NMS.py 180383.0. Version 0.4.0 has run in the game too: all of its hooks attached, the generation traces and names it recorded check out, and its arrival tone plays. Not yet tried in the game: the hotkeys, what 0.5.0 adds (locators, and generation steps inside lookups), and 0.5.1's fix for attaching to a game that's already running. If the mod misbehaves, the log file (see below) is the most useful thing to send.

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
3. Load your save and play as usual. A few seconds after you arrive in a system, the mod plays two short rising notes, and the log shows a line like:

   ```text
   Recorded <system name> (<portal code>, galaxy <number>): 50 ships (Freighter 21, Fighter 9, Shuttle 6, ...)
   ```

4. Save and quit the game normally when you're done. Pressing Ctrl+C in the terminal closes the game too.

   If you close the terminal window instead while the game keeps running, pyMHF stays inside the game until you quit it, and the mod can't attach again until then. It says so if you try.

The records go to `captures\systems.jsonl` and the logs to `logs\`, both next to `system_capture.py`. Each session adds to the same file.

If you arrive somewhere and don't hear the notes, press F6 (see below). If the log says that some values look wrong for every system, NMS.py probably doesn't match your game version yet.

When you see an exotic land in a system, press F7 if it's a squid or F8 if it isn't, while you're still in that system. In every system recorded so far the ship list holds exactly one exotic, so the mod pairs your label with that exotic's seed. Those pairs are what decoding a ship's appearance from its seed will be built and checked on. Only label exotics flown by the game, not other players' ships. If you press the wrong key, press the right one: the report keeps your last label for each system in a session.

## Hotkeys and sounds

You don't need to switch away from the game. While its window has focus, these keys do what the buttons on the TradeDepotCapture tab do, and a short tone tells you how it went:

| Key | What it does | Tone when it worked |
|---|---|---|
| F6 | Record the current system now | Two rising notes |
| F7 | Note that the exotic you just saw here is a squid | Three rising notes |
| F8 | Note that the exotic you just saw here isn't a squid | Three falling notes |

Two low notes mean it didn't work: no system was loaded yet, the system couldn't be read or written, or for F7 and F8, the system's ship list has no exotic to pair the label with. The log says which.

The keys act when you let go of them. The game's default controls don't appear to use F6 to F8. If one clashes with your own key bindings or another program, change `HOTKEYS` near the top of `system_capture.py`; pyMHF can bind single keys only, not combinations like Ctrl+F6. In the same place, `PLAY_SOUNDS`, `CHIME_ON_ARRIVAL` (the notes after you arrive) and `SOUND_VOLUME` turn the tones off or change their volume.

## Send captures

Zip `captures\systems.jsonl` and attach it to an [issue](https://github.com/ArmokGoB/One-Million-Years-Trade-Depot/issues). If something went wrong, attach the newest file in `logs\` too.

A capture file holds the address of every system you recorded and when you got there, so anyone you share it with can see where you've been. It holds nothing else about you: no player name, account or save data, and nothing about other players. The first line of each session names the game's executable by its SHA-1 hash and Steam build ID, says which of the mod's hooks attached, and lists the NMS.py, pyMHF and Python versions.

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
| `galaxy` | The galaxy generator's view of the same system: planet seeds, star attributes and region data |
| `trace` | `gen` records: the generator's random-number state at the start and end of each generation step |
| `keyAttributes` | The galaxy generator's summary that generation starts from: planet counts, the safe start planet, flags, and four bytes (`anomaly`) not yet understood. Only when the game runs that step for the system, which it didn't for any system generated in the 0.4.0 capture |
| `locators` | `gen` records: the system's locators, spawn points the generator places: `count`, and the whole array, compressed and base64-encoded, in `raw`. Most of the random numbers drawn between the planet biomes and the ships seem to go to these |
| `raw`, `rawGalaxy` | `gen` records: all of the generated system data and of the galaxy attributes, zlib-compressed and base64-encoded, for offline analysis |
| `arg`, `active`, `sim`, `loc` | Cross-checks: the seed the game passed in, whether the system was the loaded one, the simulation's address and the player's location |
| `errors`, `unusual` | Present only when part of the system couldn't be read or looked implausible |

Three other kinds of line:

- `"t": "query"`: a lookup, a system the game described without loading it. It has the system's seed, the random-number states around the lookup and around any generation steps inside it, its key attributes if that step ran, and whatever the lookup filled in. Each seed is recorded once per session.
- `"t": "name"`: a planet or region name the game generated, with the seed it was generated from (`kind`, `seed`, `name`; `local` if the shown text differs), and the system you were in at the time. Each seed is recorded once per session.
- `"t": "label"`: an exotic sighting you labelled with F7, F8 or the buttons, with the system and its exotic's seed.

[`tools/captures/report.py`](../tools/captures/report.py) reads these files. It summarises the ship pools and checks the game's data against itself. It also finds each system's ship seeds in the random-number stream seeded by the system seed, turns the traces into draw counts and lists the exotic labels. Given a clone of nms_namegen, it scores the site's generator against the game, including the names the game generated.

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
