"""Every database from the extracts, in order: each version's two edition builds, its world-index.db, then the patch diff.

    python build/build_all.py --extract <dump>/wscript/raw/world-index --game-dir 2.31="<2.31 install>" --game-dir 2.5="<2.5 install>"
        [--out out] [--versions 2.31 2.5] [--check] [--keep-editions]

<extract> holds one folder per edition from extract/world-index.wscript and extract/world-files.wscript: 2.31-ep1, 2.31-base,
2.5-ep1, 2.5-base. Each version needs its own game install, because build_world.py and fix_noderefs.py read that version's
archives. 2.31 is built before 2.5, whose build names its appearance hashes from the 2.31 database's strings. --check
reads each edition back out of the version's database (verify/editions_check.py). The edition builds in out/<version>-<edition>
are deleted once their version's database is written, unless --keep-editions. Each step's output goes straight to the
console; the run stops at the first step that fails.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run(*args):
    print(f"=== {time.strftime('%H:%M:%S')} {' '.join(args)}", flush=True)
    started = time.time()
    code = subprocess.call([sys.executable, "-u", *args], cwd=ROOT)
    print(f"=== exit {code}, {round(time.time() - started)} s", flush=True)
    if code != 0:
        raise SystemExit(code)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extract", required=True)
    ap.add_argument("--game-dir", action="append", required=True, metavar="VERSION=DIR",
                    help="a game install for one version, e.g. 2.5=\"D:/Games/Cyberpunk 2077\"; once per version")
    ap.add_argument("--out", default="out")
    ap.add_argument("--versions", nargs="+", default=["2.31", "2.5"])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--keep-editions", action="store_true")
    a = ap.parse_args()
    game_dirs = dict(g.split("=", 1) for g in a.game_dir)
    versions = sorted(a.versions, key=Decimal)   # 2.31 comes before 2.5
    missing = [v for v in versions if v not in game_dirs]
    if missing:
        raise SystemExit(f"no --game-dir for {', '.join(missing)}")
    out = os.path.abspath(os.path.join(ROOT, a.out)) if not os.path.isabs(a.out) else a.out
    built = []
    for version in versions:
        # The newest older version's database names appearance hashes, whether built in this run or before it.
        older = sorted((v for v in os.listdir(out) if os.path.exists(os.path.join(out, v, "world-index.db")) and "-" not in v
                        and Decimal(v) < Decimal(version)), key=Decimal) if os.path.isdir(out) else []
        names = ["--names-from", os.path.join(out, older[-1], "world-index.db")] if older else []
        for edition in ("ep1", "base"):
            folder = os.path.join(out, f"{version}-{edition}")
            src = os.path.join(a.extract, f"{version}-{edition}")
            run("build/build.py", "--game", version, "--edition", edition, *names, "--src", src, "--out", folder)
            run("build/build_world.py", "--game", version, "--edition", edition, "--game-dir", game_dirs[version],
                "--src", os.path.join(src, "world"), "--out", folder)
            if version != "2.31":
                # WolvenKit 10 can print a NodeRef in another spelling of its hash; 2.31 is read through WolvenKit 9.
                run("build/fix_noderefs.py", "--game-dir", game_dirs[version], "--db", folder, "--edition", edition)
        editions = [os.path.join(out, f"{version}-{e}") for e in ("base", "ep1")]
        run("build/merge_editions.py", "--base", editions[0], "--ep1", editions[1], "--out", os.path.join(out, version))
        if a.check:
            run("verify/editions_check.py", "--version", os.path.join(out, version), "--base", editions[0], "--ep1", editions[1])
        if not a.keep_editions:
            for folder in editions:
                shutil.rmtree(folder)
                print(f"deleted {folder}", flush=True)
        built.append(version)
    if len(built) >= 2:
        run("build/diff.py", "--old", os.path.join(out, built[-2]), "--new", os.path.join(out, built[-1]), "--out", out)


if __name__ == "__main__":
    main()
