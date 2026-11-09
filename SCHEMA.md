# Schema

Each game version is one database, `world-index.db`, in a folder named for the version: `2.5`, `2.31`. It holds both of the
version's editions: `ep1`, the world a game with Phantom Liberty loads, and `base`, the world a game without it loads, the
names the game's own `worldStreamingDataGroup` uses. Phantom Liberty ships its own copy of most base-game sectors, and a
copy can add, remove, move or renumber nodes, so the two worlds differ even where they share a sector path.

## Editions

Every row carries `in_ep1` and `in_base`: 1 when it is part of that edition's world. A row both editions hold exactly is
stored once, with both set; a row that differs in any column is stored once per edition, with one set. On 2.5, 9.9 million of
the base edition's 11.5 million placements are shared rows.

The views give the ep1 world under the plain names, `placements`, `plant_placements` and `refs`, and the base world under
`base_placements`, `base_plant_placements` and `base_refs`. A query on a table, rather than a view, filters on the flag:

```sql
SELECT count(*) FROM loot WHERE in_ep1 = 1;
```

What Phantom Liberty changes is the rows with one flag set: `in_ep1 = 1 AND in_base = 0` is what its world has and the base
world does not, and `in_base = 1 AND in_ep1 = 0` the reverse. A node renumbered by its sector's Phantom Liberty copy shows in
both, once under each number; the diff's `same` pairs match them by position.

It holds the sectors' placements, references and outlines (this section), the plants of every foliage node
([Plants](#plants)), every collision actor ([Collision actors](#collision-actors)), and the world's files other than sectors
([World files](#world-files)). Any SQLite client opens it: `sqlite3`, DB Browser for SQLite, Python's `sqlite3` module.
Every value is stored as the game stores it, in metres and degrees, with no encoding to undo.

`nodes.visual` splits the placements in two: 0 for entities, devices, smart objects, AI spots, markers, triggers and
areas, community and crowd data, and every other node that is not visual or physical; 1 for meshes, decals, lights,
foliage nodes, water, collision and the like.

## Tables

### `meta`

`key`, `value`: `game_version`, `schema_version`, `built_utc`, `build_commit`, `merge_counts` (JSON: rows per table and how many
both editions share), and each edition's own build record under `ep1_` and `base_`: `<edition>_built_utc`,
`<edition>_build_commit`, `<edition>_sectors_read`, `<edition>_sectors_listed`, `<edition>_audit` (JSON: what the read could
not carry through, summed over the world; every count is 0 in a clean build, including `collisionUnread`),
`<edition>_nodes_no_row_places` (JSON: count per class), `<edition>_read_errors` (JSON: per sector, each field stored with an
older type than the reader expects, with what was kept), `<edition>_world_built_utc`, `<edition>_world_build_commit`,
`<edition>_world_counts` (JSON) and `<edition>_world_read_errors` (JSON: world files that could not be read; empty in a clean
build). On 2.5, `<edition>_noderefs_corrected` and `<edition>_noderefs_left` (`node_refs` rows) and
`<edition>_community_noderefs_corrected` and `<edition>_community_noderefs_left` (`community_periods` values).

### `strings`

`id`, `text`. Every path, class name, appearance and debug name is stored once here; a column ending in `_id`
holds its `id`. Ids do not match between versions: compare by text.

### `sectors`

One row per streaming sector path, in either edition: `id`, `path_id` (the `.streamingsector` path) and `world`, the world it
belongs to: `03_night_city` or `04_main_menu`, the main menu's backdrop, whose positions are not Night City's. Every
`.streamingsector` in the game's archives is read: the three worlds' streaming blocks list all but a few, and those few are
kept with `block` NULL.

### `sector_editions`

How each edition streams a sector, one row per edition, or one for both when they agree. A sector is in an edition's world
when it has a row with that edition's flag.

| Column | |
| --- | --- |
| `sector_id` | the sector |
| `block` | the streaming block that lists it: `night_city`, `ep1` (Phantom Liberty) or `main_menu`; NULL for a sector no block lists, which the game never streams |
| `category` | `Exterior`, `Interior`, `Quest`, `Navigation` or `AlwaysLoaded`; NULL when `block` is NULL |
| `level` | streaming level |
| `prefab_id` | a quest sector's prefab node path, which names the place and the state it belongs to |
| `min_x` .. `max_z` | the streaming box; NULL for a quest sector, whose box is infinite |
| `variants` | JSON `[{name, on, range}]`: the sector's optional node ranges and whether each is on by default |
| `in_base`, `in_ep1` | which editions stream it so |

### `nodes`

One row per placement. Most placements are a row of a sector's node data. An instanced mesh, destructible or
occluder holds many copies: it has one row here per copy, numbered by `instance_no`. Each node-data row of a
destructible places its own copies, so `row_idx`, `global_id` and `variant` belong to that copy. The copies of an
instanced mesh or occluder are all under the first row of the node or group; any further row of it has a placement
with `position_source` `none`, so every node-data row of a sector is in the index.

| Column | |
| --- | --- |
| `id` | placement id |
| `sector_id`, `node_idx`, `row_idx` | the sector, the node it places and the row's position in the sector |
| `instance_index` | for a cooked node, the entry this row places; NULL otherwise |
| `type_id` | the node class as stored, e.g. `worldEntityNode`, `worldCookedStaticMeshNode` |
| `entry_type_id` | for a cooked entry, the class it stands for, e.g. `worldStaticMeshNode`; NULL otherwise |
| `global_id` | the node's `worldGlobalNodeID`, NULL where the game stores 0 (see below) |
| `x`, `y`, `z` | position in metres |
| `yaw` | heading in degrees, from the quaternion |
| `qi`, `qj`, `qk`, `qr` | rotation quaternion |
| `sx`, `sy`, `sz` | scale |
| `resource_id` | the mesh, or a decal's material |
| `appearance_id` | the mesh appearance. A 2.5 cooked entry stores it as a hash; `build.py` names it from every string it knows, and one with no known name stays the hash as a decimal |
| `template_id`, `entity_appearance_id` | an entity node's `.ent` template and appearance |
| `debug_id` | the node's debug name |
| `variant` | the sector variant range the row sits in; 0 is always on |
| `streaming_distance` | metres |
| `instance_no` | the copy's number within its node-data row; NULL for anything else |
| `position_source` | `row` (the node-data row), `instance` (the instanced node's own copy transforms) or `none` (a further row of an instanced mesh or occluder, at the origin: `x`, `y`, `z` are NULL) |
| `visual` | 1 for a visual or physical node (mesh, decal, light, foliage node, water, collision and the like), 0 otherwise |
| `in_base`, `in_ep1` | which editions' worlds hold this placement |

An instanced mesh or occluder's own node-data row sits at the origin; its copies' real positions are what the
`instance` rows hold. An occluder copy's rotation and scale come from its stored world matrix.

`global_id` is an unsigned 64-bit hash stored as a signed 64-bit integer, because SQLite integers are signed.
To look one up from its unsigned form, subtract 2^64 when it is 2^63 or more; do it before the value reaches
SQLite, which turns a literal above 2^63 into a rounded real. A CET `entEntityID.hash` for a static world
entity is this value. `gid` and `eid` values in `node_refs` use the same signed form, so
`CAST(value AS INTEGER) = global_id` joins them.

### `node_refs`

What a node references, one row per value, with `in_base` and `in_ep1`. A node placed by several rows lists its
references once. A node's index can differ between the editions' copies of a sector, so join on the flag too.

| Column | |
| --- | --- |
| `sector_id`, `node_idx` | the node |
| `kind` | `tdb` (TweakDB record), `res` (resource path), `ref` (NodeRef), `eid` (entity id hash), `gid` (global node id hash), `name` (a CName: on a community node any, on other nodes `meshAppearance`, `appearanceName` and `meshFracturedAppearance`) |
| `path_id` | where in the node the value sits, each array index written as `[]`, e.g. `instanceData.buffer.gameContainerObjectBase.lootTables[]` |
| `idx` | the array indexes of that path, in order, comma-separated; `''` when the path has none |
| `value_id` | the value |

`path_id` and `idx` together give the full path: `area.entriesData[].phasesData[].timePeriodsData[].spotNodeIds[]`
with `idx` `2,0,1,5` is `area.entriesData[2].phasesData[0].timePeriodsData[1].spotNodeIds[5]`. Values whose
`idx` share a prefix sit under the same array element, so a community area's `area.entriesData[].entryName` with
`idx` `2` names the entry whose spots have `idx` starting `2,`. A node's entity template is in
`nodes.template_id`, not here.

### `outlines`

`node_id` (a `nodes.id`), `height`, `points` (JSON `[[x, y, z]]`, world space, metres), `local` (the stored
points, in the node's own space). One row per placement of a trigger, area or other outlined node; it belongs to its
placement's editions.

### `nodes_rtree`, `sectors_rtree`

SQLite R*Tree indexes on x and y. `nodes_rtree` covers each placement with `visual` 0, in both editions. `sectors_rtree`
is the box around everything a sector has in either edition: placements, plants and collision actors. For a visual placement, a plant or an actor, it is the
way to find what is near a point: the sectors near it, then their rows by `sector_id`.

### `plants`

One row per plant of each foliage node; the node itself is a row of `nodes`. `id`, `sector_id`, `node_idx`, `row_idx`
(the foliage node's), `plant_no` (the plant's number within the node), `x`, `y`, `z`, `yaw`, `qi`, `qj`, `qk`, `qr`, `sx`,
`sy`, `sz`, `resource_id` (the plant's mesh), `appearance_id`, `variant`, `in_base`, `in_ep1`.

Plant scale is stored as the file has it: on 2.5, 22,426 plants have a negative scale. Measured by their mesh's bounding
box, 16,041 are under 1 cm across, 21,819 under 5 cm and all but one under 50 cm. The game keeps them: a loaded foliage node
counts every plant the file holds, negative ones included, and numbers them as `plant_no` does. None shows above ground: a
negative scale is the same on all three axes, which turns a plant upside down through its base, and at the places checked
nothing stands where one is listed while the plants around it with a positive scale do.

## Views

`placements` is the ep1 world's `nodes` with the text joined in: `sector`, `type`, `entry_type`, `resource`, `appearance`,
`template`, `entity_appearance`, `debug_name`, and every other column as stored. `plant_placements` is its `plants` with
`sector`, `resource` and `appearance` as text. `refs` is its `node_refs` with `sector`, `path` and `value` as text.
`base_placements`, `base_plant_placements` and `base_refs` are the same for the base world.

## Example queries

The node behind a global id (here a fast travel terminal):

```sql
SELECT type, template, x, y, z FROM placements WHERE global_id = -9170320247914694973;
```

Every node that references a record:

```sql
SELECT p.template, p.x, p.y, p.z, r.path
FROM refs r JOIN placements p ON p.sector = r.sector AND p.node_idx = r.node_idx
WHERE r.value = 'LootTables.ariadne_witcher_clothes';
```

The nearest fast travel terminals to a point:

```sql
SELECT template, x, y, z
FROM placements
WHERE id IN (SELECT id FROM nodes_rtree
             WHERE min_x > -1500 AND max_x < -500 AND min_y > 2000 AND max_y < 3000)
  AND template LIKE '%fast_travel%'
ORDER BY (x + 1000) * (x + 1000) + (y - 2500) * (y - 2500)
LIMIT 3;
```

Where a mesh is placed. Look the path up in `strings` first: matching on the view's text column reads every
placement.

```sql
SELECT p.sector, p.x, p.y, p.z
FROM placements p
WHERE p.id IN (SELECT n.id FROM nodes n
               WHERE n.resource_id = (SELECT id FROM strings
                                      WHERE text LIKE '%traffic_light_s_d_t_3_mproxy.mesh'));
```

Where each entry of a community area stands. An entry's spots are the `spotNodeIds` whose `idx` starts with
the entry's own `idx`, and each spot id is an AI spot's `global_id`:

```sql
WITH area AS (SELECT n.sector_id, n.node_idx FROM placements p JOIN nodes n ON n.id = p.id
              WHERE p.debug_name = '{q305_elevator_checkup}'),
     entries AS (SELECT r.sector_id, r.node_idx, r.idx, r.value AS entry FROM refs r
                 JOIN area a ON a.sector_id = r.sector_id AND a.node_idx = r.node_idx
                 WHERE r.path = 'area.entriesData[].entryName'),
     spots AS (SELECT e.entry, CAST(r.value AS INTEGER) AS spot FROM refs r JOIN entries e
                 ON e.sector_id = r.sector_id AND e.node_idx = r.node_idx
                 AND r.path LIKE 'area.entriesData[].%spotNodeIds[]' AND r.idx LIKE e.idx || ',%')
SELECT s.entry, p.x, p.y, p.z
FROM spots s JOIN placements p ON p.global_id = s.spot
ORDER BY s.entry;
```

The visual placements within 50 m of a point, by class:

```sql
SELECT coalesce(entry_type, type) AS kind, count(*)
FROM placements
WHERE id IN (SELECT id FROM nodes
             WHERE visual = 1
               AND sector_id IN (SELECT id FROM sectors_rtree
                                 WHERE min_x < -1000 AND max_x > -1000 AND min_y < 2500 AND max_y > 2500)
               AND abs(x + 1000) < 50 AND abs(y - 2500) < 50)
GROUP BY kind ORDER BY 2 DESC;
```

The plants within 50 m of a point:

```sql
SELECT p.resource, p.x, p.y, p.z, p.plant_no
FROM plant_placements p
WHERE p.id IN (SELECT id FROM plants
               WHERE sector_id IN (SELECT id FROM sectors_rtree
                                   WHERE min_x < -1000 AND max_x > -1000 AND min_y < 2500 AND max_y > 2500)
                 AND abs(x + 1000) < 50 AND abs(y - 2500) < 50);
```

How many plants of one mesh there are:

```sql
SELECT count(*)
FROM plants
WHERE resource_id = (SELECT id FROM strings WHERE text LIKE '%atriplex_low.mesh');
```

## Collision actors

`collision_actors` holds one row per actor of each collision and foliage destruction node. An actor belongs to its node, or
on 2.5 to its entry, and is listed once, under the first row that places it: `sector_id`, `node_idx`, `row_idx` (join these
to `nodes`), `instance_index` (2.5 cooked entry, NULL otherwise), `actor_no`, `x`, `y`, `z` (world space, metres), `qi`, `qj`,
`qk`, `qr`, `sx`, `sy`, `sz`, `shape_count`, `in_base`, `in_ep1`.

## World files

Every table has the values as the game stores them, and `in_base` and `in_ep1`. A column named `data` holds the rest of the element as JSON. Hashes
that can exceed 2^63 are stored as text in their unsigned form. `world` is `03_night_city` or `04_main_menu`.

| Table | From | Holds |
| --- | --- | --- |
| `files` | the `.archive` indexes | every file under a `worlds` folder and every `.community` file: `path`, `extension`, `archive`, `size`, `disk_size`, `sha1`, `in_tables` (1 when its contents are in these databases) |
| `world_resources` | `.streamingworld` | the world's streaming setup, whole |
| `mappins` | `.mappins` | `kind` (`cooked`, `gps` or `multi`), `journal_path_hash`, position |
| `poi_mappins` | `.poimappins` | `entity_id`, `journal_path_hash`, position |
| `areas` | `.areas` | `entity_id`, position, `radius`, `volume` |
| `loot` | `.loot` | `node_ref_hash` and each `record` it rolls, in order. `node_ref_hash` is a node's global id in its unsigned form |
| `devices` | `.devices`, `_init.devices` | `hash`, `class`, position, `parents`, `children`, `init` (1 for the `_init` file) |
| `persistent_states` | `.psrep` | `cruid`, `class`, `data` |
| `locomotion_paths` | `.locopaths` | `spline_node_ref`, `data` |
| `roads`, `road_links` | `.streamingquerydata` | `global_id`, position, `width`, the road's range in `road_links`, spline in `data` |
| `traffic_lanes` | `.traffic_persistent`, `.lane_polygons`, `.lane_connections` | `node_ref_hash`, lane numbers, `length`, `width`, `max_speed`, `flags`, `sub_graph`, `polygon`, `connections` |
| `traffic_lane_collisions` | `.traffic_collisions` | `data` |
| `traffic_neighbor_groups` | `.spatial_representation` | `lanes` |
| `null_area_collisions`, `null_area_blockades` | `.null_areas` | `area_id`, `data` |
| `sector_inplace` | `.streamingsector_inplace` | `path`, `kind` (`resource` or `embedded`), `resource` |
| `cooked_prefabs` | `.cookedprefab` | `path`, `kind` (`dependency` or `embedded`), `resource` |
| `acoustic_cells` | `.acousticdata` | `path`, `sector`, `node_bytes` (the cell's stored size; its contents are not decoded) |
| `community_entries` | `.community` | `path`, `entry`, `crowd` (1 for a crowd entry), `name`, `character` (TweakDB record), `spawn_in_view`, `initializers` |
| `community_periods` | `.community` | `path`, `entry`, `phase`, `period`, `phase_name`, `always_spawned`, `appearances`, `hour`, `quantity`, `is_sequence`, `markings`, `spot_node_refs`, `categories` |

A `devices` row is not always a placed node. Most `hash` values with no `global_id` in `nodes` belong to
`CommunityProxyPS`, which keeps a community's persistent state.

From `.smartobjects` files: `smart_object_files` (`path`, `box`, `properties`, `transforms`, `sequences`, each JSON),
`smart_objects` (`path`, `idx`, `class`, `data`), `smart_object_members` (`path`, `hash`, `idx`).

### Example queries

What a container rolls, from a global id in its unsigned form:

```sql
SELECT record FROM loot WHERE node_ref_hash = '10001235969088799390' ORDER BY idx;
```

Mappins near a point:

```sql
SELECT kind, journal_path_hash, x, y, z FROM mappins
WHERE x BETWEEN -1100 AND -900 AND y BETWEEN 2400 AND 2600;
```

What Phantom Liberty changed in a base game file:

```sql
SELECT a.path, a.size, b.size, a.sha1 = b.sha1 AS identical
FROM files a JOIN files b ON b.path = a.path AND b.in_ep1 = 1
WHERE a.in_base = 1 AND a.extension = '.mappins';
```

## What the index does not hold

- **Most node properties.** A placement has its transform, class, mesh or template, appearance and debug name, and
  `node_refs` has the TweakDB records, resources, NodeRefs and ids a node holds. Other values, such as a light's
  colour or a trigger's settings, are in the sector files only.
- **A collision actor's shapes.** `collision_actors` has each actor's transform and shape count; each shape's type, size,
  preset and materials are in the sector files only.
- **Most node-data row fields.** Streaming reference points, node flags, streaming priority, data group and proxy
  mesh id are not columns.
- **The names of cable destruction NodeRefs.** A cooked cable keeps its `buffer.innerNodes[].destructionHashes[]` as hashes
  only. The 2.5 `ref` value is a name the reader knew for that hash, or the hash as a number where it knew none (221 rows on
  2.5-ep1, 220 on 2.5-base); `meta` `noderefs_left` counts these rows. Every other NodeRef is its file's text.
- **Files listed but not decoded.** `.gidata` and `.envprobe` are baked lighting. `.geometry_cache`, `.lights`, `.cminimap`
  and the binary buffer of `.spatial_representation` have no decoder here yet. `files` has each one's path, size and hash.
- **Files with nothing to decode.** Every `.location` and `.lane_spots` file holds an empty buffer.
- **Assets stored under a `worlds` folder.** `.mesh`, `.xbm`, `.mi`, `.ent`, `.cfoliage` and the like are in `files` only.
- **World data outside a `worlds` folder, other than `.community` files.** Scenes, quest phases and the like.
- **Files whose name is not known.** `files` lists a path from the names the reader knows, so an archive entry with no
  known name is absent. Every sector the streaming blocks list has a known name.
- **Three device fields.** In `exterior_-17_21_0_0`, `exterior_-21_-1_0_0` and `exterior_-23_1_4_0` a skill check
  field is stored with a class that no longer exists. On 2.31 it is empty; on 2.5 it is read as stored. `meta` `read_errors` names each one.
- **Anything a save, a quest or a mod changes.** A node in an off-by-default `variant` range is listed with that
  range; whether it exists in a game depends on the quest state.

# The diff between two versions

`diff-<old>-<new>.db` pairs every placement of one world with its counterpart in another: `diff-2.31-ep1-2.5-ep1.db` is
what the 2.5 patch changed. `build/diff.py` reads two version databases, an edition of each, so it also builds
`diff-2.31-base-2.5-base.db` and, from one version's two editions, `diff-2.5-base-2.5-ep1.db`: what Phantom Liberty changes,
with each moved or renumbered node paired. A diff needs no index to be read. A foliage node is
paired; its plants are not.

Placements are matched within each sector path on their class and their mesh or template, by position: the same
position to 1 cm first, then the nearest remaining placement within 10 m. A cooked 2.5 entry counts as the 2.31 class
it stands for, and three classes 2.5 renamed (`worldCookedCollisionNode`, `worldCookedAcousticSectorNode`,
`worldCookedFoliageDestructionNode`) compare under their 2.31 names. Node indexes are not a key: 2.5 cooks many
nodes into one, so almost every index changed.

## Tables

### `meta`

`old_game`, `new_game`, `old_edition`, `new_edition`, `old_build`, `new_build`, `built_utc`, `move_limit_m`, and `counts` (JSON: placements
per change).

### `strings`

As in the version databases.

### `sectors`

`id`, `path_id`, `in_old`, `in_new` (1 when the sector exists on that side), `old_placements`, `new_placements`.

### `placements`

One row per pair, or per placement with no counterpart.

| Column | |
| --- | --- |
| `sector_id` | the sector |
| `change` | `same`, `moved` (paired, more than 1 cm apart), `added` (new version only) or `removed` (old version only) |
| `class_id` | the class, under its 2.31 name |
| `key_id` | the mesh, material or template the pair matched on; NULL for classes with none |
| `old_node_idx`, `new_node_idx` | the node index in each version |
| `old_row`, `new_row` | the node-data row in each version: what an ArchiveXL `.xl` deletion or mutation `index` names |
| `old_instance`, `new_instance` | a cooked entry's index within its node; NULL otherwise |
| `old_instance_no`, `new_instance_no` | a copy's number within an instanced node; NULL otherwise |
| `old_global_id`, `new_global_id` | the global node id in each version, signed as in `nodes` |
| `old_x` .. `new_z` | position in each version, metres |
| `distance` | metres between the two positions; NULL when one side is missing |

The `old_` columns are NULL for `added` and the `new_` columns for `removed`.

## View

`changes` is `placements` with `sector`, `class` and `mesh_or_template` as text.

## Example queries

How much changed:

```sql
SELECT change, count(*) FROM placements GROUP BY change;
```

What changed in one sector:

```sql
SELECT change, class, mesh_or_template, old_node_idx, new_node_idx, distance
FROM changes
WHERE sector = 'base\worlds\03_night_city\_compiled\default\exterior_-8_-10_0_0.streamingsector'
  AND change <> 'same';
```

Where a 2.31 row went in 2.5, for updating an ArchiveXL removal or sector edit made against 2.31. ArchiveXL's
`index` is the node-data row, not the node index. Most rows kept their number (83% between 2.31 and 2.5), so a
removal usually needs no change; this says which did not:

```sql
SELECT change, class, mesh_or_template, old_row, new_row, new_node_idx, new_instance
FROM changes
WHERE sector = 'base\worlds\03_night_city\_compiled\default\interior_-44_39_3_0.streamingsector'
  AND old_row = 223;
```

Everything added within 100 m of a point:

```sql
SELECT sector, class, mesh_or_template, new_x, new_y, new_z
FROM changes
WHERE change = 'added' AND new_x BETWEEN -1100 AND -900 AND new_y BETWEEN 2400 AND 2600;
```

Whether a node kept its global id:

```sql
SELECT count(*) AS paired_with_ids, sum(old_global_id = new_global_id) AS kept
FROM placements
WHERE change IN ('same', 'moved') AND old_global_id IS NOT NULL AND new_global_id IS NOT NULL;
```
