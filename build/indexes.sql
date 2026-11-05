CREATE UNIQUE INDEX strings_text ON strings (text);
CREATE INDEX nodes_global ON nodes (global_id) WHERE global_id IS NOT NULL;
CREATE INDEX nodes_sector ON nodes (sector_id, node_idx);
CREATE INDEX nodes_type ON nodes (type_id);
CREATE INDEX nodes_entry_type ON nodes (entry_type_id) WHERE entry_type_id IS NOT NULL;
CREATE INDEX nodes_resource ON nodes (resource_id) WHERE resource_id IS NOT NULL;
CREATE INDEX nodes_template ON nodes (template_id) WHERE template_id IS NOT NULL;
CREATE INDEX refs_value ON node_refs (value_id);
