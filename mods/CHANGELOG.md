# Capture mod changelog

What changed in each version of [`system_capture.py`](system_capture.py), newest first, and how it did when it ran in the game. Dates are when the version was written.

## 0.13.0 (2026-10-19)

- Records the paint the game picks for the ships and multi-tools it makes (`paint` lines), the NPCs' as well as yours: the texture option and color for each layer, the seed it painted with and the model's parts. NMS.py doesn't name the function that picks it, so the mod finds it by the pattern of its first bytes. Only the paint of the ships of a recorded system's list, of the multi-tools of a system's set or on offer, and of yours is written; the rest, such as other players', waits in memory up to two minutes for a line that names its seed, and is then dropped. `RECORD_PAINT` turns this off.
- Records, once a session, the game's color variants for suns, from the Star entries of its space POI table (a `suns` line). In the game's code, a system's suns take their colors from these, picked by the system's star type.
- System records no longer hold the bytes of the solar system that NMS.py doesn't name, nor of the sky the game draws (`gap`, `rawTail`, `rawSky`), which 0.12.0 recorded in case the colors of a system's other stars were kept there.
- The session header says where the mod reads the paint (`paintLayout`) and the space POI table (`poiLayout`).

Not run in the game.

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
