#!/usr/bin/env python3
"""
Parser regression suite: every parser with a captured fixture runs against it
and must produce the counts that were verified by hand when the fixture was
taken. Run before committing any change to scrape_venues.py:

    python3 test_parsers.py

Why this exists. On 2026-09-14 four parsers were rewritten from probe
summaries -- grep counts, class names, snippets -- and every one of them
failed on the live page. Every parser written against a saved copy of the
real HTML worked first time. The fixtures in fixtures/ are those saved
copies. They are the ground truth a parser is built against, and this file
is what catches a later "improvement" that quietly breaks one.

A fixture is a snapshot. The counts below are what the page contained on the
day it was captured, with `today` pinned to that day, so they do not drift as
the venues post new shows. When a venue redesigns its site, capture the new
page, update the count here, and say why in the commit.

The `today` pin matters: parsers that infer a year from a month name, or that
drop past dates, depend on it. Every fixture below was captured on
2026-09-14 or -15 Pacific and is tested as of 2026-09-14.
"""
import datetime
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
TODAY = datetime.date(2026, 9, 14)

spec = importlib.util.spec_from_file_location("sv", os.path.join(HERE, "scrape_venues.py"))
sv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sv)


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8", errors="replace") as f:
        return f.read()


# (fixture file, parser, expected row count, {field: count of rows where it is set}, note)
#
# Row counts are the parser's full output on the fixture BEFORE the 90-day
# horizon filter that scrape() applies -- i.e. everything the page carried,
# including recent past shows the venue left up. Field counts are the number
# of rows with that field non-empty; they pin the extraction quality that was
# verified by hand, not just that "something" parsed.
CASES = [
    ("roseland.html",          sv.parse_mammoth,        47, {"time": 47, "age": 46},        "RHP; age via URL map; time past the old 60-elem cap"),
    ("hawthorne-events.html",  sv.parse_mammoth,        61, {"time": 61, "age": 61},        "RHP; Hawthorne Lounge label; titles must not double"),
    ("dantes.html",            sv.parse_dantes,         48, {"time": 48, "ticketUrl": 48},  "TicketWeb; time sits one level above .tw-name"),
    ("jlr.html",               sv.parse_jacklondonrevue, 56, {"age": 32, "ticketUrl": 56},  "two-fragment merge; age in .tw-description"),
    ("star-theater.html",      sv.parse_startheater,    50, {"time": 50, "ticketUrl": 50},  "TicketWeb .tw-section"),
    ("rose-quarter.html",      sv.parse_rosequarter,    25, {"time": 23},                   "time from .card-date-time, skipping w-condition-invisible"),
    ("portland5.html",         sv.parse_portland5,      10, {"time": 7},                    "time from .teaser__body next to the date"),
    ("kenton.html",            sv.parse_kentonclub,     16, {"time": 0},                    "plain-text <p> list; 'No Music' day skipped; no times published"),
    ("spare-room-sept2026.html", sv.parse_spareroom,    11, {"time": 0},                    "monthly <li> list; karaoke lines skipped"),
    ("switchback-events.ics",  sv.parse_switchback,     30, {"time": 30},                   "iCal; 'Live Music:' filter; UTC -> Pacific"),
    ("switchback-music.ics",   sv.parse_switchback,      5, {"time": 5},                    "iCal; 🎵 marker; World Cup excluded"),
]

# Pages that were captured and examined but publish NO listing data the
# parser can use. Kept as fixtures so the negative finding is reproducible
# and nobody re-investigates from scratch.
NEGATIVE = [
    ("twilight.html", "no times on the listing (title + flyer + link only)"),
    ("nova.html",     "no times on the listing"),
    ("aladdin.html",  "no age on the listing; every card links only to etix.com"),
]


def main():
    fails = 0
    print(f"parser regression -- {len(CASES)} cases, today pinned to {TODAY}\n")
    for fname, parser, want_n, fields, note in CASES:
        try:
            rows = parser(load(fname), TODAY)
        except Exception as e:
            print(f"  FAIL {fname:28s} raised {type(e).__name__}: {e}")
            fails += 1
            continue
        got_n = len(rows)
        problems = []
        if got_n != want_n:
            problems.append(f"rows {got_n} != {want_n}")
        for field, want in fields.items():
            got = sum(1 for r in rows if (r.get(field) or "").strip())
            if got != want:
                problems.append(f"{field} {got} != {want}")
        # Invariants that hold for every parser.
        empty_titles = sum(1 for r in rows if not (r.get("title") or "").strip())
        if empty_titles:
            problems.append(f"{empty_titles} empty title(s)")
        junk = [r["title"] for r in rows if " end event" in r["title"].lower() or r["title"].lower().count(" with ") >= 2]
        if junk:
            problems.append(f"{len(junk)} junk title(s), e.g. {junk[0][:50]!r}")
        if problems:
            fails += 1
            print(f"  FAIL {fname:28s} {'; '.join(problems)}")
        else:
            print(f"  ok   {fname:28s} {got_n:3d} rows  -- {note}")
    print()
    for fname, why in NEGATIVE:
        present = os.path.exists(os.path.join(FIX, fname))
        print(f"  {'ref ' if present else 'MISSING'} {fname:28s} negative fixture: {why}")
    print()
    if fails:
        print(f"{fails} FAILURE(S)")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
