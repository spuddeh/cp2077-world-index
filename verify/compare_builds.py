"""Compare two builds of one edition table by table, by value rather than by row id.

Two builds of the same game data number their strings, sectors and nodes in the order they met them, so ids are not
comparable. Every *_id column that points into strings is read as its text, sector_id as the sector's path, and an
outline's node_id as its node's (sector, row_idx, instance_index, instance_no); the row's own id is left out. Each
table is then read in one fixed order from both builds and walked side by side.

A row present in one build only is listed with its table's identity columns. When the same identity is in both, the
columns that differ are named and counted, so a difference reads as "nodes.resource: 12 rows" rather than as a pair
of rows to compare by eye.

    python verify/compare_builds.py --old out/2.31-ep1 --new <dir> [--db core full collisions foliage world smartobjects] [--show 5]

A table with no IDENTITY entry (sector_inplace, cooked_prefabs, smart_object_members) is matched on every column, so a
changed row shows as one row only in old and one only in new.

Exits 1 when any table differs.
"""
import argparse
import collections
import os
import sqlite3
import sys

STRING_IDS = {
    "sectors": ["path_id", "prefab_id"],
    "nodes": ["type_id", "entry_type_id", "resource_id", "appearance_id", "template_id", "entity_appearance_id",
              "debug_id"],
    "node_refs": ["path_id", "value_id"],
}

# The columns that say which row this is; the rest are its values.
IDENTITY = {
    "sectors": ["path"],
    "nodes": ["sector", "row_idx", "instance_index", "instance_no", "node_idx"],
    "node_refs": ["sector", "node_idx", "kind", "path", "idx", "value"],
    "outlines": ["sector", "row_idx", "instance_index", "instance_no"],
    "actors": ["sector", "row_idx", "instance_index", "actor_no", "node_idx"],
    "meta": ["key"],
    # world.db and smartobjects.db: no string ids, so only the identity is needed.
    "files": ["path"],
    "world_resources": ["world"],
    "mappins": ["world", "kind", "idx"],
    "poi_mappins": ["world", "idx"],
    "areas": ["world", "idx"],
    "loot": ["world", "node_ref_hash", "idx"],
    "devices": ["world", "init", "idx"],
    "persistent_states": ["world", "idx"],
    "locomotion_paths": ["world", "idx"],
    "roads": ["world", "idx"],
    "road_links": ["world", "idx"],
    "traffic_lanes": ["world", "idx"],
    "traffic_lane_collisions": ["world", "idx"],
    "traffic_neighbor_groups": ["world", "idx"],
    "null_area_collisions": ["world", "idx"],
    "null_area_blockades": ["world", "idx"],
    "acoustic_cells": ["path", "idx"],
    "community_entries": ["path", "entry"],
    "community_periods": ["path", "entry", "phase", "period"],
    "smart_object_files": ["path"],
    "smart_objects": ["path", "idx"],
}

SKIP_META = {"built", "build_seconds", "built_utc", "source", "build_commit"}


def columns(con, table):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def query(con, table, has_strings):
    """A SELECT giving the table's rows by value, its column names, ordered by every column."""
    cols = columns(con, table)
    out, joins = [], []
    if table == "outlines":
        joins.append("JOIN nodes n ON n.id = t.node_id JOIN sectors s ON s.id = n.sector_id "
                     "JOIN strings sp ON sp.id = s.path_id")
        out += ["sp.text AS sector", "n.row_idx AS row_idx", "n.instance_index AS instance_index",
                "n.instance_no AS instance_no"]
        out += [f"t.{c} AS {c}" for c in cols if c != "node_id"]
    else:
        for c in cols:
            if c == "id":
                continue
            if c == "sector_id":
                if has_strings:
                    joins.append("JOIN sectors s ON s.id = t.sector_id JOIN strings sp ON sp.id = s.path_id")
                    out.append("sp.text AS sector")
                else:
                    joins.append("JOIN sectors s ON s.id = t.sector_id")
                    out.append("s.path AS sector")
            elif has_strings and c in STRING_IDS.get(table, []):
                alias = "j_" + c
                joins.append(f"LEFT JOIN strings {alias} ON {alias}.id = t.{c}")
                out.append(f"{alias}.text AS {c[:-3]}")
            else:
                out.append(f"t.{c} AS {c}")
    names = [o.rsplit(" AS ", 1)[1] for o in out]
    order = ", ".join(names)
    where = ("WHERE t.key NOT IN (" + ", ".join(f"'{k}'" for k in SKIP_META) + ")") if table == "meta" else ""
    sql = f'SELECT {", ".join(out)} FROM "{table}" t {" ".join(joins)} {where} ORDER BY {order}'
    return sql, names


def key(row):
    """SQLite's own order (NULL, then numbers, then text by code point), so two ordered cursors walk in step."""
    return tuple((0, 0) if v is None else (1, v) if isinstance(v, (int, float)) else (2, v) for v in row)


def compare_table(old, new, table, has_strings, show):
    sql_old, names_old = query(old, table, has_strings)
    sql_new, names_new = query(new, table, has_strings)
    if names_old != names_new:
        print(f"  {table}: columns differ: {names_old} / {names_new}")
        return 1
    ident = [names_old.index(c) for c in IDENTITY.get(table, names_old) if c in names_old]
    a, b = old.execute(sql_old), new.execute(sql_new)
    ra, rb = a.fetchone(), b.fetchone()
    only_old, only_new = {}, {}
    rows = 0
    while ra is not None or rb is not None:
        rows += 1
        if ra is not None and rb is not None and ra == rb:
            ra, rb = a.fetchone(), b.fetchone()
            continue
        if rb is None or (ra is not None and key(ra) < key(rb)):
            only_old.setdefault(tuple(ra[i] for i in ident), []).append(ra)
            ra = a.fetchone()
        else:
            only_new.setdefault(tuple(rb[i] for i in ident), []).append(rb)
            rb = b.fetchone()

    if not only_old and not only_new:
        print(f"  {table}: {rows:,} rows, the same")
        return 0

    changed = collections.Counter()
    examples = collections.defaultdict(list)
    for k in set(only_old) & set(only_new):
        for x, y in zip(only_old[k], only_new[k]):
            cols = tuple(n for n, u, v in zip(names_old, x, y) if u != v)
            changed[cols] += 1
            if len(examples[cols]) < show:
                examples[cols].append((k, [(n, u, v) for n, u, v in zip(names_old, x, y) if u != v]))
        extra = len(only_old[k]) - len(only_new[k])
        if extra:
            changed[("(row count for this identity)",)] += abs(extra)
    gone = [k for k in only_old if k not in only_new]
    added = [k for k in only_new if k not in only_old]
    print(f"  {table}: {rows:,} rows, DIFFER")
    for cols, n in changed.most_common():
        print(f"    {n:9,}  changed {', '.join(cols)}")
        for k, d in examples[cols]:
            print(f"               {k!r:.160}  {d!r:.240}")
    for label, keys, side in (("only in old", gone, only_old), ("only in new", added, only_new)):
        if keys:
            print(f"    {sum(len(side[k]) for k in keys):9,}  {label}")
            for k in keys[:show]:
                print(f"               {side[k][0]!r:.300}")
    return 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--db", nargs="*", default=["core", "full", "collisions", "foliage"])
    p.add_argument("--show", type=int, default=5)
    a = p.parse_args()
    faults = 0
    for name in a.db:
        po, pn = os.path.join(a.old, name + ".db"), os.path.join(a.new, name + ".db")
        if not (os.path.exists(po) and os.path.exists(pn)):
            print(f"{name}.db: not in both builds, skipped")
            continue
        old = sqlite3.connect(f"file:{po}?mode=ro", uri=True)
        new = sqlite3.connect(f"file:{pn}?mode=ro", uri=True)
        tables = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                  if r[0] != "strings" and "rtree" not in r[0]]
        has_strings = "strings" in [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        print(f"{name}.db")
        for table in tables:
            faults += compare_table(old, new, table, has_strings, a.show)
    print("the same" if faults == 0 else f"{faults} table(s) differ")
    sys.exit(1 if faults else 0)


if __name__ == "__main__":
    main()
