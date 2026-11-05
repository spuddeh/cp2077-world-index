"""The differences between two game versions' world indexes, as diff-<a>-<b>.db.

    python build/diff.py --old out/2.31 --new out/2.5 --out out/diff-2.31-2.5

Placements are matched within each sector path on (class, mesh or template). A cooked 2.5 entry counts as the
2.31 class it stands for, so a 2.31 worldStaticMeshNode meets the 2.5 entry that replaced it. Node indexes are not
a key: 2.5 cooks many nodes into one, so they shift. Within a group, placements at the same position (to 1 cm)
pair first, then the nearest remaining ones within MOVE_LIMIT metres; anything left is added or removed.
"""
import argparse
import datetime
import json
import math
import os
import sqlite3
from collections import defaultdict

MOVE_LIMIT = 10.0      # metres: a nearer unmatched pair is the same placement, moved
SAME = 0.01            # metres: closer than this is unmoved
BRUTE_MAX = 4_000_000  # pair comparisons per group before the nearest-pair pass gives up on it

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE strings (id INTEGER PRIMARY KEY, text TEXT NOT NULL);
-- Every sector path in either version; in_old / in_new say which.
CREATE TABLE sectors (id INTEGER PRIMARY KEY, path_id INTEGER, in_old INTEGER, in_new INTEGER,
                      old_placements INTEGER, new_placements INTEGER);
-- Each placement of the old version paired with its counterpart in the new one, or NULL on the missing side.
-- change: same, moved, added (new only), removed (old only). distance is metres between the two positions.
-- class_id is the 2.31 class; key_id the mesh or template the match was made on.
CREATE TABLE placements (
    sector_id INTEGER, change TEXT, class_id INTEGER, key_id INTEGER,
    old_db TEXT, old_node_idx INTEGER, old_row INTEGER, old_global_id INTEGER, old_x REAL, old_y REAL, old_z REAL,
    new_db TEXT, new_node_idx INTEGER, new_row INTEGER, new_global_id INTEGER, new_x REAL, new_y REAL, new_z REAL,
    distance REAL
);
CREATE VIEW changes AS
SELECT sp.text AS sector, p.change, c.text AS class, k.text AS mesh_or_template,
       p.old_db, p.old_node_idx, p.old_row, p.old_global_id, p.old_x, p.old_y, p.old_z,
       p.new_db, p.new_node_idx, p.new_row, p.new_global_id, p.new_x, p.new_y, p.new_z, p.distance
FROM placements p JOIN sectors s ON s.id = p.sector_id JOIN strings sp ON sp.id = s.path_id
LEFT JOIN strings c ON c.id = p.class_id LEFT JOIN strings k ON k.id = p.key_id;
"""

INDEXES = """
CREATE UNIQUE INDEX strings_text ON strings (text);
CREATE INDEX placements_sector ON placements (sector_id, change);
CREATE INDEX placements_change ON placements (change);
CREATE INDEX placements_old ON placements (sector_id, old_node_idx) WHERE old_node_idx IS NOT NULL;
CREATE INDEX placements_new ON placements (sector_id, new_node_idx) WHERE new_node_idx IS NOT NULL;
"""

READ = """
SELECT sp.text, coalesce(et.text, t.text), coalesce(r.text, tp.text), n.node_idx, n.row_idx, n.global_id, n.x, n.y, n.z
FROM {s}.nodes n
JOIN {s}.sectors sc ON sc.id = n.sector_id JOIN {s}.strings sp ON sp.id = sc.path_id
LEFT JOIN {s}.strings t ON t.id = n.type_id LEFT JOIN {s}.strings et ON et.id = n.entry_type_id
LEFT JOIN {s}.strings r ON r.id = n.resource_id LEFT JOIN {s}.strings tp ON tp.id = n.template_id
"""


def read(folder):
    """The index's meta, and its sectors one at a time in path order: (path, {(class, key): [placement]})
    with each placement (db, node_idx, row, global_id, x, y, z). One sector in memory at a time."""
    c = sqlite3.connect(os.path.join(folder, "core.db"))
    meta = dict(c.execute("SELECT key, value FROM meta"))
    parts = ["SELECT 'core', * FROM (" + READ.format(s="main") + ")"]
    if os.path.exists(os.path.join(folder, "full.db")):
        c.execute("ATTACH ? AS full", (os.path.join(folder, "full.db"),))
        parts.append("SELECT 'full', * FROM (" + READ.format(s="full") + ")")
    query = " UNION ALL ".join(parts) + " ORDER BY 2"

    def sectors():
        current, groups = None, defaultdict(list)
        for db, path, cls, key, idx, row, gid, x, y, z in c.execute(query):
            if path != current:
                if current is not None:
                    yield current, groups
                current, groups = path, defaultdict(list)
            groups[(cls, key)].append((db, idx, row, gid, x, y, z))
        if current is not None:
            yield current, groups
        c.close()

    return meta, sectors()


def merged(old, new):
    """(path, old groups, new groups) for every sector path in either stream, in path order."""
    o, n = next(old, None), next(new, None)
    while o is not None or n is not None:
        if n is None or (o is not None and o[0] < n[0]):
            yield o[0], o[1], {}
            o = next(old, None)
        elif o is None or n[0] < o[0]:
            yield n[0], {}, n[1]
            n = next(new, None)
        else:
            yield o[0], o[1], n[1]
            o, n = next(old, None), next(new, None)


def pair(old, new):
    """Pairs (o, n, distance) and the unpaired of each side."""
    pairs = []
    by_pos = defaultdict(list)
    for i, p in enumerate(new):
        by_pos[(round(p[4], 2), round(p[5], 2), round(p[6], 2))].append(i)
    taken_new = set()
    rest_old = []
    for o in old:
        slot = by_pos.get((round(o[4], 2), round(o[5], 2), round(o[6], 2)))
        if slot:
            i = slot.pop()
            taken_new.add(i)
            pairs.append((o, new[i], 0.0))
        else:
            rest_old.append(o)
    rest_new = [p for i, p in enumerate(new) if i not in taken_new]
    if rest_old and rest_new and len(rest_old) * len(rest_new) <= BRUTE_MAX:
        candidates = []
        for a, o in enumerate(rest_old):
            for b, n in enumerate(rest_new):
                d = math.dist(o[4:7], n[4:7])
                if d <= MOVE_LIMIT:
                    candidates.append((d, a, b))
        candidates.sort()
        used_a, used_b = set(), set()
        for d, a, b in candidates:
            if a not in used_a and b not in used_b:
                used_a.add(a)
                used_b.add(b)
                pairs.append((rest_old[a], rest_new[b], d))
        rest_old = [o for a, o in enumerate(rest_old) if a not in used_a]
        rest_new = [n for b, n in enumerate(rest_new) if b not in used_b]
    return pairs, rest_old, rest_new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    old_meta, old = read(a.old)
    new_meta, new = read(a.new)
    os.makedirs(a.out, exist_ok=True)
    name = f"diff-{old_meta['game_version']}-{new_meta['game_version']}.db"
    path = os.path.join(a.out, name)
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode = OFF")
    con.executescript(SCHEMA)
    strings = {}

    def s(text):
        if text is None:
            return None
        if text not in strings:
            strings[text] = len(strings) + 1
        return strings[text]

    counts = defaultdict(int)
    rows = []
    only_old = only_new = 0
    for sid, (sector, o_groups, n_groups) in enumerate(merged(old, new), start=1):
        only_old += not n_groups
        only_new += not o_groups
        con.execute("INSERT INTO sectors VALUES (?,?,?,?,?,?)",
                    (sid, s(sector), int(bool(o_groups)), int(bool(n_groups)),
                     sum(map(len, o_groups.values())), sum(map(len, n_groups.values()))))
        for group in set(o_groups) | set(n_groups):
            cls, key = group
            pairs, removed, added = pair(o_groups.get(group, []), n_groups.get(group, []))
            for o, n, d in pairs:
                change = "same" if d < SAME else "moved"
                counts[change] += 1
                rows.append((sid, change, s(cls), s(key), *o, *n, round(d, 3)))
            for o in removed:
                counts["removed"] += 1
                rows.append((sid, "removed", s(cls), s(key), *o, *(None,) * 7, None))
            for n in added:
                counts["added"] += 1
                rows.append((sid, "added", s(cls), s(key), *(None,) * 7, *n, None))
        if len(rows) > 500_000:
            con.executemany("INSERT INTO placements VALUES (" + ",".join("?" * 19) + ")", rows)
            rows = []
    con.executemany("INSERT INTO placements VALUES (" + ",".join("?" * 19) + ")", rows)
    con.executemany("INSERT INTO strings VALUES (?,?)", ((i, t) for t, i in strings.items()))
    meta = {"old_game": old_meta["game_version"], "new_game": new_meta["game_version"],
            "old_build": old_meta.get("build_commit", ""), "new_build": new_meta.get("build_commit", ""),
            "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "move_limit_m": str(MOVE_LIMIT), "counts": json.dumps(counts)}
    con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    con.executescript(INDEXES)
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"{name}: {dict(counts)}; sectors only in {old_meta['game_version']}: {only_old}, "
          f"only in {new_meta['game_version']}: {only_new}; {os.path.getsize(path) / 1e6:,.0f} MB")


if __name__ == "__main__":
    main()
