"""Reads each edition back out of a version's world-index.db and compares it with that edition's own build, row for row by
value: what merge_editions.py wrote must give each edition exactly.

    python verify/editions_check.py --version out/2.5 --base out/2.5-base --ep1 out/2.5-ep1

Exits 1 on any difference.
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build"))
from merge_editions import ACTORS, NODES, PLANTS, REFS, SECTOR_TABLES, STREAMING, key  # noqa: E402

# The same rows from the version file, for one edition (its flag column in {f}).
V_NODES = """SELECT sp.text, n.node_idx, n.row_idx, n.instance_index, t.text, et.text, n.global_id,
  n.x, n.y, n.z, n.yaw, n.qi, n.qj, n.qk, n.qr, n.sx, n.sy, n.sz, r.text, a.text, tp.text, ea.text, d.text,
  n.variant, n.streaming_distance, n.instance_no, n.position_source, n.visual, o.height, o.points, o.local
FROM nodes n JOIN sectors sc ON sc.id = n.sector_id JOIN strings sp ON sp.id = sc.path_id
LEFT JOIN strings t ON t.id = n.type_id LEFT JOIN strings et ON et.id = n.entry_type_id
LEFT JOIN strings r ON r.id = n.resource_id LEFT JOIN strings a ON a.id = n.appearance_id
LEFT JOIN strings tp ON tp.id = n.template_id LEFT JOIN strings ea ON ea.id = n.entity_appearance_id
LEFT JOIN strings d ON d.id = n.debug_id LEFT JOIN outlines o ON o.node_id = n.id WHERE n.{f} = 1"""
V_REFS = """SELECT sp.text, r.node_idx, r.kind, p.text, r.idx, v.text FROM node_refs r
JOIN sectors sc ON sc.id = r.sector_id JOIN strings sp ON sp.id = sc.path_id
JOIN strings p ON p.id = r.path_id JOIN strings v ON v.id = r.value_id WHERE r.{f} = 1"""
V_PLANTS = """SELECT sp.text, p.node_idx, p.row_idx, p.plant_no, p.x, p.y, p.z, p.yaw, p.qi, p.qj, p.qk, p.qr, p.sx, p.sy, p.sz,
  r.text, a.text, p.variant FROM plants p JOIN sectors sc ON sc.id = p.sector_id JOIN strings sp ON sp.id = sc.path_id
LEFT JOIN strings r ON r.id = p.resource_id LEFT JOIN strings a ON a.id = p.appearance_id WHERE p.{f} = 1"""
V_ACTORS = """SELECT sp.text, a.node_idx, a.row_idx, a.instance_index, a.actor_no, a.x, a.y, a.z, a.qi, a.qj, a.qk, a.qr,
  a.sx, a.sy, a.sz, a.shape_count FROM collision_actors a JOIN sectors sc ON sc.id = a.sector_id
JOIN strings sp ON sp.id = sc.path_id WHERE a.{f} = 1"""
V_STREAMING = """SELECT sp.text, se.block, se.category, se.level, pf.text, se.min_x, se.min_y, se.min_z, se.max_x, se.max_y, se.max_z,
  se.variants FROM sector_editions se JOIN sectors sc ON sc.id = se.sector_id JOIN strings sp ON sp.id = sc.path_id
LEFT JOIN strings pf ON pf.id = se.prefab_id WHERE se.{f} = 1"""
V_WORLDS = """SELECT sp.text, sc.world FROM sectors sc JOIN strings sp ON sp.id = sc.path_id
WHERE sc.id IN (SELECT sector_id FROM sector_editions WHERE {f} = 1)"""
E_WORLDS = """SELECT sp.text, sc.world FROM {s}.sectors sc JOIN {s}.strings sp ON sp.id = sc.path_id"""


def ordered(con, sql):
    n = len(con.execute(f"SELECT * FROM ({sql}) LIMIT 0").description)
    return con.execute(f"SELECT * FROM ({sql}) ORDER BY " + ", ".join(str(i + 1) for i in range(n)))


def compare(label, a, b):
    ra, rb = a.fetchone(), b.fetchone()
    same = only_a = only_b = 0
    examples = []
    while ra is not None or rb is not None:
        if ra is not None and rb is not None and ra == rb:
            same += 1
            ra, rb = a.fetchone(), b.fetchone()
        elif rb is None or (ra is not None and key(ra) < key(rb)):
            only_a += 1
            if len(examples) < 3:
                examples.append(("edition build only", str(ra)[:200]))
            ra = a.fetchone()
        else:
            only_b += 1
            if len(examples) < 3:
                examples.append(("version file only", str(rb)[:200]))
            rb = b.fetchone()
    print(f"  {label}: {same:,} the same, {only_a:,} only in the edition build, {only_b:,} only in the version file", flush=True)
    for e in examples:
        print("     ", e)
    return bool(only_a or only_b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="the version's folder, holding its world-index.db")
    ap.add_argument("--base", required=True)
    ap.add_argument("--ep1", required=True)
    a = ap.parse_args()
    v = sqlite3.connect(f"file:{os.path.join(a.version, 'world-index.db')}?immutable=1", uri=True)
    faults = 0
    for ed, folder in (("base", a.base), ("ep1", a.ep1)):
        e = sqlite3.connect(f"file:{os.path.join(folder, 'world-index.db')}?immutable=1", uri=True)
        f = "in_" + ed
        print(ed)
        pairs = [("sector streaming", STREAMING, V_STREAMING), ("sector worlds", E_WORLDS, V_WORLDS), ("nodes", NODES, V_NODES),
                 ("node_refs", REFS, V_REFS), ("plants", PLANTS, V_PLANTS), ("collision_actors", ACTORS, V_ACTORS)]
        tables = [r[0] for r in e.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                  if r[0] not in SECTOR_TABLES and "rtree" not in r[0]]
        for table in tables:
            cols = ", ".join(r[1] for r in e.execute(f"PRAGMA table_info({table})"))
            pairs.append((table, f"SELECT * FROM {{s}}.{table}", f"SELECT {cols} FROM {table} WHERE {{f}} = 1"))
        for label, sql_e, sql_v in pairs:
            faults += compare(label, ordered(e, sql_e.format(s="main")), ordered(v, sql_v.format(f=f)))
        vm = dict(v.execute("SELECT key, value FROM meta"))
        em = dict(e.execute("SELECT key, value FROM meta"))
        missing = [k for k, val in em.items() if k not in ("game_version", "edition", "schema_version") and vm.get(f"{ed}_{k}") != val]
        print(f"  meta: {len(em)} keys, {len(missing)} not carried over as {ed}_<key>: {missing}")
        faults += bool(missing)
    print("the same" if not faults else f"{faults} difference(s)")
    sys.exit(1 if faults else 0)


if __name__ == "__main__":
    main()
