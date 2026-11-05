"""Build core.db and full.db for one game version from the extract's NDJSON.

    python build/build.py --game 2.5 --src <dump>/wscript/raw/world-index/2.5 --out out/2.5

Both databases have the same schema (build/schema.sql). A placement row goes to full.db when its node type is
visual or physical data (meshes, decals, lights, foliage, water, collision, ...) and to core.db otherwise. Node
references and outlines follow their node's database.
"""
import argparse
import datetime
import glob
import json
import math
import os
import re
import sqlite3
import subprocess

SCHEMA_VERSION = 5
ARRAY_INDEX = re.compile(r"\[(\d+)\]")
HERE = os.path.dirname(os.path.abspath(__file__))

# A type whose name matches goes to full.db. Matched against the entry type when the row is a cooked entry.
FULL = re.compile(r"Mesh|Decal|Foliage|Water|Acoustic|Collision|Light|Particle|Occluder|Terrain|GINode|GISpace"
                  r"|Reflection|Effect|Destruction|Rotating|Advertisement|Cable|Fog|Clouds|Wind|Weather")


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
        self.next_id = 1

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
        c.executemany("INSERT INTO nodes VALUES (" + ",".join("?" * 28) + ")", self.nodes)
        c.executemany("INSERT OR IGNORE INTO node_refs VALUES (?,?,?,?,?,?)", self.refs)
        c.executemany("INSERT INTO outlines VALUES (?,?,?,?)", self.outlines)
        self.nodes, self.refs, self.outlines = [], [], []


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


def git_commit():
    """HEAD of this repo, with -dirty when build/ or extract/ has uncommitted changes."""
    try:
        head = subprocess.check_output(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", HERE, "status", "--porcelain", "--", "../build", "../extract"],
                                        text=True).strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    core, full = Db(os.path.join(a.out, "core.db")), Db(os.path.join(a.out, "full.db"))

    with open(os.path.join(a.src, "sectors.json"), encoding="utf-8") as f:
        descriptors = {d["path"]: d for d in json.load(f)}
    sector_ids = {path: i + 1 for i, path in enumerate(sorted(descriptors))}

    parts = sorted(glob.glob(os.path.join(a.src, "part-*.ndjson")))
    read = set()
    for part in parts:
        with open(part, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                s = json.loads(line)
                path = s["path"]
                sid = sector_ids[path]
                read.add(path)
                nodes = {n["i"]: n for n in s["nodes"]}
                starts = s.get("variantIndices") or []
                placed_in = {}   # node index -> (db, first placement id, row)
                for r in s["rows"]:
                    (row, idx, inst, entry, gid, x, y, z, qi, qj, qk, qr, sx, sy, sz, res, app, dist, instances) = r
                    node = nodes.get(idx, {})
                    ntype = node.get("t", "?")
                    db = full if FULL.search(entry or ntype) else core
                    if instances is not None:
                        # An instanced mesh or destructible: one placement per instance, at its own transform. A row
                        # whose instances an earlier row of the same node already listed ([]) adds none.
                        transforms = [(t, k, "instance") for k, t in enumerate(instances)]
                    elif node.get("b") and x == 0 and y == 0 and z == 0:
                        # A node stored at the origin with world bounds (an instanced occluder): the bounds' centre,
                        # or no position when the bounds are empty (min above max), which they are in 2.31 and 2.5.
                        b = node["b"]
                        if b[0] <= b[3] and b[1] <= b[4] and b[2] <= b[5]:
                            centre = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2)
                            transforms = [((*centre, qi, qj, qk, qr, sx, sy, sz), None, "bounds")]
                        else:
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
                                         db.s(node.get("d")), variant_of(row, starts), dist, number, source))
                        if idx not in placed_in:
                            placed_in[idx] = (db, pid)
                    ol = node.get("outline")
                    if ol and source == "row":
                        pts = [rotate((qi, qj, qk, qr), (p[0] * sx, p[1] * sy, p[2] * sz)) for p in ol["p"]]
                        pts = [[round(x + px, 3), round(y + py, 3), round(z + pz, 3)] for px, py, pz in pts]
                        db.outlines.append((pid, ol["h"] * sz, json.dumps(pts, separators=(",", ":")),
                                            json.dumps(ol["p"], separators=(",", ":"))))
                for idx, (db, pid) in placed_in.items():
                    node = nodes.get(idx, {})
                    for kind, at, value in node.get("refs", []):
                        if kind in ("gid", "eid"):
                            value = str(signed64(value))   # the same signed form as nodes.global_id
                        positions = ARRAY_INDEX.findall(at)
                        db.refs.append((sid, idx, kind, db.s(ARRAY_INDEX.sub("[]", at)),
                                        ",".join(positions), db.s(value)))
                for db in (core, full):
                    if len(db.nodes) > 200000:
                        db.flush()
        print(f"{os.path.basename(part)}: core {core.next_id - 1:,} full {full.next_id - 1:,}", flush=True)

    meta = {"game_version": a.game, "schema_version": str(SCHEMA_VERSION),
            "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "build_commit": git_commit() or "", "sectors_read": str(len(read)),
            "sectors_listed": str(len(descriptors))}
    for name, db in (("core", core), ("full", full)):
        db.flush()
        c = db.con
        c.executemany("INSERT INTO strings VALUES (?,?)", ((i, t) for t, i in db.strings.items()))
        for path, d in descriptors.items():
            sid = sector_ids[path]
            if sid not in db.sectors:
                continue
            lo, hi = d.get("min") or [None] * 3, d.get("max") or [None] * 3
            c.execute("INSERT INTO sectors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (sid, db.s(path), path.split("\\")[2], d.get("block"), d["category"], d["level"],
                       db.s(d.get("prefab")),
                       *lo, *hi, json.dumps(d.get("variants") or [], separators=(",", ":"))))
        # Strings added while writing sectors.
        c.executemany("INSERT OR IGNORE INTO strings VALUES (?,?)", ((i, t) for t, i in db.strings.items()))
        c.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()) + [("database", name)])
        # The box around each sector's placements in this database: a quest sector's streaming box is infinite.
        c.execute("""INSERT INTO sectors_rtree SELECT sector_id, MIN(x), MAX(x), MIN(y), MAX(y) FROM nodes GROUP BY sector_id""")
        # full.db finds placements near a point through sectors_rtree, then nodes_sector: a per-placement tree
        # over 7.5 million mesh rows would be a third of the file. Same for its type indexes.
        indexes = "indexes.sql"
        if name == "core":
            c.execute("INSERT INTO nodes_rtree SELECT id, x, x, y, y FROM nodes")
        else:
            c.execute("DROP TABLE nodes_rtree")
            indexes = "indexes-full.sql"
        with open(os.path.join(HERE, indexes), encoding="utf-8") as f:
            c.executescript(f.read())
        c.commit()
        c.execute("VACUUM")
        c.close()
        size = os.path.getsize(os.path.join(a.out, name + ".db"))
        print(f"{name}.db: {db.next_id - 1:,} placements, {size / 1e6:,.0f} MB")
    missing = sorted(set(descriptors) - read)
    print(f"sectors read {len(read):,} of {len(descriptors):,}; not read: {missing[:10]}")


if __name__ == "__main__":
    main()
