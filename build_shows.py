#!/usr/bin/env python3
"""
PortlandLive build step.

Takes scraped + hand-added shows from scripts/manual_shows.json, dedupes, sorts,
assigns ids, and writes shows.json (what the site reads). No API key required.

Pipeline:
    1. scrape_venues.py   -> writes scripts/manual_shows.json
    2. build_shows.py     -> reads that, writes shows.json
The GitHub Action runs both in order, then commits shows.json.
"""
import json, os, datetime
import re

_DASHES = re.compile(r"[\u2010-\u2015]")


def _norm_title(t):
    # dash-normalize + collapse whitespace + lower so unicode-dash variants
    # (the JLR phantom-dup bug) can never produce a distinct dedupe key.
    return re.sub(r"\s+", " ", _DASHES.sub("-", t or "")).strip().lower()

HERE = os.path.dirname(__file__)
MANUAL = os.path.join(HERE, "manual_shows.json")
OUT = os.path.join(HERE, "shows.json")

_TIME_RE = re.compile(r"^\d{1,2}:\d{2} [AP]M$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JUNK_TITLES = {"buy tickets", "tickets", "menu"}


def validate(shows):
    # Loudly report data-quality issues; never crash the build on a soft issue.
    import datetime as _dt
    from collections import Counter as _C, defaultdict as _dd
    issues = []
    today = _dt.date.today()
    max_future = today + _dt.timedelta(days=730)  # ~2 years out
    for s in shows:
        t = (s.get("title") or "").strip()
        v = s.get("venue", "")
        d = s.get("date", "")
        tm = s.get("time", "")
        if not t:
            issues.append(f"empty title @ {v} {d}")
        else:
            if "<" in t or t.lower() in _JUNK_TITLES:
                issues.append(f"junk title {t!r} @ {v} {d}")
            if len(t) > 120:
                issues.append(f"title too long ({len(t)} chars) @ {v} {d}: {t[:40]!r}")
        if not _DATE_RE.match(d):
            issues.append(f"bad date {d!r} @ {v} {t[:40]!r}")
        else:
            try:
                dd = _dt.date.fromisoformat(d)
                if dd.year <= 1970:
                    issues.append(f"epoch/1970 date {d!r} @ {v} {t[:40]!r}")
                elif dd > max_future:
                    issues.append(f"date >2yr out {d!r} @ {v} {t[:40]!r}")
            except ValueError:
                issues.append(f"unparseable date {d!r} @ {v} {t[:40]!r}")
        if tm != "" and not _TIME_RE.match(tm):
            issues.append(f"bad time {tm!r} @ {v} {d} {t[:40]!r}")
    # exact dups + cross-venue collisions
    keys = [(_norm_title(s.get("title","")), s.get("venue",""), s.get("date","")) for s in shows]
    dups = sum(1 for c in _C(keys).values() if c > 1)
    g = _dd(set)
    for s in shows:
        g[(s.get("date",""), _norm_title(s.get("title","")))].add(s.get("venue",""))
    collisions = sum(1 for vs in g.values() if len(vs) > 1)
    if dups:
        issues.append(f"{dups} exact duplicate(s)")
    if collisions:
        issues.append(f"{collisions} cross-venue title/date collision(s)")
    if issues:
        print(f"VALIDATION: {len(shows)} shows, {len(issues)} ISSUE(S):")
        for i in issues:
            print(f"  WARN: {i}")
    else:
        print(f"VALIDATION: {len(shows)} shows OK, 0 issues")
    return issues


def main():
    shows = []
    if os.path.exists(MANUAL):
        try:
            shows = json.load(open(MANUAL)).get("shows", [])
        except Exception as e:
            print(f"manual_shows.json unreadable: {e}")

    # drop past shows
    # Drop past shows using US Pacific time (venues' local zone), not the
    # GitHub runner's UTC clock, with a 1-day grace buffer so a show never
    # disappears until the day AFTER it happens.
    pacific = datetime.timezone(datetime.timedelta(hours=-8))
    today_pacific = datetime.datetime.now(pacific).date()
    cutoff = (today_pacific - datetime.timedelta(days=1)).isoformat()
    shows = [s for s in shows if s.get("date", "") >= cutoff]

    # dedupe on (title, venue, date)
    seen, deduped = set(), []
    for s in shows:
        k = (_norm_title(s.get("title","")),
             s.get("venue","").lower().strip(),
             s.get("date",""))
        if k not in seen and s.get("title") and s.get("date"):
            seen.add(k); deduped.append(s)

    deduped.sort(key=lambda s: (s["date"], s.get("venue",""), s.get("title","")))
    for i, s in enumerate(deduped, 1):
        s["id"] = i

    validate(deduped)

    out = {
        "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "Scraped from venue calendars + hand-added listings",
        "shows": deduped,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    venues = len(set(s.get("venue","") for s in deduped))
    print(f"Wrote {len(deduped)} shows across {venues} venues to shows.json")

if __name__ == "__main__":
    main()
