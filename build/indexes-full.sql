-- full.db: the lookups its questions need (by node, by mesh or material, by sector), not by type.
CREATE UNIQUE INDEX strings_text ON strings (text);
CREATE INDEX nodes_global ON nodes (global_id) WHERE global_id IS NOT NULL;
CREATE INDEX nodes_sector ON nodes (sector_id, node_idx);
CREATE INDEX nodes_resource ON nodes (resource_id) WHERE resource_id IS NOT NULL;
CREATE INDEX refs_value ON node_refs (value_id);
