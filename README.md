# Cyberpunk 2077 world index

What is placed in Night City and where: every node in every streaming sector, with its position, type,
entity template, mesh, `globalNodeId` and the TweakDB records it references, as SQLite databases built
once per game version.

**Status: in development.** The schema and build are being written; no database is released yet.

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

## Files

Each game version is one GitHub Release holding two databases with the same schema:

| File | Holds |
| --- | --- |
| `core.db` | entities, devices, smart objects, AI spots, markers, triggers and areas, community spawns, and every TweakDB reference |
| `full.db` | everything else: meshes, decals, lights, foliage, water, sound and the rest |

`core.db` answers most questions alone. Open `full.db` beside it with `ATTACH` when a query needs a mesh
node. A separate Release holds the differences between two game versions.

## What this contains, and whose it is

The world data is Cyberpunk 2077's, so it belongs to CD PROJEKT RED. This repository is an extraction of
it for modding and research, and it carries no game code, assets or binaries. The build scripts and the
database schema are this repository's own work and are [MIT licensed](LICENSE). This is an unofficial
fan work under the CD PROJEKT RED [fan content guidelines](https://www.cdprojektred.com/en/fan-content),
non-commercial, and is not approved or endorsed by CD PROJEKT RED.

This index was built with the assistance of an LLM. No rogue AIs were permitted through the Blackwall.
