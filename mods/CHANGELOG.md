# Capture mod changelog

What changed in each version of [`system_capture.py`](system_capture.py), newest first, and how it did when it ran in the game. Dates are when the version was written.

## 0.15.0 (2026-10-20)

- No longer records what earlier versions' records have settled:
  - Each system's stars (`stars` in system lines, and the game's star count function, `starCount`, in the session header). Worked out from the address, the count matched the one 0.11.0 to 0.14.0 worked out in the game for all 66 systems they counted, and the `NebulaSeed` it follows from, which system lines still hold in their raw data, was the 9th draw of the address in all 139 systems recorded with it. `RECORD_STARS` and the **Stars in the last system** line on the tab are gone.
  - The game's color variants for suns (`suns` lines, and `poiLayout` in the session header): a binary and a trinary system's suns had in the game the colors that the variants and the system's star type give them.
  - The guild of a region's space stations, and the three buttons that recorded it (`guild` lines). Worked out from the address, the guild matched all 43 recorded, in 31 regions of three galaxies.
  - The parts of the ships of a system's list as the game built them (`model` lines), with the tone that played for the exotic's, and of the models the game built with the seed of one of yours (`own` lines). The `paint` line of each holds its parts too: all 3,698 that 0.13.0 and 0.14.0 wrote for the systems' ships hold the same parts as their `model` lines, and the parts worked out from the seed matched those recorded for every one of the systems' ships and multi-tools, 3,350 in all. `RECORD_SHIP_PARTS` is gone: `RECORD_MULTITOOLS` now turns off watching the function the game loads everything through, as the mod watches it only for multi-tools.
  - The palettes of the systems' multi-tools (`palettes` in their `paint` lines). The game makes a multi-tool's the older way, with its older palettes, from the multi-tool's own seed, as it did for all 114 that 0.14.0 recorded, and the colors of all 213 of the systems' multi-tools that 0.13.0 and 0.14.0 recorded are those of the palettes made that way. The paint of a multi-tool of yours, or of one the game isn't told to make with its older palettes, still holds them.
  - The textures of ships and multi-tools the game loads with a descriptor (`tex` lines), which it didn't in 0.13.0's and 0.14.0's sessions.
- Nothing made without a seed is taken for yours. An empty place among your ships holds FFFFFFFFFFFFFFFF, which the game also gives many models it makes without a seed, NPCs' and player characters' among them; 0.12.0 to 0.14.0 took it for the seed of one of your ships, and recorded the models made with it as yours, with their paint. The paint of anything made without a seed is no longer recorded, and no item is paired with a model by such a seed.
- The script's header has `shown = true` under `[tool.pymhf.gui]`. Set to `false`, the mod runs without the pyMHF panel, which Steam's screenshots and recordings may capture instead of the game (see [Screenshots](README.md#screenshots)).

Not run in the game.

## 0.14.0 (2026-10-20)

- Each session's lines go to a file of their own in `captures\`, named for your Steam ID and when the file was made, in UTC, as the project keeps captures: `<Steam ID>_<YYYY_MM_DD_HH_MM>.jsonl`. The Steam ID is the SteamID64 of the account Steam says is logged in, or else of the game's newest save folder; failing both, a random identifier kept in `captures\identifier.txt`. Earlier versions wrote every session to `captures\systems.jsonl`. The log names the folder, not the file.
- `paint` lines for multi-tools hold the palettes the game picked their colors from (`palettes`, the places of each palette's five colors), since 0.13.0's showed they aren't made from the multi-tool's seed, as a ship's are. Every `paint` line says if the game was told to use its older palettes (`legacy`) or to paint the model with one color (`useColour`).

In the game: ran on Steam build 25732212 with NMS.py 181442.0. All of its hooks attached, and it wrote the session to a file of its own, named for the Steam ID and when the file was made. It recorded 14 systems with their ship lists and stars, the multi-tools of each but the one the save loaded into, and the paint of 2,038 models: 1,918 for the systems' ship lists, 114 multi-tools and 6 of yours. The game was told to make every multi-tool with its older palettes, and the palettes it painted each with were those it makes the older way from the multi-tool's own seed.

## 0.13.0 (2026-10-19)

- Records the paint the game picks for the ships and multi-tools it makes (`paint` lines), the NPCs' as well as yours: the texture option and color for each layer, the seed it painted with and the model's parts. NMS.py doesn't name the function that picks it, so the mod finds it by the pattern of its first bytes. Only the paint of the ships of a recorded system's list, of the multi-tools of a system's set or on offer, and of yours is written; the rest, such as other players', waits in memory up to two minutes for a line that names its seed, and is then dropped. `RECORD_PAINT` turns this off.
- Records, once a session, the game's color variants for suns, from the Star entries of its space POI table (a `suns` line). In the game's code, a system's suns take their colors from these, picked by the system's star type.
- System records no longer hold the bytes of the solar system that NMS.py doesn't name, nor of the sky the game draws (`gap`, `rawTail`, `rawSky`), which 0.12.0 recorded in case the colors of a system's other stars were kept there.
- The session header says where the mod reads the paint (`paintLayout`) and the space POI table (`poiLayout`).

In the game: ran on Steam build 25732212 with NMS.py 181442.0. All of its hooks attached, the one on the function it finds by pattern included. It recorded 13 systems with their ship lists and stars, the multi-tools of each but the one the save loaded into, and the paint of 1,917 models: 1,780 for the systems' ship lists, 108 multi-tools and 29 of yours. Every one of the 364 starships took its colors from the palettes the game makes from the ship's seed, as it makes a system's colors from the system's; 1,000 lines of freighters, frigates and other large models, such as their turrets, took theirs from their system's palettes; the multi-tools from neither. The color variants for suns are YellowStar, GreenStar, BlueStar, RedStar and PurpleStar, in the order of the game's star types.

## 0.12.0 (2026-10-18)

- Records what the game makes your own ships, multi-tool and freighter from (`custom` lines), from `cGcResourceCustomisation::CreateGenerationTask`: the customisation's seed, its parts, the texture options picked for it and its two sets of colors, where they look like colors, with all the bytes the mod read; and again 1, 5 and 20 seconds later if it changed. Of anyone else's, only the model file. `RECORD_COLORS` turns this off.
- Records your ships as your player state lists them, and the part of your player state that holds your customisations (`player` lines): half a minute after the first system, when you click **Record your ships' colors now**, and when they've changed. Records the models the game builds with the seed of one of yours (`own` lines), and the textures of ships and multi-tools it loads with a descriptor (`tex` lines).
- System records keep what NMS.py doesn't name of the solar system, where the game may keep the colors of a system's other stars: the bytes between its data and its address (`gap`), and, once the system has settled, the last 41,504 bytes of the solar system object (`rawTail`) and the sky the game draws (`rawSky`).

Not run in the game.

## 0.11.1 (2026-10-06)

- The TradeDepotCapture tab has a **Stars in the last system** line. 0.11.0 gave the count only at the end of the long line about the last system, where it was easy to miss.

In the game: ran twice, on the same game build as 0.10.0 (Steam build 25732212), the second time with NMS.py 181442.0. All of its hooks attached both times. In its second run it recorded 24 systems, with each one's stars, six of them with more than one, and the set of multi-tools of each but the one the save loaded into, which the mod leaves out (see [Record multi-tools](README.md#record-multi-tools)).

## 0.11.0 (2026-10-05)

- Works out each system's stars the way the game's star count function does, without calling it: it checks that the function's code still has the shape the mod knows and that what it reads is where NMS.py puts those values, reads them, and records the count as `stars`, or `starsUnknown` in the two game modes where the function can count another way. The session header holds the function's code and the values it reads.
- A system's set of multi-tools starts with the quick run the game builds just before it generates the system: each one less than 2 seconds after the one before, the last less than 2 seconds before the generation, with the royal, sentinel and Atlas files among them. None is taken for a session's first system. `built` lines, sets and system records say which thread, numbered, they come from.

In the game: ran on the same build as 0.10.0. All of its hooks attached, and it recorded the stars of all 19 systems visited, which screenshots of its two systems with more than one star confirm, and the set of multi-tools of each, the one the save loaded into when the game generated it again on a return visit.

## 0.10.0 (2026-10-05)

- Records each system's stars by calling the game's star count function, `cGcSolarSystem::GetStarCount`, on the game's main thread, but only if its code shows that calling it can't change anything. System records hold the solar system's bytes around what the function reads, and the session header its code. `RECORD_STARS` turns this off.
- Three buttons on the tab record the guild of a region's space stations (`guild` lines). Galaxy attributes include the region's color value.

In the game: ran on a newer build of the game (Steam build 25732212) than earlier versions had, with NMS.py 180383.0. All of its hooks attached; it paired the multi-tool in each space station's case with its model and recorded the guilds clicked. It recorded none of the systems' sets of multi-tools, which the game builds just before it generates a system, not while it does, and no stars: the star count function changes a register it may not, to check the game mode, so 0.10.0 didn't call it.

## 0.9.0 (2026-10-05)

- Records each system's own multi-tools (`pool` lines), those the game builds on the generating thread while it generates the system: each one's model file, seed, parts and resource handle.
- Pairs an item on offer with the model its resource handle names however long ago the model was built, until the game hands the handle to something else, and checks the pairing against what the game's resource manager holds for the handle.
- Multi-tool models are those in `/WEAPONS/MULTITOOL/`, but not in its `MULTITOOLPARTS`.
- The log and the records say why the player's name couldn't be read, never what was read.
- [`start_capture.bat`](start_capture.bat) starts the mod with a double-click.

Not run in the game.

## 0.8.2 (2026-10-04)

- Looks at each item on offer twice a second and records it once what it holds has looked the same twice in a row, and again whenever that changes, with the item's five inventories, the text in its bytes and its bytes, the player's name and title overwritten.
- Pairs an item with its model by the model's seed in the item's bytes and by the resource handle it holds, which the mod learns as the game builds each model, but only with a model built moments before. `built` lines note the multi-tool models the game builds, without their seeds or parts.

In the game: it recorded the multi-tool in a space station's case with its inventories, but without its model: the game builds the multi-tools a system offers as it loads the system, minutes earlier.

## 0.8.1 (2026-10-02)

- No more hotkeys, nor buttons to label an exotic as a squid or not: the parts the mod records show which exotics are squids. **Record the current system now** stays on the tab.

In the game: ran twice with its multi-tool hook attached. It recorded items the game offered, but nothing at a minor settlement's multi-tool rack or at the Space Anomaly.

## 0.8.0 (2026-10-02)

- Records the multi-tools the game offers, a merchant's or a rack's, a gift or a reward, from `cGcPurchaseableItem::Update`: `item` lines with the system, where the player was, the nearest planet and the multi-tools the item holds. `RECORD_MULTITOOLS` turns this off.

Not run in the game.

## 0.7.0 (2026-10-02)

- Records the parts the game picks for each ship in a system's ship list, and for its Sentinel crash-site ship, as the game builds them (`model` lines), from `Engine::AddResource`, which the game calls for everything it loads. A tone plays when it records the exotic's. `RECORD_SHIP_PARTS = False` leaves that function alone.

In the game: in its first run, it recorded where each planet is, and the parts of every ship in the system's list, the exotic's included, while the system was still loading; the parts it read match the raw bytes it kept.

## 0.6.0 (2026-10-02)

- Records where each planet and moon is, in system records and in lookups if the game has placed them by then.

Not run in the game; 0.7.0, which records them too, was.

## 0.5.2 (2026-10-02)

- Takes out 0.5.1's change to how the mod finds the game. Attached to a running game, the mod says so after 15 seconds without seeing it, and logs "Found the game" once it can.

In the game: all of its hooks attached.

## 0.5.1 (2026-10-01)

- Takes the game's application object from `cGcApplication::Update` every frame, so that the mod sees a game it attached to while it was running.
- Stops, saying what to do, when pyMHF from an earlier run is still inside the game.

In the game: crashed the game when a save loaded and when it attached to a running game.

## 0.5.0 (2026-10-01)

- Records each generated system's locators, and lets the generator's steps and key attributes join a lookup's trace.

In the game: all of its hooks attached, and the generation traces, names and locators it recorded check out.

## 0.4.1 (2026-10-01)

- Logs each hotkey press and what came of it, and once if `winsound` won't load.

Not run in the game.

## 0.4.0 (2026-10-01)

- Hotkeys while the game has focus: F6 records the current system, F7 and F8 label the exotic just seen as a squid or not. Short tones say how each went, and a tone plays once each system is recorded.

In the game: all of its hooks attached, and the arrival tone plays.

## 0.3.0 (2026-10-01)

- Records the planet and region names the game generates, with their seeds (`name` lines); the key attributes each generation starts from and the raw galaxy attributes; and, in session headers, the Steam build ID and whether each hook attached.
- Two buttons label the exotic just seen as a squid or not.

Not run in the game.

## 0.2.0 (2026-10-01)

- Capture format 2: records the generator's random-number state around each of its steps, the whole generated solar system data, compressed, the name the game shows, and the lookups it makes outside a full generation.

Not run in the game.

## 0.1.1 (2026-10-01)

- Refuses to start on the Microsoft Store's Python or a 32-bit one, which the game can't load, and says what to install instead.

In the game: recorded the first 10 systems, with NMS.py 180383.0.

## 0.1.0 (2026-10-01)

- Records each system the game generates, and again once it has loaded, with its ship list (`SystemShips`: each ship's seed, type, role and faction), its planet generation inputs and its galaxy attributes. It reads the game's memory only through `ReadProcessMemory`, so a struct layout that no longer matches the game logs a warning instead of crashing it.

In the game: its first run, on the Microsoft Store's Python, stopped inside the game, which can't load that Python's files.
