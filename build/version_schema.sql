-- world-index.db for one game version: both editions of its world in one database. A row is stored once when both
-- editions hold it; in_base and in_ep1 say which edition's world it belongs to (1 = yes). ep1 is the world a game with
-- Phantom Liberty loads, base the world a game without it loads. The views give the ep1 world under the plain names
-- and the base world under base_ names. merge_editions.py writes it from the two edition builds and adds the world-file
-- tables, each with in_base and in_ep1, sets PRAGMA user_version to the schema version and runs ANALYZE. SCHEMA.md
-- describes each table with example queries.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE strings (id INTEGER PRIMARY KEY, text TEXT NOT NULL);

-- One streaming sector path. world is the world folder it belongs to (03_night_city, 04_main_menu).
CREATE TABLE sectors (id INTEGER PRIMARY KEY, path_id INTEGER, world TEXT);

-- How each edition streams a sector: block is the streaming block that lists it (night_city, ep1, main_menu), NULL for a
-- sector in the game files that no block lists, which the game never streams. min/max is the streaming box, NULL for a
-- quest sector, whose box is infinite. variants: [{name, on, range}], range 0 always on. A sector is in an edition's
-- world when it has a row here with that edition's flag.
CREATE TABLE sector_editions (
    sector_id INTEGER, block TEXT, category TEXT, level INTEGER, prefab_id INTEGER,
    min_x REAL, min_y REAL, min_z REAL, max_x REAL, max_y REAL, max_z REAL, variants TEXT, in_base INTEGER, in_ep1 INTEGER
);

-- One placement: a node-data row, as in each edition's copy of the sector. See SCHEMA.md for the columns.
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY, sector_id INTEGER, node_idx INTEGER, row_idx INTEGER, instance_index INTEGER,
    type_id INTEGER, entry_type_id INTEGER, global_id INTEGER,
    x REAL, y REAL, z REAL, yaw REAL,
    qi REAL, qj REAL, qk REAL, qr REAL, sx REAL, sy REAL, sz REAL,
    resource_id INTEGER, appearance_id INTEGER, template_id INTEGER, entity_appearance_id INTEGER,
    debug_id INTEGER, variant INTEGER, streaming_distance REAL, instance_no INTEGER, position_source TEXT,
    visual INTEGER, in_base INTEGER, in_ep1 INTEGER
);

-- What a node references, keyed by sector and node index; a node's index can differ between the editions' copies.
CREATE TABLE node_refs (
    sector_id INTEGER, node_idx INTEGER, kind TEXT, path_id INTEGER, idx TEXT NOT NULL, value_id INTEGER,
    in_base INTEGER, in_ep1 INTEGER,
    PRIMARY KEY (sector_id, node_idx, kind, path_id, idx, value_id)
) WITHOUT ROWID;

-- An area outline per placement; it belongs to its node's editions.
CREATE TABLE outlines (node_id INTEGER PRIMARY KEY, height REAL, points TEXT, local TEXT);

-- One row per plant of a worldFoliageNode.
CREATE TABLE plants (
    id INTEGER PRIMARY KEY, sector_id INTEGER, node_idx INTEGER, row_idx INTEGER, plant_no INTEGER,
    x REAL, y REAL, z REAL, yaw REAL, qi REAL, qj REAL, qk REAL, qr REAL, sx REAL, sy REAL, sz REAL,
    resource_id INTEGER, appearance_id INTEGER, variant INTEGER, in_base INTEGER, in_ep1 INTEGER
);

-- One row per actor of each collision and foliage destruction node, in world space.
CREATE TABLE collision_actors (
    sector_id INTEGER, node_idx INTEGER, row_idx INTEGER, instance_index INTEGER, actor_no INTEGER,
    x REAL, y REAL, z REAL, qi REAL, qj REAL, qk REAL, qr REAL, sx REAL, sy REAL, sz REAL, shape_count INTEGER,
    in_base INTEGER, in_ep1 INTEGER
);

-- The non-visual placements (visual = 0) of both editions by x, y; filter on in_ep1 or in_base.
CREATE VIRTUAL TABLE nodes_rtree USING rtree(id, min_x, max_x, min_y, max_y);

-- The x, y box around everything each sector holds in either edition.
CREATE VIRTUAL TABLE sectors_rtree USING rtree(id, min_x, max_x, min_y, max_y);

CREATE VIEW placements AS
SELECT n.id, sp.text AS sector, n.node_idx, n.row_idx, n.instance_index,
       t.text AS type, et.text AS entry_type, n.global_id,
       n.x, n.y, n.z, n.yaw, n.qi, n.qj, n.qk, n.qr, n.sx, n.sy, n.sz,
       r.text AS resource, a.text AS appearance, tp.text AS template, ea.text AS entity_appearance,
       d.text AS debug_name, n.variant, n.streaming_distance, n.instance_no, n.position_source, n.visual
FROM nodes n
JOIN sectors s ON s.id = n.sector_id
JOIN strings sp ON sp.id = s.path_id
LEFT JOIN strings t ON t.id = n.type_id
LEFT JOIN strings et ON et.id = n.entry_type_id
LEFT JOIN strings r ON r.id = n.resource_id
LEFT JOIN strings a ON a.id = n.appearance_id
LEFT JOIN strings tp ON tp.id = n.template_id
LEFT JOIN strings ea ON ea.id = n.entity_appearance_id
LEFT JOIN strings d ON d.id = n.debug_id
WHERE n.in_ep1 = 1;

CREATE VIEW base_placements AS
SELECT n.id, sp.text AS sector, n.node_idx, n.row_idx, n.instance_index,
       t.text AS type, et.text AS entry_type, n.global_id,
       n.x, n.y, n.z, n.yaw, n.qi, n.qj, n.qk, n.qr, n.sx, n.sy, n.sz,
       r.text AS resource, a.text AS appearance, tp.text AS template, ea.text AS entity_appearance,
       d.text AS debug_name, n.variant, n.streaming_distance, n.instance_no, n.position_source, n.visual
FROM nodes n
JOIN sectors s ON s.id = n.sector_id
JOIN strings sp ON sp.id = s.path_id
LEFT JOIN strings t ON t.id = n.type_id
LEFT JOIN strings et ON et.id = n.entry_type_id
LEFT JOIN strings r ON r.id = n.resource_id
LEFT JOIN strings a ON a.id = n.appearance_id
LEFT JOIN strings tp ON tp.id = n.template_id
LEFT JOIN strings ea ON ea.id = n.entity_appearance_id
LEFT JOIN strings d ON d.id = n.debug_id
WHERE n.in_base = 1;

CREATE VIEW plant_placements AS
SELECT p.id, sp.text AS sector, p.node_idx, p.row_idx, p.plant_no,
       p.x, p.y, p.z, p.yaw, p.qi, p.qj, p.qk, p.qr, p.sx, p.sy, p.sz,
       r.text AS resource, a.text AS appearance, p.variant
FROM plants p
JOIN sectors s ON s.id = p.sector_id
JOIN strings sp ON sp.id = s.path_id
LEFT JOIN strings r ON r.id = p.resource_id
LEFT JOIN strings a ON a.id = p.appearance_id
WHERE p.in_ep1 = 1;

CREATE VIEW base_plant_placements AS
SELECT p.id, sp.text AS sector, p.node_idx, p.row_idx, p.plant_no,
       p.x, p.y, p.z, p.yaw, p.qi, p.qj, p.qk, p.qr, p.sx, p.sy, p.sz,
       r.text AS resource, a.text AS appearance, p.variant
FROM plants p
JOIN sectors s ON s.id = p.sector_id
JOIN strings sp ON sp.id = s.path_id
LEFT JOIN strings r ON r.id = p.resource_id
LEFT JOIN strings a ON a.id = p.appearance_id
WHERE p.in_base = 1;

CREATE VIEW refs AS
SELECT sp.text AS sector, r.sector_id, r.node_idx, r.kind, p.text AS path, r.idx, v.text AS value
FROM node_refs r
JOIN sectors s ON s.id = r.sector_id
JOIN strings sp ON sp.id = s.path_id
JOIN strings p ON p.id = r.path_id
JOIN strings v ON v.id = r.value_id
WHERE r.in_ep1 = 1;

CREATE VIEW base_refs AS
SELECT sp.text AS sector, r.sector_id, r.node_idx, r.kind, p.text AS path, r.idx, v.text AS value
FROM node_refs r
JOIN sectors s ON s.id = r.sector_id
JOIN strings sp ON sp.id = s.path_id
JOIN strings p ON p.id = r.path_id
JOIN strings v ON v.id = r.value_id
WHERE r.in_base = 1;
