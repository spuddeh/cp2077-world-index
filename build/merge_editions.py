"""Merge one game version's two edition builds into the version's world-index.db: every row of both, stored once where
both editions hold it, with in_base and in_ep1 saying which edition's world it belongs to (build/version_schema.sql).

    python build/merge_editions.py --base out/2.5-base --ep1 out/2.5-ep1 --out out/2.5

Each edition folder holds a world-index.db from build.py, build_world.py and, on 2.5, fix_noderefs.py. Rows are compared
by value: string ids as their text, sector ids as the sector's path, and a node's outline as part of the node. Both
editions' rows are read in one sort order and walked side by side, so a row equal in both is written once with both flags.
verify/editions_check.py reads each edition back out and compares it with its edition build.
"""
import argparse
import datetime
import json
import os
import sqlite3
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EDITIONS = ("base", "ep1")

NODES = """SELECT sp.text, n.node_idx, n.row_idx, n.instance_index, t.text, et.text, n.global_id,
  n.x, n.y, n.z, n.yaw, n.qi, n.qj, n.qk, n.qr, n.sx, n.sy, n.sz, r.text, a.text, tp.text, ea.text, d.text,
  n.variant, n.streaming_distance, n.instance_no, n.position_source, n.visual, o.height, o.points, o.local
FROM {s}.nodes n JOIN {s}.sectors sc ON sc.id = n.sector_id JOIN {s}.strings sp ON sp.id = sc.path_id
LEFT JOIN {s}.strings t ON t.id = n.type_id LEFT JOIN {s}.strings et ON et.id = n.entry_type_id
LEFT JOIN {s}.strings r ON r.id = n.resource_id LEFT JOIN {s}.strings a ON a.id = n.appearance_id
LEFT JOIN {s}.strings tp ON tp.id = n.template_id LEFT JOIN {s}.strings ea ON ea.id = n.entity_appearance_id
LEFT JOIN {s}.strings d ON d.id = n.debug_id LEFT JOIN {s}.outlines o ON o.node_id = n.id"""
REFS = """SELECT sp.text, r.node_idx, r.kind, p.text, r.idx, v.text FROM {s}.node_refs r
JOIN {s}.sectors sc ON sc.id = r.sector_id JOIN {s}.strings sp ON sp.id = sc.path_id
JOIN {s}.strings p ON p.id = r.path_id JOIN {s}.strings v ON v.id = r.value_id"""
PLANTS = """SELECT sp.text, p.node_idx, p.row_idx, p.plant_no, p.x, p.y, p.z, p.yaw, p.qi, p.qj, p.qk, p.qr, p.sx, p.sy, p.sz,
  r.text, a.text, p.variant FROM {s}.plants p JOIN {s}.sectors sc ON sc.id = p.sector_id JOIN {s}.strings sp ON sp.id = sc.path_id
LEFT JOIN {s}.strings r ON r.id = p.resource_id LEFT JOIN {s}.strings a ON a.id = p.appearance_id"""
ACTORS = """SELECT sp.text, a.node_idx, a.row_idx, a.instance_index, a.actor_no, a.x, a.y, a.z, a.qi, a.qj, a.qk, a.qr,
  a.sx, a.sy, a.sz, a.shape_count FROM {s}.collision_actors a JOIN {s}.sectors sc ON sc.id = a.sector_id
JOIN {s}.strings sp ON sp.id = sc.path_id"""
STREAMING = """SELECT sp.text, sc.block, sc.category, sc.level, pf.text, sc.min_x, sc.min_y, sc.min_z, sc.max_x, sc.max_y, sc.max_z,
  sc.variants FROM {s}.sectors sc JOIN {s}.strings sp ON sp.id = sc.path_id LEFT JOIN {s}.strings pf ON pf.id = sc.prefab_id"""
SECTOR_TABLES = ("sectors", "nodes", "node_refs", "outlines", "plants", "collision_actors", "strings", "meta")


def key(row):
    """SQLite's own order (NULL, then numbers, then text by code point), so two ordered cursors walk in step."""
    return tuple((0, 0) if v is None else (1, v) if isinstance(v, (int, float)) else (2, v) for v in row)


def walk(con, sql):
    """Every row of both editions, once each where both hold it: (row, in_base, in_ep1), in one sort order."""
    def ordered(schema):
        q = sql.format(s=schema)
        n = len(con.execute(f"SELECT * FROM ({q}) LIMIT 0").description)
        return con.execute(f"SELECT * FROM ({q}) ORDER BY " + ", ".join(str(i + 1) for i in range(n)))
    a, b = ordered("base"), ordered("ep1")
    ra, rb = a.fetchone(), b.fetchone()
    while ra is not None or rb is not None:
        if ra is not None and rb is not None and ra == rb:
            yield ra, 1, 1
            ra, rb = a.fetchone(), b.fetchone()
        elif rb is None or (ra is not None and key(ra) < key(rb)):
            yield ra, 1, 0
            ra = a.fetchone()
        else:
            yield rb, 0, 1
            rb = b.fetchone()


def git_commit():
    try:
        return subprocess.check_output(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="the base edition's folder, holding its world-index.db")
    ap.add_argument("--ep1", required=True, help="the ep1 edition's folder")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "world-index.db")
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect("file:" + os.path.abspath(path).replace(os.sep, "/"), uri=True)
    c.execute("PRAGMA journal_mode = OFF")
    c.execute("PRAGMA synchronous = OFF")
    c.execute("PRAGMA temp_store = FILE")
    for ed, folder in (("base", a.base), ("ep1", a.ep1)):
        source = os.path.abspath(os.path.join(folder, "world-index.db")).replace(os.sep, "/")
        c.execute(f"ATTACH 'file:{source}?immutable=1' AS {ed}")
    metas = {ed: dict(c.execute(f"SELECT key, value FROM {ed}.meta")) for ed in EDITIONS}
    game = metas["ep1"]["game_version"]
    if metas["base"]["game_version"] != game or metas["base"]["edition"] != "base" or metas["ep1"]["edition"] != "ep1":
        raise SystemExit(f"--base and --ep1 must be the base and ep1 builds of one game version: {metas['base'].get('game_version')} "
                         f"{metas['base'].get('edition')}, {game} {metas['ep1'].get('edition')}")
    with open(os.path.join(HERE, "version_schema.sql"), encoding="utf-8") as f:
        c.executescript(f.read())
    world_tables = [r[0] for r in c.execute("SELECT name FROM ep1.sqlite_master WHERE type = 'table'")
                    if r[0] not in SECTOR_TABLES and "rtree" not in r[0]]
    for table in world_tables:
        cols = [r[1] for r in c.execute(f"PRAGMA ep1.table_info({table})")]
        c.execute(f"CREATE TABLE {table} ({', '.join(cols)}, in_base INTEGER, in_ep1 INTEGER)")
    # The world tables keep the indexes build_world.py gives them.
    world_indexes = [sql for (sql,) in c.execute(
        "SELECT sql FROM ep1.sqlite_master WHERE type = 'index' AND sql IS NOT NULL AND tbl_name IN ("
        + ",".join("?" * len(world_tables)) + ")", world_tables)]
    started = time.time()

    strings = {}

    def s(text):
        if text is None:
            return None
        i = strings.get(text)
        if i is None:
            i = strings[text] = len(strings) + 1
        return i

    paths = sorted({p for ed in EDITIONS for (p,) in c.execute(
        f"SELECT t.text FROM {ed}.sectors s JOIN {ed}.strings t ON t.id = s.path_id")})
    sector_id = {p: k + 1 for k, p in enumerate(paths)}
    worlds = {}
    for ed in EDITIONS:
        for p, w in c.execute(f"SELECT t.text, s.world FROM {ed}.sectors s JOIN {ed}.strings t ON t.id = s.path_id"):
            worlds[p] = w
    c.executemany("INSERT INTO sectors VALUES (?,?,?)", ((sector_id[p], s(p), worlds[p]) for p in paths))
    counts = {}

    def merge(label, sql, insert, batch_size=200000):
        n = shared = base = ep1 = 0
        batch = []
        for row, in_base, in_ep1 in walk(c, sql):
            batch.append(insert(row, in_base, in_ep1))
            n += 1
            shared += in_base & in_ep1
            base += in_base
            ep1 += in_ep1
            if len(batch) >= batch_size:
                flush(label, batch)
                batch = []
        flush(label, batch)
        counts[label] = {"rows": n, "in both": shared, "base": base, "ep1": ep1}
        print(f"{label}: {n:,} rows, {shared:,} in both editions, {round(time.time() - started)} s", flush=True)

    pending = {"outlines": []}

    def flush(label, batch):
        if not batch:
            return
        if label == "nodes":
            c.executemany("INSERT INTO nodes VALUES (" + ",".join("?" * 31) + ")", batch)
            c.executemany("INSERT INTO outlines VALUES (?,?,?,?)", pending["outlines"])
            pending["outlines"] = []
        else:
            width = len(batch[0])
            c.executemany(f"INSERT INTO {label} VALUES (" + ",".join("?" * width) + ")", batch)

    merge("sector_editions", STREAMING,
          lambda r, b, e: (sector_id[r[0]], r[1], r[2], r[3], s(r[4]), *r[5:12], b, e))
    next_node = [1]

    def node(r, b, e):
        i = next_node[0]
        next_node[0] += 1
        if r[28] is not None or r[29] is not None:
            pending["outlines"].append((i, r[28], r[29], r[30]))
        return (i, sector_id[r[0]], r[1], r[2], r[3], s(r[4]), s(r[5]), r[6], *r[7:18], s(r[18]), s(r[19]), s(r[20]), s(r[21]),
                s(r[22]), r[23], r[24], r[25], r[26], r[27], b, e)
    merge("nodes", NODES, node)
    merge("node_refs", REFS, lambda r, b, e: (sector_id[r[0]], r[1], r[2], s(r[3]), r[4], s(r[5]), b, e))
    next_plant = [1]

    def plant(r, b, e):
        i = next_plant[0]
        next_plant[0] += 1
        return (i, sector_id[r[0]], *r[1:15], s(r[15]), s(r[16]), r[17], b, e)
    merge("plants", PLANTS, plant)
    merge("collision_actors", ACTORS, lambda r, b, e: (sector_id[r[0]], *r[1:], b, e))
    for table in world_tables:
        merge(table, f"SELECT * FROM {{s}}.{table}", lambda r, b, e: (*r, b, e), batch_size=20000)

    c.executemany("INSERT INTO strings VALUES (?,?)", ((i, t) for t, i in strings.items()))
    meta = {"game_version": game, "schema_version": metas["ep1"]["schema_version"],
            "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "build_commit": git_commit(), "merge_counts": json.dumps(counts)}
    for ed in EDITIONS:
        for k, v in metas[ed].items():
            if k not in ("game_version", "edition", "schema_version"):
                meta[f"{ed}_{k}"] = v
    c.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    c.commit()
    for ed in EDITIONS:
        c.execute(f"DETACH {ed}")
    c.execute("""INSERT INTO sectors_rtree SELECT sector_id, MIN(lo_x), MAX(hi_x), MIN(lo_y), MAX(hi_y) FROM (
                     SELECT sector_id, MIN(x) lo_x, MAX(x) hi_x, MIN(y) lo_y, MAX(y) hi_y FROM nodes GROUP BY sector_id
                     UNION ALL SELECT sector_id, MIN(x), MAX(x), MIN(y), MAX(y) FROM plants GROUP BY sector_id
                     UNION ALL SELECT sector_id, MIN(x), MAX(x), MIN(y), MAX(y) FROM collision_actors GROUP BY sector_id)
                 GROUP BY sector_id""")
    c.execute("INSERT INTO nodes_rtree SELECT id, x, x, y, y FROM nodes WHERE visual = 0")
    with open(os.path.join(HERE, "version_indexes.sql"), encoding="utf-8") as f:
        c.executescript(f.read())
    for sql in world_indexes:
        c.execute(sql)
    c.commit()
    c.execute("VACUUM")
    c.close()
    print(f"world-index.db: {os.path.getsize(path) / 1e6:,.0f} MB, {round(time.time() - started)} s")


if __name__ == "__main__":
    main()
