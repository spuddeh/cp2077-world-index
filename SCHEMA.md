# Schema

Each edition of each game version is one folder of databases, named `<version>-<edition>`: `2.5-ep1`, `2.5-base`,
`2.31-ep1`, `2.31-base`. `ep1` is the world a game with Phantom Liberty loads and `base` the world a game without it
loads, the names the game's own `worldStreamingDataGroup` uses. A sector both ship can differ between them.

`core.db`, `full.db` and the optional `foliage.db` use this schema. `collisions.db` is described under
[Collision actors](#collision-actors), and `world.db` and the optional `smartobjects.db`, which hold the world's files other
than sectors, under [World files](#world-files). Any SQLite client opens them: `sqlite3`, DB Browser for
SQLite, Python's `sqlite3` module. Every value is stored as the game stores it, in metres and degrees, with no
encoding to undo.

`core.db` holds entities, devices, smart objects, AI spots, markers, triggers and areas, community and crowd data,
and every other node that is not visual or physical. `full.db` holds meshes, decals, lights, foliage, water,
collision and the like. Each placement is in exactly one of them. `foliage.db` holds the plants of the foliage
nodes in `full.db`: one row per plant, `type` `worldFoliageNode`, with the node's mesh, `node_idx` and `row_idx`,
`instance_no` the plant's number and `position_source` `instance`. It has no `global_id`, `debug_id` or
`streaming_distance`, and its `node_refs` and `outlines` tables are empty. Plant scale is stored as the file has it:
on 2.5, 22,426 plants have a negative scale. Measured by their mesh's bounding box, 16,041 are under 1 cm across, 21,819 under
5 cm and all but one under 50 cm. Open the others with `ATTACH`:

```sql
ATTACH 'full.db' AS full;
ATTACH 'foliage.db' AS foliage;
```

## Tables

### `meta`

`key`, `value`: `game_version`, `edition` (`ep1` or `base`), `schema_version`, `built_utc`, `build_commit`, `sectors_read`, `sectors_listed`,
`database` (`core`, `full` or `foliage`), `audit` (JSON: what the read could not carry through, summed over the
world; every count is 0 in a clean build, including `collisionUnread`), `nodes_no_row_places` (JSON: count per class), `read_errors` (JSON: per
sector, each field stored with an older type than the reader expects, and each value the reader could not carry).

### `strings`

`id`, `text`. Every path, class name, appearance and debug name is stored once here; a column ending in `_id`
holds its `id`. Each database has its own `strings`, so ids do not match between databases.

### `sectors`

One row per streaming sector that has a placement in this database. Every `.streamingsector` in the game's
archives is read: the three worlds' streaming blocks list all but a few, and those few are kept with `block` NULL.

| Column | |
| --- | --- |
| `id` | sector id, the same in every database of a version |
| `path_id` | the `.streamingsector` path |
| `world` | the world it belongs to: `03_night_city` or `04_main_menu`, the main menu's backdrop, whose positions are not Night City's |
| `block` | the streaming block that lists it: `night_city`, `ep1` (Phantom Liberty) or `main_menu`; NULL for a sector no block lists, which the game never streams |
| `category` | `Exterior`, `Interior`, `Quest`, `Navigation` or `AlwaysLoaded`; NULL when `block` is NULL |
| `level` | streaming level |
| `prefab_id` | a quest sector's prefab node path, which names the place and the state it belongs to |
| `min_x` .. `max_z` | the streaming box; NULL for a quest sector, whose box is infinite |
| `variants` | JSON `[{name, on, range}]`: the sector's optional node ranges and whether each is on by default |

### `nodes`

One row per placement. Most placements are a row of a sector's node data. An instanced mesh, destructible or
occluder holds many copies: it has one row here per copy, numbered by `instance_no`. Each node-data row of a
destructible places its own copies, so `row_idx`, `global_id` and `variant` belong to that copy. The copies of an
instanced mesh or occluder are all under the first row of the node or group; any further row of it has a placement
with `position_source` `none`, so every node-data row of a sector is in the index.

| Column | |
| --- | --- |
| `id` | placement id, unique within the database |
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

An instanced mesh or occluder's own node-data row sits at the origin; its copies' real positions are what the
`instance` rows hold. An occluder copy's rotation and scale come from its stored world matrix.

`global_id` is an unsigned 64-bit hash stored as a signed 64-bit integer, because SQLite integers are signed.
To look one up from its unsigned form, subtract 2^64 when it is 2^63 or more; do it before the value reaches
SQLite, which turns a literal above 2^63 into a rounded real. A CET `entEntityID.hash` for a static world
entity is this value. `gid` and `eid` values in `node_refs` use the same signed form, so
`CAST(value AS INTEGER) = global_id` joins them.

### `node_refs`

What a node references, one row per value. A node placed by several rows lists its references once.

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
points, in the node's own space). One row per placement of a trigger, area or other outlined node.

### `nodes_rtree`, `sectors_rtree`

SQLite R*Tree indexes on x and y. `nodes_rtree` covers each placement and is in `core.db` only. `sectors_rtree`
is the box around each sector's placements, in every database; in `full.db` and `foliage.db` it is the way to find
placements near a point.

## Views

`placements` is `nodes` with the text joined in: `sector`, `type`, `entry_type`, `resource`, `appearance`,
`template`, `entity_appearance`, `debug_name`, and every other column as stored. `refs` is `node_refs` with
`sector`, `path` and `value` as text.

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

Where a mesh is placed (`full.db`). Look the path up in `strings` first: matching on the view's text column
reads every placement.

```sql
SELECT p.sector, p.x, p.y, p.z
FROM full.placements p
WHERE p.id IN (SELECT n.id FROM full.nodes n
               WHERE n.resource_id = (SELECT id FROM full.strings
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

What is within 50 m of a point in `full.db`:

```sql
SELECT coalesce(entry_type, type) AS kind, count(*)
FROM full.placements
WHERE sector IN (SELECT sp.text FROM full.sectors_rtree t
                 JOIN full.sectors s ON s.id = t.id JOIN full.strings sp ON sp.id = s.path_id
                 WHERE t.min_x < -1000 AND t.max_x > -1000 AND t.min_y < 2500 AND t.max_y > 2500)
  AND abs(x + 1000) < 50 AND abs(y - 2500) < 50
GROUP BY kind ORDER BY 2 DESC;
```

The plants within 50 m of a point (`foliage.db`):

```sql
SELECT p.resource, p.x, p.y, p.z, p.instance_no
FROM foliage.placements p
WHERE p.sector IN (SELECT sp.text FROM foliage.sectors_rtree t
                   JOIN foliage.sectors s ON s.id = t.id JOIN foliage.strings sp ON sp.id = s.path_id
                   WHERE t.min_x < -1000 AND t.max_x > -1000 AND t.min_y < 2500 AND t.max_y > 2500)
  AND abs(p.x + 1000) < 50 AND abs(p.y - 2500) < 50;
```

How many plants of one mesh there are:

```sql
SELECT count(*)
FROM foliage.nodes
WHERE resource_id = (SELECT id FROM foliage.strings WHERE text LIKE '%atriplex_low.mesh');
```

## Collision actors

`collisions.db` holds one row per actor of each collision and foliage destruction node. An actor belongs to its node, or on
2.5 to its entry, and is listed once, under the first row that places it.

`actors`: `sector_id`, `node_idx`, `row_idx` (join these to `nodes`), `instance_index` (2.5 cooked entry, NULL otherwise),
`actor_no`, `x`, `y`, `z` (world space, metres), `qi`, `qj`, `qk`, `qr`, `sx`, `sy`, `sz`, `shape_count`. `sectors` is `id`, `path`
with the same ids as the other databases. `sectors_rtree` is the box around each sector's actors.

## World files

### `world.db`

Every table has the values as the game stores them. A column named `data` holds the rest of the element as JSON. Hashes
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

`meta` holds `game_version`, `edition`, `schema_version` (this database's own version), `database`, `built_utc`, `build_commit`,
`counts` (JSON) and `read_errors` (JSON: files that could not be read; empty in a clean build).

A `devices` row is not always a placed node. Most `hash` values with no `global_id` in `nodes` belong to
`CommunityProxyPS`, which keeps a community's persistent state.

### `smartobjects.db`

Optional, from `.smartobjects` files. `smart_object_files` (`path`, `box`, `properties`, `transforms`, `sequences`, each JSON),
`smart_objects` (`path`, `idx`, `class`, `data`), `smart_object_members` (`path`, `hash`, `idx`).

### Example queries

Open them with `ATTACH 'world.db' AS world;`.

What a container rolls, from a global id in its unsigned form:

```sql
SELECT record FROM world.loot WHERE node_ref_hash = '10001235969088799390' ORDER BY idx;
```

Mappins near a point:

```sql
SELECT kind, journal_path_hash, x, y, z FROM world.mappins
WHERE x BETWEEN -1100 AND -900 AND y BETWEEN 2400 AND 2600;
```

What Phantom Liberty changed in a base game file, with both editions' `world.db` attached:

```sql
SELECT a.path, a.size, b.size, a.sha1 = b.sha1 AS identical
FROM base.files a JOIN ep1.files b USING (path)
WHERE a.extension = '.mappins';
```

## What the index does not hold

- **Most node properties.** A placement has its transform, class, mesh or template, appearance and debug name, and
  `node_refs` has the TweakDB records, resources, NodeRefs and ids a node holds. Other values, such as a light's
  colour or a trigger's settings, are in the sector files only.
- **A collision actor's shapes.** `collisions.db` has each actor's transform and shape count; each shape's type, size,
  preset and materials are in the sector files only.
- **Most node-data row fields.** Streaming reference points, node flags, streaming priority, data group and proxy
  mesh id are not columns.
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

`diff-<old>-<new>.db` pairs every placement of one index with its counterpart in another, by version or by edition:
`diff-2.31-ep1-2.5-ep1.db` and `diff-2.31-base-2.5-base.db` are what a patch changed, and `diff-2.5-base-2.5-ep1.db` and
`diff-2.31-base-2.31-ep1.db` are what Phantom Liberty changes. It is built from the two indexes' `core.db` and `full.db`
by `build/diff.py` and needs neither of them to be read. It does not read `foliage.db`: a foliage node is paired, its plants are not.

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
| `old_db`, `new_db` | `core` or `full`: which database of that version holds it |
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
