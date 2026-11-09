"""Sets each sector NodeRef in a built 2.5 index to the text its sector file stores, and each community spot NodeRef too.

    python build/fix_noderefs.py --game-dir "<game install>" --db out/2.5-ep1 [--edition base] [--dry-run]

WolvenKit 10 keeps a NodeRef as its hash (FNV1a64 with '#' removed, up to any ';') and prints the first text with that hash it
has met, which can be another spelling of the file's. This reads every sector with a `ref` row from the game's archives, with no
WolvenKit code, collects the NodeRef texts each node stores (its own properties, the handles it holds and the packages and CR2W
files in its buffers), and replaces a value that is not one of them with the node's text of the same hash. A value with no such
text is left as it is and counted. An empty NodeRef ("0") is not a text and is skipped. It edits world-index.db in place and writes
`noderefs_corrected` and `noderefs_left` (node_refs) and `community_noderefs_corrected` and `community_noderefs_left`
(community_periods) into its meta. Run it after build.py and build_world.py.
"""
import argparse
import collections
import json
import os
import sqlite3
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "verify"))
from rawio import fnv, game_files, load_oodle  # noqa: E402
from world_check import CR2W, NodeRefText, Package, Raw, vlq  # noqa: E402


def ref_hash(text):
    return fnv(text.replace("#", "").split(";", 1)[0])


def node_handles(f):
    """The sector's node chunks, in node index order: handles in the root chunk's appendix, 1-based, 0 for none."""
    appendix = f.chunk(0)["$appendix"]
    _version, _inner, size = struct.unpack_from("<iiI", appendix, 0)
    at = 12
    if size < 0x80000000:
        at += size
    count, at = vlq(appendix, at)
    return struct.unpack_from(f"<{count}i", appendix, at)


class Collect:
    def __init__(self, stats):
        self.stats = stats

    def texts(self, value):
        out = set()
        self.walk(value, out, set())
        return out

    def walk(self, v, out, seen):
        if isinstance(v, NodeRefText):
            if v:
                out.add(str(v))
        elif isinstance(v, dict):
            if id(v) in seen:
                return
            seen.add(id(v))
            for x in v.values():
                self.walk(x, out, seen)
        elif isinstance(v, list):
            for x in v:
                self.walk(x, out, seen)
        elif isinstance(v, Raw) and len(v) >= 4:
            self.buffer(bytes(v), out, seen)

    def buffer(self, data, out, seen):
        if data[:4] == b"CR2W":
            kind, read = "CR2W file", lambda: CR2W(data)
        else:
            kind, read = "package", lambda: Package(data, save_style=False)
        try:
            parsed = read()
            values = [parsed.chunk(k) for k in range(len(parsed.exports))] if kind == "CR2W file" else parsed.chunks
        except Exception:
            looks = kind == "CR2W file" or (data[0] in (2, 3, 4) and struct.unpack_from("<H", data, 2)[0] in (6, 7))
            self.stats[("buffers with a " + kind + " header that did not read") if looks else "buffers that are not a package"] += 1
            return
        self.stats["buffers read as a " + kind] += 1
        for x in values:
            self.walk(x, out, seen)


def fix_sectors(db_path, winner, dry_run, stats):
    c = sqlite3.connect(db_path)
    text_of = dict(c.execute("SELECT id, text FROM strings"))
    id_of = {t: i for i, t in text_of.items()}
    next_id = max(text_of) + 1
    paths = {sid: text_of[pid] for sid, pid in c.execute("SELECT id, path_id FROM sectors")}
    rows = collections.defaultdict(list)
    for r in c.execute("SELECT sector_id, node_idx, kind, path_id, idx, value_id FROM node_refs WHERE kind = 'ref'"):
        rows[r[0]].append(r)
    collect = Collect(stats)
    corrected = left = 0
    changes = []
    for sid, refs in rows.items():
        path = paths[sid]
        f = CR2W(winner[fnv(path)].read(fnv(path)))
        handles = node_handles(f)
        by_node = {}
        for row in refs:
            _s, node_idx, _k, _p, _i, value_id = row
            text = text_of[value_id]
            stats["ref values"] += 1
            if text == "0":
                stats["empty NodeRef, skipped"] += 1
                continue
            if node_idx not in by_node:
                h = handles[node_idx] if 0 <= node_idx < len(handles) else 0
                texts = collect.texts(f.chunk(h - 1)) if h > 0 else set()
                hashes = collections.defaultdict(set)
                for t in texts:
                    hashes[ref_hash(t)].add(t)
                by_node[node_idx] = (texts, hashes)
            texts, hashes = by_node[node_idx]
            if text in texts:
                stats["already the node's text"] += 1
                continue
            same = hashes.get(ref_hash(text), set())
            if len(same) == 1:
                new = next(iter(same))
                stats["corrected"] += 1
                corrected += 1
                if new not in id_of:
                    id_of[new] = next_id
                    changes.append(("string", next_id, new))
                    next_id += 1
                changes.append(("row", row, id_of[new]))
                if len(stats.examples) < 8:
                    stats.examples.append((path.rsplit(chr(92), 1)[1], node_idx, text[-70:], new[-70:]))
            else:
                stats["left: no text of that hash in the node" if not same else "left: several texts of that hash in the node"] += 1
                left += 1
    if not dry_run:
        for change in changes:
            if change[0] == "string":
                c.execute("INSERT INTO strings VALUES (?,?)", change[1:])
            else:
                row, new_id = change[1], change[2]
                c.execute("DELETE FROM node_refs WHERE sector_id=? AND node_idx=? AND kind=? AND path_id=? AND idx=? AND value_id=?", row)
                c.execute("INSERT OR IGNORE INTO node_refs VALUES (?,?,?,?,?,?)", row[:5] + (new_id,))
        c.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [("noderefs_corrected", str(corrected)), ("noderefs_left", str(left))])
        c.commit()
    c.close()
    return corrected, left


def community_refs(f):
    """The spot NodeRefs of a .community file at each place (entry, phase, period, spot), from entries and crowdEntries,
    which community_periods numbers alike."""
    template = f.chunk(0).get("communityTemplate") or {}
    out = collections.defaultdict(set)
    for key in ("entries", "crowdEntries"):
        for e, entry in enumerate(template.get(key) or []):
            for ph, phase in enumerate((entry or {}).get("phases") or []):
                for pe, period in enumerate((phase or {}).get("timePeriods") or []):
                    for k, ref in enumerate((period or {}).get("spotNodeRefs") or []):
                        out[(e, ph, pe, k)].add(str(ref))
    return out


def fix_world(db_path, winner, dry_run, stats):
    c = sqlite3.connect(db_path)
    corrected = left = 0
    changes = []
    files = {}
    rows = c.execute("SELECT rowid, path, entry, phase, period, spot_node_refs FROM community_periods WHERE spot_node_refs IS NOT NULL").fetchall()
    for rowid, path, entry, phase, period, refs_json in rows:
        refs = json.loads(refs_json)
        if not refs:
            continue
        if path not in files:
            files[path] = community_refs(CR2W(winner[fnv(path)].read(fnv(path))))
        changed = False
        for k, text in enumerate(refs):
            stats["community spot refs"] += 1
            if text == "0":
                stats["community empty NodeRef, skipped"] += 1
                continue
            here = files[path].get((entry, phase, period, k), set())
            if text in here:
                continue
            same = [t for t in here if ref_hash(t) == ref_hash(text)]
            if len(same) == 1:
                file_text = same[0]
                refs[k] = file_text
                changed = True
                corrected += 1
                stats["community corrected"] += 1
                stats.examples.append((path.rsplit(chr(92), 1)[1], (entry, phase, period, k), text[-70:], file_text[-70:]))
            else:
                left += 1
                stats["community left"] += 1
        if changed:
            changes.append((json.dumps(refs, ensure_ascii=False, separators=(",", ":")), rowid))
    if not dry_run:
        c.executemany("UPDATE community_periods SET spot_node_refs = ? WHERE rowid = ?", changes)
        c.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [("community_noderefs_corrected", str(corrected)),
                                                                   ("community_noderefs_left", str(left))])
        c.commit()
    c.close()
    return corrected, left


class Stats(collections.Counter):
    examples = []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", required=True)
    ap.add_argument("--db", required=True, help="an index folder, e.g. out/2.5-ep1, holding world-index.db")
    ap.add_argument("--edition", default="ep1", choices=["ep1", "base"])
    ap.add_argument("--dry-run", action="store_true", help="count, change nothing")
    a = ap.parse_args()
    load_oodle(a.game_dir)
    winner = game_files(a.game_dir, a.edition)
    path = os.path.join(a.db, "world-index.db")
    stats = Stats()
    stats.examples = []
    corrected, left = fix_sectors(path, winner, a.dry_run, stats)
    print("sectors corrected", corrected, "left", left, json.dumps(stats, sort_keys=True))
    for e in stats.examples:
        print("  ", e)
    stats = Stats()
    stats.examples = []
    corrected, left = fix_world(path, winner, a.dry_run, stats)
    print("community corrected", corrected, "left", left, json.dumps(stats, sort_keys=True))
    for e in stats.examples[:8]:
        print("  ", e)


if __name__ == "__main__":
    main()
