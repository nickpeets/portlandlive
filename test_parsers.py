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
    ("strum.html",              sv.parse_strum,          4, {"time": 4, "age": 4},       "HTML table; year inferred, times are PM, workshops and package rows skipped"),
    # Sep 17 2026 batch -- structured feeds captured from the Codespace on 2026-09-16 Pacific.
    ("wilfs-tribe.json",        sv.parse_wilfs,          37, {"time": 37, "imageUrl": 37, "age": 7}, "Events Calendar REST; jazz nightly; Closed-for-holiday rows skipped"),
    ("stoller-tribe.json",      sv.parse_stoller_newberg, 21, {"time": 21, "imageUrl": 21, "contentType": 1}, "Tribe REST (categories=newberg); wine club/karaoke/trivia/cornhole/bingo skipped; 'Live Music with' stripped; Comedy Night tagged"),
    ("albertaabbey-sq.json",    sv.parse_albertaabbey,   25, {"time": 25, "imageUrl": 25, "contentType": 17}, "Squarespace JSON; wine classes and the jury game skipped; SAW parody tagged comedy"),
    ("scout-sq.json",           sv.parse_scout,          14, {"time": 14, "imageUrl": 14},  "Squarespace JSON; 'Live Music:' rows only, prefix stripped; tastings out"),
    ("ridgefieldcraft-sq.json", sv.parse_ridgefieldcraft, 12, {"time": 12, "contentType": 3}, "Squarespace JSON; 'Live Music /' stripped; comedy open mic tagged; trivia and cribbage out"),
    ("oldliberty-sq.json",      sv.parse_oldliberty,      4, {"time": 4, "contentType": 3}, "Squarespace JSON; stand-up tagged comedy; burlesque left to the classifier"),
    ("wildhare.ics",            sv.parse_wildhare,       21, {"time": 21, "age": 21},       "Google iCal; one-off bands only (trivia/bingo are RRULEs); '(OC)' stripped; UTC -> Pacific"),
    ("tigardville-sh.json",     sv.parse_tigardville,    15, {"time": 15},                  "SpotHopper; food-holiday promos skipped; duplicate DJ Tony row collapsed"),
    ("chehalemvalley-sh.json",  sv.parse_chehalemvalley,  5, {"time": 5, "imageUrl": 5},    "SpotHopper; only 'Live Music' rows, act read from the text; poster from linked.images"),
    ("curious-cw.json",         sv.parse_curious,        87, {"time": 87, "imageUrl": 87, "contentType": 87}, "Crowdwork; every date expanded; improv jams skipped; all tagged comedy"),
    ("kickstand-cw.json",       sv.parse_kickstand,      85, {"time": 85, "imageUrl": 85, "contentType": 85}, "Crowdwork; per-date name/poster overrides; jams and the writers' meetup skipped"),
    # Sep 17 2026 batch 3 -- HTML pages captured from the Codespace on 2026-09-16 Pacific.
    ("turnturnturn.html",       sv.parse_turnturnturn,   24, {"time": 22, "imageUrl": 24, "age": 22}, "hand-typed WordPress media-text blocks; date line found in any paragraph; undated weekly series skipped"),
    ("offbeat.html",            sv.parse_offbeat,        10, {"time": 10, "imageUrl": 10, "age": 10}, "Astro cards; '9/19 ' title prefix stripped; all-ages from the age-policy line"),
    ("siren.html",              sv.parse_siren,          13, {"time": 13, "imageUrl": 12, "contentType": 13}, "Weebly headings in document order: date heading, show heading, ticket button; cancelled skipped; all comedy"),
    ("walters.html",            sv.parse_walters,         9, {"time": 9, "imageUrl": 9},     "City of Hillsboro Granicus tiles; puppetry, circus and dance-only nights skipped"),
    ("chehalemcc.html",         sv.parse_chehalemcc,     11, {"time": 11, "imageUrl": 11, "contentType": 4}, "Squarespace carousel; 'October 16 & 17' makes two rows; early-bird slide skipped; comedy/vaudeville tagged"),
    ("trinity.html",            sv.parse_trinity,        17, {"time": 17, "imageUrl": 17},   "Wix Events, all three widgets from the warmup blob; worship services skipped"),
    ("corner14.html",           sv.parse_corner14,        6, {"time": 6, "imageUrl": 6},     "Wix Events warmup; trivia skipped"),
    ("bluediamond-tribe.json",  sv.parse_bluediamond,    28, {"time": 28, "imageUrl": 28, "age": 28}, "Tribe REST, per_page=100; weekly regulars dominate the listing, Fri/Sat one-offs posted nearer the date (captured 2026-09-20)"),
    ("lavernes.html",           sv.parse_lavernes,        4, {"time": 4, "age": 4, "imageUrl": 4},  "hand-typed Squarespace page: h2 title + 'Day, Month Nth | 8pm | 21+ | $' line; poster in the neighbouring image block; TICKETS button link (captured 2026-09-19)"),
    ("helium.html",             sv.parse_helium,        197, {"time": 197, "imageUrl": 197, "contentType": 197}, "JSON-LD Place.Events on the homepage; UTC -> Pacific; Special Event/Helium Presents prefixes dropped; Neon Room sets tagged; all comedy (captured 2026-09-18)"),
    ("haymaker.html",           sv.parse_haymaker,      20, {"time": 20, "imageUrl": 20}, "Squarespace event list (shared reader with No Fun); comedy nights kept for the comedy bin"),
    ("kellys-tribe.json",       sv.parse_kellys_olympian, 17, {"time": 17, "imageUrl": 17},  "Tribe REST JSON via the TLS tier (curl_cffi); JSON-LD HTML path kept as fallback"),
    ("process.html",            sv.parse_process,        6, {"time": 4, "age": 6},       "Webflow schedule; event -- artists; RA ticket links; year inferred"),
    ("realm-events.html",       sv.parse_realm,         34, {"imageUrl": 34, "age": 34}, "Elementor event list via the TLS tier; multi-night runs split per night"),
    ("barrel-room.html",        sv.parse_barrelroom,     6, {"time": 6, "imageUrl": 6},  "Eventbrite organizer page: upcomingEvents JSON; mailing-list entries skipped"),
    ("headliners-tribe.json",   sv.parse_headliners,    29, {"time": 29, "imageUrl": 29, "age": 28}, "Tribe REST page 1 (network stubbed, so no page 2); weekly karaoke/cornhole skipped"),
    ("reser-tribe.json",        sv.parse_reser,          3, {"time": 3, "imageUrl": 3},  "Tribe REST; kept by the venue's own Concert/Dance categories, not keywords"),
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
    # The 1905: Turntable Tickets pages ten performances at a time, so the
    # parser fetches page 2..N itself. Feed it the captured page 2 through a
    # stubbed _turntable_page: 20 performances are 10 nights of two sets,
    # one row a night at the first set, ALL AGES read from the description.
    p2 = load("the1905-p2.json")
    def _tt(n, today):
        if n == 2:
            return p2
        raise RuntimeError("stub: no page %d" % n)
    sv._turntable_page = _tt
    rows = sv.parse_the1905(load("the1905-p1.json"), TODAY)
    n_t = sum(1 for r in rows if r.get("time")); n_a = sum(1 for r in rows if r.get("age") == "all-ages")
    two_sets = len({(r["date"], r["title"]) for r in rows}) == len(rows)
    if len(rows) == 10 and n_t == 10 and n_a == 9 and two_sets:
        print(f"  ok   the1905-p1+p2.json           {len(rows):3d} rows  -- Turntable API via stubbed _turntable_page; one row a night at the first set")
    else:
        fails += 1
        print(f"  FAIL the1905-p1+p2.json           rows {len(rows)} != 10 or time {n_t} != 10 or all-ages {n_a} != 9 or a night doubled")
    print()
    # Wild Hare: each band links to its own Facebook event (where the poster
    # is), read from the calendar DESCRIPTION -- linked, never fetched.
    wh = sv.parse_wildhare(load("wildhare.ics"), TODAY)
    fb = sum(1 for r in wh if "facebook.com/events/" in r.get("venueUrl", ""))
    if fb == len(wh) == 21:
        print(f"  ok   wildhare.ics (links)         {fb:3d} rows  -- every band links to its Facebook event")
    else:
        fails += 1
        print(f"  FAIL wildhare.ics (links)         {fb} of {len(wh)} rows link to a Facebook event; expected 21 of 21")
    print()
    # Show time, not doors (Sep 17 2026): the helpers, then Bunk Bar, whose
    # structured start is doors while the card says "Doors: 7pm Show: 8pm".
    probs = []
    for txt, want in [("6pm doors, 7pm show", "7:00 PM"), ("Doors: 7PM / Show: 8PM", "8:00 PM"),
                      ("7:30pm doors, 8pm show", "8:00 PM"), ("6-9pm", "6:00 PM"), ("8pm", "8:00 PM"),
                      ("5:30-7:30pm", "5:30 PM"), ("Show at 9 p.m.", "9:00 PM")]:
        if sv.start_time(txt) != want:
            probs.append(f"start_time({txt!r}) = {sv.start_time(txt)!r}, want {want!r}")
    bb = {r["title"]: r["time"] for r in sv.parse_bunkbar(load("bunkbar.html"), TODAY)}
    if bb.get("Sean Rowe") != "8:00 PM":
        probs.append(f"Bunk Bar Sean Rowe time {bb.get('Sean Rowe')!r}, want '8:00 PM' (show, not doors)")
    if probs:
        fails += 1
        print("  FAIL show-time helpers            " + "; ".join(probs))
    else:
        print("  ok   show-time helpers             7 cases + Bunk Bar -- show time wins over doors; range reads its start")
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
    # Show time, not doors: 7 of these 10 cards read "7:30pm doors, 8pm show".
    doors_taken = sum(1 for r in rows if r.get("time") in ("7:30 PM", "5:30 PM", "8:30 PM") )
    if len(rows) == 10 and n_t == 10 and n_a == 8 and doors_taken == 0:
        print(f"  ok   mcmenamins-scroll-10.html    {len(rows):3d} rows  -- getScrollEvents fragment via stubbed session; age from card text; show time not doors")
    else:
        fails += 1
        print(f"  FAIL mcmenamins-scroll-10.html    rows {len(rows)} != 10 or time {n_t} != 10 or age {n_a} != 8 or {doors_taken} rows took the doors time")
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
    # Vivid Seats catalog matcher (build_shows.vivid_index) against a saved
    # 400-row sample of the Impact feed (header + Portland-area rows). Pins
    # the column mapping (Text1 venue, Text3 address, Money2 price, date
    # inside the tracked URL) and the venue-name map.
    feed = load("vivid-feed-sample.txt")
    idx = bs.vivid_index(feed, {"Revolution Hall", "Keller Auditorium", "Crystal Ballroom", "Dante's", "Star Theater", "Hops Ballpark", "Al's Den", "Moda Center"})
    hit = (idx.get(("Keller Auditorium", "2026-09-17")) or [None])[0]
    probs = []
    if len(idx) < 40:
        probs.append(f"only {len(idx)} (venue,date) entries; expected 40+ from the sample")
    if not hit or "vivid-seats.pxf.io/c/4969747/" not in hit[0]:
        probs.append("Keller 2026-09-17 (Dan and Phil) not indexed with a tracked link")
    # Two shows one night: the listing follows the title, not the price.
    two = {("Helium Comedy Club", "2026-09-17"): [("u-kev", "40", "kev herrera"), ("u-kelsey", "58", "kelsey cook")]}
    rows = [{"venue": "Helium Comedy Club", "date": "2026-09-17", "title": "Kelsey Cook"},
            {"venue": "Helium Comedy Club", "date": "2026-09-17", "title": "Somebody Else"}]
    bs.vivid_apply(rows, two)
    if rows[0].get("resaleUrl") != "u-kelsey" or rows[1].get("resaleUrl"):
        probs.append("two-show night: Kelsey Cook should get u-kelsey and an unmatched title nothing")
    # Resale-only Ticketmaster links give way to the venue's own page.
    rz = [{"venue": "Crystal Ballroom", "venueUrl": "https://www.crystalballroompdx.com/events/x"},
          {"venue": "Crystal Ballroom", "venueUrl": "https://www.ticketmaster.com/event/Z7r9jZ1AAZ8Gt", "ticketUrl": "https://www.ticketmaster.com/event/Z7r9jZ1AAZ8Gt"},
          {"venue": "Helium Comedy Club", "venueUrl": "https://www.ticketmaster.com/event/Z7r9jZ1A70Af6", "ticketUrl": "https://www.ticketmaster.com/event/Z7r9jZ1A70Af6"},
          {"venue": "Star Theater", "venueUrl": "https://www.ticketweb.com/event/1", "ticketUrl": "https://www.ticketweb.com/event/1"}]
    nfix = bs.tm_resale_links(rz)
    if nfix != 2 or rz[1]["venueUrl"] != "https://www.crystalballroompdx.com/" or rz[1]["ticketUrl"] or rz[2]["venueUrl"] != "https://portland.heliumcomedy.com/" or rz[3]["ticketUrl"] != "https://www.ticketweb.com/event/1":
        probs.append(f"resale links: fixed {nfix}, crystal -> {rz[1]['venueUrl']}, helium -> {rz[2]['venueUrl']}")
    if not any(k[0] == "Dante's" for k in idx) or not any(k[0] == "Hops Ballpark" for k in idx):
        probs.append("venue-name map failed (Dantes -> Dante's, Hillsboro Ballpark -> Hops Ballpark)")
    if probs:
        fails += 1
        print("  FAIL vivid-feed-sample.txt        " + "; ".join(probs))
    else:
        print(f"  ok   vivid-feed-sample.txt        {len(idx):3d} events -- Impact catalog: per-venue/date listings; title picks on a two-show night; resale-only TM links replaced")
    print()
    # festivals.json: every lineup entry becomes a feed row titled
    # "Artist -- Festival" at its real venue, tagged with the festival slug.
    frows = bs.festival_rows()
    fsum = bs.festival_summaries(frows)
    bad = [r for r in frows if not (r.get("festival") and " \u2014 " in r.get("title","") and r.get("venue") and r.get("date"))]
    if frows and not bad and fsum and all(f.get("slug") and f.get("name") and f.get("start") for f in fsum):
        print(f"  ok   festivals.json               {len(frows):3d} sets  -- {len(fsum)} festival(s); rows titled 'Artist \u2014 Festival', tagged by slug")
    else:
        fails += 1
        print(f"  FAIL festivals.json               {len(frows)} rows, {len(bad)} malformed, summaries {fsum}")
    print()
    # PAM watcher: nothing on a real capture (their calendar is films and
    # lectures), but a concert must still be caught. Both halves are the
    # test -- a filter that only ever returns nothing is not working, it is
    # just quiet.
    pam_raw = load("pam-tribe.json")
    live = sv.parse_pam(pam_raw, TODAY)
    import json as _json
    _d = _json.loads(pam_raw)
    _d["events"] = _d["events"][:4] + [
        {"title": "Summer Tour w/ Garcia Birthday Band", "start_date": "2026-10-02 19:00:00", "all_day": False,
         "description": "<p>The band performs live.</p>", "venue": {"venue": "PAM CUT&#8217;s Tomorrow Theater"}},
        {"title": "The Mummy (4K Restoration)", "start_date": "2026-10-03 19:00:00", "all_day": False,
         "description": "<p>A film screening with live score discussion.</p>", "venue": {"venue": "PAM CUT&#8217;s Tomorrow Theater"}},
        {"title": "Here We Are: A PAM Highlights Tour", "start_date": "2026-10-04 14:00:00", "all_day": False,
         "description": "<p>Explore highlights.</p>", "venue": {"venue": "Portland Art Museum"}}]
    _d["next_rest_url"] = None
    seeded = sv.parse_pam(_json.dumps(_d), TODAY)
    if not live and len(seeded) == 1 and seeded[0]["venue"] == "Tomorrow Theater":
        print("  ok   pam-tribe.json                 0 rows  -- watcher: nothing on the real calendar; a seeded concert is caught, a film and a tour are not")
    else:
        fails += 1
        print(f"  FAIL pam-tribe.json               live {len(live)} (want 0), seeded {[r['title'] for r in seeded]} (want the concert only)")
    print()
    if fails:
        print(f"{fails} FAILURE(S)")
        sys.exit(1)
    print("ALL PASS")

    # Not-a-show gate (Sep 20 2026): drop words lose to music words.
    _nas = [("Beaumont Cribbage Club", True), ("New England Patriots", True), ("Mission Theater History & Art Tour", True),
            ("Intermediate Two-Step Lessons with Peggy and Dillon", True), ("Science On Tap – Recycle! …or Not?", True), ("Flipside, Vegan Market", True),
            ("Square Dancing with Calling Lessons from Bex Bee and Boondoggle String Band", False), ("Waylon Wyatt – Dustpiles World Tour", False),
            ("Open Jam and Games", False), ("Sea Shanty Sing Along", False), ("PJCE Happy Hour Jazz w/ Christopher Brown Trio", False), ("Oktoberfest", False)]
    _bad = [f"{ti!r} -> {bs.is_not_a_show(ti)}" for ti, want in _nas if bs.is_not_a_show(ti) != want]
    if _bad:
        fails += 1
        print("  FAIL not-a-show gate              " + "; ".join(_bad))
    else:
        print("  ok   not-a-show gate               12 titles -- trivia/cribbage/sports/markets/tours/lessons out; anything with a music word stays")
    print()

if __name__ == "__main__":
    main()
