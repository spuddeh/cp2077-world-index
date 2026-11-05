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

One row per streaming sector that has a placement in this database.

| Column | |
| --- | --- |
| `id` | sector id, the same in both databases |
| `path_id` | the `.streamingsector` path |
| `category` | `Exterior`, `Interior`, `Quest`, `Navigation` or `AlwaysLoaded` |
| `level` | streaming level |
| `prefab_id` | a quest sector's prefab node path, which names the place and the state it belongs to |
| `min_x` .. `max_z` | the streaming box; NULL for a quest sector, whose box is infinite |
| `variants` | JSON `[{name, on, range}]`: the sector's optional node ranges and whether each is on by default |

### `nodes`

One row per placement: a row of a sector's node data.

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
