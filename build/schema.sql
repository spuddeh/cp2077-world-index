-- core.db and full.db share this schema. Columns ending in _id point into strings. Query through the
-- placements view, which gives metres, degrees and text.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE strings (id INTEGER PRIMARY KEY, text TEXT NOT NULL);

-- One streaming sector, from the streaming blocks. min/max is the streaming box; NULL for a quest sector,
-- whose box is infinite. variants: [{name, on, range}], range 0 always on.
CREATE TABLE sectors (
    id INTEGER PRIMARY KEY, path_id INTEGER, category TEXT, level INTEGER, prefab_id INTEGER,
    min_x REAL, min_y REAL, min_z REAL, max_x REAL, max_y REAL, max_z REAL, variants TEXT
);

-- One placement: a node-data row. A cooked node's row is one of its entries (instance_index), typed as the
-- 2.31 node it stands for (entry_type_id). global_id is the u64 worldGlobalNodeID as a signed 64-bit integer,
-- NULL where the game stores 0. Position is in whole millimetres and yaw in hundredths of a degree.
-- qi..qr are set only when the rotation has pitch or roll; otherwise yaw alone is the rotation. sx..sz are
-- NULL for a scale of 1, 1, 1. variant is the sector variant range. streaming_dm is the streaming distance
-- in decimetres.
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY, sector_id INTEGER, node_idx INTEGER, row_idx INTEGER, instance_index INTEGER,
    type_id INTEGER, entry_type_id INTEGER, global_id INTEGER,
    x_mm INTEGER, y_mm INTEGER, z_mm INTEGER, yaw_cdeg INTEGER,
    qi REAL, qj REAL, qk REAL, qr REAL, sx REAL, sy REAL, sz REAL,
    resource_id INTEGER, appearance_id INTEGER, template_id INTEGER, entity_appearance_id INTEGER,
    debug_id INTEGER, variant INTEGER, streaming_dm INTEGER
);

-- What a node references, keyed by sector and node index (a node placed by several rows lists it once).
-- kind: tdb (TweakDBID), res (resource path), ref (NodeRef), eid (entEntityID hash), gid (worldGlobalNodeID
-- hash), name (CName, community nodes only). path_id is the property path with array indexes removed.
CREATE TABLE node_refs (
    sector_id INTEGER, node_idx INTEGER, kind TEXT, path_id INTEGER, value_id INTEGER,
    PRIMARY KEY (sector_id, node_idx, kind, path_id, value_id)
) WITHOUT ROWID;

-- A reference path that holds the same value on every node it appears on, kept once instead of per node.
CREATE TABLE constant_refs (path_id INTEGER PRIMARY KEY, value_id INTEGER, nodes INTEGER);

-- An area outline per placement. points: world space [[x, y, z]] in metres; local: as stored, in the node's
-- space. height is the stored height times the placement's z scale.
CREATE TABLE outlines (node_id INTEGER PRIMARY KEY, height REAL, points TEXT, local TEXT);

-- Placements by x, y in metres; filter height on nodes.z_mm. core.db only: in full.db, find sectors near a
-- point with sectors_rtree, then their placements with nodes_sector.
CREATE VIRTUAL TABLE nodes_rtree USING rtree(id, min_x, max_x, min_y, max_y);

-- The x, y box around each sector's placements in this database, in metres.
CREATE VIRTUAL TABLE sectors_rtree USING rtree(id, min_x, max_x, min_y, max_y);

CREATE VIEW placements AS
SELECT n.id, sp.text AS sector, n.node_idx, n.row_idx, n.instance_index,
       t.text AS type, et.text AS entry_type, n.global_id,
       n.x_mm / 1000.0 AS x, n.y_mm / 1000.0 AS y, n.z_mm / 1000.0 AS z, n.yaw_cdeg / 100.0 AS yaw,
       n.qi, n.qj, n.qk, n.qr, COALESCE(n.sx, 1) AS sx, COALESCE(n.sy, 1) AS sy, COALESCE(n.sz, 1) AS sz,
       r.text AS resource, a.text AS appearance, tp.text AS template, ea.text AS entity_appearance,
       d.text AS debug_name, n.variant, n.streaming_dm / 10.0 AS streaming_distance
FROM nodes n
JOIN sectors s ON s.id = n.sector_id
JOIN strings sp ON sp.id = s.path_id
LEFT JOIN strings t ON t.id = n.type_id
LEFT JOIN strings et ON et.id = n.entry_type_id
LEFT JOIN strings r ON r.id = n.resource_id
LEFT JOIN strings a ON a.id = n.appearance_id
LEFT JOIN strings tp ON tp.id = n.template_id
LEFT JOIN strings ea ON ea.id = n.entity_appearance_id
LEFT JOIN strings d ON d.id = n.debug_id;

CREATE VIEW refs AS
SELECT sp.text AS sector, r.sector_id, r.node_idx, r.kind, p.text AS path, v.text AS value
FROM node_refs r
JOIN sectors s ON s.id = r.sector_id
JOIN strings sp ON sp.id = s.path_id
JOIN strings p ON p.id = r.path_id
JOIN strings v ON v.id = r.value_id;
