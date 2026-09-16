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
import sys
import json, os, datetime
import re
import html as _html

_DASHES = re.compile(r"[\u2010-\u2015]")
_TAG_RE = re.compile(r"<[^>]+>")
_NONALNUM = re.compile(r"[^0-9a-z]+")


def clean_title(t):
    # Strip HTML tags and decode entities so raw markup (e.g. a <span> from
    # a source feed) never reaches shows.json. Decode first (entities can
    # reveal tag chars), strip tags, decode again, then collapse whitespace.
    t = _html.unescape(t or "")
    t = _TAG_RE.sub("", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


# Age restriction, derived from the title. Sources put it there as a trailing
# suffix ("... - 21+", "... (21+)", "... - ALL AGES!") rather than in a field
# of its own, so this reads it back out into one.
#
# CRITICAL: this NEVER modifies the title. make_slug() derives a show's
# permanent identity from its title, and those slugs are referenced by
# archive.json and by every show_slug row in Supabase (comments, ticket_posts,
# show_attendees, show_threads). Rewriting a title to strip the suffix would
# silently break all of them.
#
# Three states, not two: "21+", "all-ages", or absent. Absent means UNKNOWN and
# must stay distinguishable from "known to be all-ages" -- most shows carry no
# age information at all, and a filter that quietly treats unknown as either
# answer would be lying about coverage.
_AGE_21 = re.compile(r"(?:^|[\s\-\u2013\u2014(\[])(?:21\s*\+|21\s*(?:&|and)\s*over|21\s*and\s*up)", re.I)
_AGE_18 = re.compile(r"(?:^|[\s\-\u2013\u2014(\[])18\s*\+", re.I)
_AGE_ALL = re.compile(r"(?:^|[\s\-\u2013\u2014(\[])all\s*ages", re.I)


def detect_age(title):
    """Return '21+', '18+', 'all-ages', or '' (unknown) for a show title."""
    t = title or ""
    # Checked most-restrictive first: a title carrying both (rare, e.g. an
    # all-ages early show followed by a 21+ late one) should not be advertised
    # as all-ages.
    if _AGE_21.search(t):
        return "21+"
    if _AGE_18.search(t):
        return "18+"
    if _AGE_ALL.search(t):
        return "all-ages"
    return ""


# Venue-level age defaults, applied ONLY where the title says nothing.
#
# Title detection covers about 3% of the feed, because most venues simply do
# not put an age in the show title. The rest of the coverage has to come from
# house policy -- but a wrong age here is worse than no age at all: it sends
# someone to a door they cannot get through, or keeps a parent home from a
# show their kid could have attended. That is exactly the trust this site
# trades on, so the bar for entry is deliberately high.
#
# ADMISSION STANDARD -- a venue belongs here only if BOTH hold:
#   1. The venue states the policy ITSELF (its own site, its own ticketing
#      page, its own booking info). Aggregators and ticket resellers hedge
#      ("most events are 21+") and are not evidence of a blanket rule.
#   2. The policy is UNCONDITIONAL -- "all shows are 21+", not "most shows".
#      A venue that runs all-ages matinees, has a kid-friendly dining room,
#      or varies by show does NOT get a default, no matter how many of its
#      shows are in fact 21+.
#
# Laurelthirst is the worked example of an exclusion: a full bar that is also
# kid-friendly and runs free all-ages bluegrass matinees. At 90 shows it is
# the second-largest venue in the feed and defaulting it to 21+ would be
# wrong on every matinee. It stays unknown until the venue is asked directly.
#
# Each entry carries the source it was read from, so a future maintainer can
# re-check it rather than inheriting an unsourced assertion. Venues drift --
# ownership changes, licenses change -- so these are re-verifiable claims,
# not permanent facts.
VENUE_AGE_DEFAULT = {
    # "All shows are 21+" -- venue's own Eventbrite organizer page.
    # https://www.eventbrite.com/o/kellys-olympian-3225803660
    "Kelly's Olympian": "21+",
    # 21+ with no exceptions -- confirmed by Nick, who plays and books these
    # rooms, against the same standard as Kelly's: no all-ages nights, no
    # matinees, minors never admitted. Asked about eight bars at once; this is
    # the only one he was certain enough to put on the list. 2026-09-14.
    "Starday Tavern": "21+",
}


def _norm_key(s):
    # Aggressive normalization used ONLY for the dedupe key (not display):
    # strip HTML, dash-normalize, lower, and collapse every run of
    # non-alphanumerics to one space so punctuation/spacing/markup variants
    # of the same title or venue can never form a distinct key.
    s = _TAG_RE.sub("", _html.unescape(s or ""))
    s = _DASHES.sub("-", s).lower()
    return _NONALNUM.sub(" ", s).strip()


def _norm_title(t):
    return _norm_key(t)


def _norm_venue(v):
    return _norm_key(v)

HERE = os.path.dirname(__file__)
MANUAL = os.path.join(HERE, "manual_shows.json")
OUT = os.path.join(HERE, "shows.json")
ARCHIVE = os.path.join(HERE, "archive.json")


# --- Append-only past-show archive -------------------------------------------
# archive.json is an accumulative record of shows that have already happened.
# It only ever GROWS: past shows are merged in before the live feed drops them,
# so their data survives even after the scraper overwrites manual_shows.json.
# Identity is a STABLE SLUG derived from immutable facts (date + venue + title),
# NOT the build's sequential integer id (which is reassigned every run).

_ARCHIVE_SOURCE = "Append-only archive of past shows (accumulated across builds)"
_ARCHIVE_FIELDS = ("title", "venue", "neighborhood", "address",
                   "date", "time", "venueUrl", "ticketUrl", "imageUrl", "age")


def make_slug(show):
    """Deterministic permanent identity for a show.

    Reuses the existing dedupe normalization (_norm_key -> strip HTML/entities,
    dash-normalize, lowercase, collapse every non-alphanumeric run) so the slug
    is immune to markup/punctuation/whitespace variants, then joins the tokens
    with hyphens to form a URL-safe slug. Same show -> same slug on every run.
    """
    date = (show.get("date", "") or "").strip()
    venue = _norm_key(show.get("venue", ""))
    title = _norm_key(clean_title(show.get("title", "")))
    raw = " ".join(p for p in (date, venue, title) if p)
    slug = re.sub(r"\s+", "-", raw).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


def _snapshot(show, slug):
    rec = {f: show.get(f, "") for f in _ARCHIVE_FIELDS}
    rec["title"] = clean_title(show.get("title", ""))
    rec["slug"] = slug
    return rec


def archive_past_shows(past_shows, generated_iso):
    """Merge past shows into archive.json. Add-only; never remove/overwrite.

    Dedupe is on the stable slug. If two GENUINELY DISTINCT past shows collide
    on slug (same date+venue+title) but differ by time, a disambiguator is
    appended so they don't silently merge. Returns (added, collisions)."""
    data = {"generated": generated_iso, "source": _ARCHIVE_SOURCE, "shows": []}
    if os.path.exists(ARCHIVE):
        try:
            existing = json.load(open(ARCHIVE))
            if isinstance(existing, dict) and isinstance(existing.get("shows"), list):
                data = existing
        except Exception as e:
            print(f"archive.json unreadable, starting fresh: {e}")
            data = {"generated": generated_iso, "source": _ARCHIVE_SOURCE, "shows": []}

    by_slug = {}
    for rec in data.get("shows", []):
        if rec.get("slug"):
            by_slug[rec["slug"]] = rec

    added = 0
    collisions = []
    for s in past_shows:
        if not (s.get("title") and s.get("date")):
            continue
        base = make_slug(s)
        if not base:
            continue
        slug = base
        existing = by_slug.get(slug)
        if existing is not None:
            # Already archived. Only disambiguate if this is a genuinely
            # different show (same date/venue/title, different non-empty time).
            t_new = (s.get("time", "") or "").strip()
            t_old = (existing.get("time", "") or "").strip()
            if t_new and t_old and t_new != t_old:
                n = 2
                cand = f"{base}-{n}"
                while cand in by_slug and not (
                    by_slug[cand].get("time", "").strip() == t_new):
                    n += 1
                    cand = f"{base}-{n}"
                if cand in by_slug:
                    continue  # this exact time already archived under disambig slug
                slug = cand
                collisions.append((base, slug, t_old, t_new))
            else:
                continue  # true duplicate of an already-archived show -> skip
        rec = _snapshot(s, slug)
        by_slug[slug] = rec
        data["shows"].append(rec)
        added += 1

    data["generated"] = generated_iso
    data["source"] = _ARCHIVE_SOURCE
    data["shows"].sort(key=lambda r: (r.get("date", ""), r.get("venue", ""),
                                      r.get("title", ""), r.get("slug", "")))
    with open(ARCHIVE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Archive: +{added} new past show(s), {len(data['shows'])} total in archive.json")
    if collisions:
        print(f"Archive: {len(collisions)} slug collision(s) disambiguated:")
        for base, slug, t_old, t_new in collisions:
            print(f"  COLLIDE base={base!r} -> {slug!r} (times {t_old!r} vs {t_new!r})")
    return added, collisions


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
    _pac = _dt.timezone(_dt.timedelta(hours=-8))
    today_pacific = _dt.datetime.now(_pac).date()
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
                elif dd < today_pacific:
                    issues.append(f"past-dated show leaked {d!r} @ {v} {t[:40]!r}")
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



# --- Layer 1: build-side hard-fail guardrails ---------------------------------
# A build that produces catastrophically less data than the last good one is a
# failure, not a result. These checks run BEFORE shows.json is written, so a bad
# build leaves the last good feed in place and fails the run RED instead of
# quietly publishing a gutted feed. Thresholds are calibrated against observed
# healthy runs (see BUILDLOG); they are deliberately loose enough that normal
# variation never trips them.
MIN_TOTAL_SHOWS = 600      # ~48% of the healthy 1239; lowest healthy run observed was 1070
MAX_NEW_ZERO_VENUES = 3    # historical newly-zero-per-run: 0,0,0,0,0,1,2,4


# Junk that has actually reached the live feed. Each pattern is a thing that
# was seen in production, not a guess about what might go wrong.
_TITLE_JUNK = (
    ("end event",           "HTML comment leaked into title"),      # Roseland, Sep 2026
    ("sub header",          "HTML comment leaked into title"),
    ("image container",     "HTML comment leaked into title"),
    ("more info",           "link label leaked into title"),
)
_TITLE_MAX = 140

# Listing pages verified (captured HTML, Sep 2026) to carry NO show time in
# any format. The time exists only on each event's detail page, so getting
# it means one extra fetch per show -- a runtime decision, not a parser bug.
# Listed here so the 0%-time check does not keep reporting them as broken.
_NO_LISTING_TIME = {
    "Twilight Cafe & Bar",   # twilightcafeandbar.com/calendar_list: title, flyer, link
    "NOVA PDX",              # novapdxevents.com/event-calendar: same shape
    # musicmillennium.com/InStore, captured through the headless tier (a plain
    # fetch returns a challenge page). No time in any format. The only "Show:"
    # strings on the page are carousel config -- "Show: 6," and "Show: 3," --
    # i.e. slides per view, not a door time. In-store performances are also
    # the one case where a missing time matters least: they happen during
    # shop hours.
    "Music Millennium",
    # kentonclub.com: a plain-text Squarespace list, date line + band names,
    # no time on any entry. "Open Everyday Noon to 2AM" is the only clock on
    # the page.
    "Kenton Club",
    # spareroomrestaurantandlounge.com: hand-written monthly <li> list, no
    # times on the live-music entries (one karaoke line says "7pm").
    "Spare Room",
}


def check_shape(shows):
    """Warn about rows that are VALID but WRONG. Never fatal.

    Every guard before this one counts things: total shows, venues at zero,
    venues that spiked. None of them can see a bad row, because a bad row is
    still a row. 30 of 41 Roseland titles shipped as "CupcakKe (w/ Father
    Fannie with Father Fannie end event sub header)" and 0 of 41 had a show
    time, for weeks, and every count-based check called the build healthy.
    The feed had no way to know it was embarrassing itself.

    This looks at what the rows SAY. It reports, it does not block: a junk
    title is worse than a clean one but still better than no feed, and a
    blocked feed goes stale (see the festival incident in guard_build)."""
    from collections import defaultdict
    problems = []

    # 1. Titles carrying markup leakage, doubled support acts, or absurd length.
    by_venue = defaultdict(list)
    for sh in shows:
        t = (sh.get("title") or "").strip()
        v = sh.get("venue") or "?"
        low = t.lower()
        why = None
        if not t:
            why = "empty title"
        else:
            for needle, label in _TITLE_JUNK:
                if needle in low:
                    why = label
                    break
            if not why and low.count(" with ") >= 2:
                why = "support act listed twice"
            if not why and len(t) > _TITLE_MAX:
                why = f"title over {_TITLE_MAX} chars"
        if why:
            by_venue[v].append((why, t))
    for v, hits in sorted(by_venue.items(), key=lambda kv: -len(kv[1])):
        why, sample = hits[0]
        problems.append(f"{v}: {len(hits)} bad title(s) -- {why} -- e.g. {sample[:70]!r}")

    # 2. Venues where NO show has a time. One missing time is normal; a venue
    #    at 0% is either a parser missing data the page carries (Dante's:
    #    the block was the name wrapper, time sat one level up) or a listing
    #    page that never carries a time at all (Twilight, NOVA PDX: title +
    #    flyer + link, nothing else -- the time is on each detail page). The
    #    check cannot tell those apart, so it says so rather than blaming the
    #    parser. Sources known to publish no time on the listing are named in
    #    _NO_LISTING_TIME so they stop appearing here.
    per_venue = defaultdict(lambda: [0, 0])
    for sh in shows:
        c = per_venue[sh.get("venue") or "?"]
        c[0] += 1
        if (sh.get("time") or "").strip():
            c[1] += 1
    for v, (n, timed) in sorted(per_venue.items()):
        if n >= 5 and timed == 0 and v not in _NO_LISTING_TIME:
            problems.append(f"{v}: 0 of {n} shows have a time -- either the parser misses it "
                            f"or the listing page never carries one; capture the page to tell")

    if problems:
        print(f"SHAPE WARNING: {len(problems)} issue(s) in rows that are valid but wrong:")
        for pr in problems:
            print(f"  SHAPE: {pr}")
        print("  ^ not fatal; the feed still ships. These are parser bugs the "
              "count-based guards cannot see.")
    return problems


def guard_build(new_shows, out_path):
    """Return a list of fatal problems with the freshly built feed. Empty = OK."""
    from collections import Counter as _C
    fatal = []
    total = len(new_shows)
    if total < MIN_TOTAL_SHOWS:
        fatal.append(f"total upcoming shows {total} < floor {MIN_TOTAL_SHOWS}")

    prev = []
    if os.path.exists(out_path):
        try:
            prev = json.load(open(out_path)).get("shows", [])
        except Exception as e:
            print(f"  guard: previous shows.json unreadable ({e}); skipping zero-drop check")
            prev = None
    if prev:
        old_c = _C(s.get("venue", "") for s in prev)
        new_c = _C(s.get("venue", "") for s in new_shows)
        newly_zero = sorted(v for v in old_c if v and old_c[v] > 0 and new_c.get(v, 0) == 0)

        # A venue at zero because its dates moved into the past has not
        # "dropped" -- time passed, which is the one thing this feed does every
        # day. Only a venue that still had UPCOMING shows in the last build and
        # has none now is evidence of something breaking.
        #
        # Without this split the guard fails whenever a multi-venue festival
        # ends: St. Johns Music Fest ran 2026-09-11..12 across four hand-added
        # venues (Beer Porch Food Carts, Fixin' To, Lombard House, St Johns
        # Square), all four went to zero on the same build, and the nightly
        # refresh failed for two days over a completely expected event. A
        # blocked feed is not a safe default -- it went stale, and stale
        # attendance rows kept showing finished shows as upcoming on profiles.
        _pac_today = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=-8))).date().isoformat()
        prev_upcoming = _C(s.get("venue", "") for s in prev
                           if (s.get("date") or "") >= _pac_today)
        expired = [v for v in newly_zero if prev_upcoming.get(v, 0) == 0]
        vanished = [v for v in newly_zero if prev_upcoming.get(v, 0) > 0]
        if expired:
            print(f"  guard: {len(expired)} venue(s) aged out (all dates now past, not counted): "
                  f"{', '.join(expired)}")
        # MAX_NEW_ZERO_VENUES is the largest count still ALLOWED, so the build
        # fails only when strictly more than that many venues go to zero.
        if len(vanished) > MAX_NEW_ZERO_VENUES:
            fatal.append(
                f"{len(vanished)} venues with UPCOMING shows dropped to zero in one build "
                f"(limit {MAX_NEW_ZERO_VENUES}): {', '.join(vanished)}")
        elif vanished:
            print(f"  guard: {len(vanished)} venue(s) newly zero (under limit): {', '.join(vanished)}")
    return fatal


_SUBMISSIONS_RPC = "/rest/v1/rpc/approved_submissions"


def _supabase_public_config():
    """(url, anon_key) from auth.js -- the one place they are written down.
    Both are public by design (they ship to every browser)."""
    try:
        src = open(os.path.join(HERE, "auth.js")).read()
        url = re.search(r'SUPABASE_URL\s*=\s*"([^"]+)"', src).group(1)
        key = re.search(r'SUPABASE_ANON_KEY\s*=\s*"([^"]+)"', src).group(1)
        return url, key
    except Exception:
        return None, None


def fetch_approved_submissions():
    """Approved rows from the submissions line, in the feed's 8-field shape.

    Served by a public SECURITY DEFINER RPC (supabase/schema-submissions.sql)
    that exposes nothing private -- no email, no notes, no reviewer -- so the
    build pulls it with the anon key and needs no secret in CI. A failure here
    is a WARN, never fatal: the feed is the scrape plus whatever submissions
    could be read, and a Supabase blip must not block the nightly build."""
    url, key = _supabase_public_config()
    if not url or not key:
        print("  WARN: submissions: could not read Supabase config from auth.js; skipping")
        return []
    try:
        import urllib.request
        req = urllib.request.Request(
            url + _SUBMISSIONS_RPC, data=b"{}", method="POST",
            headers={"apikey": key, "Authorization": "Bearer " + key,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            rows = json.load(r)
    except Exception as e:
        print(f"  WARN: submissions: fetch failed: {type(e).__name__}: {e}; skipping")
        return []
    out = []
    for r in rows or []:
        if not (r.get("title") and r.get("venue") and r.get("date")):
            continue
        out.append({"title": r["title"], "venue": r["venue"],
                    "neighborhood": r.get("neighborhood") or "",
                    "address": r.get("address") or "",
                    "date": r["date"], "time": r.get("time") or "",
                    "venueUrl": r.get("venueUrl") or "", "imageUrl": "",
                    "age": r.get("age") or "", "_submitted": True})
    print(f"  submissions: {len(out)} approved show(s) merged from the submissions line")
    return out


def _venue_directory(shows):
    """Sorted list of {name, neighborhood, address}: VENUE_INFO from the
    scraper plus any venue present in the feed but not in VENUE_INFO."""
    seen = {}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("sv", os.path.join(HERE, "scrape_venues.py"))
        sv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sv)
        for name, (nb, addr) in sv.VENUE_INFO.items():
            seen[name] = {"name": name, "neighborhood": nb or "", "address": addr or ""}
    except Exception as e:
        print(f"  WARN: venue directory: could not read VENUE_INFO ({type(e).__name__}); using feed venues only")
    for sh in shows:
        v = sh.get("venue") or ""
        if v and v not in seen:
            seen[v] = {"name": v, "neighborhood": sh.get("neighborhood") or "",
                       "address": sh.get("address") or ""}
    return sorted(seen.values(), key=lambda d: d["name"].lower())


# ---------------------------------------------------------------------------
# Ticketmaster Discovery API: enrichment and gap-fill.
#
# Explored 2026-09-15: Portland / OR / music / next 90 days is 487 events at
# 21 venues in three calls (quota 5,000 a day). Every event carries a start
# time, a poster, and a ticket URL -- and for TicketWeb venues that URL is
# ticketweb.com's, the one that becomes the affiliate link. The structured
# age field is empty, but 180 of 487 state the age in pleaseNote, which
# _age_in_text reads conservatively like everywhere else.
#
# Two jobs, in this order:
#   1. ENRICH: match each TM event to a feed row by date + venue + title-word
#      overlap, and fill only what is blank -- time, poster, age, ticketUrl.
#      The scraper's own values win; TM backfills.
#   2. ADD: a TM event at a venue the site already covers, with no matching
#      row, is a show the scraper missed. Crystal Ballroom had 11 in the feed
#      and 39 on TM the day this was explored. Added rows are marked
#      _tm=True (stripped before publish) and go through the same dedupe.
# Events at venues the site does not cover are counted and named, not added.
#
# Key: TM_API_KEY in the environment (a GitHub secret in CI). Without it the
# pass is skipped with a note; a failed fetch is a WARN. Never fatal.
# ---------------------------------------------------------------------------
TM_VENUE_MAP = {
    "Revolution Hall - Portland": "Revolution Hall",
    "McMenamins Crystal Ballroom": "Crystal Ballroom",
    "McMenamins Mission Theater": "Mission Theater",
    "The Den - Portland": "Al's Den",
    "The Get Down Music Venue": "The Get Down",
}
# Names that are add-ons to a show, not shows: never added as rows, and not
# used to enrich (their pleaseNote is about the package, not the gig).
_TM_ADDON = re.compile(r"\b(VIP|Platinum|Package|Parking|Meet\s*&\s*Greet|Upgrade|Pre-?Show|Soundcheck)\b", re.I)
_TM_STOP = {"the", "and", "w", "with", "tour", "live", "of", "a", "at", "in", "presents", "an", "evening", "night"}


def _tm_words(title):
    return set(re.findall(r"[a-z0-9]+", (title or "").lower())) - _TM_STOP


def _tm_headliner(title):
    """The act, as a word set: the title up to the first support/suffix
    marker (":" / "w/" / "with" / "(" / " - "). "Beck: Ride Lonesome Tour"
    and "Beck" agree; "Oregon Symphony presents Holst" and "Gregory Alan
    Isakov with the Oregon Symphony" do not."""
    head = re.split(r"\s*[:(]|\s+(?:w/|with|feat\.?|featuring)\s+|\s+-\s+", title or "", maxsplit=1)[0]
    return frozenset(_tm_words(head))


def _tm_normalize(ev, venue_info):
    """One Discovery API event -> feed-shaped dict, or None if it is an add-on
    or at a venue the site does not know."""
    name = ev.get("name") or ""
    if _TM_ADDON.search(name):
        return None
    vraw = ((ev.get("_embedded") or {}).get("venues") or [{}])[0].get("name") or ""
    venue = TM_VENUE_MAP.get(vraw, vraw)
    if venue not in venue_info:
        return {"_uncovered": vraw}
    st = (ev.get("dates") or {}).get("start") or {}
    date = st.get("localDate") or ""
    tm = ""
    lt = st.get("localTime") or ""
    if lt and not st.get("timeTBA") and not st.get("noSpecificTime"):
        try:
            h, m = int(lt[:2]), int(lt[3:5])
            tm = f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
        except Exception:
            tm = ""
    imgs = ev.get("images") or []
    # Prefer a wide poster at a sane size; TM ships six renditions per event.
    pick = ""
    for ratio in ("16_9", "3_2", "4_3"):
        c = sorted((i for i in imgs if i.get("ratio") == ratio and (i.get("width") or 0) >= 600),
                   key=lambda i: i.get("width") or 0)
        if c:
            pick = c[0].get("url") or ""
            break
    if not pick and imgs:
        pick = imgs[0].get("url") or ""
    note = " ".join(x for x in ((ev.get("pleaseNote") or ""), (ev.get("info") or "")) if x)
    nb, addr = venue_info[venue]
    return {"title": name.strip(), "venue": venue, "neighborhood": nb, "address": addr,
            "date": date, "time": tm, "venueUrl": ev.get("url") or "",
            "ticketUrl": ev.get("url") or "", "imageUrl": pick,
            "age": _sv().__dict__["_age_in_text"](note) if note else "", "_tm": True}


def _sv():
    """scrape_venues as a module, loaded once (for _age_in_text and VENUE_INFO)."""
    if not hasattr(_sv, "mod"):
        import importlib.util
        spec = importlib.util.spec_from_file_location("sv", os.path.join(HERE, "scrape_venues.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _sv.mod = mod
    return _sv.mod


def tm_fetch(today, days=90):
    key = os.environ.get("TM_API_KEY", "").strip()
    if not key:
        print("  note: Ticketmaster: TM_API_KEY not set; pass skipped")
        return []
    import urllib.request, urllib.parse
    end = today + datetime.timedelta(days=days)
    out, page = [], 0
    while page < 10:
        q = urllib.parse.urlencode({
            "apikey": key, "city": "Portland", "stateCode": "OR", "classificationName": "music",
            "size": 200, "page": page, "sort": "date,asc",
            "startDateTime": today.isoformat() + "T00:00:00Z",
            "endDateTime": end.isoformat() + "T23:59:59Z"})
        try:
            with urllib.request.urlopen("https://app.ticketmaster.com/discovery/v2/events.json?" + q, timeout=30) as r:
                d = json.load(r)
        except Exception as e:
            print(f"  WARN: Ticketmaster: fetch failed on page {page}: {type(e).__name__}: {e}")
            break
        ev = ((d.get("_embedded") or {}).get("events")) or []
        out += ev
        if not ev or page >= (d.get("page") or {}).get("totalPages", 1) - 1:
            break
        page += 1
    return out


def tm_apply(shows, events, today):
    """Enrich matched rows in place; append missed shows at covered venues.
    Returns (matched, added, uncovered_counter). Pure: no network."""
    from collections import Counter
    venue_info = _sv().VENUE_INFO
    by = {}
    by_venue_head = {}          # (venue, headliner) -> [rows] from the feed
    for r in shows:
        by.setdefault((r.get("date"), r.get("venue")), []).append(r)
        by_venue_head.setdefault((r.get("venue"), _tm_headliner(r.get("title"))), []).append(r)
    # Every date Ticketmaster lists per (venue, headliner). A real two-night
    # stand (Spafford at Al's Den, Sep 19 and 20) shows both dates here; a
    # reschedule the API has not caught up with shows only the old one.
    tm_dates = {}
    norm = []
    for ev in events:
        n = _tm_normalize(ev, venue_info)
        norm.append(n)
        if n and "_uncovered" not in n and n.get("date"):
            tm_dates.setdefault((n["venue"], _tm_headliner(n["title"])), set()).add(n["date"])
    matched = added = rescheduled = dead = 0
    uncovered = Counter()
    seen_add = set()
    for ev, n in zip(events, norm):
        if not n:
            continue
        if "_uncovered" in n:
            uncovered[n["_uncovered"]] += 1
            continue
        if not n["date"] or n["date"] < today.isoformat():
            continue
        # Ticketmaster's own verdict first: cancelled / offsale / postponed
        # events are not shows to add (9 offsale and 1 cancelled in the
        # captured pull).
        # "offsale" is NOT dead: Ticketmaster flips a show to offsale when the
        # box office closes on show day, hours before doors. Thievery
        # Corporation at Crystal vanished from the feed on the afternoon of
        # its show (2026-09-15) for exactly that reason. Only cancelled and
        # postponed mean the show is not happening.
        code = (((ev.get("dates") or {}).get("status") or {}).get("code") or "").lower()
        if code in ("cancelled", "canceled", "postponed"):
            dead += 1
            continue
        tw = _tm_words(n["title"])
        best = None
        for r in by.get((n["date"], n["venue"]), []):
            rw = _tm_words(r.get("title"))
            ov = len(tw & rw)
            # Same date, same venue, and the SHORTER title is mostly inside the
            # longer one. Either side can be the short one: the scraper had
            # "Hovvdy" where Ticketmaster had "Hovvdy w/ Emma Ogier", and
            # measuring against the TM title alone (1 of 3 words) missed it
            # and added a duplicate row -- seven of them, live, 2026-09-15.
            if ov and (ov >= 2 or ov >= max(1, min(len(tw), len(rw))) * 0.6):
                best = r
                break
        if best is not None:
            matched += 1
            for k in ("time", "imageUrl", "age", "ticketUrl"):
                if not (best.get(k) or "").strip() and n.get(k):
                    best[k] = n[k]
            continue
        # No row on that date. Reschedule check: the venue lists the same
        # headliner on another date that Ticketmaster does NOT list. Beck
        # moved Sep 19 -> Nov 10 (announced 2026-09-14); Portland'5 updated
        # that day, the API still said Sep 19, and the pass added a second
        # Beck. The venue wins. A two-night stand is safe: the API lists
        # both nights, so the other date is in tm_dates and nothing fires.
        hk = _tm_headliner(n["title"])
        others = [r for r in by_venue_head.get((n["venue"], hk), []) if r.get("date") != n["date"]]
        listed = tm_dates.get((n["venue"], hk), set())
        moved = next((r for r in others if r.get("date") not in listed), None)
        if hk and moved is not None:
            print(f"  note: Ticketmaster says {n['date']} but {n['venue']} lists {moved.get('date')} -- {n['title'][:40]!r}; keeping the venue's date")
            rescheduled += 1
            continue
        key = (n["date"], n["venue"], frozenset(tw))
        if key in seen_add:
            continue
        seen_add.add(key)
        shows.append(n)
        by.setdefault((n["date"], n["venue"]), []).append(n)
        by_venue_head.setdefault((n["venue"], hk), []).append(n)
        added += 1
    if rescheduled or dead:
        print(f"  Ticketmaster: {rescheduled} skipped as rescheduled (venue date kept), {dead} skipped as cancelled/offsale")
    return matched, added, uncovered


# ---------------------------------------------------------------------------
# Vivid Seats resale links, from the Impact product catalog.
#
# Vivid publishes its whole event catalog through Impact (Content -> Product
# Catalogs -> "Ticket Feed", ~180,000 rows, refreshed daily), and every row's
# Product URL is a tracked deep link to THAT event with Nick's affiliate ID
# already in it. That is the answer to "make sure we point at the right
# place": match each show at a resale venue to its catalog row by venue and
# date, and store the exact link. No row, no link.
#
# Feed shape (tab-separated, 70 columns, most empty): Product Name (event),
# Product URL (tracked link; the Vivid URL inside carries the date as
# -M-D-YYYY), Text1 = venue, Text2 = city, Text3 = address, Money2 = lowest
# listing price. Fetched over FTP from products.impact.com with
# IMPACT_FTP_USER / IMPACT_FTP_PASS (GitHub secrets). Gzipped, ~10 MB.
#
# Without credentials the pass is skipped with a note; a failed fetch is a
# WARN. Rows keep whatever resaleUrl they had -- nothing is invented.
# ---------------------------------------------------------------------------
VIVID_VENUE_MAP = {
    "Revolution Hall Portland": "Revolution Hall",
    "McMenamins Crystal Ballroom": "Crystal Ballroom",
    "McMenamins Mission Theater": "Mission Theater",
    "Veterans Memorial Coliseum - Portland": "Veterans Memorial Coliseum",
    "Star Theater Portland": "Star Theater",
    "Dantes": "Dante's",
    "The Den - Portland": "Al's Den",
    "Hillsboro Ballpark": "Hops Ballpark",
    "The Melody Event Center - The Get Down Music Venue": "The Get Down",
    "Helium Comedy Club - Portland": "Helium Comedy Club",
}
_VIVID_DATE = re.compile(r"-(\d{1,2})-(\d{1,2})-(\d{4})(?=--|/|$)")
_VIVID_AREA = re.compile(r", (OR|WA) \d{5}")


def vivid_fetch_feed():
    """The catalog as text, or '' -- never raises."""
    user = os.environ.get("IMPACT_FTP_USER", "").strip()
    pw = os.environ.get("IMPACT_FTP_PASS", "").strip()
    if not (user and pw):
        print("  note: Vivid: IMPACT_FTP_USER/PASS not set; resale pass skipped")
        return ""
    import ftplib, gzip, io
    try:
        ftp = ftplib.FTP("products.impact.com", timeout=60)
        ftp.login(user, pw)
        # The file lives under a brand folder that the root listing does not
        # show (root lists as empty; found 2026-09-15 by trying the name).
        ftp.cwd("/Vivid-Seats")
        names = ftp.nlst()
        cand = [n for n in names if n.endswith("_IR.txt.gz")] or [n for n in names if "Ticket-Feed" in n]
        if not cand:
            print(f"  WARN: Vivid: no Ticket-Feed file in /Vivid-Seats; saw {names[:8]}")
            ftp.quit()
            return ""
        buf = io.BytesIO()
        ftp.retrbinary("RETR " + cand[0], buf.write)
        ftp.quit()
        raw = buf.getvalue()
        if cand[0].endswith(".gz"):
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")
    except Exception as e:
        print(f"  WARN: Vivid: FTP fetch failed: {type(e).__name__}: {e}")
        return ""


def vivid_index(feed_text, venue_names):
    """{(venue, date): (tracked_url, lowest_price)} for Portland-area rows at
    venues the site knows. Pure; used by the suite against a saved sample."""
    lines = feed_text.splitlines()
    if not lines:
        return {}
    hdr = lines[0].split("\t")
    ix = {h: i for i, h in enumerate(hdr)}
    need = ("Product URL", "Text1", "Text3", "Money2")
    if any(k not in ix for k in need):
        print(f"  WARN: Vivid: feed columns changed; missing {[k for k in need if k not in ix]}")
        return {}
    known = set(venue_names)
    out = {}
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= max(ix[k] for k in need):
            continue
        addr = cols[ix["Text3"]]
        if not _VIVID_AREA.search(addr):
            continue
        venue = VIVID_VENUE_MAP.get(cols[ix["Text1"]], cols[ix["Text1"]])
        if venue not in known:
            continue
        url = cols[ix["Product URL"]]
        try:
            import urllib.parse
            inner = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("u", [""])[0])
        except Exception:
            inner = ""
        m = _VIVID_DATE.search(inner)
        if not m:
            continue
        date = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        price = cols[ix["Money2"]].strip()
        key = (venue, date)
        # Several rows can share a venue+date (packages, parking, a second
        # listing); keep the cheapest real one.
        if key not in out or (price and (not out[key][1] or float(price) < float(out[key][1] or 1e9))):
            out[key] = (url, price)
    return out


def vivid_apply(shows, index):
    """Attach resaleUrl / resaleFrom to matched rows. Returns count."""
    n = 0
    for r in shows:
        hit = index.get((r.get("venue"), r.get("date")))
        if hit:
            r["resaleUrl"], r["resaleFrom"] = hit[0], hit[1]
            n += 1
    return n


# ---------------------------------------------------------------------------
# Festivals. festivals.json is Nick's file: one object per festival with the
# poster, dates, link, a line about it, and a day-by-day lineup of sets
# (date, time, artist, venue). Two things come out of it:
#
#   1. Every set becomes an ordinary feed row at its real venue, titled
#      "Artist -- Festival Name" -- the convention that worked for St. Johns
#      Music Fest, where the suffix made it obvious in the feed which shows
#      were the festival. The row carries festival: <slug> so the app can
#      group them. Past sets are dropped like any other past row.
#   2. shows.json carries a "festivals" array (everything but the lineup) so
#      the Festivals view can draw cards without another fetch; the festival
#      page itself loads festivals.json for the full lineup.
# ---------------------------------------------------------------------------
FESTIVALS_FILE = os.path.join(HERE, "festivals.json")


def load_festivals():
    try:
        with open(FESTIVALS_FILE) as f:
            return [x for x in (json.load(f).get("festivals") or []) if x.get("slug") and x.get("name")]
    except Exception as e:
        print(f"  WARN: festivals.json unreadable: {e}")
        return []


def festival_rows():
    """Every lineup set as a fresh feed row (no matching against the feed).
    Used by the suite; the build uses festival_apply, which matches first."""
    out = []
    for f in load_festivals():
        for l in f.get("lineup") or []:
            if not (l.get("date") and l.get("artist") and l.get("venue")):
                continue
            out.append(_festival_row(f, l))
    return out


def _festival_row(f, l):
    return {"title": f"{l['artist']} \u2014 {f['name']}", "venue": l["venue"],
            "neighborhood": l.get("neighborhood") or f.get("neighborhood") or "",
            "address": l.get("address") or "", "date": l["date"], "time": l.get("time") or "",
            "venueUrl": l.get("url") or f.get("url") or "", "imageUrl": l.get("imageUrl") or "",
            "age": l.get("age") or f.get("age") or "", "festival": f["slug"], "_hand": True}


def festival_apply(shows):
    """Fold the lineups into the feed. A set at a venue the site scrapes is
    usually already there -- Portland'5 lists the Schnitz, McMenamins lists
    Crystal -- so adding it blind would double it (St. Johns did not hit
    this only because its rooms are not scraped). For each set: if a row
    exists at that venue on that date whose title shares the artist (same
    overlap rule as the Ticketmaster pass), TAG that row -- festival slug
    and the "-- Festival" suffix -- keeping its poster and ticket link.
    Otherwise add the set as a new row."""
    by = {}
    for r in shows:
        by.setdefault((r.get("date"), r.get("venue")), []).append(r)
    tagged = added = 0
    for f in load_festivals():
        for l in f.get("lineup") or []:
            if not (l.get("date") and l.get("artist") and l.get("venue")):
                continue
            aw = _tm_words(l["artist"])
            hit = None
            for r in by.get((l["date"], l["venue"]), []):
                if r.get("festival"):
                    continue
                rw = _tm_words(r.get("title"))
                ov = len(aw & rw)
                if ov and (ov >= 2 or ov >= max(1, min(len(aw), len(rw))) * 0.6):
                    hit = r
                    break
            if hit is not None:
                hit["festival"] = f["slug"]
                if f["name"].lower() not in (hit.get("title") or "").lower():
                    hit["title"] = f"{hit['title']} \u2014 {f['name']}"
                if not hit.get("time") and l.get("time"):
                    hit["time"] = l["time"]
                tagged += 1
            else:
                row = _festival_row(f, l)
                shows.append(row)
                by.setdefault((row["date"], row["venue"]), []).append(row)
                added += 1
    if tagged or added:
        print(f"  Festivals: {tagged} feed row(s) tagged, {added} set(s) added from festivals.json")


def festival_summaries(shows):
    """The festivals array for shows.json: metadata plus counts, no lineup."""
    out = []
    for f in load_festivals():
        lineup = f.get("lineup") or []
        out.append({k: f.get(k, "") for k in ("slug", "name", "edition", "start", "end", "neighborhood", "url", "imageUrl", "blurb", "free")}
                   | {"sets": len(lineup), "venues": len({l.get("venue") for l in lineup if l.get("venue")}),
                      "upcoming": sum(1 for r in shows if r.get("festival") == f["slug"])})
    return out


def main():
    shows = []
    if os.path.exists(MANUAL):
        try:
            shows = json.load(open(MANUAL)).get("shows", [])
        except Exception as e:
            print(f"manual_shows.json unreadable: {e}")
    # The submissions line: shows venues and people sent in, reviewed and
    # approved. They join the scrape here and go through the same dedupe,
    # so a submitted show that the scraper also found collapses to one row.
    shows.extend(fetch_approved_submissions())
    festival_apply(shows)

    # Ticketmaster: backfill what the scrape left blank, and add what it
    # missed at venues the site covers. See the block above.
    _pac = datetime.timezone(datetime.timedelta(hours=-8))
    _today = datetime.datetime.now(_pac).date()
    _tm_events = tm_fetch(_today)
    if _tm_events:
        _m, _a, _unc = tm_apply(shows, _tm_events, _today)
        _u = ", ".join(f"{v} ({c})" for v, c in _unc.most_common(6))
        print(f"  Ticketmaster: {len(_tm_events)} events -> {_m} matched, {_a} added"
              + (f"; {sum(_unc.values())} at venues not covered: {_u}" if _unc else ""))

    # Vivid Seats: exact resale links from the Impact catalog. See the block
    # above. Runs after Ticketmaster so TM-added rows can match too.
    _vf = vivid_fetch_feed()
    if _vf:
        _vi = vivid_index(_vf, {r.get("venue") for r in shows})
        _vn = vivid_apply(shows, _vi)
        print(f"  Vivid: {len(_vi)} Portland-area events in the catalog -> {_vn} rows linked")

    # drop past shows
    # Drop past shows using US Pacific time (venues' local zone), not the
    # GitHub runner's UTC clock, (no grace buffer) so a show
    # disappears at Pacific midnight the night it ends.
    pacific = datetime.timezone(datetime.timedelta(hours=-8))
    today_pacific = datetime.datetime.now(pacific).date()
    cutoff = today_pacific.isoformat()
    # Accumulate past shows into the append-only archive BEFORE the live
    # feed drops them. Live feed (shows.json) is unchanged by this step.
    #
    # Sourced from BOTH manual_shows.json and the PREVIOUS shows.json, because
    # manual_shows alone silently loses most of them. CI runs scrape_venues.py
    # first, and the scraper rewrites manual_shows.json keeping only today
    # forward -- so by the time this runs, a show from a HEALTHY scraper is
    # already gone and never reaches the archive. The only past shows left in
    # the file are hand-added ones and the stale entries a BROKEN scraper
    # retains, which is why the archive was 218 rows of Barrel Room, Hawthorne,
    # Main Street and Pioneer Courthouse Square -- the dead sources -- while
    # every Laurelthirst and Holocene show that ever happened vanished.
    #
    # The previous shows.json is exactly the last known-good feed and still
    # holds yesterday's shows at this point, so it closes the gap. Merging is
    # safe: archive_past_shows is add-only and dedupes on slug, so a show
    # present in both sources archives once.
    _prev_feed = []
    if os.path.exists(OUT):
        try:
            _prev_feed = json.load(open(OUT)).get("shows", [])
        except Exception as e:
            print(f"  archive: previous shows.json unreadable ({e}); "
                  f"archiving from manual_shows.json only")
    _past = [s for s in shows if s.get("date", "") < cutoff]
    _seen_past = {(s.get("venue", ""), s.get("date", ""), s.get("title", "")) for s in _past}
    for s in _prev_feed:
        if s.get("date", "") >= cutoff:
            continue
        k = (s.get("venue", ""), s.get("date", ""), s.get("title", ""))
        if k in _seen_past:
            continue
        _seen_past.add(k)
        _past.append(s)
    _archive_gen = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    archive_past_shows(_past, _archive_gen)
    shows = [s for s in shows if s.get("date", "") >= cutoff]

    # Sanitize titles: strip HTML tags + decode entities at build time.
    for s in shows:
        if s.get("title"):
            s["title"] = clean_title(s["title"])

    # Derive the age restriction from the (already sanitized) title. Additive:
    # a show with no age information gets "", meaning UNKNOWN, and the title
    # itself is left exactly as-is so slugs stay stable. A source that ever
    # supplies a real age field wins over the title-derived guess.
    #
    # Precedence, most specific first:
    #   1. an age the scraper supplied for THIS show
    #   2. an age stated in THIS show's title
    #   3. the venue's unconditional house policy (VENUE_AGE_DEFAULT)
    # The venue default is last on purpose: a house that is normally 21+ but
    # advertises a given show as all-ages must not have that overwritten.
    for s in shows:
        if not (s.get("age") or "").strip():
            s["age"] = detect_age(s.get("title", ""))
        if not (s.get("age") or "").strip():
            s["age"] = VENUE_AGE_DEFAULT.get(s.get("venue", ""), "")

    # dedupe on (normalized title, normalized venue, date)
    seen, deduped = {}, []
    time_collisions = []
    for s in shows:
        k = (_norm_title(s.get("title","")),
             _norm_venue(s.get("venue","")),
             s.get("date",""))
        if not (s.get("title") and s.get("date")):
            continue
        if k not in seen:
            seen[k] = s; deduped.append(s)
        else:
            # Same title/venue/date already kept. If BOTH rows carry a
            # non-empty, differing time they may be two real shows that day
            # -> flag instead of silently dropping.
            kept = seen[k]
            t_new = (s.get("time") or "").strip()
            t_old = (kept.get("time") or "").strip()
            if t_new and t_old and t_new != t_old:
                time_collisions.append((s.get("title"), s.get("venue"), s.get("date"), t_old, t_new))
            # Field-merge: the dropped duplicate may carry data the kept row
            # lacks. Adopt the dup's value for any field the kept row left
            # empty so dedupe never discards information (e.g. a missing time,
            # image, or ticket link filled in by a second listing of the show).
            for _f in ("time", "imageUrl", "venueUrl", "ticketUrl"):
                if not (kept.get(_f) or "").strip() and (s.get(_f) or "").strip():
                    kept[_f] = s[_f]

    deduped.sort(key=lambda s: (s["date"], s.get("venue",""), s.get("title","")))
    for i, s in enumerate(deduped, 1):
        s["id"] = i

    validate(deduped)

    # Surface same title/venue/date rows that differ only by time. These are
    # NOT auto-merged blindly here: the first row is kept, but each conflict
    # is reported so a human can confirm they are not two distinct shows.
    if time_collisions:
        print(f"WARNING: {len(time_collisions)} same-day time collision(s) (kept first, flagged):")
        for ti, ve, da, t_old, t_new in time_collisions:
            print(f"  FLAG: {ti!r} @ {ve!r} {da} kept-time={t_old!r} dropped-time={t_new!r}")

    # Layer 1: refuse to publish a catastrophically degraded feed. Checked
    # BEFORE the write so the last good shows.json survives a bad build.
    check_shape(deduped)
    _fatal = guard_build(deduped, OUT)
    if _fatal:
        print("::error::BUILD GUARD FAILED - shows.json NOT written, last good feed left in place")
        for f in _fatal:
            print(f"  FATAL: {f}")
        sys.exit(1)
    print(f"Build guard OK: {len(deduped)} shows >= floor {MIN_TOTAL_SHOWS}")

    out = {
        "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "Scraped from venue calendars + hand-added listings",
        "shows": deduped,
        # Every venue the site knows -- name, neighborhood, address -- whether
        # or not it has a show this week. The submit form suggests from this
        # list (a room that has gone quiet is exactly one someone might send a
        # show for) and fills neighborhood/address when the name matches.
        # Feed venues are unioned in so a submitted venue with no VENUE_INFO
        # row still appears once it has a show.
        "venues": _venue_directory(deduped),
    }
    # Strip internal-only keys (leading underscore, e.g. the scraper's _hand
    # retention flag) so they never reach the public feed.
    if isinstance(out, dict) and "shows" in out:
        out["shows"] = [{k: v for k, v in s.items() if not k.startswith("_")}
                        for s in out["shows"]]
        out["festivals"] = festival_summaries(out["shows"])
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    venues = len(set(s.get("venue","") for s in deduped))
    print(f"Wrote {len(deduped)} shows across {venues} venues to shows.json")
    write_clean_urls(out["shows"], out.get("venues") or [])


# ---------------------------------------------------------------------------
# Clean URLs: a real page per show and per venue, so links unfurl.
#
# The app lives at /#/show/<slug>. Everything after the # never reaches a
# server, so a pasted link previews as the homepage -- generic title, no
# poster. /show/<slug>/index.html is a real 200: the show's title, the
# poster as og:image, one line of description -- and a script that opens
# the app at the show. Nobody sees the shell; link previews and search
# engines do. Same for /venue/<slug>/.
#
# Regenerated every build from the feed plus the archive (permanent show
# pages outlive the feed). The directories are cleared first so a show that
# is gone from both stops having a page. ~1.2 KB each; git stores a new blob
# only when a page's content changes, which is rarely.
# ---------------------------------------------------------------------------
SHOW_PAGES = os.path.join(HERE, "show")
VENUE_PAGES = os.path.join(HERE, "venue")
SITE = "https://rainorshows.com"
DEFAULT_OG_IMAGE = SITE + "/og-default.png"


def _venue_slug(name):
    return re.sub(r"\s+", "-", _norm_key(name)).strip("-")


def _esc(x):
    return _html.escape(x or "", quote=True)


def _shell(title, desc, image, canonical, app_hash):
    """One clean-URL page. og:* for previews, a script for people."""
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{_esc(title)}</title>"
            f"<meta name=\"description\" content=\"{_esc(desc)}\">"
            f"<link rel=\"canonical\" href=\"{_esc(canonical)}\">"
            f"<meta property=\"og:type\" content=\"website\">"
            f"<meta property=\"og:site_name\" content=\"Rain Or Shows\">"
            f"<meta property=\"og:title\" content=\"{_esc(title)}\">"
            f"<meta property=\"og:description\" content=\"{_esc(desc)}\">"
            f"<meta property=\"og:image\" content=\"{_esc(image)}\">"
            f"<meta property=\"og:url\" content=\"{_esc(canonical)}\">"
            f"<meta name=\"twitter:card\" content=\"{'summary_large_image' if image != DEFAULT_OG_IMAGE else 'summary'}\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<meta http-equiv=\"refresh\" content=\"0; url={_esc(SITE + '/' + app_hash)}\">"
            f"<script>location.replace({json.dumps(SITE + '/' + app_hash)});</script>"
            "</head><body style=\"font-family:Georgia,serif;background:#2f5a4a;color:#f3ead7;padding:24px\">"
            f"<p>{_esc(title)}</p><p>{_esc(desc)}</p>"
            f"<p><a style=\"color:#f3ead7\" href=\"{_esc(SITE + '/' + app_hash)}\">Open on Rain Or Shows</a></p>"
            "</body></html>")


def _show_desc(s):
    bits = []
    try:
        d = datetime.date.fromisoformat(s.get("date", ""))
        bits.append(d.strftime("%A, %B %-d"))
    except Exception:
        if s.get("date"):
            bits.append(s["date"])
    if s.get("time"):
        bits.append(s["time"])
    where = s.get("venue", "")
    if s.get("neighborhood"):
        where += f", {s['neighborhood']}"
    if where:
        bits.append(where)
    if s.get("age") == "all-ages":
        bits.append("All ages")
    elif s.get("age"):
        bits.append(s["age"])
    return " \u00b7 ".join(bits)


def write_clean_urls(shows, venues):
    import shutil
    rows = list(shows)
    # Permanent pages: the archive too, so a link shared last month still
    # unfurls after the show has left the feed.
    # ... but only the last year of it: 4,412 pages on the first run, most
    # for shows nobody will link to again. A year covers any stub or
    # invite still in circulation without regenerating the whole history.
    floor = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    try:
        rows += [s for s in json.load(open(ARCHIVE)).get("shows", []) if (s.get("date") or "") >= floor]
    except Exception:
        pass
    for d in (SHOW_PAGES, VENUE_PAGES):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
    n_show = 0
    seen = set()
    for s in rows:
        slug = make_slug(s)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        title = f"{s.get('title','')} at {s.get('venue','')} \u2014 Rain Or Shows"
        img = (s.get("imageUrl") or "").strip()
        if not img.startswith("http"):
            img = DEFAULT_OG_IMAGE
        os.makedirs(os.path.join(SHOW_PAGES, slug), exist_ok=True)
        with open(os.path.join(SHOW_PAGES, slug, "index.html"), "w", encoding="utf-8") as f:
            f.write(_shell(title, _show_desc(s), img, f"{SITE}/show/{slug}/", f"#/show/{slug}"))
        n_show += 1
    n_venue = 0
    for v in venues:
        name = v.get("name") or ""
        vs = _venue_slug(name)
        if not name or not vs:
            continue
        upcoming = [s for s in shows if s.get("venue") == name]
        desc = (f"{len(upcoming)} upcoming show{'s' if len(upcoming) != 1 else ''}" if upcoming else "Live music venue")
        if v.get("neighborhood"):
            desc += f" \u00b7 {v['neighborhood']}"
        if v.get("address"):
            desc += f" \u00b7 {v['address']}"
        img = next((s.get("imageUrl") for s in upcoming if (s.get("imageUrl") or "").startswith("http")), DEFAULT_OG_IMAGE)
        os.makedirs(os.path.join(VENUE_PAGES, vs), exist_ok=True)
        with open(os.path.join(VENUE_PAGES, vs, "index.html"), "w", encoding="utf-8") as f:
            f.write(_shell(f"{name} \u2014 Rain Or Shows", desc, img, f"{SITE}/venue/{vs}/", f"#/venue/{vs}"))
        n_venue += 1
    n_fest = 0
    fest_dir = os.path.join(HERE, "festival")
    shutil.rmtree(fest_dir, ignore_errors=True)
    for f in load_festivals():
        slug = f["slug"]
        os.makedirs(os.path.join(fest_dir, slug), exist_ok=True)
        lineup = f.get("lineup") or []
        desc = f"{f.get('start','')} to {f.get('end','')}"
        if f.get("neighborhood"):
            desc += f" \u00b7 {f['neighborhood']}"
        desc += f" \u00b7 {len(lineup)} sets"
        img = (f.get("imageUrl") or "").strip()
        with open(os.path.join(fest_dir, slug, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(_shell(f"{f['name']} \u2014 Rain Or Shows", desc, img if img.startswith("http") else DEFAULT_OG_IMAGE,
                            f"{SITE}/festival/{slug}/", f"#/festival/{slug}"))
        n_fest += 1
    print(f"Wrote {n_show} show pages, {n_venue} venue pages and {n_fest} festival pages (clean URLs)")


if __name__ == "__main__":
    main()
