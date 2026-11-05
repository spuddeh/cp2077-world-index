# Cyberpunk 2077 world index

What is placed in Night City and where: every node in every streaming sector, with its position, type,
entity template, mesh, `globalNodeId` and the TweakDB records it references, as SQLite databases built
once per game version.

**Status:** built for game 2.31 and 2.5, schema version 5. No database is released yet.

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

## Files

Each game version is one GitHub Release holding two databases, and an optional third, with the same schema.
Sizes are game 2.5, raw and under zstd level 19:

| File | Holds | Placements | Raw | zstd |
| --- | --- | --- | --- | --- |
| `core.db` | entities, devices, smart objects, AI spots, markers, triggers and areas, community spawns, and every TweakDB reference | 703,821 | 308 MB | 71 MB |
| `full.db` | everything else: meshes, decals, lights, foliage nodes, water, sound and the rest | 12,421,882 | 2.0 GB | 450 MB |
| `foliage.db` | optional: every plant of every foliage node, one row each | 10,281,911 | 1.7 GB | 523 MB |

`core.db` answers most questions alone. Open `full.db` or `foliage.db` beside it with `ATTACH` when a query
needs a mesh node or a plant. A separate Release holds the differences between two game versions:
`diff-2.31-2.5.db`, 2.2 GB, 385 MB under zstd.

Any SQLite client reads them, with no other tool needed. [SCHEMA.md](SCHEMA.md) describes every table and
column and has example queries. Its [Known gaps](SCHEMA.md#known-gaps) section lists what the index does not hold.

## Building

The databases are built from NDJSON that `extract/world-index.wscript` writes from the game's archives. The script
calls two host functions, `wkit.WorldIndexSector` and `wkit.WorldIndexFoliage`, that WolvenKit does not ship, so it
does not run in stock WolvenKit. The loaded archives must be the game's own: a mod archive that replaces a sector
would put the mod's copy in the index.

```
python build/build.py --game 2.5 --src <extract>/2.5 --out out/2.5
python build/build.py --game 2.31 --src <extract>/2.31 --out out/2.31
python build/diff.py --old out/2.31 --new out/2.5 --out out
```

Each command takes about 3 minutes. `build.py` writes `foliage.db` only when the extract has `foliage-*.ndjson` files.

## What this contains, and whose it is

The world data is Cyberpunk 2077's, so it belongs to CD PROJEKT RED. This repository is an extraction of
it for modding and research, and it carries no game code, assets or binaries. The build scripts and the
database schema are this repository's own work and are [MIT licensed](LICENSE). This is an unofficial
fan work under the CD PROJEKT RED [fan content guidelines](https://www.cdprojektred.com/en/fan-content),
non-commercial, and is not approved or endorsed by CD PROJEKT RED.

This index was built with the assistance of an LLM. No rogue AIs were permitted through the Blackwall.
