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


# A regression suite must never touch the network, or it is testing the
# venue's website rather than the parser. Some parsers paginate on their
# own (parse_portland5 fetches ?page=1..20 and stops on the first error),
# so with network available they return the whole live calendar and the
# count is different every day. Stub the fetchers: anything that reaches
# for the network gets an error, which paginating parsers treat as
# "last page" and fall back to the fixture alone.
def _no_network(url, *a, **k):
    raise RuntimeError(f"test_parsers: network disabled ({url})")


sv.fetch = _no_network
if hasattr(sv, "fetch_headless"):
    sv.fetch_headless = _no_network


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
    ("roseland.html",          sv.parse_mammoth,        47, {"time": 47, "age": 46, "imageUrl": 47},  "RHP; age + poster via URL map; time past the old 60-elem cap"),
    ("hawthorne-events.html",  sv.parse_mammoth,        61, {"time": 61, "age": 61, "imageUrl": 61},  "RHP; Hawthorne Lounge label; titles must not double"),
    ("dantes.html",            sv.parse_dantes,         48, {"time": 48, "ticketUrl": 48, "imageUrl": 48}, "TicketWeb; time and poster one level above .tw-name"),
    ("jlr.html",               sv.parse_jacklondonrevue, 56, {"age": 32, "ticketUrl": 56},  "two-fragment merge; age in .tw-description"),
    ("star-theater.html",      sv.parse_startheater,    50, {"time": 50, "ticketUrl": 50},  "TicketWeb .tw-section"),
    ("rose-quarter.html",      sv.parse_rosequarter,    25, {"time": 23, "imageUrl": 25},   "time from .card-date-time, skipping w-condition-invisible; poster is the card img"),
    ("portland5.html",         sv.parse_portland5,      10, {"time": 7},                    "time from .teaser__body next to the date"),
    ("kenton.html",            sv.parse_kentonclub,     16, {"time": 0},                    "plain-text <p> list; 'No Music' day skipped; no times published"),
    ("spare-room-sept2026.html", sv.parse_spareroom,    15, {"time": 0},                    "monthly <li> list; karaoke/bingo skipped except Karaoke From Hell (live band; Nick's call)"),
    ("switchback-events.ics",  sv.parse_switchback,     30, {"time": 30},                   "iCal; 'Live Music:' filter; UTC -> Pacific"),
    ("switchback-music.ics",   sv.parse_switchback,      5, {"time": 5},                    "iCal; 🎵 marker; World Cup excluded"),
    ("alberta-rose.html",      sv.parse_albertarose,    51, {"imageUrl": 51},              "RHP; poster via URL map"),
    ("holocene.html",          sv.parse_holocene,       60, {"imageUrl": 60},              "RHP (Elementor); poster via URL map"),
    ("mississippi-studios.html", sv.parse_msstudios,    30, {"imageUrl": 30},              "etix; poster is cdn.etix.com img in .event__inner, two above the h2"),
    ("showdown.html",          sv.parse_showdown,       10, {"time": 10, "age": 10, "imageUrl": 10, "ticketUrl": 10}, "TicketWeb; page one of seven (network stubbed, so no pagination here)"),
    ("mississippi-pizza.html",  sv.parse_mississippipizza, 34, {"imageUrl": 34, "age": 34},   "RHP; poster via URL map; age from eventAgeRestriction"),
    ("bunkbar.html",           sv.parse_bunkbar,        10, {"imageUrl": 10, "time": 10, "age": 3}, "Next.js cards; poster unwrapped from /_next/image?url=; age only where the card says it"),
    ("nofun-events.html",      sv.parse_nofun,          45, {"time": 45, "age": 45, "imageUrl": 24}, "Squarespace event list (HTML; the JSON endpoint serves an error page); karaoke/trivia/closed skipped; trailing TBA stripped"),
]

# Pages that were captured and examined but publish NO listing data the
# parser can use. Kept as fixtures so the negative finding is reproducible
# and nobody re-investigates from scratch.
NEGATIVE = [
    ("twilight.html", "no times on the listing (title + flyer + link only)"),
    ("nova.html",     "no times on the listing"),
    ("aladdin.html",  "no age on the listing; every card links only to etix.com"),
    ("laurelthirst.html", "EventON renders the calendar by AJAX; this HTML is the shell. The real case is laurelthirst-sept2026.html below, fed through a stubbed _laurel_month"),
    ("tomorrows-verse.html", "Wix; events come from the JSON API, not this HTML -- the warmup blob has mainImage, the API tier fieldset did not"),
    ("portland5-detail.html", "one portland5.com event page: dt/dd pairs for age and doors, og:image poster; _p5_detail() reads it, exercised in the enrichment path"),
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
    # Laurelthirst walks months by POSTing to EventON itself, so it cannot be
    # driven from one HTML file the way the others are. Feed it the captured
    # September month through a stubbed _laurel_month and check the poster
    # fallback: 22 of 28 events carry one pasted into the description.
    month = load("laurelthirst-sept2026.html")
    sv._laurel_nonces = lambda h: ("n", "x")
    sv._laurel_month = lambda m, y, n, x: month if (m, y) == (10, 2026) else ""
    rows = sv.parse_laurelthirst("<html></html>", TODAY)
    imgs = sum(1 for r in rows if (r.get("imageUrl") or "").strip())
    if len(rows) == 28 and imgs == 22:
        print(f"  ok   laurelthirst-sept2026.html   {len(rows):3d} rows  -- EventON month via stubbed _laurel_month; poster from description img")
    else:
        fails += 1
        print(f"  FAIL laurelthirst-sept2026.html   rows {len(rows)} != 28 or imageUrl {imgs} != 22")
    print()
    # McMenamins: the parser drives its own session (postback per venue, then
    # the getScrollEvents.aspx fragment for the full list). Stub those three
    # calls with the captured White Eagle pages and check the card loop reads
    # the scroll fragment -- times on every card, ages from the card text.
    p1 = load("mcmenamins-whiteeagle.html"); frag = load("mcmenamins-scroll-10.html")
    sv._mcmenamins_session_get = lambda s, u: "<html></html>"
    sv._mcmenamins_filter_html = lambda s, t, vid: p1
    sv._mcmenamins_scroll_html = lambda s, vid, page_size=100: frag
    sv.MCMENAMINS_VENUES = {"55": "White Eagle Saloon"}
    rows = sv.parse_mcmenamins("<html></html>", TODAY)
    n_t = sum(1 for r in rows if (r.get("time") or "").strip()); n_a = sum(1 for r in rows if (r.get("age") or "").strip())
    if len(rows) == 10 and n_t == 10 and n_a == 8:
        print(f"  ok   mcmenamins-scroll-10.html    {len(rows):3d} rows  -- getScrollEvents fragment via stubbed session; age from card text")
    else:
        fails += 1
        print(f"  FAIL mcmenamins-scroll-10.html    rows {len(rows)} != 10 or time {n_t} != 10 or age {n_a} != 8")
    print()
    # Ticketmaster enrichment/gap-fill (build_shows.tm_apply) against the
    # captured Discovery API pull. The feed it matches against changes
    # nightly, so the assertions are invariants, not counts: every TM venue
    # maps to a known venue, add-on packages are never added, added rows
    # never duplicate, and the normalizer reads the fields it should.
    bspec = importlib.util.spec_from_file_location("bs", os.path.join(HERE, "build_shows.py"))
    bs = importlib.util.module_from_spec(bspec)
    bspec.loader.exec_module(bs)
    import json as _json
    tm = _json.load(open(os.path.join(FIX, "ticketmaster-portland.json")))
    probs = []
    n0 = bs._tm_normalize(tm[0], sv.VENUE_INFO)
    if not (n0 and n0.get("time") == "7:00 PM" and n0.get("imageUrl", "").startswith("http")
            and "ticketweb.com" in n0.get("ticketUrl", "") and n0.get("age") == "21+"):
        probs.append(f"normalizer on event 0: {n0}")
    rows = []
    m, a, unc = bs.tm_apply(rows, tm, datetime.date(2026, 9, 15))
    if unc:
        probs.append(f"uncovered venues: {dict(unc)}")
    if any(bs._TM_ADDON.search(r["title"]) for r in rows):
        probs.append("an add-on package was added as a show")
    keys = [(r["date"], r["venue"], frozenset(bs._tm_words(r["title"]))) for r in rows]
    if len(keys) != len(set(keys)):
        probs.append("duplicate rows added")
    if not (400 <= a <= 487):
        probs.append(f"against an empty feed, added {a}; expected the whole pull minus add-ons")
    if probs:
        fails += 1
        print("  FAIL ticketmaster-portland.json  " + "; ".join(probs))
    else:
        print(f"  ok   ticketmaster-portland.json  {a:3d} rows  -- Discovery API pull; tm_apply invariants (no uncovered venues, no add-ons, no dupes)")
    print()
    if fails:
        print(f"{fails} FAILURE(S)")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
