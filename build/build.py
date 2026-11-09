"""Build world-index.db for one game version and edition from the extract's NDJSON: sectors, placements, node
references, outlines, plants and collision actors (build/schema.sql).

    python build/build.py --game 2.5 --src <dump>/wscript/raw/world-index/2.5-ep1 --out out/2.5-ep1

It writes a new database, so build_world.py, which adds the world-file tables to it, runs after it. A placement is
visual (nodes.visual = 1) when its node type is visual or physical data: meshes, decals, lights, foliage, water,
collision and the like. Plants come from foliage-*.ndjson, one row each.
"""
import argparse
import datetime
import glob
import json
import math
import os
import re
import sqlite3

from stamp import git_commit

SCHEMA_VERSION = 9
BACKSLASH = chr(92)
ARRAY_INDEX = re.compile(r"\[(\d+)\]")
HERE = os.path.dirname(os.path.abspath(__file__))

# A type whose name matches is visual. Matched against the entry type when the row is a cooked entry.
VISUAL = re.compile(r"Mesh|Decal|Foliage|Water|Acoustic|Collision|Light|Particle|Occluder|Terrain|GINode|GISpace"
                  r"|Reflection|Effect|Destruction|Rotating|Advertisement|Cable|Fog|Clouds|Wind|Weather")


def fnv1a64(text):
    h = 0xcbf29ce484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xffffffffffffffff
    return h


class Db:
    def __init__(self, path):
        if os.path.exists(path):
            os.remove(path)
        self.con = sqlite3.connect(path)
        self.con.execute("PRAGMA journal_mode = OFF")
        self.con.execute("PRAGMA synchronous = OFF")
        with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
            self.con.executescript(f.read())
        self.strings = {}
        self.sectors = set()
        self.nodes = []
        self.refs = []
        self.outlines = []
        self.plants = []
        self.actors = []
        self.next_id = 1
        self.next_plant = 1
        self.actor_count = 0

    def s(self, text):
        if text is None:
            return None
        sid = self.strings.get(text)
        if sid is None:
            sid = len(self.strings) + 1
            self.strings[text] = sid
        return sid

    def flush(self):
        c = self.con
        c.executemany("INSERT INTO nodes VALUES (" + ",".join("?" * 29) + ")", self.nodes)
        c.executemany("INSERT OR IGNORE INTO node_refs VALUES (?,?,?,?,?,?)", self.refs)
        c.executemany("INSERT INTO outlines VALUES (?,?,?,?)", self.outlines)
        c.executemany("INSERT INTO plants VALUES (" + ",".join("?" * 19) + ")", self.plants)
        c.executemany("INSERT INTO collision_actors VALUES (" + ",".join("?" * 16) + ")", self.actors)
        self.nodes, self.refs, self.outlines, self.plants, self.actors = [], [], [], [], []

    def pending(self):
        return len(self.nodes) + len(self.plants) + len(self.actors)


def yaw_degrees(qi, qj, qk, qr):
    return math.degrees(math.atan2(2 * (qr * qk + qi * qj), 1 - 2 * (qj * qj + qk * qk)))


def rotate(q, v):
    qi, qj, qk, qr = q
    x, y, z = v
    # v' = v + 2r(u x v) + 2(u x (u x v)), u = (qi, qj, qk)
    cx, cy, cz = qj * z - qk * y, qk * x - qi * z, qi * y - qj * x
    dx, dy, dz = qj * cz - qk * cy, qk * cx - qi * cz, qi * cy - qj * cx
    return (x + 2 * (qr * cx + dx), y + 2 * (qr * cy + dy), z + 2 * (qr * cz + dz))


def signed64(text):
    if text is None:
        return None
    v = int(text)
    return v - (1 << 64) if v >= (1 << 63) else v


def variant_of(row, starts):
    k = 0
    for i, start in enumerate(starts):
        if row >= start:
            k = i
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--names-from", action="append", default=[], metavar="DB",
                    help="a built database whose strings name appearance hashes a cooked entry keeps")
    ap.add_argument("--edition", default="ep1", choices=["ep1", "base"],
                    help="ep1: the copy a game with Phantom Liberty loads; base: the copy a game without it loads")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    out_path = os.path.join(a.out, "world-index.db")
    db = Db(out_path)

    with open(os.path.join(a.src, "sectors.json"), encoding="utf-8") as f:
        descriptors = {d["path"]: d for d in json.load(f)}
    sector_ids = {path: i + 1 for i, path in enumerate(sorted(descriptors))}

    parts = sorted(glob.glob(os.path.join(a.src, "part-*.ndjson")))
    read = set()
    # What a read could not carry through, summed over the world, and each accepted parsing error by sector.
    audit = {"nodes": 0, "rows": 0, "rowsNoNode": 0, "emptyChunks": 0, "walkCut": 0, "walkErrors": 0, "outlineBad": 0,
             "instanceSplit": 0, "occluderShear": 0, "occluderNonFinite": 0, "occluderUnread": 0, "occluderMismatch": 0,
             "collisionUnread": 0}
    read_errors, analyze_errors, unplaced = {}, {}, {}
    for part in parts:
        with open(part, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                s = json.loads(line)
                path = s["path"]
                sid = sector_ids[path]
                read.add(path)
                for key in audit:
                    audit[key] += s["audit"][key]
                if s["audit"]["readErrors"]:
                    read_errors[path] = s["audit"]["readErrors"]
                if s["audit"].get("analyzeError"):
                    analyze_errors[path] = s["audit"]["analyzeError"]
                for n in s["nodes"]:
                    if n.get("u"):
                        unplaced[n["t"]] = unplaced.get(n["t"], 0) + 1
                for row, node_idx, entry, actors in s.get("collisions") or []:
                    db.sectors.add(sid)
                    for k, t in enumerate(actors):
                        db.actors.append((sid, node_idx, row, entry if entry >= 0 else None, k, *t))
                    db.actor_count += len(actors)
                nodes = {n["i"]: n for n in s["nodes"]}
                starts = s.get("variantIndices") or []
                placed = set()   # node indexes with a placement
                for r in s["rows"]:
                    (row, idx, inst, entry, gid, x, y, z, qi, qj, qk, qr, sx, sy, sz, res, app, dist, instances, _) = r
                    node = nodes.get(idx, {})
                    ntype = node.get("t", "?")
                    visual = 1 if VISUAL.search(entry or ntype) else 0
                    if instances:
                        # An instanced mesh, destructible or occluder: one placement per instance, at its own transform.
                        transforms = [(t, k, "instance") for k, t in enumerate(instances)]
                    elif instances is not None:
                        # A further row of an instanced mesh or occluder, at the origin. Its copies are on the first
                        # row of the node or group; it keeps a placement so its row number can be looked up.
                        transforms = [((None, None, None, qi, qj, qk, qr, sx, sy, sz), None, "none")]
                    else:
                        transforms = [((x, y, z, qi, qj, qk, qr, sx, sy, sz), None, "row")]
                    if not transforms:
                        continue
                    db.sectors.add(sid)
                    for (px, py, pz, pi, pj, pk, pr, psx, psy, psz), number, source in transforms:
                        pid = db.next_id
                        db.next_id += 1
                        db.nodes.append((pid, sid, idx, row, inst if inst >= 0 else None, db.s(ntype), db.s(entry),
                                         signed64(gid), px, py, pz, round(yaw_degrees(pi, pj, pk, pr), 2),
                                         pi, pj, pk, pr, psx, psy, psz,
                                         db.s(res), db.s(app), db.s(node.get("tpl")), db.s(node.get("app")),
                                         db.s(node.get("d")), variant_of(row, starts), dist, number, source, visual))
                        placed.add(idx)
                    ol = node.get("outline")
                    if ol and source == "row":
                        pts = [rotate((qi, qj, qk, qr), (p[0] * sx, p[1] * sy, p[2] * sz)) for p in ol["p"]]
                        pts = [[round(x + px, 3), round(y + py, 3), round(z + pz, 3)] for px, py, pz in pts]
                        db.outlines.append((pid, ol["h"] * sz, json.dumps(pts, separators=(",", ":")),
                                            json.dumps(ol["p"], separators=(",", ":"))))
                for idx in placed:
                    node = nodes.get(idx, {})
                    for kind, at, value in node.get("refs", []):
                        if kind in ("gid", "eid"):
                            value = str(signed64(value))   # the same signed form as nodes.global_id
                        positions = ARRAY_INDEX.findall(at)
                        db.refs.append((sid, idx, kind, db.s(ARRAY_INDEX.sub("[]", at)),
                                        ",".join(positions), db.s(value)))
                if db.pending() > 200000:
                    db.flush()
        print(f"{os.path.basename(part)}: placements {db.next_id - 1:,} collision actors {db.actor_count:,}", flush=True)

    # One row per plant of each worldFoliageNode, from an ONLY = "foliage" extract.
    for part in sorted(glob.glob(os.path.join(a.src, "foliage-*.ndjson"))):
        with open(part, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                s = json.loads(line)
                sid = sector_ids[s["path"]]
                starts = s.get("variantIndices") or []
                for row, idx, mesh, app, plants in s["rows"]:
                    if not plants:
                        continue
                    db.sectors.add(sid)
                    for number, (x, y, z, qi, qj, qk, qr, sx, sy, sz) in enumerate(plants):
                        db.plants.append((db.next_plant, sid, idx, row, number, x, y, z, round(yaw_degrees(qi, qj, qk, qr), 2),
                                          qi, qj, qk, qr, sx, sy, sz, db.s(mesh), db.s(app), variant_of(row, starts)))
                        db.next_plant += 1
                if db.pending() > 200000:
                    db.flush()
        print(f"{os.path.basename(part)}: plants {db.next_plant - 1:,}", flush=True)

    print("audit", json.dumps(audit), flush=True)
    print("nodes no row places", json.dumps(unplaced, sort_keys=True), flush=True)
    print("accepted while reading", json.dumps(read_errors, indent=1), flush=True)
    print("instance decode errors", json.dumps(analyze_errors), flush=True)
    meta = {"game_version": a.game, "edition": a.edition, "schema_version": str(SCHEMA_VERSION), "audit": json.dumps(audit),
            "nodes_no_row_places": json.dumps(unplaced, sort_keys=True), "read_errors": json.dumps(read_errors),
            "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "build_commit": git_commit(), "sectors_read": str(len(read)),
            "sectors_listed": str(len(descriptors))}
    known = {}
    for other in a.names_from:
        o = sqlite3.connect(f"file:{other}?immutable=1", uri=True)
        for (text,) in o.execute("SELECT text FROM strings"):
            known[fnv1a64(text)] = text
        o.close()
    for text in db.strings:
        if not text.isdigit():
            known[fnv1a64(text)] = text
    db.flush()
    c = db.con
    hashes = [(sid, known[int(t)]) for t, sid in list(db.strings.items()) if t.isdigit() and int(t) in known]
    if hashes:
        c.execute("CREATE TEMP TABLE named (old INTEGER PRIMARY KEY, new INTEGER)")
        c.executemany("INSERT INTO named VALUES (?,?)", [(sid, db.s(text)) for sid, text in hashes])
        for table in ("nodes", "plants"):
            c.execute(f"UPDATE {table} SET appearance_id = (SELECT new FROM named WHERE old = appearance_id) "
                      "WHERE appearance_id IN (SELECT old FROM named)")
        c.execute("DROP TABLE named")
    left = sum(1 for t in db.strings if t.isdigit() and int(t) not in known)
    print(f"appearance hashes named {len(hashes):,}, strings still a number {left:,}")
    for path, d in descriptors.items():
        sid = sector_ids[path]
        if sid not in db.sectors:
            continue
        lo, hi = d.get("min") or [None] * 3, d.get("max") or [None] * 3
        c.execute("INSERT INTO sectors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, db.s(path), path.split(BACKSLASH)[2], d.get("block"), d["category"], d["level"],
                   db.s(d.get("prefab")),
                   *lo, *hi, json.dumps(d.get("variants") or [], separators=(",", ":"))))
    c.executemany("INSERT INTO strings VALUES (?,?)", ((i, t) for t, i in db.strings.items()))
    c.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    # The box around everything each sector has: a quest sector's streaming box is infinite.
    c.execute("""INSERT INTO sectors_rtree SELECT sector_id, MIN(lo_x), MAX(hi_x), MIN(lo_y), MAX(hi_y) FROM (
                     SELECT sector_id, MIN(x) lo_x, MAX(x) hi_x, MIN(y) lo_y, MAX(y) hi_y FROM nodes GROUP BY sector_id
                     UNION ALL SELECT sector_id, MIN(x), MAX(x), MIN(y), MAX(y) FROM plants GROUP BY sector_id
                     UNION ALL SELECT sector_id, MIN(x), MAX(x), MIN(y), MAX(y) FROM collision_actors GROUP BY sector_id)
                 GROUP BY sector_id""")
    # A tree per placement only for the non-visual ones: over millions of mesh rows it would be a third of the file.
    c.execute("INSERT INTO nodes_rtree SELECT id, x, x, y, y FROM nodes WHERE visual = 0")
    with open(os.path.join(HERE, "indexes.sql"), encoding="utf-8") as f:
        c.executescript(f.read())
    c.commit()
    c.execute("VACUUM")
    c.close()
    print(f"world-index.db: {db.next_id - 1:,} placements, {db.next_plant - 1:,} plants, {db.actor_count:,} collision actors, "
          f"{os.path.getsize(out_path) / 1e6:,.0f} MB")
    missing = sorted(set(descriptors) - read)
    print(f"sectors read {len(read):,} of {len(descriptors):,}; not read: {missing[:10]}")


if __name__ == "__main__":
    main()
