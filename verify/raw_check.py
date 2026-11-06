"""Compares an extract with the sector files read straight from the game's .archive bytes, with no WolvenKit code.

    python verify/raw_check.py --game-dir "<game install>" --src <extract>/2.5 [--limit N]

Reads every node's class and every node-data row: transform, node index, instance index, global id, streaming
distance. --tamper changes each sector's first row before comparing, to prove the comparison can fail.
Exits 1 on any difference.
"""
import argparse
import collections
import ctypes
import glob
import json
import math
import os
import struct
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--game-dir", required=True)
ap.add_argument("--src", required=True)
ap.add_argument("--limit", type=int)
ap.add_argument("--tamper", action="store_true")
args = ap.parse_args()
root, limit = args.game_dir, args.limit
oodle = ctypes.WinDLL(root + "/bin/x64/oo2ext_7_win64.dll")
oodle.OodleLZ_Decompress.restype = ctypes.c_longlong
oodle.OodleLZ_Decompress.argtypes = [ctypes.c_char_p, ctypes.c_longlong, ctypes.c_char_p, ctypes.c_longlong] + [ctypes.c_longlong] * 10


def kraken(data):
    assert data[:4] == b"KARK", data[:8]
    size = struct.unpack_from("<I", data, 4)[0]
    out = ctypes.create_string_buffer(size)
    got = oodle.OodleLZ_Decompress(data[8:], len(data) - 8, out, size, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3)
    assert got == size, (got, size)
    return out.raw


def fnv(text):
    h = 0xcbf29ce484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xffffffffffffffff
    return h


class Archive:
    def __init__(self, path):
        self.f = open(path, "rb")
        magic, version, index_pos, index_size = struct.unpack("<IIQI", self.f.read(20))
        assert magic == 0x52414452, hex(magic)
        self.f.seek(index_pos)
        _table_offset, _table_size, _crc, entries, segments, deps = struct.unpack("<IIQIII", self.f.read(28))
        self.entries = {}
        data = self.f.read(entries * 56)
        for k in range(entries):
            h, _ts, _inline, start, end = struct.unpack_from("<QqIII", data, k * 56)
            self.entries[h] = (start, end)
        self.segments = list(struct.iter_unpack("<QII", self.f.read(segments * 16)))

    def read(self, h):
        start, end = self.entries[h]
        parts = []
        for k in range(start, end):
            offset, zsize, size = self.segments[k]
            self.f.seek(offset)
            raw = self.f.read(zsize)
            parts.append(kraken(raw) if k == start and zsize != size else raw)
        return b"".join(parts)


def sector(file):
    """(class of each node, the node-data bytes) read from a CR2W file."""
    assert file[:4] == b"CR2W", file[:4]
    tables = [struct.unpack_from("<III", file, 40 + k * 12) for k in range(10)]
    strings_at = tables[0][0]

    def text(offset):
        at = strings_at + offset
        return file[at:file.index(b"\0", at)].decode("utf-8")

    names = [text(struct.unpack_from("<I", file, tables[1][0] + k * 8)[0]) for k in range(tables[1][1])]
    exports = [struct.unpack_from("<HHIIIII", file, tables[4][0] + k * 24) for k in range(tables[4][1])]
    buffers = [struct.unpack_from("<IIIIII", file, tables[5][0] + k * 24) for k in range(tables[5][1])]
    root_export = exports[0]
    assert names[root_export[0]] == "worldStreamingSector", names[root_export[0]]
    at = root_export[4] + 1
    while True:
        name = struct.unpack_from("<H", file, at)[0]
        if name == 0:
            at += 2
            break
        size = struct.unpack_from("<I", file, at + 4)[0]
        at += 8 + size - 4
    # The sector's appendix: version, a size, the node-data buffer, then the node handles.
    version, _inner, buffer_size = struct.unpack_from("<iiI", file, at)
    at += 12
    rows = b""
    if buffer_size > 0x80000000:
        info = buffers[(buffer_size ^ 0x80000000) - 1]
        raw = file[info[2]:info[2] + info[3]]
        rows = raw if info[3] == info[4] else kraken(raw)
    elif buffer_size != 0x80000000:
        rows = file[at:at + buffer_size]
        at += buffer_size
    first = file[at]
    count = first & 0x3F
    at += 1
    shift = 6
    more = first & 0x40
    while more:
        b = file[at]
        at += 1
        count |= (b & 0x7F) << shift
        shift += 7
        more = b & 0x80
    handles = struct.unpack_from(f"<{count}i", file, at)
    classes = [names[exports[h - 1][0]] if h > 0 else None for h in handles]
    return classes, rows or b"", version


def f32(v):
    return struct.pack("<f", v)


archives = []
for folder in ("content", "ep1"):
    for path in sorted(glob.glob(f"{root}/archive/pc/{folder}/*.archive")):
        name = os.path.basename(path)
        if not (name.startswith("lang_") or name.startswith("audio_")):
            archives.append(Archive(path))
winner = {}
for a in archives:
    for h in a.entries:
        winner[h] = a   # the game loads ep1 after the base game, so its copy of a path wins
stats = collections.Counter()
bad = []
started = time.time()
done = False
for part in sorted(glob.glob(os.path.join(args.src, "part-[0-9]*.ndjson"))):
    with open(part, encoding="utf-8") as h:
        for line in h:
            if not line.strip():
                continue
            s = json.loads(line)
            stats["sectors"] += 1
            a = winner.get(fnv(s["path"]))
            if a is None:
                stats["not in these archives"] += 1
                bad.append((s["path"], "not found"))
                continue
            try:
                classes, rows, version = sector(a.read(fnv(s["path"])))
            except Exception as e:
                stats["raw read failed"] += 1
                bad.append((s["path"], "raw read", repr(e)[:160]))
                continue
            if args.tamper:
                r0 = s["rows"][0]
                r0[5] += 1.0
                r0[1] += 1
                r0[4] = "123"
                r0[17] += 1.0
                s["nodes"][0]["t"] = "tampered"
            types = {n["i"]: n["t"] for n in s["nodes"]}
            stats["nodes"] += len(classes)
            if len(classes) != len(types):
                stats["node count differs"] += 1
                bad.append((s["path"], "nodes", len(classes), len(types)))
            for i, c in enumerate(classes):
                if types.get(i) != c:
                    stats["node class differs"] += 1
                    if len(bad) < 30:
                        bad.append((s["path"], "class", i, c, types.get(i)))
            n = len(rows) // 0x90
            stats["rows"] += n
            if len(rows) % 0x90 or n != len(s["rows"]):
                stats["row count differs"] += 1
                bad.append((s["path"], "rows", n, len(s["rows"])))
                continue
            for k, r in enumerate(s["rows"]):
                at = k * 0x90
                # position xyz w, quaternion, scale
                raw = rows[at:at + 12] + rows[at + 16:at + 32] + rows[at + 32:at + 44]
                mine = b"".join(f32(v) for v in (r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13], r[14]))
                if raw != mine:
                    # -0 and NaN compare as bytes; allow only those
                    a1 = struct.unpack("<10f", raw)
                    if any(x != y and not (math.isnan(x) and math.isnan(y)) for x, y in zip(a1, struct.unpack("<10f", mine))):
                        stats["transform differs"] += 1
                        if len(bad) < 30:
                            bad.append((s["path"], "transform", k, a1[:3], r[5:8]))
                _patched, gid, _proxy, _ext = struct.unpack_from("<QQQQ", rows, at + 80)
                if (str(gid) if gid else None) != r[4]:
                    stats["global id differs"] += 1
                if version != 62:
                    bits = struct.unpack_from("<Q", rows, at + 112)[0]
                    idx = bits & 0x7FFFF
                    _second, dist = struct.unpack_from("<ff", rows, at + 120)
                    inst = struct.unpack_from("<I", rows, at + 128)[0]
                    if (inst if inst != 0xFFFFFFFF else -1) != r[2]:
                        stats["instance index differs"] += 1
                else:
                    _second, dist = struct.unpack_from("<ff", rows, at + 112)
                    idx = struct.unpack_from("<Q", rows, at + 120)[0] & 0xFFFFF
                if idx != r[1]:
                    stats["node index differs"] += 1
                if f32(dist) != f32(r[17]):
                    stats["streaming distance differs"] += 1
            if limit and stats["sectors"] >= limit:
                done = True
                break
    if done:
        break
print(json.dumps(stats, sort_keys=True), "seconds", round(time.time() - started))
print("mismatches listed", len(bad))
for b in bad[:20]:
    print("  ", str(b)[:260])
sys.exit(1 if bad or any(k.endswith("differs") for k in stats) else 0)
