"""Every NodeRef the index lists for a sector node must appear, as text, in that sector's own bytes.

    python verify/noderef_check.py --game-dir "<game install>" --db out/2.5-ep1 [--edition base]

--db is the folder holding world-index.db.

WolvenKit keeps a NodeRef as its hash, which stops at ';', so it can print the text of another NodeRef with the same hash.
This finds each value whose text is not the file's.
"""
import argparse
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rawio import fnv, game_files, kraken, load_oodle  # noqa: E402
import struct  # noqa: E402


def searchable(file):
    """The file's bytes with each of its buffers decompressed after them: a node's data can sit in a compressed buffer."""
    t = [struct.unpack_from("<III", file, 40 + k * 12) for k in range(10)]
    parts = [file]
    for k in range(t[5][1]):
        _flags, _i, offset, disk, mem, _crc = struct.unpack_from("<IIIIII", file, t[5][0] + k * 24)
        raw = file[offset:offset + disk]
        parts.append(raw if disk == mem else kraken(raw))
    return b"".join(parts)

ap = argparse.ArgumentParser()
ap.add_argument("--game-dir", required=True)
ap.add_argument("--db", required=True, help="an index folder, e.g. out/2.5-ep1")
ap.add_argument("--edition", default="ep1", choices=["ep1", "base"])
a = ap.parse_args()
load_oodle(a.game_dir)
winner = game_files(a.game_dir, a.edition)
stats = collections.Counter()
examples = []
c = sqlite3.connect(f"file:{os.path.join(a.db, 'world-index.db')}?immutable=1", uri=True)
s = dict(c.execute("SELECT id, text FROM strings"))
by_sector = collections.defaultdict(set)
for sid, value in c.execute("SELECT sector_id, value_id FROM node_refs WHERE kind = 'ref'"):
    by_sector[sid].add(s[value])
paths = {sid: s[pid] for sid, pid in c.execute("SELECT id, path_id FROM sectors")}
for sid, values in by_sector.items():
    data = searchable(winner[fnv(paths[sid])].read(fnv(paths[sid])))
    for v in values:
        stats["refs checked"] += 1
        if v.encode("utf-8") in data:
            stats["text in the sector's bytes"] += 1
        elif ";" in v and v.split(";", 1)[0].encode("utf-8") in data:
            stats["only the part before ';' is in the sector's bytes"] += 1
            if len(examples) < 6:
                examples.append((paths[sid].rsplit(chr(92), 1)[1], v[-80:]))
        elif struct.pack("<Q", fnv(v.replace("#", "").split(";", 1)[0])) in data:
            # The file holds the NodeRef as its hash; the text comes from WolvenKit's pool of names.
            stats["the file holds its hash; the text is a name WolvenKit knows"] += 1
        else:
            stats["not in the sector's bytes"] += 1
            if len(examples) < 12:
                examples.append(("missing", paths[sid].rsplit(chr(92), 1)[1], v[-80:]))
print(dict(stats))
for e in examples:
    print("  ", e)
sys.exit(1 if stats["refs checked"] != stats["text in the sector's bytes"] else 0)
