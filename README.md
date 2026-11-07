# Cyberpunk 2077 world index

What is placed in Night City and where: every node in every streaming sector, with its position, type,
entity template, mesh, `globalNodeId` and the TweakDB records it references, and the world's other files, such as
mappins, loot, devices and traffic, as SQLite databases built per game version and edition.

**Status:** built for game 2.31 and 2.5, each with and without Phantom Liberty, schema version 7. Every sector of all
four is read, and each node's class and each node-data row has been compared with the game's archive bytes, with no
differences. Rows, resources, appearances, instanced copies and collision actors also match
[Akiway's node exports](https://github.com/Akiway/ArchiveXL-Sector-Updater), a separate read of the same files. No database is
released yet.

## Editions

| Edition | The world of | Sectors on 2.5 |
| --- | --- | --- |
| `ep1` | a game with Phantom Liberty | 26,384 |
| `base` | a game without it | 23,735 |

The names are the game's own, from `worldStreamingDataGroup`. Phantom Liberty does more than add sectors: it replaces
the base game's copy of 1,941 existing sectors with one holding a different number of placements, so a compatibility
patch for a player without it needs the `base` index.

## Game truth only

Every row is read from the game's own sector files and nothing else. A mod that corrects or reshapes
world data (a district outline drawn from trigger areas, a set of LOD distances) keeps its version in
its own repository and derives it from this one. That way a patch can be checked against both: what the
game changed, and what each derived set needs to follow.

## What it answers

- the node behind a `globalNodeId`, such as an entity hash read in game
- every node that references a record, such as the containers using one loot table
- where a community spawn set places its characters
- the nearest nodes of a type or template to a point
- where a mesh or template is placed in the world
- trigger and area outlines as the game stores them
- which nodes a patch added, removed or moved, matched across versions
- every plant of a foliage node, or the plants near a point
- what a container rolls, where a mappin stands, which lanes a road has
- what Phantom Liberty changes in a sector of the base game
- every file under a `worlds` folder and every `.community` file, with its size and hash
- which characters a community file spawns, when and where
- every collision actor near a point

## Files

Each edition of each game version is one set of these databases. Sizes are game 2.5 with Phantom Liberty, raw and
under zstd level 19:

| File | Holds | Placements | Raw | zstd |
| --- | --- | --- | --- | --- |
| `core.db` | entities, devices, smart objects, AI spots, markers, triggers and areas, community spawns, and every TweakDB reference | 705,194 | 315 MB | 72 MB |
| `full.db` | everything else: meshes, decals, lights, foliage nodes, water, sound and the rest | 12,462,383 | 2.1 GB | 457 MB |
| `collisions.db` | optional: every actor of every collision and foliage destruction node | 8,576,699 | 905 MB | 253 MB |
| `foliage.db` | optional: every plant of every foliage node, one row each | 10,309,405 | 1.7 GB | 524 MB |
| `world.db` | the world's files other than sectors: mappins, areas, loot, devices, persistent state, roads, traffic, communities, and every file under a `worlds` folder | | 649 MB | 38 MB |
| `smartobjects.db` | optional: the `.smartobjects` files | | 1.2 GB | 26 MB |

`core.db` answers most questions alone. Open the others beside it with `ATTACH` when a query needs a mesh node, a
plant or a world file. The differences are separate databases: `diff-2.31-ep1-2.5-ep1.db` (2.2 GB, 385 MB under zstd)
and `diff-2.31-base-2.5-base.db` for what a patch changed, `diff-2.5-base-2.5-ep1.db` (2.1 GB, 344 MB under zstd) and
`diff-2.31-base-2.31-ep1.db` for what Phantom Liberty changes.

Any SQLite client reads them, with no other tool needed. [SCHEMA.md](SCHEMA.md) describes every table and
column and has example queries. [What the index does not hold](SCHEMA.md#what-the-index-does-not-hold) lists what is left out.

## Building

The databases are built from NDJSON that `extract/world-index.wscript` and `extract/world-files.wscript` write from the
game's archives. The first calls two host functions, `wkit.WorldIndexSector` and `wkit.WorldIndexFoliage`, that WolvenKit
does not ship, and both call `wkit.BaseGameFile` for the `base` edition, so neither runs in stock WolvenKit. The loaded
archives must be the game's own: the scripts stop on a sector or world file a mod archive serves.

```
python build/build.py --game 2.31 --edition ep1 --src <extract>/2.31-ep1 --out out/2.31-ep1
python build/build.py --game 2.5 --edition ep1 --names-from out/2.31-ep1/full.db --src <extract>/2.5-ep1 --out out/2.5-ep1
python build/build_world.py --game 2.5 --edition ep1 --game-dir "<game install>" --src <extract>/2.5-ep1/world --out out/2.5-ep1
python build/diff.py --old out/2.31-ep1 --new out/2.5-ep1 --out out
python build/diff.py --old out/2.5-base --new out/2.5-ep1 --out out
```

`build.py` and `diff.py` take about 3 minutes each and `build_world.py` about 25 seconds. `build.py` writes `foliage.db`
only when the extract has `foliage-*.ndjson` files. `--names-from` names the appearance hashes a 2.5 cooked entry keeps.

`verify/raw_check.py` reads every sector straight from the game's `.archive` files, with no WolvenKit code, and compares
every node class and node-data row with an extract. It takes about a minute and needs only Python and the game:

```
python verify/raw_check.py --game-dir "<game install>" --src <extract>/2.5-base --edition base
```

## What this contains, and whose it is

The world data is Cyberpunk 2077's, so it belongs to CD PROJEKT RED. This repository is an extraction of
it for modding and research, and it carries no game code, assets or binaries. The build scripts and the
database schema are this repository's own work and are [MIT licensed](LICENSE). This is an unofficial
fan work under the CD PROJEKT RED [fan content guidelines](https://www.cdprojektred.com/en/fan-content),
non-commercial, and is not approved or endorsed by CD PROJEKT RED.

This index was built with the assistance of an LLM. No rogue AIs were permitted through the Blackwall.
