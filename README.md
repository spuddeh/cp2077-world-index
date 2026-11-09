# Cyberpunk 2077 world index

What is placed in Night City and where: every node in every streaming sector, with its position, type,
entity template, mesh, `globalNodeId` and the TweakDB records it references, and the world's other files, such as
mappins, loot, devices and traffic, as one SQLite database per game version.

**Status:** built for game 2.31 and 2.5, each with and without Phantom Liberty, schema version 8. Every sector of all
four editions is read, and each node's class and each node-data row has been compared with the game's archive bytes, with no
differences. Rows, resources, appearances, instanced copies and collision actors also match
[Akiway's node exports](https://github.com/Akiway/ArchiveXL-Sector-Updater), a separate read of the same files. No database is
released yet.

## Editions

| Edition | The world of | Sectors on 2.5 |
| --- | --- | --- |
| `ep1` | a game with Phantom Liberty | 26,384 |
| `base` | a game without it | 23,735 |

The names are the game's own, from `worldStreamingDataGroup`. Phantom Liberty does more than add sectors: it ships its
own copy of 21,603 of the base game's sectors, and 9,089 of them hold something different, so a compatibility patch for a
player without it needs the `base` world. Each version's database holds both: every row says which edition's world it
belongs to, and a row both editions share is stored once.

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

One database per game version, `world-index.db`, with both editions. Sizes for game 2.5, raw and under zstd level 19:

| File | Raw | zstd |
| --- | --- | --- |
| `2.5/world-index.db` | 8.3 GB | 1.45 GB |
| `2.31/world-index.db` | 8.4 GB | not yet measured |

Each holds every sector's placements (13.2 million in the 2.5 ep1 world: entities, devices, smart objects, AI spots,
markers, triggers and areas, meshes, decals, lights, foliage nodes, water and the rest), every TweakDB record, resource,
NodeRef and id a node references, trigger and area outlines, every plant of every foliage node (10.3 million), every actor
of every collision and foliage destruction node (8.6 million), and the world's files other than sectors: mappins, areas,
loot, devices, persistent state, roads, traffic, communities, smart objects, and every file under a `worlds` folder.
The plain views (`placements`, `plant_placements`, `refs`) give the world a game with Phantom Liberty loads, and the
`base_` views the world a game without it loads.

The difference between the versions is a separate database: `diff-2.31-ep1-2.5-ep1.db` (2.2 GB, 385 MB under zstd)
pairs every placement of 2.31 with its 2.5 counterpart.

Any SQLite client reads them, with no other tool needed. [SCHEMA.md](SCHEMA.md) describes every table and
column and has example queries. [What the index does not hold](SCHEMA.md#what-the-index-does-not-hold) lists what is left out.

## Building

The databases are built from NDJSON that `extract/world-index.wscript` and `extract/world-files.wscript` write from the
game's archives. The first calls two host functions, `wkit.WorldIndexSector` and `wkit.WorldIndexFoliage`, that WolvenKit
does not ship, and both call `wkit.BaseGameFile` for the `base` edition, so neither runs in stock WolvenKit. The loaded
archives must be the game's own: the scripts stop on a sector or world file a mod archive serves.

Each edition is built on its own into `out/<version>-<edition>/world-index.db`, and the two are merged into the version's
`out/<version>/world-index.db`. For each edition (`ep1`, then `base`):

```
python build/build.py --game 2.5 --edition ep1 --names-from out/2.31/world-index.db --src <extract>/2.5-ep1 --out out/2.5-ep1
python build/build_world.py --game 2.5 --edition ep1 --game-dir "<game install>" --src <extract>/2.5-ep1/world --out out/2.5-ep1
python build/fix_noderefs.py --game-dir "<game install>" --db out/2.5-ep1
```

then:

```
python build/merge_editions.py --base out/2.5-base --ep1 out/2.5-ep1 --out out/2.5
python build/diff.py --old out/2.31-ep1 --new out/2.5-ep1 --out out
```

`build.py` takes about 5 minutes, `build_world.py` about 40 seconds and `merge_editions.py` about 12 minutes. `build_world.py`
adds its tables to the database `build.py` wrote, replacing only its own, so it can run again on its own. `--names-from`
names the appearance hashes a 2.5 cooked entry keeps. `fix_noderefs.py` runs on every 2.5 edition, after `build.py` and
`build_world.py`, and takes about 15 seconds: the 2.5 extract can print a NodeRef in another spelling of the same hash, and
it sets each one to the text its file stores. It edits the database in place, a second run changes nothing, and `meta`
keeps `noderefs_corrected` and `noderefs_left`. `diff.py` reads the edition builds, which can also pair the two editions of
one version (`--old out/2.5-base --new out/2.5-ep1`).

`verify/raw_check.py` reads every sector straight from the game's `.archive` files, with no WolvenKit code, and compares
every node class and node-data row with an extract. `verify/world_check.py` does the same for every world file: it reads each
CR2W property by its own name and type, and the custom data of loot, devices, lanes, persistent state and compiled smart objects
by their layouts; on a 2.5 extract it reports the community NodeRefs in another spelling (193 on ep1, 192 on base) and exits 1,
while its `--db` check of the edition's `world-index.db` passes once `fix_noderefs.py` has run. `verify/noderef_check.py` looks for each sector
NodeRef's text in its own sector; after `fix_noderefs.py` only the cable destruction hashes are left. Each needs only Python and the
game, and takes one to two minutes. `verify/editions_check.py` reads each edition back out of a version's database and
compares it row for row with that edition's build, in about 15 minutes:

```
python verify/raw_check.py --game-dir "<game install>" --src <extract>/2.5-base --edition base
python verify/world_check.py --game-dir "<game install>" --src <extract>/2.5-base/world --edition base --db out/2.5-base/world-index.db
python verify/noderef_check.py --game-dir "<game install>" --db out/2.5-base --edition base
python verify/editions_check.py --version out/2.5 --base out/2.5-base --ep1 out/2.5-ep1
```

## What this contains, and whose it is

The world data is Cyberpunk 2077's, so it belongs to CD PROJEKT RED. This repository is an extraction of
it for modding and research, and it carries no game code, assets or binaries. The build scripts and the
database schema are this repository's own work and are [MIT licensed](LICENSE). This is an unofficial
fan work under the CD PROJEKT RED [fan content guidelines](https://www.cdprojektred.com/en/fan-content),
non-commercial, and is not approved or endorsed by CD PROJEKT RED.

This index was built with the assistance of an LLM. No rogue AIs were permitted through the Blackwall.
