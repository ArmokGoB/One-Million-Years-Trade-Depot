# Capture mod

`system_capture.py` records every star system you visit in No Man's Sky, together with `SystemShips`: the list of ships the game prepares for that system (each ship's seed, type, role and faction). The project used these records to work out how the game picks a system's ship seeds from its address, which the site now shows, and uses them to check that model. When the game builds one of those ships, the mod also records the parts the game picked for it. Those records showed which exotics are squids, which the site now predicts, and are how the project means to work out the rest of what a seed looks like: the next step on the [roadmap](../README.md#roadmap). For multi-tools, it records each system's own set, with each one's seed and parts, as the game generates the system, and the items the game offers, such as the multi-tool in a space station's case: what each one holds (its inventories, and the seed and parts of its model) and where you were when it was offered.

The mod only reads. It changes nothing in the game or your save, and it runs on top of [NMS.py](https://github.com/monkeyman192/NMS.py).

**Status:** version 0.1 recorded the first systems in the game, with NMS.py 180383.0. Versions 0.4.0, 0.5.0, 0.5.2 and 0.7.0 have run in the game too: all of their hooks attached, the generation traces, names and locators they recorded check out, and the arrival tone plays. Version 0.5.1 crashed the game when a save loaded or when it attached to a running game; 0.5.2 took out the change that did it. In its first run, 0.7.0 recorded where each planet is, and the parts of every ship in the system's list, the exotic's included, while the system was still loading; the parts it read match the raw bytes it kept. Not yet tried in the game: finding a game that was already running when the mod attached. To record ship parts, 0.7.0 watches a function the game calls for everything it loads. If the game crashes or loads slowly with it, set `RECORD_SHIP_PARTS = False` near the top of `system_capture.py` and the mod leaves that function alone. Version 0.8.1 ran in the game with its multi-tool hook attached and recorded two items the game offered, but nothing at a minor settlement's multi-tool offer or at the Space Anomaly. Version 0.8.2 ran in the game too and recorded the multi-tool in a space station's case with its inventories, but without its model: it paired an item only with a model built moments before, and the game builds the multi-tools a system offers as it loads the system, minutes earlier. Version 0.9.0 pairs them however long ago the model was built, and records each system's set as the game builds it; it hasn't run in the game yet (see [Record multi-tools](#record-multi-tools)). If the mod misbehaves, the log file (see below) is the most useful thing to send.

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

   Or double-click [`start_capture.bat`](start_capture.bat) in the same folder, which runs that for you and keeps its window open if the mod stops with an error.

   This starts the game through Steam with the mod attached, or attaches the mod to the game if it's already running. Two extra windows open: a log console and the pyMHF panel, which has a **TradeDepotCapture** tab.

   Starting the game this way is better: the mod then sees how the system you load into is generated. A system that was generated before the mod attached gets recorded without those details.

   Attached to a game that's already running, the mod can't see the game until the game next changes state. Opening the galaxy map should do it. The log says "Found the game" when it has.
3. Load your save and play as usual. A few seconds after you arrive in a system, the mod plays two short rising notes, and the log shows a line like:

   ```text
   Recorded <system name> (<portal code>, galaxy <number>): 50 ships (Freighter 21, Fighter 9, Shuttle 6, ...)
   ```

   As a system loads, the game builds every ship in its ship list, and the mod records the parts the game picked for each. When it gets to the exotic, three high notes play, often before the loading screen ends, and the log says `Recorded the parts of the exotic (seed ...)`, with its parts. You don't need to wait for the exotic to land. If its first part is `_SCLASSSHIP_SQU`, it's a squid. While the game generates the system, it also builds the system's multi-tools: two quick very high notes play while the system loads, and the log says `Recorded the 8 multi-tools of the system at ...`.
4. Save and quit the game normally when you're done. Pressing Ctrl+C in the terminal closes the game too.

   If you close the terminal window instead while the game keeps running, pyMHF stays inside the game until you quit it, and the mod can't attach again until then. It says so if you try.

The records go to `captures\systems.jsonl` and the logs to `logs\`, both next to `system_capture.py`. Each session adds to the same file.

If you arrive somewhere and don't hear the notes, click **Record the current system now** on the TradeDepotCapture tab. If the log says that some values look wrong for every system, NMS.py probably doesn't match your game version yet.

## Record multi-tools

Each system has several multi-tools of its own. The game builds the whole set while it generates the system, so the mod records it as you arrive, without your going anywhere: each multi-tool's model file, seed and parts, in the order the game built them. In 0.8.2's captures the game built 8 to 10 per system that way, one each from the royal, sentinel and Atlas model files and the rest from the standard one; both times it loaded one system, it built the same files with the same numbers of parts, in the same order. (0.8.2 didn't record their seeds.) The mod takes only the multi-tools built on the thread that generates the system, while it does, as the system's: in the captures so far, the game built yours, and other players' in the Nexus, at other times. The TradeDepotCapture tab counts the multi-tools recorded, the systems whose sets are recorded, and the multi-tools recorded on offer.

To record which of them is on offer, with its class, inventory and stats, go up to where the game offers one: a space station's multi-tool case, a minor settlement's multi-tool rack, or a gift or a reward. Look at what's on offer, as if to buy it, for two or three seconds per multi-tool, then back out. The mod looks at each item the game offers twice a second. It records an item once what it holds has looked the same twice in a row, so anything you look at for about a second or more, and again whenever that changes: in each system, at most 10 times for each thing an item offers and 100 times in all. An item that never looks the same twice in a row is recorded as it is every 20 looks, marked `unsettled`. Two quick very high notes mean it recorded an item holding a multi-tool, the first time it does in a system; the log says `Recorded a multi-tool the game offers (seed ..., number 2 of the system's set)`, with its parts. According to the [No Man's Sky wiki](https://nomanssky.fandom.com/wiki/Multi-Tool), each planet and moon has its own pool of 2 to 4 multi-tools, found in its minor settlements, so a settlement's rack may show multi-tools that aren't in the system's set.

How the game keeps an item on offer is only partly known. NMS.py names a few of its fields, and the items recorded so far showed five inventories in it. Two were in use when the game offered a multi-tool: the first was the same in two systems, and the third (`"i": 2`) changed with what was on offer. The mod pairs an item with a model by the resource handle the item holds, which the mod learns as the game builds each model, however long ago that was, until the game hands that handle to something else; and by a model's seed found in the item's bytes. As a check, it also reads what the game's resource manager holds for the item's handle (`resource`), from where NMS.py says it keeps its resources. It records each item's inventories, the text in it and its bytes, so the rest can be worked out later, and notes each time the game builds a multi-tool's model outside a system's set. Screenshots of the multi-tools you saw, with their class, type and slots, would help match them up.

If the game misbehaves near a multi-tool rack, set `RECORD_MULTITOOLS = False` near the top of `system_capture.py`, and the mod records neither systems' multi-tools nor items on offer. Multi-tools also need `RECORD_SHIP_PARTS`, because their models come through the same function.

## Sounds

Short tones tell you what the mod did, so you needn't switch away from the game:

| Tone | What happened |
|---|---|
| Two rising notes | The system is recorded: a few seconds after you arrive, once per system, or when you click **Record the current system now** |
| Three high notes, the last one higher | The parts of the system's exotic are recorded, once per exotic |
| Two quick very high notes | The system's multi-tools are recorded, while it loads, once per system; or a multi-tool the game offers is recorded, once per multi-tool and system |
| Two low notes | **Record the current system now** didn't work: no system was loaded yet, or the system couldn't be read or written. The log says which |

Near the top of `system_capture.py`, `PLAY_SOUNDS`, `CHIME_ON_ARRIVAL` (the notes after you arrive) and `SOUND_VOLUME` turn the tones off or change their volume, and `RECORD_SHIP_PARTS` and `RECORD_MULTITOOLS` turn off recording ship parts and multi-tools.

## Send captures

Zip `captures\systems.jsonl` and attach it to an [issue](https://github.com/ArmokGoB/One-Million-Years-Trade-Depot/issues). If something went wrong, attach the newest file in `logs\` too.

A capture file holds the address of every system you recorded and when you got there, so anyone you share it with can see where you've been. It holds nothing else about you: no player name, account or save data, and nothing about other players. Ship parts are recorded only for ships in the system's own ship list, never for your ships or other players'. Items the game offers are recorded with what they hold, including any text and their bytes. Your player name and title are overwritten with asterisks in those first, and each word of them three characters or longer, but for "the" and "and", wherever it is; a two-character word, other than a few common ones such as "of", only where it stands alone. A one-character word is left: a lone letter says nothing of who you are, and can't be taken out of bytes without taking out much else. If the mod can't read your name, it leaves an item's text and bytes out, and the log says why (the name was empty, or wasn't text, which would mean NMS.py's idea of where the game keeps it is out of date), never what it read. The game also builds the ships and multi-tools you and other players have. The mod keeps the seeds and parts of the models it sees built in memory only, and writes a model's to the file only as part of a system's own set of multi-tools, built on the thread that generated the system while it did, or of an item on offer that holds its seed or resource handle, and never a ship's unless it's in a recorded system's ship list. A `built` line says that the game built a multi-tool's model outside a system's set, but not its seed or parts. Items and `built` lines are recorded with whether you were in a space station, on foot and so on, and items with which planet was nearest too, but not your position. The first line of each session names the game's executable by its SHA-1 hash and Steam build ID, says which of the mod's hooks attached, and lists the NMS.py, pyMHF and Python versions.

## What a record holds

One JSON object per line. A `"t": "session"` line starts each run of the game and carries the column names for the compact rows below and the game's enum names, since game updates can renumber enums. Each `"t": "sys"` line is one system:

| Field | Meaning |
|---|---|
| `via` | What triggered the record: `gen` (the game generated the system), `poll` (the mod noticed it while you were there), `btn` (you asked, with the button) |
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

Six other kinds of line:

- `"t": "query"`: a lookup, a system the game described without loading it. It has the system's seed, the random-number states around the lookup and around any generation steps inside it, its key attributes if that step ran, and whatever the lookup filled in, perhaps including where its planets are. Each seed is recorded once per session.
- `"t": "name"`: a planet or region name the game generated, with the seed it was generated from (`kind`, `seed`, `name`; `local` if the shown text differs), and the system you were in at the time. Each seed is recorded once per session.
- `"t": "model"`: a ship of a system's ship list that the game built: the system and the ship's `slot` in its list (`"crash"` for the Sentinel crash-site ship), the model file (`name`) and resource `type`, the ship's `seed` (and a second seed, `seed2`, if the game gave one), and the IDs of the parts the game picked (`parts`). The first records of a session also keep the descriptor the game passed, as `raw`, to check the mod reads it right. Each model of each ship is recorded once per session.
- `"t": "pool"`: a system's own multi-tools, the ones the game built while it generated the system: the `system` (its address without the planet digit) and `tools`, in the order the game built them, each with its model file (`name`), resource `type`, `seed` (and `seed2`, if it has one), `parts` and resource `handle`. The same model built twice is listed once. Written once per system per session, and again if the set ever comes out different; with `late`, the generation took longer than the mod waits (60 seconds), so the set may be missing some.
- `"t": "item"`: an item the game offered: the loaded `system`; where you were (`where`, a value of the game's EnvironmentLocation, such as SpaceStation or PlanetOnFoot; the nearest `planet`'s index; and `loc`, your location as in a system line); where the item is in the game's memory (`addr`), which shows when the game reuses an item for another offer; the item's kind (`itemType`, not yet matched to names), `state`, and whether it was `free`, a `gift`, a `reward` or came with an `extra` item; its model's resource `handle` and its scene `node`; `stores`, the inventories it uses out of five, each with its place among them (`i`), its `size` (width, height, slots), `valid` (a bit per usable slot, a row at a time), `class` (C to S), `layout` (the seed, use-seed flag, level and slot count it was laid out from), `autoMax`, `stack` and `name`, and the lists it points to: `entries` and `history` (what's in its slots), `special` (special slots) and `stats` (base stats), or only `implausible` if those bytes can't be an inventory; `entitlement`, two IDs that link the item to an entitlement or reward, when it has them; `texts`, each run of text in the item's bytes with its offset; `model`, the model whose handle the item holds, with its file (`name`), resource `type`, `seed`, `parts`, `handle`, and `pool`, its place in the system's set counting from 0, if it's one of the system's own multi-tools; `tools`, the models whose seed is in the item's bytes, each with its byte `offset` too; `resource`, what the game's resource manager holds for the item's handle: the `slot` in its list, the file (`name`), resource `type`, how many things hold it (`refs`) and, if it has a descriptor, its `seed` and `parts`, or an `error` saying why it couldn't be read; and the item's bytes as `raw`, with `scrubbed`, how many times your name or title was overwritten in them, if any was. With `nameUnread`, the mod couldn't read your name, and says why (`empty`, `not text`, `not UTF-8`, `no player state` or `unreadable`); the text, the inventories' names, the entitlement IDs and the bytes are left out. An item is recorded once what it holds has looked the same twice in a row, half a second apart, and again whenever that changes, once per system per session for each thing it holds; in each system, at most 10 times for each thing an item offers and 100 times in all. With `unsettled`, the item hadn't looked the same twice in 20 looks, and is recorded as it was.
- `"t": "built"`: the game built a multi-tool's model outside a system's set, or, the first time in a session, another model with parts that isn't a ship: its file (`name`), resource `type`, how many `parts` it has and its resource `handle`, with the loaded `system` and `where` you were. Never its seed or parts.

[`tools/captures/report.py`](../tools/captures/report.py) reads these files. It summarises the ship pools and checks the game's data against itself. It also finds each system's ship seeds in the random-number stream seeded by the system seed, turns the traces into draw counts, lists the parts recorded for each exotic, checking whether it's a squid against what the site predicts from its seed, lists each system's own multi-tools, checking that a system's set came out the same each time and that no seed turns up in two systems' sets, and lists the items the game offered, with their inventories and models, which of the system's multi-tools each one was, and the multi-tool models the game built. Given a clone of nms_namegen, it scores the site's generator against the game, including the names the game generated, and checks the ship seeds that [`ship_model.py`](../tools/captures/ship_model.py) predicts from each system's address.

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
