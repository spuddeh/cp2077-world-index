-- core.db and full.db share this schema. Text columns ending in _id point into strings.

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
-- NULL where the game stores 0. yaw is in degrees, from the quaternion. variant is the sector variant range.
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY, sector_id INTEGER, node_idx INTEGER, row_idx INTEGER, instance_index INTEGER,
    type_id INTEGER, entry_type_id INTEGER, global_id INTEGER,
    x REAL, y REAL, z REAL, qi REAL, qj REAL, qk REAL, qr REAL, sx REAL, sy REAL, sz REAL, yaw REAL,
    resource_id INTEGER, appearance_id INTEGER, template_id INTEGER, entity_appearance_id INTEGER,
    debug_id INTEGER, variant INTEGER, streaming_distance REAL
);

-- What a node references, keyed by sector and node index (a node placed by several rows lists it once).
-- kind: tdb (TweakDBID), res (resource path), ref (NodeRef), eid (entEntityID hash), gid (worldGlobalNodeID
-- hash), name (CName, community nodes only). path_id is the property path with array indexes removed.
CREATE TABLE node_refs (sector_id INTEGER, node_idx INTEGER, kind TEXT, path_id INTEGER, value_id INTEGER);

-- An area outline per placement. points: world space [[x, y, z]]; local: as stored, in the node's space.
-- height is the stored height times the placement's z scale.
CREATE TABLE outlines (node_id INTEGER PRIMARY KEY, height REAL, points TEXT, local TEXT);

CREATE VIRTUAL TABLE nodes_rtree USING rtree(id, min_x, max_x, min_y, max_y, min_z, max_z);
