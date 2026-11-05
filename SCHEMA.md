# Schema

Both databases, `core.db` and `full.db`, use this schema. Any SQLite client opens them: `sqlite3`, DB Browser for
SQLite, Python's `sqlite3` module. Every value is stored as the game stores it, in metres and degrees, with no
encoding to undo.

`core.db` holds entities, devices, smart objects, AI spots, markers, triggers and areas, community and crowd data,
and every other node that is not visual or physical. `full.db` holds meshes, decals, lights, foliage, water,
collision and the like. Each placement is in exactly one of them. Open both with `ATTACH`:

```sql
ATTACH 'full.db' AS full;
```

## Tables

### `meta`

`key`, `value`: `game_version`, `schema_version`, `built_utc`, `build_commit`, `sectors_read`, `sectors_listed`,
`database` (`core` or `full`).

### `strings`

`id`, `text`. Every path, class name, appearance and debug name is stored once here; a column ending in `_id`
holds its `id`. Each database has its own `strings`, so ids do not match between `core.db` and `full.db`.

### `sectors`

One row per streaming sector that has a placement in this database. Every `.streamingsector` in the game's
archives is read: the three worlds' streaming blocks list all but a few, and those few are kept with `block` NULL.

| Column | |
| --- | --- |
| `id` | sector id, the same in both databases |
| `path_id` | the `.streamingsector` path |
| `world` | the world it belongs to: `03_night_city` (with Phantom Liberty) or `04_main_menu`, the main menu's backdrop, whose positions are not Night City's |
| `block` | the streaming block that lists it: `night_city`, `ep1` (Phantom Liberty) or `main_menu`; NULL for a sector no block lists, which the game never streams |
| `category` | `Exterior`, `Interior`, `Quest`, `Navigation` or `AlwaysLoaded`; NULL when `block` is NULL |
| `level` | streaming level |
| `prefab_id` | a quest sector's prefab node path, which names the place and the state it belongs to |
| `min_x` .. `max_z` | the streaming box; NULL for a quest sector, whose box is infinite |
| `variants` | JSON `[{name, on, range}]`: the sector's optional node ranges and whether each is on by default |

### `nodes`

One row per placement. Most placements are a row of a sector's node data. An instanced mesh or destructible holds
many copies of one mesh: it has one row here per copy, all with the same `node_idx` and `row_idx`, numbered by
`instance_no`.

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
| `appearance_id` | the mesh appearance |
| `template_id`, `entity_appearance_id` | an entity node's `.ent` template and appearance |
| `debug_id` | the node's debug name |
| `variant` | the sector variant range the row sits in; 0 is always on |
| `streaming_distance` | metres |
| `instance_no` | the copy's number within its instanced node (or 2.5 group); NULL for anything else |
| `position_source` | `row` (the node-data row), `instance` (the instanced node's own copy transforms), `bounds` (the centre of the node's world bounds) or `none` (no position in the files: `x`, `y`, `z` are NULL) |

A 2.5 instanced mesh group's own node-data row sits at the origin; its copies' real positions are what the
`instance` rows hold. Instanced occluders (about 12,000 per version) are `none`: their copies are not decoded and
their world bounds are empty.

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
| `kind` | `tdb` (TweakDB record), `res` (resource path), `ref` (NodeRef), `eid` (entity id hash), `gid` (global node id hash), `name` (CName, community nodes only) |
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
is the box around each sector's placements, in both databases; in `full.db` it is the way to find placements
near a point.

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

# The diff between two versions

`diff-<old>-<new>.db` (e.g. `diff-2.31-2.5.db`) pairs every placement of one game version with its counterpart in
the next. It is built from the two versions' `core.db` and `full.db` by `build/diff.py` and needs neither of them
to be read.

Placements are matched within each sector path on their class and their mesh or template, by position: the same
position to 1 cm first, then the nearest remaining placement within 10 m. A cooked 2.5 entry counts as the 2.31 class
it stands for, and three classes 2.5 renamed (`worldCookedCollisionNode`, `worldCookedAcousticSectorNode`,
`worldCookedFoliageDestructionNode`) compare under their 2.31 names. Node indexes are not a key: 2.5 cooks many
nodes into one, so almost every index changed.

## Tables

### `meta`

`old_game`, `new_game`, `old_build`, `new_build`, `built_utc`, `move_limit_m`, and `counts` (JSON: placements
per change).

### `strings`

As in the version databases.

### `sectors`

`id`, `path_id`, `in_old`, `in_new` (1 when the sector exists in that version), `old_placements`, `new_placements`.

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
| `old_row`, `new_row` | the node-data row in each version |
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

Where a 2.31 node went in 2.5, for updating a removal or sector edit made against 2.31. A 2.31 node can become
an entry of a cooked 2.5 node, so read `new_instance` too:

```sql
SELECT change, class, new_node_idx, new_instance, new_row
FROM changes
WHERE sector = 'base\worlds\03_night_city\_compiled\default\exterior_-8_19_0_1.streamingsector'
  AND old_node_idx = 474;
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
