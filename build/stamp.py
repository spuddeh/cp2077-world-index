"""The build stamp every database's meta carries: HEAD of this repo, with -dirty when build/ or extract/ has uncommitted
changes. A build that cannot name its commit stops, because a database with no stamp cannot be traced to its code."""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def git_commit():
    try:
        head = subprocess.check_output(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", HERE, "status", "--porcelain", "--", "../build", "../extract"],
                                        text=True).strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(f"git could not name this build's commit: {e}")
    if not head:
        raise SystemExit("git returned no commit for this build")
    return head + ("-dirty" if dirty else "")
