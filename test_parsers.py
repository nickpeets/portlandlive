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
import re
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
sv.SD_RETRY_PAUSE_S = 0
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
    ("den-events.json",        sv.parse_den,            20, {"time": 20, "imageUrl": 20, "ticketUrl": 15, "age": 18}, "Squarespace events JSON; genre tag dropped; Eventim tickets; 21+ from the body"),
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
    ("swandive-sq.json",        sv.parse_swandive,       22, {"time": 22, "imageUrl": 22},          "Squarespace events at /events-2-1 (captured 2026-09-21)"),
    ("vinoveritas-sq.json",     sv.parse_vinoveritas,     0, {},                                    "Squarespace events at /events; nothing upcoming at capture (2026-09-21)"),
    ("firkin-tribe.json",       sv.parse_firkin,          0, {},                                    "Tribe REST; empty at capture (2026-09-21)"),
    ("lyonsden-sq.json",        sv.parse_lyonsden,        2, {"time": 2},                         "Squarespace events (captured 2026-09-21)"),
    ("birchstreet.html",        sv.parse_birchstreet,     9, {"time": 9},                         "hand-typed lineup page (captured 2026-09-21)"),
    ("montavilla.html",         sv.parse_montavilla,      1, {},                                  "homepage lineup ends 9/19; suite clock 9/14"),
    ("winona.ics",              sv.parse_winona,          3, {"time": 3},                         "Events Manager ics, allow-list keeps ceili + square dances (captured 2026-09-21)"),
    ("cascade-mcdonald-theatre.html",      sv.parse_mcdonald,   20, {"time": 20, "imageUrl": 20, "age": 20}, "Cascade Tickets RHP page (captured 2026-09-21)"),
    ("cascade-cuthbert-amphitheater.html", sv.parse_cuthbert,    2, {"time": 2},                         "Cascade Tickets RHP page, season's tail (captured 2026-09-21)"),
    ("cascade-mcmenamins-lolas-room.html", sv.parse_lolasroom,   5, {"time": 5, "age": 5},               "Cascade Tickets RHP page (captured 2026-09-21)"),
    ("wowhall-tribe.json",      sv.parse_wowhall,        23, {"time": 23, "imageUrl": 23},       "Tribe REST; classes, meetings and talks dropped (captured 2026-09-21)"),
    ("lavernes.html",           sv.parse_lavernes,        5, {"time": 5, "age": 5, "imageUrl": 5},  "hand-typed Squarespace page (past rows returned too since Sep 25 2026; the loop drops them): h2 title + 'Day, Month Nth | 8pm | 21+ | $' line; poster in the neighbouring image block; TICKETS button link (captured 2026-09-19)"),
    ("helium.html",             sv.parse_helium,        197, {"time": 197, "imageUrl": 197, "contentType": 197}, "JSON-LD Place.Events on the homepage; UTC -> Pacific; Special Event/Helium Presents prefixes dropped; Neon Room sets tagged; all comedy (captured 2026-09-18)"),
    ("haymaker.html",           sv.parse_haymaker,      20, {"time": 20, "imageUrl": 20}, "Squarespace event list (shared reader with No Fun); comedy nights kept for the comedy bin"),
    ("kellys-shows.html",      sv.parse_kellys_olympian, 20, {"time": 20, "imageUrl": 20}, "rebuilt site Oct 27 2026: /shows articles, no year (inferred); postponed skipped; Eventbrite ticketUrl; captured 2026-10-28"),
    ("process.html",            sv.parse_process,        6, {"time": 4, "age": 6},       "Webflow schedule; event -- artists; RA ticket links; year inferred"),
    ("realm-events.html",       sv.parse_realm,         34, {"imageUrl": 34, "age": 34}, "Elementor event list via the TLS tier; multi-night runs split per night"),
    ("barrel-room.html",        sv.parse_barrelroom,     6, {"time": 6, "imageUrl": 6},  "Eventbrite organizer page: upcomingEvents JSON; mailing-list entries skipped"),
    ("headliners-tribe.json",   sv.parse_headliners,    29, {"time": 29, "imageUrl": 29, "age": 28}, "Tribe REST page 1 (network stubbed, so no page 2); weekly karaoke/cornhole skipped"),
    ("reser-tribe.json",        sv.parse_reser,          3, {"time": 3, "imageUrl": 3},  "Tribe REST; kept by the venue's own Concert/Dance categories, not keywords"),
    ("armory-sq.json",          sv.parse_armory,         4, {"time": 4, "imageUrl": 4, "age": 4}, "Squarespace events; age from the body, not the 21+ bar line (captured 2026-09-29)"),
    ("talentclub.html",         sv.parse_talentclub,    16, {"time": 16, "imageUrl": 16, "age": 16, "contentType": 2}, "Elementor loop; venue's own live-music/comedy categories; room is 21+ (captured 2026-09-29)"),
    ("britt-events.html",       sv.parse_britt,          1, {"time": 1, "imageUrl": 1},  "Pavilion tiles only, grid+calendar deduped, year inferred; off-site events dropped (captured 2026-09-29)"),
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
    ("britt-event.html", "one britt.org show page (Jim Gaffigan); _britt_is_comedy() reads it -- checked below"),
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
    # Britt: comedy is read from each show's own page (fetched live; the
    # network is stubbed here, so check the reader on the captured page).
    if sv._britt_is_comedy(load("britt-event.html")) and not sv._britt_is_comedy(load("talentclub.html")):
        print("  ok   britt-event.html              comedy read from the show page (and not from a music page)")
    else:
        fails += 1
        print("  FAIL britt-event.html              _britt_is_comedy() misread the captured pages")
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
    # Sep 24 2026: ages and prices from the one-line subtitle. The four 1 PM
    # matinees say ALL AGES; evenings say nothing, so they must stay unknown.
    ages = [(r["time"], r.get("age", "")) for r in rows if r.get("age")]
    matinee_ages = all(t == "1:00 PM" and a == "all-ages" for t, a in ages) and len(ages) == 4
    prices = sum(1 for r in rows if r.get("price"))
    door = any(r.get("price") == "$10 adv / $15 door" for r in rows)
    if len(rows) == 28 and imgs == 22 and matinee_ages and prices == 28 and door:
        print(f"  ok   laurelthirst-sept2026.html   {len(rows):3d} rows  -- EventON month via stubbed _laurel_month; poster from description img; 1 PM matinees all ages, price from the subtitle")
    else:
        fails += 1
        print(f"  FAIL laurelthirst-sept2026.html   rows {len(rows)} != 28 or imageUrl {imgs} != 22 or ages {ages} or prices {prices} != 28 or adv/door {door}")
    print()
    # Jack London (Oct 15 2026): the calendar page is an empty shell that
    # POSTs admin-ajax per month. Check the nonce/params come out of the real
    # shell, and that the month walk feeds the TicketWeb reader (stubbed with
    # the old full page for the first month).
    shell = load("jlr-calendar-shell.html")
    args = sv._jlr_args(shell)
    calls = []
    def _stub(start, end, nonce, params, mv):
        calls.append(start)
        return load("jlr.html") if len(calls) == 1 else ""
    sv._jlr_post = _stub
    rows = sv.parse_jlr(shell, TODAY)
    ok = (args and args[0] and '"type":"calendar2"' in args[1] and len(calls) == 4
          and calls[0] == "2026-9-14 00:00:00" and len(rows) == 56)
    if ok:
        print(f"  ok   jlr-calendar-shell.html      {len(rows):3d} rows  -- nonce + params from the shell; 4 month POSTs to the horizon; TicketWeb reader on the response")
    else:
        fails += 1
        print(f"  FAIL jlr-calendar-shell.html     args {bool(args)} calls {calls} rows {len(rows)}")
    print()
    # Singacoustic (Oct 11 2026): EventPrime. The REST list is ids + titles;
    # the reader fetches each show's own page and the venue's Eventbrite
    # organizer page itself, so both are stubbed with the captured copies.
    # Run as of the capture day -- its dates are a month past the suite's.
    _pages = dict(re.findall(r"<!-- singacoustic event (\d+) -->\n(.*?)\n(?=<!-- singacoustic event |\Z)", load("singacoustic-events.html"), re.S))
    sv._SING_PAUSE_S = 0
    sv._singacoustic_page = lambda eid: _pages[str(eid)]
    sv._singacoustic_eventbrite = lambda: load("singacoustic-eventbrite.html")
    rows = sv.parse_singacoustic(load("singacoustic-rest.json"), datetime.date(2026, 10, 11))
    by = {r["title"]: r for r in rows}
    want = {"Nathan Stanley: A Tribute to Dr. Ralph Stanley": ("2026-10-27", "7:30 PM", "$33.85"),          # page says 07:30 AM
            "Rooster Blackspur: Folk, Roots & Americana": ("2026-10-14", "7:30 PM", "$25 adv / $30 door"),
            "Christmas on Six Strings: Terry Robb & Adam Scramstad": ("2026-12-12", "7:30 PM", "$25 adv / $30 door"),
            "A Conversation in Keys & Strings: Ernie Votto & Bill Mitchell": ("2026-10-15", "7:30 PM", "Free"),
            "The Art of the Protest Song": ("2026-10-22", "7:00 PM", "$10 donation"),
            "Phoenix: Songs of Renewal & Americana": ("2026-11-14", "7:30 PM", "By donation"),
            "Singacoustic Open Mic": ("2026-10-13", "7:00 PM", "Free")}                                       # Eventbrite only
    bad = [t for t, w in want.items() if (by.get(t, {}).get("date"), by.get(t, {}).get("time"), by.get(t, {}).get("price")) != w]
    n = lambda f: sum(1 for r in rows if (r.get(f) or "").strip())
    ages = {r["title"][:12]: r["age"] for r in rows if r.get("age")}
    sv._singacoustic_eventbrite = lambda: ""
    alone = sv.parse_singacoustic(load("singacoustic-rest.json"), datetime.date(2026, 10, 11))
    blank = [r["time"] for r in alone if r["title"].startswith("Nathan Stanley")]
    if (len(rows) == 12 and not bad and n("time") == 12 and n("imageUrl") == 12 and n("price") == 12 and n("ticketUrl") == 9
            and ages == {"Bryan Bowers": "all-ages"} and len(alone) == 11 and blank == [""] and sum(1 for r in alone if r["time"]) == 10):
        print(f"  ok   singacoustic-events.html     {len(rows):3d} rows  -- EventPrime show pages + Eventbrite extras via stubs; 07:30 AM typo takes Eventbrite's time, blank without it; prices from the page's own words")
    else:
        fails += 1
        print(f"  FAIL singacoustic-events.html     rows {len(rows)} (want 12), wrong {bad}, time {n('time')}, imageUrl {n('imageUrl')}, price {n('price')}, ticketUrl {n('ticketUrl')}, ages {ages}, alone {len(alone)}, Nathan without Eventbrite {blank}")
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
    # Fold: Crystal lists the Friday as "Portland's Folk Festival"; the feed
    # must carry ONE row that night -- the set -- with Crystal's ticket link.
    _pf = [r for r in frows if r.get("festival") == "portlands-folk-festival-2027" and r["date"] == "2027-01-29"]
    _feed = [{"title": "Portland's Folk Festival", "venue": "Crystal Ballroom", "date": "2027-01-29",
              "time": "6:00 PM", "ticketUrl": "https://www.etix.com/x"},
             {"title": "Mike D", "venue": "Crystal Ballroom", "date": "2027-01-29"}]
    bs.festival_apply(_feed)
    _night = [r for r in _feed if r["venue"] == "Crystal Ballroom" and r["date"] == "2027-01-29"]
    _set = [r for r in _night if r.get("festival") == "portlands-folk-festival-2027"]
    if _pf and len(_night) == 2 and len(_set) == 1 and _set[0].get("ticketUrl") == "https://www.etix.com/x" \
            and _set[0]["title"] == _pf[0]["title"] and any(r["title"] == "Mike D" for r in _night):
        print("  ok   festival fold                  venue row named for the festival folds into the set (slug kept, ticket link borrowed); other shows that night untouched")
    else:
        fails += 1
        print(f"  FAIL festival fold                  {_night}")
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
            ("Open Jam and Games", False), ("Sea Shanty Sing Along", False), ("PJCE Happy Hour Jazz w/ Christopher Brown Trio", False), ("Oktoberfest", True),
            ("10th Annual Kennedy School Oktoberfest Brewfest", True), ("Oktoberfest with The Polka Kings", False),
            ("Oktoberfest: Alpine Dave & the Lederhosen", False), ("Octoberfest Music Festival", True),
            ("OMSI Science Pub: Smoke and Mirrors OMSI Science Pub", True), ("OMSI Science Pub", True)]
    _bad = [f"{ti!r} -> {bs.is_not_a_show(ti)}" for ti, want in _nas if bs.is_not_a_show(ti) != want]
    if _bad:
        fails += 1
        print("  FAIL not-a-show gate              " + "; ".join(_bad))
        # A gate failure used to print after "ALL PASS" and still exit 0, so
        # the paste blocks' grep for ALL PASS let it through (Sep 22 2026).
        print("GATE FAILURE")
        import sys as _sys; _sys.exit(1)
    else:
        print("  ok   not-a-show gate               18 titles -- trivia/cribbage/sports/markets/tours/lessons out; anything with a music word stays; beer fests only with a named act")
    print()

def talk_page_check():
    """Alberta Rose event pages (Sep 22 2026): an author talk reads as a talk."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "alberta-rose-event.html")
    if not os.path.exists(path):
        print("  --   alberta-rose-event.html       (fixture not present; skipped)")
        return
    kind = sv._page_kind(open(path, encoding="utf-8", errors="replace").read(), "Consider This with Stephanie Land")
    if kind != "other":
        print(f"  FAIL alberta-rose-event.html       Consider This with Stephanie Land -> {kind!r} (want 'other')")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   alberta-rose-event.html       author talk (Oregon Humanities, Stephanie Land) read as a talk")


def multi_time_check():
    """Early and late shows (Sep 22 2026): Helium's 9:30 must survive dedupe."""
    bspec = importlib.util.spec_from_file_location("bs", os.path.join(HERE, "build_shows.py"))
    bs = importlib.util.module_from_spec(bspec)
    bspec.loader.exec_module(bs)
    rows = [dict(title="Mark Normand", venue="Helium Comedy Club", date="2026-10-24", time=t) for t in ("4:00 PM", "7:00 PM", "9:30 PM")]
    rows += [dict(title="Band X", venue="V", date="2026-10-01", time="8:00 PM"), dict(title="Band X", venue="V", date="2026-10-01", time="7:30 PM")]
    d, c = bs.dedupe_shows(rows)
    by = {r["title"]: r for r in d}
    ok = (len(d) == 2 and by["Mark Normand"].get("times") == ["4:00 PM", "7:00 PM", "9:30 PM"]
          and by["Mark Normand"]["time"] == "4:00 PM" and "times" not in by["Band X"] and len(c) == 1)
    if not ok:
        print(f"  FAIL multi-show nights           {[(r['title'], r.get('time'), r.get('times')) for r in d]} collisions={c}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   multi-show nights             4:00/7:00/9:30 kept on one row; 7:30 vs 8:00 (doors vs show) stays one time")


def submission_fold_check():
    """Submissions (Sep 22 2026): "The Starday Tavern" is our Starday Tavern,
    and a same-night look-alike folds into the listing we already have."""
    bspec = importlib.util.spec_from_file_location("bs", os.path.join(HERE, "build_shows.py"))
    bs = importlib.util.module_from_spec(bspec)
    bspec.loader.exec_module(bs)
    shows = [dict(title="James T & Friends", venue="Starday Tavern", neighborhood="Brentwood-Darlington", address="6517 SE Foster Rd",
                  date="2026-10-20", time="6:00 PM", venueUrl="", age="21+")]
    subs = [dict(title="James T's Treasure Chest", venue="The Starday Tavern", neighborhood="FoPo", address="6517 SE Foster Rd",
                 date="2026-10-20", time="6:00 PM", venueUrl="https://facebook.com/events/x", age="21+", _submitted=True),
            dict(title="Late Band", venue="the starday tavern", neighborhood="", address="", date="2026-10-20", time="9:30 PM",
                 venueUrl="", age="", _submitted=True)]
    out = bs.fold_submissions(shows, subs, venue_info={"Starday Tavern": ("Brentwood-Darlington", "6517 SE Foster Rd")})
    ok = (len(out) == 2 and out[0]["title"] == "James T & Friends" and out[0]["venueUrl"] == "https://facebook.com/events/x"
          and out[1]["venue"] == "Starday Tavern" and out[1]["neighborhood"] == "Brentwood-Darlington")
    if not ok:
        print(f"  FAIL submission fold               {[(r['title'], r['venue'], r.get('neighborhood')) for r in out]}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   submission fold               The Starday Tavern -> Starday Tavern; same-night look-alike folded; 9:30 show kept")


def tm_same_act_check():
    """Ticketmaster (Sep 22 2026): same venue, same date, same act -- one row,
    even when the two titles share only the band's name."""
    bspec = importlib.util.spec_from_file_location("bs", os.path.join(HERE, "build_shows.py"))
    bs = importlib.util.module_from_spec(bspec)
    bspec.loader.exec_module(bs)
    import datetime as _dt
    shows = [dict(title="Everything Everything - Get To Heaven, 10th Anniversary, North America 2026", venue="Aladdin Theater",
                  date="2026-09-22", time="8:00 PM", imageUrl="", ticketUrl="")]
    ev = {"name": "Everything Everything w/ Psymon Spine", "dates": {"start": {"localDate": "2026-09-22", "localTime": "20:00:00"}, "status": {"code": "onsale"}},
          "url": "https://www.ticketmaster.com/event/x", "images": [{"url": "https://s1.ticketm.net/x.jpg", "width": 1024, "ratio": "16_9"}],
          "_embedded": {"venues": [{"name": "Aladdin Theater", "city": {"name": "Portland"}, "state": {"stateCode": "OR"}}]}}
    matched, added, _ = bs.tm_apply(shows, [ev], _dt.date(2026, 9, 20))
    # ...but an early/late pair stays two shows.
    shows2 = [dict(title="Ron Funches", venue="Revolution Hall", date="2026-11-15", time="7:00 PM", imageUrl="", ticketUrl="")]
    ev2 = {"name": "Ron Funches (Late Show)", "dates": {"start": {"localDate": "2026-11-15", "localTime": "21:30:00"}, "status": {"code": "onsale"}},
           "url": "https://www.ticketmaster.com/event/y", "images": [],
           "_embedded": {"venues": [{"name": "Revolution Hall - Portland", "city": {"name": "Portland"}, "state": {"stateCode": "OR"}}]}}
    m2, a2, _ = bs.tm_apply(shows2, [ev2], _dt.date(2026, 9, 20))
    # The final dedupe folds same-act twins the same way (Wilfs listed
    # Norman Sylvester twice) and still keeps an early/late pair apart.
    tw, _c = bs.dedupe_shows([dict(title="Norman Sylvester Band", venue="Wilfs", date="2026-12-19", time="7:00 PM"),
                              dict(title="Norman Sylvester Band w/ Lenanne Miller", venue="Wilfs", date="2026-12-19", time="7:00 PM"),
                              dict(title="ALOK (Early Show)", venue="Revolution Hall", date="2026-09-26", time="7:00 PM"),
                              dict(title="ALOK (Late Show)", venue="Revolution Hall", date="2026-09-26", time="10:00 PM"),
                              # Oct 14 2026: an en dash is a separator too.
                              dict(title="GLAIVE \u2013 GOD SAVE THE THREE TOUR", venue="Wonder Ballroom", date="2026-10-14", time="8:00 PM"),
                              dict(title="glaive w/ Tiffany Day", venue="Wonder Ballroom", date="2026-10-14", time="8:00 PM")])
    if len(tw) != 4:
        print(f"  FAIL tm same act                  final dedupe gave {[r['title'] for r in tw]}")
        print("GATE FAILURE")
        sys.exit(1)
    if not (len(shows) == 1 and added == 0 and matched == 1 and a2 == 1):
        print(f"  FAIL tm same act                  rows={[r['title'] for r in shows]} matched={matched} added={added} late_added={a2}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   tm same act                   Everything Everything + TM's w/ Psymon Spine -> one row; Wilfs twins -> one; glaive en-dash twins -> one; early/late pairs kept")


def tm_guard_check():
    """Ticketmaster safety net (Sep 23 2026): a failed or shrunken pull keeps
    the last good pull's shows instead of dropping them."""
    import datetime as _dt, tempfile
    bspec = importlib.util.spec_from_file_location("bs", os.path.join(HERE, "build_shows.py"))
    bs = importlib.util.module_from_spec(bspec)
    bspec.loader.exec_module(bs)
    today = _dt.date(2026, 9, 23)
    ev = lambda i: {"id": f"e{i}", "name": f"Show {i}", "dates": {"start": {"localDate": "2026-10-06"}}, "images": [],
                    "_embedded": {"venues": [{"name": "Moda Center"}]}}
    path = os.path.join(tempfile.mkdtemp(), "tm_cache.json")
    pulls = [("portland|music", {})]
    good = lambda t, status=None, **k: [ev(i) for i in range(50)]
    short = lambda t, status=None, **k: [ev(i) for i in range(10)]
    def failed(t, status=None, **k):
        status["failed"] = True
        return []
    a = len(bs.tm_fetch_guarded(today, pulls, path, good))
    b = len(bs.tm_fetch_guarded(today, pulls, path, short))
    c = len(bs.tm_fetch_guarded(today, pulls, path, failed))
    if (a, b, c) != (50, 50, 50):
        print(f"  FAIL tm guard                     good/short/failed gave {a}/{b}/{c} (want 50/50/50)")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   tm guard                      a short pull (10 of 50) and a failed pull both keep the last good 50")


def batch_four_check():
    """Batch four readers (Sep 23 2026) against their captured pages: each
    keeps at least what the capture showed, and the traps stay closed
    (Elks bingo nights out, Cazadero's band "Exit 52" not read as a date,
    Beach Hut's "7-10pm" jam read as 7 PM)."""
    import datetime as _dt
    today = _dt.date(2026, 9, 23)
    d = os.path.join(HERE, "fixtures", "intake")
    want = [("elks823-rest.json", sv.parse_elks823, 8), ("hoku-events.json", sv.parse_hoku, 18),
            ("cazadero-events.html", sv.parse_cazadero, 12), ("hopworks-music.html", sv.parse_hopworks, 15),
            ("threshold-doc.html", sv.parse_threshold, 20), ("beachhut-tigard.html", sv.parse_beachhut, 4)]
    bad = []
    rows = {}
    for fx, fn, n in want:
        r = fn(open(os.path.join(d, fx), encoding="utf-8").read(), today)
        rows[fx] = r
        if len(r) < n:
            bad.append(f"{fx}: {len(r)} < {n}")
    if any("ingo" in r["title"] for r in rows["elks823-rest.json"]):
        bad.append("elks: a bingo night got through")
    if not any(r["title"] == "Exit 52" for r in rows["cazadero-events.html"]):
        bad.append("cazadero: Exit 52 (Oct 3) missing")
    if sum(1 for r in rows["hopworks-music.html"] if r.get("imageUrl")) < 8:
        bad.append("hopworks: posters missing")
    if not any(r["time"] == "7:00 PM" and "Jam" in r["title"] for r in rows["beachhut-tigard.html"]):
        bad.append("beach hut: jam night time wrong")
    if bad:
        print("  FAIL batch four                   " + "; ".join(bad))
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   batch four                    Elks, Hoku, Cazadero, Hopworks, Threshold, Beach Hut read from their captures")


def safety_net_check():
    """The venue safety net (Sep 24 2026: The Goodfoot lost all 39 shows when
    five builds in one afternoon used up a 5-run retention)."""
    import datetime as _dt
    t = _dt.date(2026, 9, 24)
    row = lambda v, d, title: {"venue": v, "date": d, "title": title}
    prev = [row("The Goodfoot", "2026-09-26", f"Band {i}") for i in range(39)] \
         + [row("Big Room", "2026-10-0%d" % (i % 9 + 1), f"Act {i}") for i in range(20)] \
         + [row("Oregon Zoo", "2026-10-01", "Zoo Lights")] \
         + [row("Old Room", "2026-10-02", "Last Show")]
    hist = {"The Goodfoot": [39] * 5 + [0] * 5, "Big Room": [20] * 10, "Oregon Zoo": [0] * 10, "Old Room": [5] * 5 + [0] * 5}
    today = [row("Big Room", "2026-10-01", "Act 0"), row("Big Room", "2026-10-02", "Act 1")]   # 2 of ~20: partial
    keep, lg, rep = sv.safety_net(today, prev, {"The Goodfoot": "2026-09-23", "Old Room": "2026-09-10"}, hist, t)
    kv = {}
    for r in keep:
        kv[r["venue"]] = kv.get(r["venue"], 0) + 1
    ok = (kv.get("The Goodfoot") == 39 and kv.get("Big Room") == 18 and kv.get("Oregon Zoo") == 1
          and "Old Room" in rep["expired"] and "Old Room" not in kv and lg.get("Big Room") == "2026-09-24")
    if not ok:
        print(f"  FAIL safety net                   kept={kv} report={rep}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   safety net                    Goodfoot 0 -> kept 39; Big Room 2 of ~20 -> 18 added back; hand-added zoo kept; 14-day-dead room expired")
    # Feed health: the same run as data for the moderator menu.
    h = sv.net_health(rep, dict(lg, **{"Gone Room": "2026-09-01", "Ancient Room": "2026-07-01"}), today, t,
                      [("Empty Source", "page loaded, 0 events")])
    k = {i["venue"]: i for i in h["items"]}
    ok = (k.get("The Goodfoot", {}).get("kind") == "zero" and k["The Goodfoot"]["shown"] == 39
          and k["The Goodfoot"]["drops"] == "2026-10-01"
          and k.get("Big Room", {}).get("kind") == "partial" and k["Big Room"]["added"] == 18
          and k.get("Old Room", {}).get("kind") == "expired"
          and k.get("Gone Room", {}).get("kind") == "dark" and "Ancient Room" not in k
          and k.get("Empty Source", {}).get("kind") == "empty" and h["checked"] == "2026-09-24")
    if not ok:
        print(f"  FAIL feed health                  {h}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   feed health                   held (0 and partial), expired, dark 23 days, empty source -> report; 85-day-dark room dropped off")
    import json
    # TLS fallbacks (Sep 25 2026): a challenged Chrome handshake tries Safari,
    # then a browser; a may_be_empty source stops after the handshakes.
    import fetch_headless as _fh
    calls = []
    def _tls(url, timeout=30, impersonate="chrome"):
        calls.append(impersonate)
        raise sv.ChallengeError("challenge signature 'Just a moment'")
    _real_tls, _real_hj = sv.fetch_tls, _fh.fetch_headless_json
    sv.fetch_tls = _tls
    _fh.fetch_headless_json = lambda home, url, headed=False: {"events": [1, 2]}
    try:
        src = {"name": "Kelly's (test)", "parser": lambda t, d: json.loads(t)["events"] if t else []}
        got = sv.tls_rows(src, "https://x.example/wp-json/tribe/events/v1/events", datetime.date(2026, 9, 25))
        quiet = sv.tls_rows(dict(src, may_be_empty=True), "https://x.example/wp-json/tribe/events/v1/events", datetime.date(2026, 9, 25))
    finally:
        sv.fetch_tls, _fh.fetch_headless_json = _real_tls, _real_hj
    h2 = sv.net_health({"zero": {"Realm": (28, 1)}}, {"Realm": "2026-09-24"}, [], datetime.date(2026, 9, 25),
                       [("Realm (realmpdx.com)", "fetched OK but the parser found no events")])
    if got != [1, 2] or quiet != [] or calls != ["chrome", "safari", "chrome", "safari"] or len(h2["items"]) != 1:
        print(f"  FAIL tls fallback                 got {got} quiet {quiet} calls {calls} health {h2}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   tls fallback                  challenged chrome -> safari -> browser; quiet source stops at the handshakes; one health line per venue")
    # Sold out (Sep 25 2026): only the venue's own structured signals count.
    _d = datetime.date(2026, 9, 14)
    _fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
    got = {}
    for f, fn in (("roseland.html", sv.parse_mammoth), ("hawthorne-events.html", sv.parse_mammoth), ("holocene.html", sv.parse_holocene), ("mississippi-studios.html", sv.parse_msstudios)):
        h = open(os.path.join(_fx, f), encoding="utf-8").read()
        rows = fn(h, _d); sv.mark_sold_out(rows, h)
        got[f] = sum(1 for r in rows if r.get("soldOut"))
    titles = [{"title": t} for t in ("SOLD OUT: Am\u00e9lie Farren", "Dean Johnson - SOLD OUT -", "Blasting Company (SOLD OUT)", "Sold Out Sessions: a showcase", "The Sold Out Tour 2026", "comic on sold-out tours")]
    sv.mark_sold_out(titles)
    tmarks = [bool(r.get("soldOut")) for r in titles]
    if got != {"roseland.html": 4, "hawthorne-events.html": 2, "holocene.html": 3, "mississippi-studios.html": 3} or tmarks != [True, True, True, False, False, False]:
        print(f"  FAIL sold out                     {got} {tmarks}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   sold out                      Roseland 4, Hawthorne 2, Holocene 3 (RHP buttons), Mississippi Studios 3 (Etix links); title markers yes, band names and bios no")
    # Holocene rebuilt (Oct 28 2026): article.crow cards, date in the link,
    # poster = base64 of the Etix 1200w URL, "At the door" = no ticket link.
    import base64 as _b64
    _poster = "https://cdn.etix.com/etix/performance-image/performance_image_1200w/4bf3d12e554e897c0d7761be5112b576.jpg"
    _enc = _b64.urlsafe_b64encode(_poster.encode()).decode().rstrip("=")
    _crow = '''<div class="crows">
    <article class="crow" data-id="63240311">
      <div class="crow-date">Tonight<b>OCT 29</b></div>
      <div class="crow-thumb"><img src="/img/150/%s" alt="" loading="eager"></div>
      <div class="crow-main"><h3 class="crow-title"><a href="/events/2026-10-29-harryween-harry-styles-halloween-dance-ni" data-event-link="">HARRYWEEN</a></h3>
      <span class="crow-more" aria-hidden="true">More info \u2192</span></div>
      <div class="crow-side"><div class="crow-meta"><span class="crow-when">9PM \u00b7 21+</span><b>$25.82</b></div>
      <a class="spec-buy" href="https://www.etix.com/ticket/p/63240311/harryween-harry-styles-halloween-dance-ni-21-portland-holocene?partner_id=100" target="_blank">Tickets \u2197</a></div>
    </article>
    <article class="crow" data-id="1">
      <div class="crow-date">SAT<b>OCT 31</b></div>
      <div class="crow-thumb"><img src="/img/150/%s" alt=""></div>
      <div class="crow-main"><h3 class="crow-title"><a href="/events/2026-10-31-betty-a-queer-dance-party">BETTY: A Queer Dance Party (HALLOWEEN EDITION)</a></h3></div>
      <div class="crow-side"><div class="crow-meta"><span class="crow-when">9PM \u00b7 21+</span></div><span class="spec-buy at-door">At the door</span></div>
    </article>
    <article class="crow" data-id="2">
      <div class="crow-date">FRI<b>NOV 06</b></div>
      <div class="crow-thumb"><img src="/img/150/%s" alt=""></div>
      <div class="crow-main"><h3 class="crow-title"><a href="/events/2026-11-06-shanghai-quitian">Shanghai Quitian</a></h3></div>
      <div class="crow-side"><div class="crow-meta"><span class="crow-when">5PM \u00b7 All Ages</span></div>
      <a class="spec-buy" href="https://www.etix.com/ticket/p/9/sold-out-shanghai">Sold out</a></div>
    </article></div>''' % (_enc, _enc, _enc)
    hr = sv.parse_holocene(_crow, datetime.date(2026, 10, 29))
    want = [("2026-10-29", "HARRYWEEN", "9:00 PM", "21+", True, False), ("2026-10-31", "BETTY: A Queer Dance Party (HALLOWEEN EDITION)", "9:00 PM", "21+", False, False),
            ("2026-11-06", "Shanghai Quitian", "5:00 PM", "All Ages", True, True)]
    gotc = [(r["date"], r["title"], r["time"], r["age"], bool(r["ticketUrl"]), bool(r.get("soldOut"))) for r in hr]
    if gotc != want or any(r["imageUrl"] != _poster for r in hr) or hr[1]["venueUrl"] != "https://www.holocene.org/events/2026-10-31-betty-a-queer-dance-party":
        print(f"  FAIL holocene crow                {hr}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   holocene crow                 rebuilt calendar: date from link, time + age, Etix tickets, decoded 1200w poster, sold out, at-the-door")
    # Failure captures (Oct 29 2026): an empty source leaves the runner's page + an index.
    import tempfile as _tf
    _old = sv.CAPTURE_DIR
    sv.CAPTURE_DIR = _tf.mkdtemp()
    sv._reset_captures(); sv._save_capture("Holocene", "<html>x</html>", "0 events"); sv._save_capture("The Goodfoot", None, "HeadlessChallengeError")
    _idx = json.load(open(os.path.join(sv.CAPTURE_DIR, "index.json")))
    _ok = (sorted(os.listdir(sv.CAPTURE_DIR)) == ["holocene.html", "index.json"] and len(_idx["sources"]) == 2
           and _idx["sources"][1]["file"] == "")
    sv._reset_captures(); _ok = _ok and os.listdir(sv.CAPTURE_DIR) == []
    sv.CAPTURE_DIR = _old
    if not _ok:
        print(f"  FAIL failure captures             {_idx}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   failure captures              empty source -> og/health/<slug>.html + index.json; cleared each run")
    # Showdown paging (Oct 30 2026 auto-repair): the runner got page one (10
    # rows, usual ~52) and the walk stopped with no reason logged. A failed
    # page now retries once, and an early stop leaves a note + page one.
    _sd = load("showdown.html")
    _calls = []
    def _sd_fail(url, *a, **k):
        _calls.append(url); raise RuntimeError("504 Gateway Timeout")
    sv.fetch = _sd_fail; sv.FETCH_NOTES.pop("Showdown Saloon", None); sv.EARLY_STOP_PAGES.clear()
    r1 = sv.parse_showdown(_sd, TODAY)
    n1 = sv.FETCH_NOTES.get("Showdown Saloon", "")
    # pager says 7 pages: 2 and 3 each tried three times, both dead -> the
    # site is down, walk stops (no 18 slow tries); noted
    _ok = (len(r1) == 10 and len(_calls) == 6 and _calls[0].endswith("/page/2/") and _calls[-1].endswith("/page/3/")
           and "1 of 7 pages" in n1 and "stopped at 3" in n1 and "504" in n1 and sv.EARLY_STOP_PAGES.get("Showdown Saloon") == _sd)
    _calls.clear()
    _p2 = _sd.replace("<", "<", 1)
    import re as _re
    _alt = _re.sub(r'(class="tw-event-date[^"]*"[^>]*>)\s*([A-Z][a-z]{2})\s+(\d{1,2})', lambda m: m.group(1) + "Dec " + m.group(3), _sd)
    def _sd_flaky(url, *a, **k):
        _calls.append(url)
        if url.endswith("/page/3/"):
            raise RuntimeError("504 Gateway Timeout")
        if url.endswith("/page/2/") and _calls.count(url) == 1:
            raise RuntimeError("timeout")
        return _alt if url.endswith("/page/2/") else _sd
    sv.fetch = _sd_flaky; sv.FETCH_NOTES.pop("Showdown Saloon", None); sv.EARLY_STOP_PAGES.clear()
    r2 = sv.parse_showdown(_sd, TODAY)
    n2 = sv.FETCH_NOTES.get("Showdown Saloon", "")
    # page 2 recovers on its retry (adds the Dec copies), page 3 fails 3x
    # and is SKIPPED, pages 4..7 still fetched.
    _ok = _ok and len(r2) == 20 and _calls.count(_calls[0]) == 2 and any(c.endswith("/page/7/") for c in _calls) \
        and "6 of 7 pages" in n2 and "failed 3x: 3 (" in n2
    _h = sv.net_health({"partial": {"Showdown Saloon": (10, 52, 41, 1)}}, {"Showdown Saloon": "2026-10-29"}, [],
                       datetime.date(2026, 10, 30), (), {"Showdown Saloon": "10 rows, 1 of 7 pages; x"})
    _ok = _ok and _h["items"][0].get("why", "").startswith("10 rows, 1 of 7")
    sv.fetch = _no_network; sv.FETCH_NOTES.pop("Showdown Saloon", None); sv.EARLY_STOP_PAGES.clear()
    if not _ok:
        print(f"  FAIL showdown paging              calls={len(_calls)} n1={n1!r} n2={sv.FETCH_NOTES.get('Showdown Saloon')!r} r2={len(r2)} health={_h}")
        print("GATE FAILURE")
        sys.exit(1)
    print("  ok   showdown paging               pages 2..last from the pager, 3 tries each, a dead page skipped not fatal; 'why' + page-one capture")
    # Turn! Turn! Turn! on Opendate (Sep 24 2026): the capture is the real
    # page, saved from the Codespace (the venue moved its calendar there).
    _od = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "turn-opendate.html")
    if os.path.exists(_od):
        rows = sv.parse_turn_opendate(open(_od, encoding="utf-8").read(), datetime.date(2026, 9, 24))
        n = len(rows)
        timed = sum(1 for r in rows if r.get("time"))
        posters = sum(1 for r in rows if r.get("imageUrl"))
        dated = all(r.get("date") and r.get("title") for r in rows)
        if n < 10 or not dated or timed < n * 0.8 or posters < n * 0.6:
            print(f"  FAIL turn-opendate.html          rows {n}, timed {timed}, posters {posters}, all dated {dated}")
            print("GATE FAILURE")
            sys.exit(1)
        print(f"  ok   turn-opendate.html          {n:3d} rows  -- Opendate embed; date from each event link; show time; poster before the link; age from the venue's day/night rule")


if __name__ == "__main__":
    main()
    talk_page_check()
    multi_time_check()
    submission_fold_check()
    tm_same_act_check()
    tm_guard_check()
    batch_four_check()
    safety_net_check()
