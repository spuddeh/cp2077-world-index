"""List the TweakDBIDs a world-index.db references that its game's TweakDB has no record for, with every place each is used.

    python verify/dangling_tweakdbids.py --db out/2.5-ep1/world-index.db --tweakdb "<game>/r6/cache/tweakdb_ep1.bin" --out <file>.csv

The TweakDB file is read directly: its record table holds every record id, named or not. A reference is dangling when
its id is in no row of that table. Uses read: loot records, community characters, and every TweakDBID held in persistent
device state (the JSON key names the field). The CSV has one row per use: id as <TDBID:HEX>, its text when known, the
use, the world file or loot node it comes from, and for a loot node the position of the node that holds it. --db is an
edition build: in a version's database, a row of both editions would be read twice.
"""
import argparse
import collections
import csv
import json
import re
import sqlite3
import struct
import zlib

HEX = re.compile(r"^<TDBID:([0-9A-F]+)>$")
ID_MASK = 0xFFFFFFFFFF  # the CRC32 and the length byte; the top bytes are not part of the id


def record_ids(path):
    data = open(path, "rb").read()
    magic, _blob, _parser, _sum, _flats, records = struct.unpack_from("<6I", data, 0)
    if magic != 0x0BB1DB47:
        raise SystemExit(f"{path} is not a TweakDB file (magic {magic:08X})")
    n = struct.unpack_from("<I", data, records)[0]
    return {struct.unpack_from("<Q", data, records + 4 + k * 12)[0] & ID_MASK for k in range(n)}


def as_id(v):
    """A stored TweakDBID value as (id, text): <TDBID:HEX>, a decimal, or a name."""
    if not v:
        return 0, ""
    m = HEX.match(v)
    if m:
        return int(m.group(1), 16) & ID_MASK, ""
    if v.isdigit():
        return int(v) & ID_MASK, ""
    b = v.encode("utf-8")
    return (zlib.crc32(b) | (len(b) << 32)) & ID_MASK, v


def tdbid_values(v, key=""):
    """Every string under a TweakDBID-shaped key or in the <TDBID:...> form, with the key that holds it."""
    if isinstance(v, dict):
        for k, x in v.items():
            yield from tdbid_values(x, k)
    elif isinstance(v, list):
        for x in v:
            yield from tdbid_values(x, key)
    elif isinstance(v, str) and (HEX.match(v) or re.search(r"(Record|RecordID|TweakDBID|tweakDBRecord|keycard)$", key)):
        yield key, v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="a built world-index.db")
    ap.add_argument("--tweakdb", required=True, help="the TweakDB file that edition loads: tweakdb_ep1.bin or tweakdb.bin")
    ap.add_argument("--out", required=True, help="the CSV to write")
    a = ap.parse_args()
    records = record_ids(a.tweakdb)
    w = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    uses = []  # (id, text, use, source, node)

    for world, node, rec in w.execute("SELECT world, node_ref_hash, record FROM loot"):
        i, text = as_id(rec)
        if i and i not in records:
            uses.append((i, text, "loot.record", world, node))
    for path, entry, char in w.execute("SELECT path, entry, character FROM community_entries"):
        i, text = as_id(char)
        if i and i not in records:
            uses.append((i, text, "community_entries.character", f"{path}#{entry}", ""))
    for world, idx, cls, data in w.execute("SELECT world, idx, class, data FROM persistent_states"):
        for key, v in tdbid_values(json.loads(data)):
            i, text = as_id(v)
            if i and i not in records:
                uses.append((i, text, f"persistent_states.{key}", f"{world} persistent {idx} {cls}", ""))

    where = {}
    # nodes keeps a global id as a signed 64-bit integer; loot keeps it as unsigned text.
    nodes = {int(u[4]) - (1 << 64) if int(u[4]) >= 1 << 63 else int(u[4]) for u in uses if u[4]}
    for gid, x, y, z, path in w.execute(
            "SELECT n.global_id, n.x, n.y, n.z, s.text FROM nodes n JOIN sectors sc ON sc.id = n.sector_id "
            "JOIN strings s ON s.id = sc.path_id WHERE n.global_id IS NOT NULL"):
        if gid in nodes:
            where[str(gid & 0xFFFFFFFFFFFFFFFF)] = (round(x, 2), round(y, 2), round(z, 2), path)

    with open(a.out, "w", newline="", encoding="utf-8") as h:
        out = csv.writer(h)
        out.writerow(["id", "text", "use", "source", "node", "x", "y", "z", "sector"])
        for i, text, use, source, node in sorted(uses, key=lambda u: (u[0], u[2], u[3])):
            x, y, z, sector = where.get(str(node), ("", "", "", ""))
            out.writerow([f"<TDBID:{i:X}>", text, use, source, node, x, y, z, sector])

    by_use = collections.defaultdict(set)
    for u in uses:
        by_use[u[2]].add(u[0])
    print(f"{len({u[0] for u in uses})} dangling ids, {len(uses)} uses, {len(records):,} records in {a.tweakdb}")
    for use, s in sorted(by_use.items(), key=lambda x: -len(x[1])):
        print(f"  {len(s):5} ids  {sum(1 for u in uses if u[2] == use):6} uses  {use}")
    print(f"  loot nodes placed: {len(where)} of {len({u[4] for u in uses if u[4]})}")


if __name__ == "__main__":
    main()
