"""Compares the world-files extract with the same files read straight from the game's .archive bytes, with no WolvenKit code.

    python verify/world_check.py --game-dir "<game install>" --src <extract>/2.5-ep1/world [--edition base] [--db out/2.5-ep1/world.db]

Reads each CR2W file's properties from their own names and types, and the custom data of loot, devices, lane polygons, lane
connections and persistent state from their layouts, then compares every value with the extract. With --db, also checks
that world.db holds one row for each element of the extract. --tamper changes one value per file before comparing, to prove
the comparison can fail. Exits 1 on any difference.
"""
import argparse
import base64
import collections
import glob
import json
import os
import re
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rawio import fnv, game_files, kraken, load_oodle  # noqa: E402

DUMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_game", "rtti-dump", "json")
BS = chr(92)
FUNDAMENTAL = {"Bool": "<?", "Int8": "<b", "Uint8": "<B", "Int16": "<h", "Uint16": "<H", "Int32": "<i", "Uint32": "<I",
               "Int64": "<q", "Uint64": "<Q", "Float": "<f", "Double": "<d", "CDateTime": "<Q", "CRUID": "<Q",
               "gamedataLocKeyWrapper": "<Q", "EditorObjectID": "<Q"}


def names_in(folder):
    path = os.path.join(DUMP, folder)
    return {os.path.splitext(f)[0] for f in os.listdir(path)} if os.path.isdir(path) else set()


ENUMS, BITFIELDS = names_in("enums"), names_in("bitfields")


class Tdb(int):
    """A TweakDBID as stored: CRC32 of the text in the low 32 bits, its length in the next 8."""


class Raw(bytes):
    """A data buffer's bytes, decompressed."""


def vlq(data, at):
    b = data[at]
    at += 1
    negative = b & 0x80
    value = b & 0x3F
    more = b & 0x40
    shift = 6
    while more:
        b = data[at]
        at += 1
        value |= (b & 0x7F) << shift
        shift += 7
        more = b & 0x80
    return (-value if negative else value), at


def split_type(t):
    """'array:handle:x' -> ('array', 'handle:x'); '[4]Float' -> ('fixed', 'Float')."""
    m = re.match(r"^\[(\d+)\](.+)$", t)
    if m:
        return "fixed", m.group(2)
    for prefix in ("array", "handle", "whandle", "rRef", "raRef", "curveData", "multiChannelCurve"):
        if t.startswith(prefix + ":"):
            return prefix, t[len(prefix) + 1:]
    if t.startswith("static:"):
        return "static", t.split(",", 1)[1]
    return t, None


class CR2W:
    def __init__(self, data):
        assert data[:4] == b"CR2W", data[:4]
        self.data = data
        t = [struct.unpack_from("<III", data, 40 + k * 12) for k in range(10)]
        strings_at = t[0][0]

        def text(offset):
            at = strings_at + offset
            return data[at:data.index(b"\0", at)].decode("utf-8")

        self.names = [text(struct.unpack_from("<I", data, t[1][0] + k * 8)[0]) for k in range(t[1][1])]
        self.imports = [text(struct.unpack_from("<I", data, t[2][0] + k * 8)[0]) for k in range(t[2][1])]
        self.exports = [struct.unpack_from("<HHIIIII", data, t[4][0] + k * 24) for k in range(t[4][1])]
        self.buffers = [struct.unpack_from("<IIIIII", data, t[5][0] + k * 24) for k in range(t[5][1])]
        self.embedded = [struct.unpack_from("<IIQ", data, t[6][0] + k * 16) for k in range(t[6][1])]
        self.cache = {}

    def buffer(self, index):
        _flags, _i, offset, disk, mem, _crc = self.buffers[index]
        raw = self.data[offset:offset + disk]
        return Raw(raw if disk == mem else kraken(raw))

    def chunk(self, index):
        if index in self.cache:
            return self.cache[index]
        cls, _flags, _parent, size, offset, _t, _c = self.exports[index]
        value = {"$type": self.names[cls]}
        self.cache[index] = value
        if self.data[offset:offset + 4] == b"\xff\xff\xff\xff":
            # gameCompiledSmartObjectData and its subclasses keep their data in a layout of their own.
            value["buffer"] = compiled_smart_object(self.data[offset:offset + size])
            return value
        if self.data[offset] != 0:
            # A class with its own layout (WolvenKit's IRedCustomData): kept as its bytes.
            value["$custom"] = Raw(self.data[offset:offset + size])
            return value
        end = self.props(value, offset, offset + size)
        if end < offset + size:
            value["$appendix"] = Raw(self.data[end:offset + size])
        return value

    def props(self, value, at, end):
        d = self.data
        assert d[at] == 0, ("class does not start with 0", at)
        at += 1
        while end is None or at < end:
            name = struct.unpack_from("<H", d, at)[0]
            if name == 0:
                return at + 2
            typ, size = struct.unpack_from("<HI", d, at + 2)
            at += 8
            value[self.names[name]] = self.value(self.names[typ], at, at + size - 4)[0]
            at += size - 4
        return at

    def value(self, t, at, end):
        d = self.data
        kind, inner = split_type(t)
        if kind in FUNDAMENTAL:
            f = FUNDAMENTAL[kind]
            return struct.unpack_from(f, d, at)[0], at + struct.calcsize(f)
        if kind == "CName":
            return self.names[struct.unpack_from("<H", d, at)[0]], at + 2
        if kind == "TweakDBID":
            return Tdb(struct.unpack_from("<Q", d, at)[0]), at + 8
        if kind in ("String", "NodeRef"):
            return self.string(at)
        if kind == "LocalizationString":
            s, at2 = self.string(at + 8)
            return {"unk1": struct.unpack_from("<Q", d, at)[0], "value": s}, at2
        if kind == "CGUID":
            return Raw(d[at:at + 16]), at + 16
        if kind == "DataBuffer":
            n = struct.unpack_from("<I", d, at)[0]
            if n == 0x80000000:
                return Raw(b""), at + 4
            if n > 0x80000000:
                return self.buffer((n ^ 0x80000000) - 1), at + 4
            return Raw(d[at + 4:at + 4 + n]), at + 4 + n
        if kind == "serializationDeferredDataBuffer":
            return self.buffer(struct.unpack_from("<H", d, at)[0] - 1), at + 2
        if kind == "SharedDataBuffer":
            n = struct.unpack_from("<I", d, at)[0]
            return Raw(d[at + 4:at + 4 + n]), at + 4 + n
        if kind == "Variant":
            typ, size = struct.unpack_from("<HI", d, at)
            if size - 4 <= 0:
                return None, at + 6
            return self.value(self.names[typ], at + 6, at + 2 + size)[0], at + 2 + size
        if kind in ("handle", "whandle"):
            p = struct.unpack_from("<i", d, at)[0] - 1
            return (self.chunk(p) if p >= 0 else None), at + 4
        if kind in ("rRef", "raRef"):
            i = struct.unpack_from("<H", d, at)[0]
            return (self.imports[i - 1] if 0 < i <= len(self.imports) else None), at + 2
        if kind in ("array", "static", "fixed"):
            count = struct.unpack_from("<i", d, at)[0]
            at += 4
            out = []
            for _ in range(count):
                v, at = self.value(inner, at, None)
                out.append(v)
            if kind == "array" and end is not None:
                while at < end:   # a property's array runs on to the property's end, as WolvenKit reads it
                    v, at = self.value(inner, at, None)
                    out.append(v)
            return out, at
        if kind in BITFIELDS:
            out = []
            while True:
                i = struct.unpack_from("<H", d, at)[0]
                at += 2
                if i == 0:
                    return out, at
                out.append(self.names[i])
        if kind in ENUMS:
            return self.names[struct.unpack_from("<H", d, at)[0]], at + 2
        if kind in ("curveData", "multiChannelCurve"):
            if end is None:
                raise ValueError("a curve inside an array: its size is not known")
            return Raw(d[at:end]), end
        v = {"$type": kind}
        return v, self.props(v, at, end)

    def string(self, at):
        n, at = vlq(self.data, at)
        if n == 0:
            return "", at
        if n < 0:
            return self.data[at:at - n].decode("utf-8"), at - n
        return self.data[at:at + 2 * n].decode("utf-16-le"), at + 2 * n


class Package:
    """A RedPackage buffer (gamePersistentStateDataResource.buffer): root chunks and the CRUID each is keyed by."""

    def __init__(self, data):
        self.d = data
        d = data
        self.version, _unk, sections = struct.unpack_from("<BBH", d, 0)
        at = 8
        if sections == 7:
            ref_desc, ref_data = struct.unpack_from("<II", d, at)
            at += 8
        else:
            ref_desc = ref_data = 0
        name_desc, name_data, chunk_desc, chunk_data = struct.unpack_from("<IIII", d, at)
        at += 16
        # A persistent-state package keeps its root CRUIDs behind a 32-bit count, as a save resource does.
        n = struct.unpack_from("<I", d, at)[0]
        at += 4
        self.cruids = list(struct.unpack_from(f"<{n}Q", d, at))
        at += 8 * n
        base = at
        self.imports = []
        for k in range((ref_data - ref_desc) // 4):
            bits = struct.unpack_from("<I", d, base + ref_desc + 4 * k)[0]
            off, size = bits & ((1 << 23) - 1), (bits >> 23) & 0xFF
            self.imports.append(d[base + off:base + off + size].decode("utf-8"))
        self.names = []
        for k in range((name_data - name_desc) // 4):
            off = struct.unpack_from("<I", d, base + name_desc + 4 * k)[0] & 0xFFFFFF
            self.names.append(d[base + off:d.index(b"\0", base + off)].decode("utf-8"))
        heads = [struct.unpack_from("<II", d, base + chunk_desc + 8 * k) for k in range((chunk_data - chunk_desc) // 8)]
        self.chunks = []
        self.used = set()
        for typ, off in heads:
            v = {"$type": self.names[typ]}
            self.chunks.append(v)
        for k, (typ, off) in enumerate(heads):
            self.fields(self.chunks[k], base + off)
        self.roots = [c for k, c in enumerate(self.chunks) if k not in self.used]

    def fields(self, value, at):
        """Reads a class's fields; returns where its data ends, after its last field's value."""
        d = self.d
        count = struct.unpack_from("<H", d, at)[0]
        end = at + 2 + 8 * count
        for k in range(count):
            name, typ, off = struct.unpack_from("<HHI", d, at + 2 + 8 * k)
            value[self.names[name]], stop = self.value(self.names[typ], at + off)
            end = max(end, stop)
        return end

    def value(self, t, at):
        d = self.d
        kind, inner = split_type(t)
        if kind in FUNDAMENTAL:
            f = FUNDAMENTAL[kind]
            return struct.unpack_from(f, d, at)[0], at + struct.calcsize(f)
        if kind == "CName":
            return self.names[struct.unpack_from("<H", d, at)[0]], at + 2
        if kind == "TweakDBID":
            if self.version in (2, 3):
                n = struct.unpack_from("<h", d, at)[0]
                return d[at + 2:at + 2 + n].decode("utf-8"), at + 2 + n
            return Tdb(struct.unpack_from("<Q", d, at)[0]), at + 8
        if kind == "NodeRef":
            n = struct.unpack_from("<h", d, at)[0]
            return d[at + 2:at + 2 + n].decode("utf-8"), at + 2 + n
        if kind == "String":
            n = struct.unpack_from("<H", d, at)[0]
            return d[at + 2:at + 2 + n].decode("utf-8"), at + 2 + n
        if kind == "LocalizationString":
            n = struct.unpack_from("<H", d, at + 8)[0]
            return {"unk1": struct.unpack_from("<Q", d, at)[0], "value": d[at + 10:at + 10 + n].decode("utf-8")}, at + 10 + n
        if kind == "CGUID":
            return Raw(d[at:at + 16]), at + 16
        if kind in ("handle", "whandle"):
            if kind == "handle" and self.version == 2:
                p, at2 = struct.unpack_from("<h", d, at)[0], at + 2
            else:
                p, at2 = struct.unpack_from("<i", d, at)[0], at + 4
            if p < 0:
                return None, at2
            self.used.add(p)
            return self.chunks[p], at2
        if kind in ("rRef", "raRef"):
            i = struct.unpack_from("<h", d, at)[0]
            return (self.imports[i] if 0 <= i < len(self.imports) else None), at + 2
        if kind in ("array", "static", "fixed"):
            count = struct.unpack_from("<i", d, at)[0]
            at += 4
            out = []
            for _ in range(count):
                v, at = self.value(inner, at)
                out.append(v)
            return out, at
        if kind in BITFIELDS:
            count = d[at]
            vals = [self.names[struct.unpack_from("<H", d, at + 1 + 2 * k)[0]] for k in range(count)]
            return vals, at + 1 + 2 * count
        if kind in ENUMS:
            return self.names[struct.unpack_from("<H", d, at)[0]], at + 2
        if kind == "DataBuffer":
            n = struct.unpack_from("<I", d, at)[0]
            return Raw(d[at + 4:at + 4 + n]), at + 4 + n
        v = {"$type": kind}
        return v, self.fields(v, at)


def compiled_smart_object(data):
    unk1 = data[4]
    n, at = vlq(data, 5)
    unk2 = list(struct.unpack_from(f"<{n}H", data, at))
    at += 2 * n
    out = {"unk1": unk1, "unk2": unk2, "unk3": data[at]}
    at += 1
    if at < len(data):
        h, a, b, c = struct.unpack_from("<Qfff", data, at)
        out["unk4"] = {"unk1": h, "unk2": a, "unk3": b, "unk4": c}
    return out


def loot(appendix):
    count, at = vlq(appendix, 0)
    hashes = list(struct.unpack_from(f"<{count}Q", appendix, at))
    at += 8 * count
    records = []
    for _ in range(count):
        n = appendix[at] + 1
        records.append([Tdb(x) for x in struct.unpack_from(f"<{n}Q", appendix, at + 1)])
        at += 1 + 8 * n
    return hashes, records


def devices(appendix, names):
    _size, count = struct.unpack_from("<ii", appendix, 0)
    at = 8
    out = []
    for _ in range(count):
        h, cls = struct.unpack_from("<QH", appendix, at)
        at += 10
        children, at = vlq(appendix, at)
        parents, at = vlq(appendix, at)
        kids = list(struct.unpack_from(f"<{children}Q", appendix, at))
        at += 8 * children
        ups = list(struct.unpack_from(f"<{parents}Q", appendix, at))
        at += 8 * parents
        x, y, z = struct.unpack_from("<fff", appendix, at)
        at += 12
        out.append({"hash": h, "className": names[cls], "children": kids, "parents": ups, "nodePosition": {"X": x, "Y": y, "Z": z}})
    return out


def lane_polygons(appendix):
    count = struct.unpack_from("<I", appendix, 0)[0]
    at = 4
    out = []
    for _ in range(count):
        index = struct.unpack_from("<H", appendix, at)[0]
        at += 2
        n, at = vlq(appendix, at)
        outline = [dict(zip("XYZ", struct.unpack_from("<fff", appendix, at + 12 * k))) for k in range(n)]
        at += 12 * n
        m, at = vlq(appendix, at)
        polygon = [dict(zip("XY", struct.unpack_from("<ff", appendix, at + 8 * k))) for k in range(m)]
        at += 8 * m
        out.append({"index": index, "value": {"outline": outline, "polygon": polygon}})
    return out


def lane_connections(appendix):
    count = struct.unpack_from("<I", appendix, 0)[0]
    at = 4
    out = []
    for _ in range(count):
        index = struct.unpack_from("<H", appendix, at)[0]
        at += 2
        n, at = vlq(appendix, at)
        outs = []
        for _ in range(n):
            lane, prob, sharp, here, there = struct.unpack_from("<HB?ff", appendix, at)
            outs.append({"laneIndex": lane, "exitProbabilityCompressed": prob, "isSharpAngle": sharp,
                         "thisLaneExitPosition": here, "nextLaneEntryPosition": there})
            at += 12
        m, at = vlq(appendix, at)
        ins = [{"laneIndex": struct.unpack_from("<H", appendix, at + 2 * k)[0]} for k in range(m)]
        at += 2 * m
        out.append({"index": index, "value": {"outlanes": outs, "inLanes": ins}})
    return out


# ---- comparison ----

def tdb_text(text):
    b = text.encode("utf-8")
    return zlib.crc32(b) | (len(b) << 32)


def norm_enum(s):
    return re.sub(r"[^0-9a-z]", "", str(s).lower())


def is_default(v):
    if v is None or v is False or v == 0 or v == "" or v == "None" or v == []:
        return True
    if isinstance(v, dict):
        return all(is_default(x) for k, x in v.items() if k != "$type")
    if isinstance(v, str):
        return v in ("0", "0.0", "<TDBID:00000000:00>")
    return False


class Compare:
    def __init__(self):
        self.stats = collections.Counter()
        self.bad = []
        self.defaults = collections.Counter()

    def differ(self, where, raw, ext):
        self.stats["values differ"] += 1
        if len(self.bad) < 40:
            self.bad.append((where, str(raw)[:120], str(ext)[:120]))

    def eq(self, raw, ext, where):
        self.stats["values compared"] += 1
        if isinstance(raw, Tdb):
            if isinstance(ext, str):
                m = re.match(r"^<TDBID:([0-9A-Fa-f]{8}):([0-9A-Fa-f]{2})>$", ext)
                whole = re.match(r"^<TDBID:([0-9A-Fa-f]+)>$", ext)  # the extract's form for one WolvenKit has no text for
                want = ((int(m.group(1), 16) | (int(m.group(2), 16) << 32)) if m else int(whole.group(1), 16) if whole
                        else int(ext) if ext.isdigit() else tdb_text(ext))
            else:
                want = int(ext) if ext is not None else 0
            if (raw & 0xFFFFFFFFFF) != (want & 0xFFFFFFFFFF):
                self.differ(where, raw, ext)
            return
        if isinstance(raw, Raw):
            if isinstance(ext, str):
                try:
                    ok = base64.b64decode(ext) == bytes(raw)
                except ValueError:
                    ok = False
                if not ok:
                    self.differ(where, f"{len(raw)} bytes", ext)
            elif isinstance(ext, dict) and "Bytes" in ext:
                self.eq(raw, ext["Bytes"], where)
            elif isinstance(ext, dict) and ext.get("Data") is not None:
                self.stats["buffer WolvenKit decodes and this does not"] += 1
            elif ext is None and len(raw) == 0:
                pass
            else:
                self.differ(where, f"{len(raw)} bytes", ext)
            return
        if isinstance(raw, dict):
            if isinstance(ext, dict) and "HandleId" in ext and "Data" in ext:
                ext = ext["Data"]
            if not isinstance(ext, dict):
                self.differ(where, raw.get("$type"), ext)
                return
            if "$type" in ext and "$type" in raw and ext["$type"] != raw["$type"]:
                self.differ(where + ".$type", raw["$type"], ext["$type"])
            for k, v in raw.items():
                if k in ("$type", "$appendix"):
                    continue
                if k == "$custom":
                    self.stats["class with its own layout, not decoded here: " + str(raw.get("$type"))] += 1
                    continue
                if k not in ext:
                    self.stats["file value the extract lacks"] += 1
                    if len(self.bad) < 40:
                        self.bad.append((where + "." + k, "missing from the extract", str(v)[:80]))
                    continue
                self.eq(v, ext[k], where + "." + k)
            for k, v in ext.items():
                if k == "$type" or k in raw:
                    continue
                # A file leaves out a property at its class's default; WolvenKit writes that default in.
                self.defaults[(raw.get("$type"), k)] += 1
                self.stats["left at the class default by the file"] += 1
                if not is_default(v):
                    self.stats["class default that is not zero"] += 1
            return
        if isinstance(raw, list):
            if isinstance(ext, dict) and "Elements" in ext:
                ext = ext["Elements"]
            if not isinstance(ext, list) or len(ext) != len(raw):
                self.differ(where + "[len]", len(raw), len(ext) if isinstance(ext, list) else ext)
                return
            for k, (a, b) in enumerate(zip(raw, ext)):
                self.eq(a, b, f"{where}[{k}]")
            return
        if isinstance(ext, dict) and "$value" in ext:
            ext = ext["$value"]
        if isinstance(ext, dict) and "DepotPath" in ext:
            ext = ext["DepotPath"]
            if isinstance(ext, dict):
                ext = ext.get("$value")
        if isinstance(raw, float):
            if raw == 0 and ext in (0, 0.0) and struct.pack("<f", raw) != struct.pack("<f", 0.0):
                self.stats["-0 written as 0 by the extract's JSON"] += 1
                return
            try:
                same = struct.pack("<f", raw) == struct.pack("<f", float(ext)) or (raw != raw and float(ext) != float(ext))
            except (TypeError, ValueError, OverflowError):
                same = False
            if not same and not (isinstance(ext, float) and abs(raw - ext) <= abs(raw) * 1e-12):
                self.differ(where, raw, ext)
            return
        if isinstance(raw, bool):
            if bool(ext) != raw and not (str(ext).lower() == str(raw).lower()):
                self.differ(where, raw, ext)
            return
        if isinstance(raw, int):
            try:
                ok = int(ext) == raw
            except (TypeError, ValueError):
                ok = isinstance(ext, str) and fnv(ext) == raw   # a resource path stored as its hash
            if not ok:
                self.differ(where, raw, ext)
            return
        if raw is None:
            if isinstance(ext, dict) and ext.get("HandleRefId") == "-1":
                self.stats["null handle"] += 1
                return
            if not is_default(ext):
                self.differ(where, raw, ext)
            return
        if isinstance(raw, str):
            if ext is None:
                ext = ""
            if str(ext) == raw or (raw == "" and ext == "None"):   # an empty CName prints as None
                return
            if raw == "" and ext == "0":
                self.stats["empty NodeRef written as 0 by WolvenKit"] += 1
                return
            if str(ext).startswith(raw + ";"):
                # WolvenKit keeps a NodeRef as its hash, which stops at ';', and prints the text of whichever NodeRef with
                # that hash it met: the value names the same node, the text is not this file's.
                self.stats["NodeRef text taken from another NodeRef with the same hash"] += 1
                if len(self.bad) < 40:
                    self.bad.append((where, raw[-60:], str(ext)[-60:]))
                return
            if str(ext).isdigit() and fnv(raw) == int(ext):
                return
            if norm_enum(ext) == norm_enum(raw):
                self.stats["enum compared by its letters"] += 1
                return
            self.differ(where, raw, ext)
            return
        self.differ(where, type(raw).__name__, ext)


def lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", required=True)
    ap.add_argument("--src", required=True, help="the world folder of an extract, e.g. <extract>/2.5-ep1/world")
    ap.add_argument("--edition", default="ep1", choices=["ep1", "base"])
    ap.add_argument("--db", help="the world.db built from this extract")
    ap.add_argument("--only", help="compare only these kinds, comma-separated (world, mappins, loot, ..., inplace, smartobjects)")
    ap.add_argument("--tamper", action="store_true")
    a = ap.parse_args()
    load_oodle(a.game_dir)
    winner = game_files(a.game_dir, a.edition)
    only = set(a.only.split(",")) if a.only else None
    cmp = Compare()
    started = time.time()

    def raw_file(path):
        arc = winner.get(fnv(path))
        if arc is None:
            cmp.stats["file not in the game's archives"] += 1
            cmp.bad.append((path, "not in the archives"))
            return None
        return CR2W(arc.read(fnv(path)))

    def check(kind, raws, ext, where):
        if only and kind not in only:
            return
        if a.tamper and ext:
            first = ext[0]
            first["v" if "v" in first else next(iter(first))] = "tampered"
        cmp.stats[kind + " elements"] += len(raws)
        if len(raws) != len(ext):
            cmp.differ(where + " count", len(raws), len(ext))
            return
        cmp.eq(raws, ext, where)

    def v_of(rows):
        return [r["v"] for r in rows]

    for w in ("03_night_city", "04_main_menu"):
        C = BS.join(["base", "worlds", w, "_compiled", "default"]) + BS
        T = BS.join(["base", "worlds", w, "sectors", "_generated", "traffic"]) + BS

        def ex(kind):
            return lines(os.path.join(a.src, f"{w}-{kind}.ndjson"))

        def root(path):
            f = raw_file(path)
            return (f, f.chunk(0)) if f else (None, None)

        f, r = root(C + w + ".streamingworld")
        if r:
            check("world", [r], v_of(ex("world")), w + ".streamingworld")
        f, r = root(C + w + ".mappins")
        if r:
            for kind, prop in (("mappins", "cookedData"), ("mappins_gps", "cookedGpsData"), ("mappins_multi", "cookedMultiData")):
                check(kind, r.get(prop) or [], v_of(ex(kind)), w + ".mappins." + prop)
        f, r = root(C + w + ".poimappins")
        if r:
            check("poi", r.get("cookedData") or [], v_of(ex("poi")), w + ".poimappins")
        f, r = root(C + w + ".areas")
        if r:
            check("areas", r.get("cookedData") or [], v_of(ex("areas")), w + ".areas")
        f, r = root(C + w + ".loot")
        if r:
            data = r.get("data")
            hashes, records = loot(data["$appendix"]) if data and "$appendix" in data else ([], [])
            ext = ex("loot")
            check("loot", [{"hash": h, "records": rec} for h, rec in zip(hashes, records)], ext, w + ".loot")
        for name, kind in ((".devices", "devices"), ("_init.devices", "devices_init")):
            f, r = root(C + w + name)
            if r:
                data = r.get("data")
                check(kind, devices(data["$appendix"], f.names) if data and "$appendix" in data else [], v_of(ex(kind)), w + name)
        f, r = root(C + w + ".locopaths")
        if r:
            check("locopaths", r.get("paths") or [], v_of(ex("locopaths")), w + ".locopaths")
        f, r = root(C + w + ".streamingquerydata")
        if r:
            check("roads", r.get("roadDatas") or [], v_of(ex("roads")), w + ".roads")
            check("road_links", [r.get("connectedRoadDataIndices") or []], v_of(ex("road_links")), w + ".road_links")
        f, r = root(C + w + ".psrep")
        if r:
            buf = r.get("buffer")
            pkg = Package(bytes(buf)) if buf else None
            ext = ex("persistent")
            raws = [{"cruid": c, "v": ch} for c, ch in zip(pkg.cruids, pkg.roots)] if pkg else []
            if pkg and len(pkg.cruids) != len(pkg.roots):
                cmp.differ(w + ".psrep roots", len(pkg.roots), len(pkg.cruids))
            check("persistent", raws, ext, w + ".psrep")
        f, r = root(T + "all.traffic_persistent")
        if r:
            check("lanes", (r.get("data") or {}).get("lanes") or [], v_of(ex("lanes")), w + ".lanes")
        f, r = root(T + "all.lane_polygons")
        if r:
            check("lane_polygons", lane_polygons(r["$appendix"]) if "$appendix" in r else [], v_of(ex("lane_polygons")), w + ".lane_polygons")
        f, r = root(T + "all.lane_connections")
        if r:
            check("lane_connections", lane_connections(r["$appendix"]) if "$appendix" in r else [], v_of(ex("lane_connections")), w + ".lane_connections")
        f, r = root(T + "all.traffic_collisions")
        if r:
            check("lane_collisions", ((r.get("data") or {}).get("laneCollisions")) or [], v_of(ex("lane_collisions")), w + ".lane_collisions")
        f, r = root(T + "all.spatial_representation")
        if r:
            check("lane_neighbors", r.get("neighborGroups") or [], v_of(ex("lane_neighbors")), w + ".lane_neighbors")
        f, r = root(T + "traffic.null_areas")
        if r:
            check("null_collisions", ((r.get("nullAreasCollisionData") or {}).get("nullAreaCollisions")) or [], v_of(ex("null_collisions")), w + ".null_collisions")
            check("null_blockades", ((r.get("nullAreaBlockadeData") or {}).get("nullAreasBlockades")) or [], v_of(ex("null_blockades")), w + ".null_blockades")
        print(f"{w}: {round(time.time() - started)} s", flush=True)

    for kind in ("inplace", "prefab", "acoustic", "smartobjects", "community"):
        if only and kind not in only:
            continue
        parts = sorted(glob.glob(os.path.join(a.src, kind + "-*.ndjson")))
        for part in parts:
            for e in lines(part):
                f = raw_file(e["path"])
                if f is None:
                    continue
                r = f.chunk(0)
                embedded = [f.imports[i - 1] for i, _c, _h in f.embedded]
                if kind == "inplace":
                    raw = {"path": e["path"], "resources": r.get("inplaceResources") or [], "embedded": embedded}
                elif kind == "prefab":
                    raw = {"path": e["path"], "dependencies": r.get("dependencies") or [], "embedded": embedded}
                elif kind == "acoustic":
                    raw = {"path": e["path"], "cells": [{"sector": c.get("sectorId", 0), "bytes": len(c.get("nodes") or b"")} for c in r.get("cells") or []]}
                elif kind == "smartobjects":
                    raw = {"path": e["path"], "box": r.get("localBoundingBox"), "nodes": r.get("compiledNodesData"), "members": r.get("soMembership"),
                           "properties": r.get("propertyDictionary"), "transforms": r.get("transformDictionary"), "sequences": r.get("transformSequenceDictionary")}
                else:
                    raw = {"path": e["path"], "template": r.get("communityTemplate")}
                if a.tamper:
                    e["path"] = e["path"] + "x"
                cmp.stats[kind + " files"] += 1
                cmp.eq(raw, e, e["path"])
        print(f"{kind}: {round(time.time() - started)} s", flush=True)

    if a.db:
        import sqlite3
        db = sqlite3.connect(f"file:{a.db}?immutable=1", uri=True)
        tables = {"mappins": ("mappins", "mappins_gps", "mappins_multi"), "poi_mappins": ("poi",), "areas": ("areas",),
                  "devices": ("devices", "devices_init"), "persistent_states": ("persistent",), "locomotion_paths": ("locopaths",),
                  "roads": ("roads",), "traffic_lanes": ("lanes",), "traffic_lane_collisions": ("lane_collisions",),
                  "traffic_neighbor_groups": ("lane_neighbors",), "null_area_collisions": ("null_collisions",), "null_area_blockades": ("null_blockades",)}
        for table, kinds in tables.items():
            want = sum(len(lines(os.path.join(a.src, f"{w}-{k}.ndjson"))) for w in ("03_night_city", "04_main_menu") for k in kinds)
            have = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            cmp.stats["world.db tables checked"] += 1
            if want != have:
                cmp.differ("world.db " + table, have, want)
        want = sum(len(r["records"]) for w in ("03_night_city", "04_main_menu") for r in lines(os.path.join(a.src, f"{w}-loot.ndjson")))
        if db.execute("SELECT count(*) FROM loot").fetchone()[0] != want:
            cmp.differ("world.db loot", "rows", want)

    print(json.dumps(cmp.stats, sort_keys=True), "seconds", round(time.time() - started))
    print("properties files leave at their class default, by class and name (top 8):", cmp.defaults.most_common(8))
    print("mismatches listed", len(cmp.bad))
    for b in cmp.bad[:25]:
        print("  ", str(b)[:300])
    sys.exit(1 if any(k.endswith("differ") or k.endswith("lacks") or k.startswith("NodeRef text") for k in cmp.stats) else 0)


if __name__ == "__main__":
    main()
