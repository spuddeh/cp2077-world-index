"""Build world.db and the optional smartobjects.db for one game version and edition from world-files.wscript's output.

    python build/build_world.py --game 2.5 --edition ep1 --game-dir "<game install>" --src <extract>/2.5-ep1/world --out out/2.5-ep1

world.db holds the world's data outside sector files, and `files`: every file under a worlds folder with its size and
content hash, read from the game's own .archive indexes, so a baked or opaque file that has no table of its own is still
listed. Values are stored as the game has them. A column named data holds the rest of an element as JSON.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import sqlite3
import struct
import subprocess

SCHEMA_VERSION = 2
HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files (path TEXT PRIMARY KEY, extension TEXT, archive TEXT, size INTEGER, disk_size INTEGER, sha1 TEXT, in_tables INTEGER);
CREATE TABLE world_resources (world TEXT PRIMARY KEY, data TEXT);
CREATE TABLE mappins (world TEXT, idx INTEGER, kind TEXT, journal_path_hash INTEGER, x REAL, y REAL, z REAL, data TEXT);
CREATE TABLE poi_mappins (world TEXT, idx INTEGER, entity_id TEXT, journal_path_hash INTEGER, x REAL, y REAL, z REAL);
CREATE TABLE areas (world TEXT, idx INTEGER, entity_id TEXT, x REAL, y REAL, z REAL, radius REAL, volume TEXT);
CREATE TABLE loot (world TEXT, node_ref_hash TEXT, record TEXT, idx INTEGER);
CREATE TABLE devices (world TEXT, idx INTEGER, init INTEGER, hash TEXT, class TEXT, x REAL, y REAL, z REAL, parents TEXT, children TEXT);
CREATE TABLE persistent_states (world TEXT, idx INTEGER, cruid TEXT, class TEXT, data TEXT);
CREATE TABLE locomotion_paths (world TEXT, idx INTEGER, spline_node_ref TEXT, data TEXT);
CREATE TABLE roads (world TEXT, idx INTEGER, global_id TEXT, x REAL, y REAL, z REAL, width REAL, first_link INTEGER, link_count INTEGER, data TEXT);
CREATE TABLE road_links (world TEXT, idx INTEGER, road INTEGER);
CREATE TABLE traffic_lanes (world TEXT, idx INTEGER, node_ref_hash TEXT, lane_number INTEGER, seq_number INTEGER, is_reversed INTEGER,
    length REAL, width REAL, max_speed REAL, flags INTEGER, sub_graph INTEGER, data TEXT, polygon TEXT, connections TEXT);
CREATE TABLE traffic_lane_collisions (world TEXT, idx INTEGER, data TEXT);
CREATE TABLE traffic_neighbor_groups (world TEXT, idx INTEGER, lanes TEXT);
CREATE TABLE null_area_collisions (world TEXT, idx INTEGER, area_id TEXT, data TEXT);
CREATE TABLE null_area_blockades (world TEXT, idx INTEGER, data TEXT);
CREATE TABLE sector_inplace (path TEXT, kind TEXT, resource TEXT);
CREATE TABLE cooked_prefabs (path TEXT, kind TEXT, resource TEXT);
CREATE TABLE acoustic_cells (path TEXT, idx INTEGER, sector INTEGER, node_bytes INTEGER);
CREATE TABLE community_entries (path TEXT, entry INTEGER, crowd INTEGER, name TEXT, character TEXT, spawn_in_view TEXT, initializers TEXT);
CREATE TABLE community_periods (path TEXT, entry INTEGER, phase INTEGER, period INTEGER, phase_name TEXT, always_spawned TEXT, appearances TEXT,
    hour TEXT, quantity INTEGER, is_sequence INTEGER, markings TEXT, spot_node_refs TEXT, categories TEXT);
"""
INDEXES = """
CREATE INDEX files_ext ON files (extension);
CREATE INDEX mappins_journal ON mappins (journal_path_hash);
CREATE INDEX poi_entity ON poi_mappins (entity_id);
CREATE INDEX areas_entity ON areas (entity_id);
CREATE INDEX loot_ref ON loot (node_ref_hash);
CREATE INDEX loot_record ON loot (record);
CREATE INDEX devices_hash ON devices (hash);
CREATE INDEX devices_class ON devices (class);
CREATE INDEX persistent_cruid ON persistent_states (cruid);
CREATE INDEX persistent_class ON persistent_states (class);
CREATE INDEX roads_global ON roads (global_id);
CREATE INDEX lanes_ref ON traffic_lanes (node_ref_hash);
CREATE INDEX inplace_path ON sector_inplace (path);
CREATE INDEX inplace_resource ON sector_inplace (resource);
CREATE INDEX prefab_path ON cooked_prefabs (path);
CREATE INDEX prefab_resource ON cooked_prefabs (resource);
CREATE INDEX acoustic_path ON acoustic_cells (path);
CREATE INDEX community_path ON community_entries (path);
CREATE INDEX community_name ON community_entries (name);
CREATE INDEX community_character ON community_entries (character);
CREATE INDEX community_periods_path ON community_periods (path, entry);
"""
SMART_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE smart_object_files (path TEXT PRIMARY KEY, box TEXT, properties TEXT, transforms TEXT, sequences TEXT);
CREATE TABLE smart_objects (path TEXT, idx INTEGER, class TEXT, data TEXT);
CREATE TABLE smart_object_members (path TEXT, hash TEXT, idx INTEGER);
CREATE INDEX smart_objects_path ON smart_objects (path);
CREATE INDEX smart_members_hash ON smart_object_members (hash);
"""
TABLED = {".mappins", ".poimappins", ".areas", ".loot", ".devices", ".psrep", ".locopaths", ".streamingquerydata", ".traffic_persistent",
          ".lane_polygons", ".lane_connections", ".traffic_collisions", ".null_areas", ".streamingworld", ".streamingsector_inplace",
          ".cookedprefab", ".acousticdata", ".smartobjects", ".streamingsector", ".streamingblock", ".spatial_representation", ".community"}


def fnv(text):
    h = 0xcbf29ce484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xffffffffffffffff
    return h


def archive_index(game_dir, edition):
    """hash -> (archive, size, disk size, sha1) from the .archive indexes; a later archive's copy replaces an earlier one's."""
    found = {}
    for folder in ("content", "ep1") if edition == "ep1" else ("content",):
        for path in sorted(glob.glob(os.path.join(game_dir, "archive", "pc", folder, "*.archive"))):
            with open(path, "rb") as f:
                magic, _version, index_pos, _index_size = struct.unpack("<IIQI", f.read(20))
                assert magic == 0x52414452, path
                f.seek(index_pos)
                _a, _b, _c, entries, segments, _deps = struct.unpack("<IIQIII", f.read(28))
                table = f.read(entries * 56)
                seg = list(struct.iter_unpack("<QII", f.read(segments * 16)))
            name = os.path.basename(path)
            for k in range(entries):
                h, _ts, _inline, start, end, _d0, _d1 = struct.unpack_from("<QqIIIII", table, k * 56)
                sha1 = table[k * 56 + 36:k * 56 + 56].hex()
                found[h] = (name, sum(s[2] for s in seg[start:end]), sum(s[1] for s in seg[start:end]), sha1)
    return found


def lines(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def dumps(v):
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False)


def xyz(p):
    return (p["X"], p["Y"], p["Z"]) if p else (None, None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--edition", required=True, choices=["ep1", "base"])
    ap.add_argument("--game-dir", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "world.db")
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode = OFF")
    c.execute("PRAGMA synchronous = OFF")
    c.executescript(SCHEMA)
    src = a.src
    counts = collections.Counter()

    index = archive_index(a.game_dir, a.edition)
    for part in glob.glob(os.path.join(src, "mod-served-*.json")):
        with open(part, encoding="utf-8") as f:
            shipped = [p for p in json.load(f) if fnv(p) in index]
        if shipped:
            raise SystemExit(f"{len(shipped)} files the game ships were read as a mod's copy, first {shipped[0]}: unload that mod and extract again")
    community_parts = sorted(glob.glob(os.path.join(src, "community-*.ndjson")))
    with open(os.path.join(src, "filelist.json"), encoding="utf-8") as f:
        listed = json.load(f)
    listed += [r["path"] for part in community_parts for r in lines(part)]
    rows = []
    for p in listed:
        entry = index.get(fnv(p))
        if entry is None:
            counts["listed files with no copy in this edition"] += 1
            continue
        ext = p[p.rfind("."):]
        rows.append((p, ext, entry[0], entry[1], entry[2], entry[3], int(ext in TABLED)))
    c.executemany("INSERT INTO files VALUES (?,?,?,?,?,?,?)", rows)
    counts["files"] = len(rows)

    worlds = sorted({os.path.basename(p).split("-")[0] for p in glob.glob(os.path.join(src, "*-world.ndjson"))})
    for w in worlds:
        def kind(name):
            return lines(os.path.join(src, f"{w}-{name}.ndjson"))

        for r in kind("world"):
            c.execute("INSERT INTO world_resources VALUES (?,?)", (w, dumps(r["v"])))
        for name, label in (("mappins", "cooked"), ("mappins_gps", "gps"), ("mappins_multi", "multi")):
            for r in kind(name):
                v = r["v"]
                x, y, z = xyz(v.get("position"))
                rest = {k: e for k, e in v.items() if k not in ("$type", "journalPathHash", "position")}
                c.execute("INSERT INTO mappins VALUES (?,?,?,?,?,?,?,?)", (w, r["i"], label, v["journalPathHash"], x, y, z, dumps(rest)))
                counts["mappins"] += 1
        for r in kind("poi"):
            v = r["v"]
            c.execute("INSERT INTO poi_mappins VALUES (?,?,?,?,?,?,?)", (w, r["i"], v["entityID"]["hash"], v["journalPathHash"], *xyz(v["position"])))
            counts["poi_mappins"] += 1
        for r in kind("areas"):
            v = r["v"]
            c.execute("INSERT INTO areas VALUES (?,?,?,?,?,?,?,?)", (w, r["i"], v["entityID"]["hash"], *xyz(v["position"]), v["radius"], dumps(v.get("volume"))))
            counts["areas"] += 1
        for r in kind("loot"):
            counts["loot nodes"] += 1
            for k, record in enumerate(r["records"]):
                c.execute("INSERT INTO loot VALUES (?,?,?,?)", (w, r["hash"], record, k))
        for name, init in (("devices", 0), ("devices_init", 1)):
            for r in kind(name):
                v = r["v"]
                c.execute("INSERT INTO devices VALUES (?,?,?,?,?,?,?,?,?,?)", (w, r["i"], init, v["hash"], v["className"], *xyz(v["nodePosition"]), dumps(v["parents"]), dumps(v["children"])))
                counts["devices"] += 1
        for k, r in enumerate(kind("persistent")):
            v = r["v"]
            cls = v.pop("$type", None)
            c.execute("INSERT INTO persistent_states VALUES (?,?,?,?,?)", (w, k, r["cruid"], cls, dumps(v)))
            counts["persistent_states"] += 1
        for r in kind("locopaths"):
            v = r["v"]
            c.execute("INSERT INTO locomotion_paths VALUES (?,?,?,?)", (w, r["i"], v.get("splineNodeRef"), dumps(v)))
            counts["locomotion_paths"] += 1
        for r in kind("roads"):
            v = r["v"]
            p = v.get("transform", {}).get("position") if v.get("transform") else None
            c.execute("INSERT INTO roads VALUES (?,?,?,?,?,?,?,?,?,?)", (w, r["i"], v["roadGlobalNodeId"]["hash"], *xyz(p), v["totalRoadWidth"], v["connectedRoadsStartIndex"], v["connectedRoadsCount"], dumps(v.get("splineData"))))
            counts["roads"] += 1
        for r in kind("road_links"):
            c.executemany("INSERT INTO road_links VALUES (?,?,?)", [(w, k, road) for k, road in enumerate(r["v"] or [])])
        poly = {r["i"]: r["v"] for r in kind("lane_polygons")}
        conn = {r["i"]: r["v"] for r in kind("lane_connections")}
        for r in kind("lanes"):
            v = r["v"]
            # The polygon and connection files key a lane by its position in the lane list.
            pv = next((e.get("value") for e in [poly.get(r["i"])] if e), None)
            cv = next((e.get("value") for e in [conn.get(r["i"])] if e), None)
            keep = {k: e for k, e in v.items() if k not in ("$type", "nodeRefHash", "laneNumber", "seqNumber", "isReversed", "length", "width", "maxSpeed", "flags", "subGraphId")}
            c.execute("INSERT INTO traffic_lanes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                w, r["i"], v["nodeRefHash"], v["laneNumber"], v["seqNumber"], v["isReversed"], v["length"], v["width"], v["maxSpeed"], v["flags"], v["subGraphId"],
                dumps(keep), dumps(pv), dumps(cv)))
            counts["traffic_lanes"] += 1
        for r in kind("lane_collisions"):
            c.execute("INSERT INTO traffic_lane_collisions VALUES (?,?,?)", (w, r["i"], dumps(r["v"])))
        for r in kind("lane_neighbors"):
            c.execute("INSERT INTO traffic_neighbor_groups VALUES (?,?,?)", (w, r["i"], dumps(r["v"])))
        for r in kind("null_collisions"):
            c.execute("INSERT INTO null_area_collisions VALUES (?,?,?,?)", (w, r["i"], r["v"]["areaID"], dumps(r["v"])))
        for r in kind("null_blockades"):
            c.execute("INSERT INTO null_area_blockades VALUES (?,?,?)", (w, r["i"], dumps(r["v"])))

    for part in sorted(glob.glob(os.path.join(src, "inplace-*.ndjson"))):
        for r in lines(part):
            counts["inplace files"] += 1
            c.executemany("INSERT INTO sector_inplace VALUES (?,?,?)", [(r["path"], "resource", e) for e in r["resources"]] + [(r["path"], "embedded", e) for e in r["embedded"]])
    for part in sorted(glob.glob(os.path.join(src, "prefab-*.ndjson"))):
        for r in lines(part):
            counts["cooked prefabs"] += 1
            c.executemany("INSERT INTO cooked_prefabs VALUES (?,?,?)", [(r["path"], "dependency", e) for e in r["dependencies"]] + [(r["path"], "embedded", e) for e in r["embedded"]])
    for part in sorted(glob.glob(os.path.join(src, "acoustic-*.ndjson"))):
        for r in lines(part):
            counts["acoustic files"] += 1
            c.executemany("INSERT INTO acoustic_cells VALUES (?,?,?,?)", [(r["path"], k, e["sector"], e["bytes"]) for k, e in enumerate(r["cells"])])

    for part in community_parts:
        for r in lines(part):
            counts["community files"] += 1
            t = r["template"] or {}
            for crowd, key in ((0, "entries"), (1, "crowdEntries")):
                for e, entry in enumerate(t.get(key) or []):
                    counts["community entries"] += 1
                    c.execute("INSERT INTO community_entries VALUES (?,?,?,?,?,?,?)", (r["path"], e, crowd, entry.get("entryName"), entry.get("characterRecordId"), entry.get("spawnInView"), dumps(entry.get("initializers"))))
                    for ph, phase in enumerate(entry.get("phases") or []):
                        for pe, period in enumerate(phase.get("timePeriods") or []):
                            counts["community periods"] += 1
                            c.execute("INSERT INTO community_periods VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                                r["path"], e, ph, pe, phase.get("phaseName"), phase.get("alwaysSpawned"), dumps(phase.get("appearances")),
                                period.get("hour"), period.get("quantity"), period.get("isSequence"), dumps(period.get("markings")), dumps(period.get("spotNodeRefs")), dumps(period.get("categories"))))

    smart_parts = sorted(glob.glob(os.path.join(src, "smartobjects-*.ndjson")))
    if smart_parts:
        smart_path = os.path.join(a.out, "smartobjects.db")
        if os.path.exists(smart_path):
            os.remove(smart_path)
        s = sqlite3.connect(smart_path)
        s.execute("PRAGMA journal_mode = OFF")
        s.execute("PRAGMA synchronous = OFF")
        s.executescript(SMART_SCHEMA)
        for part in smart_parts:
            for r in lines(part):
                counts["smart object files"] += 1
                s.execute("INSERT INTO smart_object_files VALUES (?,?,?,?,?)", (r["path"], dumps(r["box"]), dumps(r["properties"]), dumps(r["transforms"]), dumps(r["sequences"])))
                for k, n in enumerate((r["nodes"] or {}).get("compiledSmartObjects") or []):
                    data = n.get("compiledData") or {}
                    s.execute("INSERT INTO smart_objects VALUES (?,?,?,?)", (r["path"], k, data.get("$type"), dumps(n)))
                    counts["smart objects"] += 1
                s.executemany("INSERT INTO smart_object_members VALUES (?,?,?)", [(r["path"], m["hash"], m["index"]) for m in (r["members"] or {}).get("members") or []])

    errors = []
    for f in glob.glob(os.path.join(src, "errors-*.json")):
        with open(f, encoding="utf-8") as h:
            errors += json.load(h)
    commit = ""
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    meta = {"game_version": a.game, "edition": a.edition, "schema_version": str(SCHEMA_VERSION), "database": "world",
            "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "build_commit": commit,
            "counts": json.dumps(counts, sort_keys=True), "read_errors": json.dumps(errors)}
    c.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    c.executescript(INDEXES)
    c.commit()
    c.close()
    if smart_parts:
        s.executemany("INSERT INTO meta VALUES (?,?)", list({**meta, "database": "smartobjects"}.items()))
        s.commit()
        s.close()
        print(f"smartobjects.db: {os.path.getsize(smart_path) / 1e6:,.0f} MB")
    print(f"world.db: {os.path.getsize(path) / 1e6:,.0f} MB")
    print(json.dumps(counts, indent=1, sort_keys=True))
    print("files that could not be read:", json.dumps(errors)[:800])


if __name__ == "__main__":
    main()
