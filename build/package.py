"""Compresses the release databases for a GitHub Release, with a sha256 of each raw and compressed file.

    python build/package.py [--out out] [--threads 4] [--only world-index-2.5.db.zst ...]

Reads out/2.5/world-index.db, out/2.31/world-index.db and out/diff-2.31-ep1-2.5-ep1.db and writes, into out/release/,
one .zst per file at zstd level 19, SHA256SUMS (raw and compressed) and release.json (sizes, hashes and build stamps).
Each .zst is decompressed again and its hash compared with the raw file's before it is accepted.

Refuses a version database whose user_version is not SCHEMA, whose build stamps are missing, or whose stamps end in
-dirty; a diff whose build stamps are missing or -dirty; and any asset over 2 GiB, the GitHub Release limit per file.
Few threads, because each zstd worker at level 19 holds its own window and this machine stops shells when memory runs low.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time

import zstandard

SCHEMA = 9
LEVEL = 19
MAX_ASSET = 2 * 1024 ** 3  # 2,147,483,648 bytes
CHUNK = 16 * 1024 ** 2

# asset name -> (path under --out, kind)
ASSETS = {
    "world-index-2.5.db.zst": (os.path.join("2.5", "world-index.db"), "version"),
    "world-index-2.31.db.zst": (os.path.join("2.31", "world-index.db"), "version"),
    "diff-2.31-ep1-2.5-ep1.db.zst": ("diff-2.31-ep1-2.5-ep1.db", "diff"),
}


def stamps(path, kind):
    """The build stamps a release file must carry; stops on a wrong schema or a missing or dirty stamp."""
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        meta = dict(c.execute("SELECT key, value FROM meta"))
        if kind == "version":
            user_version = c.execute("PRAGMA user_version").fetchone()[0]
            if user_version != SCHEMA:
                raise SystemExit(f"{path}: user_version {user_version}, expected {SCHEMA}")
            keys = [k for k in meta if k == "build_commit" or k.endswith("_build_commit")]
        else:
            keys = ["old_build", "new_build"]
    finally:
        c.close()
    if kind == "version" and "build_commit" not in keys:
        raise SystemExit(f"{path}: no build_commit in meta")
    found = {k: meta.get(k) or "" for k in keys}
    bad = {k: v for k, v in found.items() if not v or v.endswith("-dirty")}
    if bad:
        raise SystemExit(f"{path}: missing or dirty build stamps {bad}")
    return found


def compress(src, dst, threads):
    """Streams src into dst at LEVEL; returns (raw sha256, compressed sha256)."""
    raw_hash, zst_hash = hashlib.sha256(), hashlib.sha256()
    total, done, start = os.path.getsize(src), 0, time.time()
    cctx = zstandard.ZstdCompressor(level=LEVEL, threads=threads, write_checksum=True, write_content_size=True)

    class Hashing:
        def __init__(self, f):
            self.f = f

        def write(self, b):
            zst_hash.update(b)
            return self.f.write(b)

        def flush(self):
            self.f.flush()

    tmp = dst + ".part"
    with open(src, "rb") as fin, open(tmp, "wb") as fout:
        with cctx.stream_writer(Hashing(fout), size=total, closefd=False) as w:
            while chunk := fin.read(CHUNK):
                raw_hash.update(chunk)
                w.write(chunk)
                done += len(chunk)
                if done % (CHUNK * 32) < CHUNK:
                    rate = done / max(time.time() - start, 1) / 1024 ** 2
                    print(f"  {done * 100 // total}% ({rate:.1f} MB/s)", flush=True)
    os.replace(tmp, dst)
    return raw_hash.hexdigest(), zst_hash.hexdigest()


def decompressed_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f, zstandard.ZstdDecompressor().stream_reader(f) as r:
        while chunk := r.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="out")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--only", nargs="+", choices=sorted(ASSETS), help="package these assets; keep the others' entries")
    a = ap.parse_args()

    release = os.path.join(a.out, "release")
    os.makedirs(release, exist_ok=True)
    manifest_path = os.path.join(release, "release.json")
    manifest = {}
    if a.only and os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

    names = a.only or list(ASSETS)
    # Every stamp is checked before any compression starts, so a bad file stops the run at once.
    checked = {}
    for name in names:
        rel, kind = ASSETS[name]
        src = os.path.join(a.out, rel)
        if not os.path.isfile(src):
            raise SystemExit(f"missing {src}")
        checked[name] = (src, stamps(src, kind))

    for name in names:
        src, found = checked[name]
        dst = os.path.join(release, name)
        print(f"{name} <- {src} ({os.path.getsize(src):,} bytes)", flush=True)
        start = time.time()
        raw_sha, zst_sha = compress(src, dst, a.threads)
        size = os.path.getsize(dst)
        if size > MAX_ASSET:
            os.remove(dst)
            raise SystemExit(f"{name}: {size:,} bytes is over the 2 GiB asset limit; removed")
        if decompressed_sha256(dst) != raw_sha:
            raise SystemExit(f"{name}: decompressed file does not match {src}")
        manifest[name] = {
            "source": os.path.relpath(src, a.out).replace(os.sep, "/"),
            "raw_bytes": os.path.getsize(src), "raw_sha256": raw_sha,
            "zst_bytes": size, "zst_sha256": zst_sha,
            "zstd_level": LEVEL, "stamps": found,
        }
        print(f"  {size:,} bytes in {(time.time() - start) / 60:.1f} min, round trip matches", flush=True)
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, indent=2)

    with open(os.path.join(release, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        for name in sorted(manifest):
            m = manifest[name]
            f.write(f"{m['zst_sha256']}  {name}\n")
            f.write(f"{m['raw_sha256']}  {name[:-4]}\n")
    for name in sorted(manifest):
        m = manifest[name]
        print(f"{name}: {m['raw_bytes'] / 1e6:,.0f} MB -> {m['zst_bytes'] / 1e6:,.0f} MB")


if __name__ == "__main__":
    sys.exit(main())
