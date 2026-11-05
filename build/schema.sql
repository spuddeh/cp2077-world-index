-- core.db and full.db share this schema. Every value is stored as the game has it, in metres and degrees.
-- Columns ending in _id point into strings; the placements and refs views join the text in. SCHEMA.md
-- describes each table with example queries.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE strings (id INTEGER PRIMARY KEY, text TEXT NOT NULL);

-- One streaming sector. world is the world folder it belongs to (03_night_city, 04_main_menu). block is the
-- streaming block that lists it (night_city, ep1, main_menu), NULL for a sector in the game files that no block
-- lists: the game never streams it, and it has no category, level or box. min/max is the streaming box; NULL for
-- a quest sector, whose box is infinite. variants: [{name, on, range}], range 0 always on.
CREATE TABLE sectors (
    id INTEGER PRIMARY KEY, path_id INTEGER, world TEXT, block TEXT, category TEXT, level INTEGER, prefab_id INTEGER,
    min_x REAL, min_y REAL, min_z REAL, max_x REAL, max_y REAL, max_z REAL, variants TEXT
);

-- One placement: a node-data row. A cooked node's row is one of its entries (instance_index), typed as the
-- 2.31 node it stands for (entry_type_id). global_id is the u64 worldGlobalNodeID as a signed 64-bit integer,
-- NULL where the game stores 0. x, y, z in metres; qi, qj, qk, qr the rotation quaternion; yaw in degrees,
-- derived from it; sx, sy, sz the scale. variant is the sector variant range the row sits in (0 = always on).
-- An instanced mesh or destructible has one row per instance: instance_no numbers them within the node (or 2.5
-- group), and the transform is that instance's. position_source says where the transform comes from: row (the
-- node-data row), instance (the node's own instance transforms), bounds (the centre of the node's world bounds) or
-- none: x, y, z are NULL because the files give no position (an instanced occluder, whose instances are not
-- decoded and whose world bounds are empty).
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY, sector_id INTEGER, node_idx INTEGER, row_idx INTEGER, instance_index INTEGER,
    type_id INTEGER, entry_type_id INTEGER, global_id INTEGER,
    x REAL, y REAL, z REAL, yaw REAL,
    qi REAL, qj REAL, qk REAL, qr REAL, sx REAL, sy REAL, sz REAL,
    resource_id INTEGER, appearance_id INTEGER, template_id INTEGER, entity_appearance_id INTEGER,
    debug_id INTEGER, variant INTEGER, streaming_distance REAL, instance_no INTEGER, position_source TEXT
);

-- What a node references, keyed by sector and node index (a node placed by several rows lists it once).
-- kind: tdb (TweakDBID), res (resource path), ref (NodeRef), eid (entEntityID hash), gid (worldGlobalNodeID
-- hash), name (CName, community nodes only). path_id is the property path with each array index written
-- as []; idx holds those indexes in order, comma-separated ('' when the path has none). Values whose idx
-- share a prefix sit under the same array element.
CREATE TABLE node_refs (
    sector_id INTEGER, node_idx INTEGER, kind TEXT, path_id INTEGER, idx TEXT NOT NULL, value_id INTEGER,
    PRIMARY KEY (sector_id, node_idx, kind, path_id, idx, value_id)
) WITHOUT ROWID;

-- An area outline per placement. points: world space [[x, y, z]] in metres; local: as stored, in the node's
-- space. height is the stored height times the placement's z scale.
CREATE TABLE outlines (node_id INTEGER PRIMARY KEY, height REAL, points TEXT, local TEXT);

-- Placements by x, y in metres; filter height on nodes.z. core.db only: in full.db, find sectors near a
-- point with sectors_rtree, then their placements with nodes_sector.
CREATE VIRTUAL TABLE nodes_rtree USING rtree(id, min_x, max_x, min_y, max_y);

-- The x, y box around each sector's placements in this database, in metres.
CREATE VIRTUAL TABLE sectors_rtree USING rtree(id, min_x, max_x, min_y, max_y);

CREATE VIEW placements AS
SELECT n.id, sp.text AS sector, n.node_idx, n.row_idx, n.instance_index,
       t.text AS type, et.text AS entry_type, n.global_id,
       n.x, n.y, n.z, n.yaw, n.qi, n.qj, n.qk, n.qr, n.sx, n.sy, n.sz,
       r.text AS resource, a.text AS appearance, tp.text AS template, ea.text AS entity_appearance,
       d.text AS debug_name, n.variant, n.streaming_distance, n.instance_no, n.position_source
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
SELECT sp.text AS sector, r.sector_id, r.node_idx, r.kind, p.text AS path, r.idx, v.text AS value
FROM node_refs r
JOIN sectors s ON s.id = r.sector_id
JOIN strings sp ON sp.id = s.path_id
JOIN strings p ON p.id = r.path_id
JOIN strings v ON v.id = r.value_id;
