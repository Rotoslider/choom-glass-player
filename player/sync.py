#!/usr/bin/env python3
"""Copy the glass from home before a trip: the page, tower_ears.py, the props and the clips, from the
home glass's share (tools/share_glass.py in the Choom repo's hologram folder, started there first).

    python player/sync.py [share address]     (default: config.json "share_url")

Only what changed since the last sync is fetched (by size and time). Files the share no longer has
are removed, but only ones an earlier sync put here; nothing else in glass/ is touched.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common import CONFIG, GLASS_DIR

SYNCED = GLASS_DIR / ".synced.json"  # what earlier syncs put here (the only files a sync may remove)


def main():
    share = (sys.argv[1] if len(sys.argv) > 1 else CONFIG.get("share_url", "")).rstrip("/")
    if not share:
        raise SystemExit('No share address: give one, or set "share_url" in config.json (e.g. http://192.168.1.23:8770).')
    try:
        with urllib.request.urlopen(f"{share}/manifest.json", timeout=20) as response:
            files = json.loads(response.read())
    except Exception as e:
        raise SystemExit(f"Can't reach the share at {share} ({e}). Start tools/share_glass.py on the home glass first.")
    GLASS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        before = set(json.loads(SYNCED.read_text()))
    except (OSError, ValueError):
        before = set()

    wanted = [f for f in files if not up_to_date(f)]
    total = sum(f["size"] for f in wanted)
    print(f"{len(files)} files at home, {len(wanted)} to fetch ({total / 1e9:.2f} GB)", flush=True)
    done, started = 0, time.time()
    for n, f in enumerate(wanted, 1):
        fetch(share, f)
        done += f["size"]
        if n % 25 == 0 or n == len(wanted):
            rate = done / max(time.time() - started, 0.1) / 1e6
            print(f"  {n}/{len(wanted)}  {done / 1e9:.2f} of {total / 1e9:.2f} GB  ({rate:.1f} MB/s)", flush=True)

    now = {f["path"] for f in files}
    gone = sorted(before - now)
    for path in gone:
        local = GLASS_DIR / path
        if local.is_file():
            local.unlink()
    SYNCED.write_text(json.dumps(sorted(now)))
    print(f"done{f'; removed {len(gone)} files home no longer has' if gone else ''}.", flush=True)


def local_path(path):
    local = (GLASS_DIR / path).resolve()
    if GLASS_DIR not in local.parents:
        raise SystemExit(f"refusing a path outside the glass folder: {path}")
    return local


def up_to_date(f):
    local = local_path(f["path"])
    try:
        st = local.stat()
    except FileNotFoundError:
        return False
    return st.st_size == f["size"] and int(st.st_mtime) == f["mtime"]


def fetch(share, f):
    """One file, written beside its place and moved in when whole, with home's time on it."""
    local = local_path(f["path"])
    local.parent.mkdir(parents=True, exist_ok=True)
    part = local.with_name(local.name + ".part")
    with urllib.request.urlopen(f"{share}/files/{urllib.parse.quote(f['path'])}", timeout=60) as response, \
            part.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    if part.stat().st_size != f["size"]:
        part.unlink()
        raise SystemExit(f"{f['path']} came incomplete; run the sync again.")
    os.utime(part, (f["mtime"], f["mtime"]))
    part.replace(local)


if __name__ == "__main__":
    main()
