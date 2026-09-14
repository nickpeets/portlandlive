#!/usr/bin/env python3
"""
One-off: recover past shows the archive never captured.

WHY THIS IS NEEDED
archive.json is meant to be an append-only record of every show that has
happened. It was not. CI runs scrape_venues.py before build_shows.py, and the
scraper rewrites manual_shows.json keeping only today forward -- so by the time
build_shows.py looked for past shows to archive, anything from a HEALTHY
scraper was already gone. What survived in the file was hand-added shows and
the stale entries a BROKEN scraper retains, which is why the archive held 218
rows dominated by Barrel Room, Hawthorne Theatre, Main Street and Pioneer
Courthouse Square -- the dead sources -- while every Laurelthirst, Holocene and
Revolution Hall show that ever happened simply vanished.

build_shows.py now also archives from the previous shows.json, which closes the
gap going forward. This recovers what was already lost.

WHERE THE DATA IS
Every nightly build committed shows.json, so each of those ~149 commits is a
snapshot of the feed on that day. A show that ran on June 20 appears in the
builds before it and is absent after. Walking the history and collecting every
row whose date is now past reconstructs the record.

SAFETY
Reuses build_shows.archive_past_shows, which is add-only and dedupes on slug,
so existing entries are never overwritten and re-running changes nothing.
Read-only against git (no checkout, no branch switching) -- it reads blobs with
`git show`, so the working tree is untouched.

Run:  python3 backfill_archive.py          (dry run, reports only)
      python3 backfill_archive.py --write  (writes archive.json)
"""
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_shows  # noqa: E402


def git(*args):
    return subprocess.run(["git", "-C", HERE, *args],
                          capture_output=True, text=True).stdout


def main():
    write = "--write" in sys.argv
    cutoff = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=-8))).date().isoformat()

    commits = [c for c in git("log", "--format=%H", "--", "shows.json").split() if c]
    print(f"scanning {len(commits)} builds of shows.json for shows now past "
          f"(cutoff {cutoff})")

    # Keyed on the same identity archive_past_shows dedupes by, so a show seen
    # in fifty consecutive builds is collected once.
    found = {}
    unreadable = 0
    for i, c in enumerate(commits):
        raw = git("show", f"{c}:shows.json")
        if not raw.strip():
            unreadable += 1
            continue
        try:
            rows = json.loads(raw).get("shows", [])
        except Exception:
            unreadable += 1
            continue
        for s in rows:
            d = s.get("date", "")
            if not d or d >= cutoff:
                continue
            if not (s.get("title") and s.get("venue")):
                continue
            found.setdefault((s["venue"], d, s["title"]), s)
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(commits)} builds, {len(found)} distinct past shows so far")

    print(f"\n{len(found)} distinct past shows across the history"
          + (f" ({unreadable} builds unreadable, skipped)" if unreadable else ""))

    existing = set()
    if os.path.exists(build_shows.ARCHIVE):
        for r in json.load(open(build_shows.ARCHIVE)).get("shows", []):
            if r.get("slug"):
                existing.add(r["slug"])
    print(f"{len(existing)} already in archive.json")

    new = [s for s in found.values() if build_shows.make_slug(s) not in existing]
    print(f"{len(new)} would be ADDED\n")

    from collections import Counter
    by_venue = Counter(s["venue"] for s in new)
    print("top venues recovered:")
    for v, n in by_venue.most_common(15):
        print(f"   {v:34s} {n}")
    if new:
        dates = sorted(s["date"] for s in new)
        print(f"\ndate range recovered: {dates[0]} .. {dates[-1]}")

    if not write:
        print("\nDRY RUN -- nothing written. Re-run with --write to apply.")
        return

    gen = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    added, collisions = build_shows.archive_past_shows(list(found.values()), gen)
    print(f"\nwrote archive.json: +{added} added, {len(collisions)} slug collision(s)")
    for c in collisions[:10]:
        print(f"   collision: {c}")


if __name__ == "__main__":
    main()
