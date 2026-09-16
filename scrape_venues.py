#!/usr/bin/env python3
"""
PortlandLive venue scraper.

Scrapes venues' OWN published calendars and writes manual_shows.json, which
build_shows.py merges into shows.json. Uses BeautifulSoup for robust HTML parsing
(handles real-world attribute order, nesting, entities) — no API key, no browser.

Sources:
  - Mammoth NW / Double Tee (roselandpdx.com): one page lists Roseland, Hawthorne,
    Aladdin, Crystal Ballroom, Wonder, Revolution Hall, Mississippi, Holocene,
    Star Theater, Alberta Rose, the big halls.
  - Dante's (danteslive.com): venue's own TicketWeb calendar, paginated.

Run:  pip install requests beautifulsoup4 && python3 scripts/scrape_venues.py
"""
import re, json, os, sys, time, datetime

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("pip install requests beautifulsoup4")

MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
HORIZON_DAYS = 90

# Shared Pacific tzinfo for the Squarespace-derived parsers (Alberta
# Street Pub, Havalina, etc.) -- these all call .astimezone(_ASP_PDT) on
# a UTC epoch-ms startDate. This constant was referenced in 8 places but
# never actually assigned anywhere in the file, so every one of those
# parsers raised NameError on every real run (caught -- and hidden -- by
# scrape()'s per-source try/except, silently zeroing their output).
try:
    from zoneinfo import ZoneInfo
    _ASP_PDT = ZoneInfo("America/Los_Angeles")
except Exception:
    _ASP_PDT = datetime.timezone(datetime.timedelta(hours=-7))

MONTHS_FULL = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July",
     "August","September","October","November","December"], 1)}

# Venues identifiable by their etix URL slug (Mississippi Studios site lists both
# Mississippi Studios and Polaris Hall; Revolution Hall shares the same network).
VENUE_BY_SLUG = {
    "mississippi-studios": "Mississippi Studios",
    "polaris-hall": "Polaris Hall",
    "revolution-hall": "Revolution Hall",
}

VENUE_INFO = {
    "Dublin Pub": ("Raleigh Hills", "6821 SW Beaverton-Hillsdale Hwy, Portland, OR 97225"),
    "Kelly's Olympian": ("Downtown", "426 SW Washington St, Portland, OR 97204"),
    "Barrel Room": ("Old Town/Chinatown", "120 NW Couch St, Portland, OR 97209"),
    "Arbor Beer Lodge": ("Arbor Lodge", "6550 N Interstate Ave, Portland, OR 97217"),
    "Artichoke Music": ("Brooklyn", "2007 SE Powell Blvd, Portland, OR 97202"),
    "NOVA PDX": ("Buckman", "722 E Burnside St, Portland, OR 97214"),
    "Roseland Theater": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Peter's Room (Roseland)": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Roseland Ballroom": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Hawthorne Theatre": ("Mt Tabor/Hawthorne", "1507 SE 39th Ave"),
    # The lounge is the small room inside the Theatre; same address. Without
    # this entry its five shows fell through to the parser's "Roseland
    # Theater" default.
    "Hawthorne Lounge": ("Mt Tabor/Hawthorne", "1507 SE 39th Ave"),
    "Kenton Club": ("Kenton", "2025 N Kilpatrick St"),
    "Spare Room": ("Cully", "4830 NE 42nd Ave"),
    "Switchback Saloon": ("Richmond", "4847 SE Division St"),
    "Aladdin Theater": ("Brooklyn", "3017 SE Milwaukie Ave"),
    "Crystal Ballroom": ("Downtown", "1332 W Burnside St"),
    "McMenamins Edgefield": ("Troutdale", "2126 SW Halsey St, Troutdale"),
    "McMenamins Grand Lodge": ("Forest Grove", "3505 Pacific Ave, Forest Grove"),
    "White Eagle Saloon": ("Boise/Eliot", "836 N Russell St, Portland, OR 97227"),
    "Al's Den": ("West End/Downtown", "303 SW 12th Ave, Portland, OR 97205"),
    "Mission Theater": ("Nob Hill/NW", "1624 NW Glisan St, Portland, OR 97209"),
    "Kennedy School": ("Concordia", "5736 NE 33rd Ave, Portland, OR 97211"),
    "The Goodfoot": ("Buckman", "2845 SE Stark St, Portland, OR 97214"),
    "Music Millennium": ("Kerns", "3158 E Burnside St, Portland, OR 97214"),
    "Arlene Schnitzer Concert Hall": ("Downtown", "1037 SW Broadway"),
    "Paramount Theatre": ("Downtown", "911 SW Salmon St"),
    "The Old Church": ("Downtown", "1422 SW 11th Ave"),
    "Ponderosa Lounge & Grill": ("North Portland", "10350 N Vancouver Way"),
    "Wonder Ballroom": ("Eliot/Boise", "128 NE Russell St"),
    "Revolution Hall": ("Buckman", "1300 SE Stark St"),
    "Process": ("Sellwood-Moreland", "5040 SE Milwaukie Ave, Portland, OR 97202"),
    "Old Market Pub": ("Multnomah Village", "6959 SW Multnomah Blvd, Portland, OR 97223"),
    "The Headliners Club": ("Lake Oswego", "17880 SW McEwan Rd, Lake Oswego, OR 97035"),
    "Realm": ("Central Eastside", "615 SE Alder St, Portland, OR 97214"),
    "The Den": ("Central Eastside", "116 SE Yamhill St, Portland, OR 97214"),
    "Polaris Hall": ("Overlook/N Portland", "635 N Killingsworth Ct"),
    "Mississippi Studios": ("Boise/Mississippi", "3939 N Mississippi Ave"),
    "Havalina": ("St. Johns", "8927 N Lombard St, Portland, OR 97203"),
    "Starday Tavern": ("Brentwood-Darlington", "6517 SE Foster Rd, Portland, OR 97206"),
    "Holocene": ("Central Eastside", "1001 SE Morrison St"),
    "Dante's": ("Old Town/Chinatown", "350 W Burnside St"),
    "Star Theater": ("Old Town/Chinatown", "13 NW 6th Ave"),
    "The Get Down": ("Central Eastside", "615 SE Alder St"),
    "Showdown Saloon": ("Central Eastside", ""),
    "Alberta Rose Theatre": ("Alberta Arts", "3000 NE Alberta St"),
    "Arlene Schnitzer Concert Hall": ("Downtown", "1037 SW Broadway"),
    "Keller Auditorium": ("Downtown", "222 SW Clay St"),
    "Newmark Theatre": ("Downtown", "1111 SW Broadway"),
    "Brunish Theatre": ("Downtown", "1111 SW Broadway"),
    "Winningstad Theatre": ("Downtown", "1111 SW Broadway"),
    "Main Street": ("Downtown", "SW Main St"),
    "Moda Center": ("Lloyd/Rose Quarter", "1 N Center Ct St"),
    "Veterans Memorial Coliseum": ("Lloyd/Rose Quarter", "300 N Winning Way"),
    "Theater of the Clouds": ("Lloyd/Rose Quarter", "1 N Center Ct St"),
    "Jack London Revue": ("Downtown", "529 SW 4th Ave"),
    "Pioneer Courthouse Square": ("Downtown", "701 SW 6th Ave"),
    "Twilight Cafe & Bar": ("Hosford-Abernethy", "1420 SE Powell Blvd"),
    "No Fun": ("Buckman", "1709 SE Hawthorne Blvd"),
    "Bunk Bar": ("Central Eastside", "1028 SE Water Ave"),
    "Mississippi Pizza": ("Boise", "3552 N Mississippi Ave"),
    "Laurelthirst Public House": ("Kerns", "2958 NE Glisan St"),
    "Alberta Street Pub": ("Alberta Arts", "1036 NE Alberta St"),
    "Tomorrow's Verse": ("Beaumont-Wilshire", "4605 NE Fremont St, Portland, OR 97213"),
    "Cascades Amphitheater": ("Ridgefield, WA", "17200 NE Delfel Rd, Ridgefield, WA 98642"),
    # Columbia Gorge (Sep 2026). Outside Portland, so neighborhood is the
    # town, the way Cascades Amphitheater does it.
    "Trout Lake Hall": ("Trout Lake, WA", "15 Guler Rd, Trout Lake, WA 98650"),
    "The Ruins": ("Hood River, OR", "13 Railroad St, Hood River, OR 97031"),
}

def clean(s):
    s = (s or "").replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", s).strip()

def to_time(s):
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*([ap])m', s, re.I)
    if not m:
        return ""
    h = int(m.group(1)); mm = m.group(2) or "00"; ap = m.group(3).upper()
    return f"{h}:{mm} {ap}M"

def infer_year(month, today):
    return today.year + 1 if month < today.month else today.year

class ChallengeError(Exception):
    """Raised when a response looks like a bot-wall / WAF challenge rather than
    real content, so per-venue isolation flags + skips it instead of parsing
    the challenge page as 0 events."""


_CHALLENGE_STATUS = {202, 403, 415, 429}
# Strong challenge signatures only. Deliberately NOT triggering on the bare
# word "captcha" (Laurelthirst's page has it as a harmless form label).
_CHALLENGE_SIGS = ("One moment", "Just a moment", "awsWafCookieDomainList", "gokuProps")


_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _challenged(r):
    if r.status_code in _CHALLENGE_STATUS:
        return f"status {r.status_code}"
    for sig in _CHALLENGE_SIGS:
        if sig in r.text:
            return f"signature {sig!r}"
    return None


def fetch(url):
    r = requests.get(url, headers={"User-Agent":
        "Mozilla/5.0 (compatible; PortlandLive/1.0; listings aggregator)"}, timeout=30)
    why = _challenged(r)
    if why:
        # Some venues (e.g. WordPress hardened with a WAF) reject the aggregator UA.
        # Retry once with a plain browser UA before giving up.
        r = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=30)
        why = _challenged(r)
        if why:
            raise ChallengeError(f"challenge {why} from {url}")
    r.raise_for_status()
    return r.text


# ---- Per-show age restriction ------------------------------------------------
# Most venues in this feed publish an age restriction PER SHOW, in the same
# listing HTML we already fetch -- we were simply throwing it away. Reading it
# is strictly better than inferring a house policy: Aladdin's own FAQ says most
# of its shows are all-ages but to check the event page, and Wonder's listing
# carries both "all ages" and "ages 21 +" on different nights. A venue-level
# default would assert one answer for every show and be wrong on the exceptions.
#
# Three template families emit it, found by probing the live pages:
#   .event-age-restriction  (WLCR theme)   Revolution Hall, Mississippi/Polaris
#   .eventAgeRestriction    (RHP/Elementor) Holocene, Wonder, Miss. Pizza, Monqui
#   .age-restriction        (Suki child)    Dante's
# Monqui's carries d-none (visually hidden, still in the DOM) -- fine, we read
# the markup, not the rendering.
_AGE_SEL = ".event-age-restriction, .eventAgeRestriction, .age-restriction, .rhp-event-notes-box"

# Deliberately conservative. Anything unrecognized returns "" (UNKNOWN) rather
# than a guess: a wrong age sends someone to a door they can't get through, and
# "" is already a first-class state everywhere downstream.
_AGE_ALL_RE = re.compile(r"\ball\s*ages\b", re.I)
_AGE_21_RE = re.compile(r"(?<![$\d.])\b(?:ages?\s*)?21\s*(?:\+|&|and)?\s*(?:over|up|plus)?\b", re.I)
_AGE_18_RE = re.compile(r"(?<![$\d.])\b(?:ages?\s*)?18\s*(?:\+|&|and)?\s*(?:over|up|plus)?\b", re.I)


# A restriction qualified by a time or a companion is NOT the same claim as the
# bare one. "All ages until 9pm" tells a parent their kid gets in; it does not
# tell them the kid gets thrown out mid-set. The three-value field cannot hold
# the qualifier, so these resolve to UNKNOWN rather than to the half-truth.
_AGE_CONDITIONAL = re.compile(
    r"\b(?:until|till|til|before|after|w/?\s*(?:a\s+)?(?:parent|guardian|adult)|"
    r"with\s+(?:a\s+)?(?:parent|guardian|adult)|accompanied)\b", re.I)


def _norm_age(text):
    """Normalize a venue's printed age restriction to the feed's vocabulary.

    Returns '21+', '18+', 'all-ages', or '' (unknown). Checked most-restrictive
    first so a string carrying both ("All Ages / 21+ to drink") resolves to the
    restriction on ENTRY, which is what the field means."""
    t = clean(text or "")
    if not t:
        return ""
    if _AGE_CONDITIONAL.search(t):
        return ""
    if _AGE_21_RE.search(t):
        return "21+"
    if _AGE_18_RE.search(t):
        return "18+"
    if _AGE_ALL_RE.search(t):
        return "all-ages"
    # Seen in the wild and deliberately NOT mapped: "Minors w/ parent or
    # guardian", "All ages until 9pm". Both are real door policies that the
    # three-value field cannot express, and flattening them to either answer
    # would be a lie. They stay unknown until the field can hold them.
    return ""


# Scanning a whole event BLURB is different from reading a dedicated age
# element, and needs a stricter pattern. _AGE_21_RE makes its trailing marker
# optional -- fine when the element contains nothing but the age, but in prose a
# bare "21" appears in dates ("Sat, Sep 21"), prices and street numbers. These
# require an explicit marker, so only a real age statement matches.
_AGE_TXT_ALL = re.compile(r"\ball\s*ages\b", re.I)
_AGE_TXT_21 = re.compile(r"(?<![$\d.])\b(?:ages?\s*)?21\s*(?:\+|&\s*(?:over|up)|and\s+(?:over|up)|\s*over)", re.I)
_AGE_TXT_18 = re.compile(r"(?<![$\d.])\b(?:ages?\s*)?18\s*(?:\+|&\s*(?:over|up)|and\s+(?:over|up)|\s*over)", re.I)


def _age_in_text(text):
    """Read an age restriction out of a longer event blurb, or ''.

    For parsers that have no per-event element to read -- Jack London Revue
    prints "Doors: 7:00pm Show: 8:00pm Ages 21+." inside a description that
    then runs on into the artist bio. Same conservative contract as _norm_age:
    unrecognized or conditional means UNKNOWN, never a guess.

    The conditional check is scoped to a window around the age phrase, not the
    whole blurb. Checking the whole text was how every Jack London show came
    back unknown: "George Benson's reaction after hearing the Mel Brown B-3
    Organ Group" contains "after", and the guard read that as an "all ages
    until/after 9pm" qualifier. A qualifier that actually modifies the age
    sits next to it; one three sentences into a bio does not."""
    t = clean(text or "")
    if not t:
        return ""
    for rx, val in ((_AGE_TXT_21, "21+"), (_AGE_TXT_18, "18+"), (_AGE_TXT_ALL, "all-ages")):
        m = rx.search(t)
        if not m:
            continue
        window = t[max(0, m.start() - 40):m.end() + 40]
        if _AGE_CONDITIONAL.search(window):
            return ""
        return val
    return ""


def _age_map_by_event_url(soup, max_up=6):
    """Map each event URL on a listing page to its age, or {}.

    For RHP-family listings (Wonder, Roseland, Monqui) where the age element is
    NOT inside the event container the parser iterates -- probing the live pages
    showed 0 of 50 Wonder thumbs and 0 of 47 Roseland thumbs contain one; the
    thumb holds only the date. So instead of searching down from the event,
    search UP from each age node to the card that owns it.

    An age is only claimed while the ancestor holds exactly ONE distinct event
    URL. Past that the card boundary is gone and the age could belong to a
    neighbouring show, so it is dropped rather than guessed.

    Junk nodes fall out for free: Wonder emits 78 age elements for 50 events
    because .cust_age placeholders contain just a comma, and _norm_age turns
    those into '' which is skipped."""
    out = {}
    for node in soup.select(_AGE_SEL):
        age = _norm_age(node.get_text(" ", strip=True))
        if not age:
            continue
        anc = node
        for _ in range(max_up):
            anc = anc.parent
            if anc is None or getattr(anc, "name", None) is None:
                break
            hrefs = {a["href"].split("?")[0]
                     for a in anc.select('a[href*="/event/"]') if a.get("href")}
            if len(hrefs) == 1:
                out.setdefault(hrefs.pop(), age)
                break
            if len(hrefs) > 1:
                break
    return out


_RHP_IMG_SEL = "img.rhp-event__image--list, .rhp-events-event-image img, img.eventListImage"


def _img_map_by_event_url(soup, max_up=6):
    """Map each event URL on an RHP listing to its poster, or {}.

    Same shape as _age_map_by_event_url: the poster <img> is not inside the
    thumb the parser iterates, so search UP from each image to the card that
    owns exactly one event URL. Roseland and Hawthorne carry a poster on
    every card (47/47, 61/61 on captured pages) and the parsers never read
    them -- 42% of the feed had an image, and the misses were exactly the
    template venues that always have one."""
    out = {}
    for im in soup.select(_RHP_IMG_SEL):
        src = (im.get("src") or im.get("data-src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        anc = im
        for _ in range(max_up):
            anc = anc.parent
            if anc is None or getattr(anc, "name", None) is None:
                break
            hrefs = {a["href"].split("?")[0]
                     for a in anc.select('a[href*="/event/"]') if a.get("href")}
            if len(hrefs) == 1:
                out.setdefault(hrefs.pop(), src)
                break
            if len(hrefs) > 1:
                break
    return out


def _age_positional(soup, n_events):
    """Ages for a listing whose parser has no per-event container at all.

    Wonder Ballroom keys events by slug off loose anchors, so there is nothing
    to scope a lookup to. Its parser already pairs show times to events by
    document order, and the age divs sit in the same order.

    Positional pairing is only safe while the counts line up exactly -- one
    missing age would shift every later show onto the wrong door policy, which
    is precisely the mislabelling worth avoiding. So this returns a usable list
    ONLY on an exact match, and otherwise gives back nothing and leaves every
    show unknown."""
    nodes = soup.select(".eventAgeRestriction, .event-age-restriction, .age-restriction")
    if len(nodes) != n_events:
        return None
    return [_norm_age(n.get_text(" ", strip=True)) for n in nodes]


def _age_from(el):
    """Read the age restriction out of one event's container element, or ''."""
    if el is None:
        return ""
    for node in el.select(_AGE_SEL):
        age = _norm_age(node.get_text(" ", strip=True))
        if age:
            return age
    return ""


def _age_near(el, max_up=6):
    """Age for an event whose age element sits OUTSIDE its own container.

    Monqui is the case: the parser iterates .rhp-event-thumb, but the
    .eventAgeRestriction div lives five levels up in a sibling branch, so
    _age_from(thumb) finds nothing. Hardcoding the intervening class names
    (.bottomSection, .rhp-event-info) would break the next time Elementor
    reshuffles the card.

    Instead, climb until an ancestor contains an age element -- but only accept
    it while that ancestor still holds exactly ONE event link. The moment an
    ancestor covers two events we have left the card and any age we read could
    belong to the wrong show, so we stop and return unknown. That makes the
    card boundary self-validating rather than a guess about markup."""
    if el is None:
        return ""
    node = el
    for _ in range(max_up):
        node = node.parent
        if node is None or getattr(node, "name", None) is None:
            break
        # Left the card once a SECOND, DIFFERENT event is in scope -- an age
        # read here could be the neighbouring show's. Unknown beats wrong.
        #
        # Count distinct hrefs, not <a> elements: one card links to its own
        # event several times (artwork, title, ticket button), so counting
        # elements made this trip on the very first step and the walk never
        # got anywhere. That is exactly why the first Monqui attempt changed
        # nothing -- Crystal and Edgefield stayed unknown.
        hrefs = {a["href"].split("?")[0].rstrip("/")
                 for a in node.select('a[href*="/event/"]') if a.get("href")}
        if len(hrefs) > 1:
            break
        age = _age_from(node)
        if age:
            return age
    return ""


def _img_from(el, needle):
    """First <img> src under el whose src/data-src contains needle, else ''."""
    if el is None:
        return ""
    for im in el.find_all("img"):
        s = im.get("src") or im.get("data-src") or ""
        if needle in s:
            return s.strip()
    return ""

def _bump(url):
    """Bump HoldMyTicket Cloudinary thumbnail width to a larger size."""
    return url.replace("/w_225/", "/w_600/") if url else url

# ---- Mammoth NW (roselandpdx.com) --------------------------------------------
# On the live page each event has SEPARATE links: one whose text is just the date
# ("Fri, Jun 05") and another whose text is the title. We trigger on the date-link,
# then find the title-link within the same event block.
DATE_ONLY = re.compile(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Z][a-z]{2})\s+(\d{1,2})')

def _normalize_ws(s):
    # turn every kind of unicode space (incl. \xa0 nbsp) into a plain space
    return re.sub(r'\s+', ' ', re.sub(r'[\u00a0\u2009\u202f\u200b]', ' ', s or '')).strip()

def date_link_match(text):
    """True only when link text is essentially just a date (short), tolerant of
    any unicode whitespace. Returns the regex match or None."""
    t = _normalize_ws(text)
    if len(t) > 18:
        return None
    return DATE_ONLY.search(t)

def parse_mammoth(html, today):
    soup = BeautifulSoup(html, "html.parser")
    # All anchors in document order. Events appear as: [date-link][title-link]...
    # [venue-link][etix-link][More Info-link], then the next event's date-link.
    anchors = soup.find_all("a", href=True)
    # Roseland prints the age in a .rhp-event-notes-box that sits OUTSIDE the
    # event thumb (0 of 47 thumbs contain one), and outside the `seg` text
    # window this parser builds -- which is why scanning seg found nothing.
    # Resolve it by event URL instead.
    age_by_url = _age_map_by_event_url(soup)
    img_by_url = _img_map_by_event_url(soup)
    shows = []
    seen = set()

    for i, a in enumerate(anchors):
        if "/event/" not in a["href"]:
            continue
        m = date_link_match(a.get_text())
        if not m:
            continue
        url = a["href"].split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        mon = MONTHS[m.group(2)]; day = int(m.group(3))
        date = f"{infer_year(mon, today)}-{mon:02d}-{day:02d}"

        # Look ahead in document order for this event's details, stopping when we
        # reach the NEXT event's date-link.
        title, venue, tix, support, showtime = "", "Roseland Theater", url, "", ""
        for b in anchors[i+1:i+12]:
            bt = clean(b.get_text())
            href = b.get("href", "")
            if "/event/" in href and date_link_match(b.get_text()):
                break  # next event started
            if not title and "/event/" in href and bt and bt.lower() != "more info":
                title = bt
            if "/venue/" in href and bt in VENUE_INFO:
                venue = bt
            if "etix.com" in href:
                tix = b["href"]
        if not title:
            continue

        # support act + show time: collect the elements BETWEEN this date anchor and
        # the next event's date anchor (document order), and read them from there.
        between = []
        for el in a.next_elements:
            # stop at the next event date-link
            if getattr(el, "name", None) == "a" and "/event/" in (el.get("href") or "") \
               and date_link_match(el.get_text()):
                break
            between.append(el)
            # Was 60. The show time sits 75-89 elements past the date link
            # on both roselandpdx.com and hawthornetheatre.com (measured on
            # captured pages, Sep 2026), so the window closed before
            # reaching it and every Roseland show shipped without a time --
            # 0 of 41 in the live feed while every other RHP venue was
            # 100%. Nothing flagged it: a missing time is not an error, the
            # row is still valid, it just says less. 160 leaves headroom.
            if len(between) > 160:
                break
        seg = clean(" ".join(getattr(el, "string", "") or "" for el in between
                             if getattr(el, "string", None)))
        sm = re.search(r'Show:\s*([\d:]+\s*[ap]m)', seg, re.I)
        if sm:
            showtime = to_time(sm.group(1))
        # Terminators widened when the window grew from 60 to 160 elements:
        # the page lists the support act twice (thumb + info) and the window
        # now also crosses HTML comments ("end event image container"), all of
        # which arrive in seg as bare strings. Without stopping at a second
        # "with", a "Show:", or a comment fragment, the capture ran on and
        # appended junk to titles -- and titles feed slugs, so that would have
        # orphaned every attendance row and comment on those shows.
        # Search for a support act only OUTSIDE the title. Some venues write
        # the support into the headline itself ("... ft. AmpLive with Special
        # Guest Brother Ali") and leave the sub-header empty; the "with" in
        # that headline then read as a support line and the title came out
        # doubled: "X with Y (w/ Y X)" -- 197 characters. Removing every copy
        # of the title from the window first means a "with" that belongs to
        # the title cannot start a capture. If the support lives only in the
        # title, the title already says it, and nothing is appended.
        seg_support = seg.replace(title, " ") if title else seg
        wm = re.search(r'\bwith\s+(.+?)(?:\s+All Ages|\s+\d+\+|\s+Doors:|\s+Show:'
                       r'|\s+with\s|\s+end\s|\s+Ages\s|\s+\d+\s*&\s*Over|$)', seg_support)
        if wm:
            support = clean(wm.group(1))

        nb, addr = VENUE_INFO.get(venue, ("Portland", ""))
        full = f"{title} (w/ {support})" if support else title
        shows.append({"title": full, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix,
                      "imageUrl": img_by_url.get(url.split("?")[0], ""),
                      # Keyed on the /event/ page URL (`url`), not `tix`: tix is
                      # overwritten with the etix.com ticket link, which is not
                      # what the age map is keyed by. Verified against the real
                      # page: the map resolves 46 of 47 events; the tix lookup
                      # resolved 1.
                      "age": age_by_url.get(url.split("?")[0], "") or _age_in_text(seg)})

    if not shows:
        ev_links = [a for a in soup.find_all("a", href=True) if "/event/" in a["href"]]
        print(f"    [debug] event-links found={len(ev_links)}")
        for a in ev_links[:6]:
            raw = a.get_text()
            print(f"    [debug] raw={raw!r} norm={_normalize_ws(raw)!r} match={bool(date_link_match(raw))}")
    return shows

# ---- Dante's (danteslive.com) ------------------------------------------------
# Each event has an <a href=".../tm-event/..." title="TITLE - DD/MM/YY"> plus a
# nearby "Show: N pm" and a ticketweb link.
DANTES_DATE = re.compile(r'-\s*(\d{2})/(\d{2})/(\d{2})\s*$')

def parse_dantes(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    for a in soup.find_all("a", href=True, title=True):
        if "/tm-event/" not in a["href"]:
            continue
        title_attr = a.get("title", "")
        m = DANTES_DATE.search(title_attr)
        if not m:
            continue
        # event header anchor (the text one; skip if it wraps only an <img>)
        link_text = clean(a.get_text())
        if not link_text:  # image-only anchor, skip; the text anchor has the same title
            continue
        url = a["href"].split("?")[0]
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        date = f"20{yy:02d}-{mm:02d}-{dd:02d}"
        key = (url, date)
        if key in seen:
            continue
        seen.add(key)
        title = clean(re.sub(r'-\s*\d{2}/\d{2}/\d{2}\s*$', '', title_attr))
        # show time + ticketweb from the enclosing block
        block = a.find_parent(["article", "div", "li"]) or a.parent
        # find_parent takes the TIGHTEST match, and on danteslive.com that is
        # the .tw-name wrapper -- 17 characters of text, no time in it. The
        # .tw-event-time-complete element sits one level up. So climb until
        # the block holds a time element, but only while it still holds
        # exactly one event name; past that we'd be reading the neighbour's
        # card. Measured on the captured page: 0 of 48 shows had a time
        # before, 48 of 48 after.
        for _ in range(4):
            if block.select_one(".tw-event-time-complete, .tw-event-time"):
                break
            up = block.parent
            if up is None or getattr(up, "name", None) is None:
                break
            if len(up.select(".tw-name")) != 1:
                break
            block = up
        btext = clean(block.get_text(" "))
        sm = re.search(r'Show:\s*([\d:]+\s*[ap]m)', btext, re.I)
        showtime = to_time(sm.group(1)) if sm else ""
        # venueUrl stays the venue's own event page: it carries the
        # description, poster and door info, and it is the venue's own
        # property. ticketUrl is the ticketing platform link, stored
        # separately so an affiliate wrapper can be applied to it later
        # without touching the venue link or the render.
        # The TicketWeb link is in .tw-info-price-buy-tix, which sits under
        # the event's .tw-section -- outside `block`, which stops as soon as
        # it holds a time element. Climb to the section, but only while it
        # still holds exactly one event name, so a neighbour's ticket link
        # can never be attached to this show.
        scope = block
        for _ in range(4):
            if scope.find("a", href=re.compile(r'ticketweb\.com')):
                break
            up = scope.parent
            if up is None or getattr(up, "name", None) is None:
                break
            if len(up.select(".tw-name")) != 1:
                break
            scope = up
        tlink = scope.find("a", href=re.compile(r'ticketweb\.com'))
        tixurl = tlink["href"] if tlink else ""
        # The poster (img.event-img on i.ticketweb.com) sits in the same
        # scope as the ticket link. Same helper Star Theater and JLR use.
        img = _img_from(scope, "i.ticketweb.com")
        tix = url
        nb, addr = VENUE_INFO["Dante's"]
        shows.append({"title": title, "venue": "Dante's", "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix,
                      "ticketUrl": tixurl,
                      "imageUrl": img, "age": _age_from(block) or _age_in_text(btext)})
    return shows


# ---- Mississippi Studios + Polaris Hall (mississippistudios.com) --------------
# One page lists both venues (and sometimes Revolution Hall). The etix ticket URL
# slug (...-portland-<venue>) is the reliable venue signal. Date comes from the
# "Weekday, Month D, YYYY" headings above each event.
MS_DATE_HDR = re.compile(r'(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})')

def _venue_from_etix(url):
    for slug, name in VENUE_BY_SLUG.items():
        if slug in url:
            return name
    return None

# ---- Wonder Ballroom (wonderballroom.com/events/) ----------------------------
# In document order each event is: a dated /event/ link ("Sat, Jun 06, 2026")
# (sometimes duplicated), then the title /event/ link, then optional <h4> support,
# "Doors : 7 pm, Show : 8 pm", and an etix link. Trigger on the dated link, pair
# with the next non-date /event/ link for the title, then walk forward from the
# title for support/time/tickets. Dedupe on the /event/ slug.
WB_DATE = re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),\s+(\d{4})')

def parse_wonder(html, today):
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)
    shows = []
    seen = set()
    for i, a in enumerate(anchors):
        if "/event/" not in a["href"]:
            continue
        m = WB_DATE.search(clean(a.get_text()))
        if not m:
            continue
        slug = a["href"].split("?")[0]
        if slug in seen:
            continue
        seen.add(slug)
        date = f"{int(m.group(3))}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
        title, title_anchor = "", None
        for b in anchors[i+1:i+8]:
            if "/event/" not in b["href"]:
                continue
            bt = clean(b.get_text())
            if not bt or WB_DATE.search(bt) or bt.lower() == "more info":
                continue
            title, title_anchor = bt, b
            break
        if not title_anchor:
            continue
        support, showtime, tix = "", "", slug
        for el in title_anchor.find_all_next(["a", "h4", "div", "h2"], limit=14):
            if el.name == "a" and "/event/" in (el.get("href") or "") \
               and WB_DATE.search(clean(el.get_text())):
                break
            etx = clean(el.get_text())
            if el.name == "h4" and not support:
                support = re.sub(r'^(With special guests?|with)\s+', '', etx, flags=re.I).strip()
            sm = re.search(r'Show\s*:\s*([\d:]+\s*[ap]m)', etx, re.I)
            if sm and not showtime:
                showtime = to_time(sm.group(1))
            if el.name == "a" and "etix.com" in (el.get("href") or ""):
                tix = el["href"]
        full = f"{title} (w/ {support})" if support else title
        shows.append({"title": full, "venue": "Wonder Ballroom",
                      "neighborhood": "Eliot/Boise", "address": "128 NE Russell St",
                      "date": date, "time": showtime, "venueUrl": tix, "imageUrl": ""})
    if not shows:
        ev = [a for a in anchors if "/event/" in a["href"]]
        print(f"    [debug-wb-v2] event-links={len(ev)}")
        for a in ev[:5]:
            print(f"    [debug-wb-v2] text={clean(a.get_text())!r}")
    return shows

# ---- Mississippi Studios + Polaris Hall (mississippistudios.com) --------------
# One page lists both venues (and sometimes Revolution Hall). The etix ticket URL
# slug (...-portland-<venue>) is the reliable venue signal. Date comes from the
# "Weekday, Month D, YYYY" headings above each event.
MS_DATE_HDR = re.compile(r'(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})')

def _venue_from_etix(url):
    for slug, name in VENUE_BY_SLUG.items():
        if slug in url:
            return name
    return None

_ETIX_HREF = re.compile("etix[.]com")
_ETIX_CDN = re.compile("cdn[.]etix[.]com")


def parse_msstudios(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    cur_date = None
    # Walk headings and content in document order.
    for el in soup.find_all(["h5", "h2", "h4", "p", "div"]):
        t = clean(el.get_text())
        if el.name == "h5":
            m = MS_DATE_HDR.search(t)
            if m and m.group(1) in MONTHS_FULL:
                cur_date = f"{int(m.group(3))}-{MONTHS_FULL[m.group(1)]:02d}-{int(m.group(2)):02d}"
            continue
        if el.name == "h2":
            a = el.find("a", href=True)
            if not a or "etix.com" not in (a.get("href") or ""):
                continue
            url = a["href"]
            venue = _venue_from_etix(url)
            if not venue or not cur_date:
                continue
            key = (url, cur_date)
            if key in seen:
                continue
            seen.add(key)
            title = re.sub(r'^SOLD OUT:\s*', '', clean(a.get_text()))
            # show time + support from following siblings until next h2/h5
            support, showtime = "", ""
            for sib in el.find_all_next(["h2", "h5", "h4", "div", "p"], limit=8):
                if sib.name in ("h2", "h5"):
                    break
                st = clean(sib.get_text())
                if sib.name == "h4" and not support:
                    support = st
                sm = re.search(r'Show:\s*([\d:]+\s*[AP]M)', st, re.I)
                if sm and not showtime:
                    showtime = to_time(sm.group(1))
            nb, addr = VENUE_INFO.get(venue, ("Portland", ""))
            full = f"{title} (w/ {support})" if support else title
            # The poster is a cdn.etix.com image in .event__inner, two levels
            # above the h2. Climb only while the ancestor holds exactly one
            # event heading, so a neighbour's poster is never attached. 30 of
            # 60 events carried one on the captured page; the rest are blank.
            img = ""
            box = el
            for _ in range(4):
                box = box.parent
                if box is None or getattr(box, "name", None) is None:
                    break
                if len([h for h in box.find_all("h2") if h.find("a", href=_ETIX_HREF)]) != 1:
                    break
                cand = box.find("img", src=_ETIX_CDN)
                if cand:
                    img = cand["src"]
                    break
            shows.append({"title": full, "venue": venue, "neighborhood": nb,
                          "address": addr, "date": cur_date, "time": showtime, "venueUrl": url,
                          "imageUrl": img})
    return shows


# ---- Wonder Ballroom (wonderballroom.com/events/) ----------------------------
# Each event: a dated /event/ link ("Fri, May 29, 2026"), a title <h2>, optional
# <h4> support, "Doors : 7 pm, Show : 8 pm", and an etix ticket link.
WB_DATE = re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),\s+(\d{4})')

def parse_wonder(html, today):
    soup = BeautifulSoup(html, "html.parser")
    events = {}
    for a in soup.find_all("a", href=True):
        if "/event/" not in a["href"]:
            continue
        slug = a["href"].split("?")[0]
        txt = clean(a.get_text())
        e = events.setdefault(slug, {"date": None, "title": None})
        m = WB_DATE.search(txt)
        if m and not e["date"]:
            e["date"] = f"{int(m.group(3))}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
        elif txt and txt.lower() != "more info" and not m and not e["title"]:
            e["title"] = txt

    # show times appear in document order as "Show : 8 pm" per event
    show_times = re.findall(r'Show\s*:?\s*([\d:]+\s*[apAP][mM])', soup.get_text(" "))
    # Ages come from the card that owns each event link, not from the thumb --
    # a live probe found 0 of 50 thumbs contain an age element.
    age_by_url = _age_map_by_event_url(soup)
    img_by_url = _img_map_by_event_url(soup)
    shows = []
    ti = 0
    for slug, e in events.items():
        if not e["date"] or not e["title"]:
            continue
        tix = slug
        for a in soup.find_all("a", href=True):
            if "etix.com" in a["href"] and e["title"][:12].lower() in clean(a.get("title", "")).lower():
                tix = a["href"]
                break
        showtime = to_time(show_times[ti]) if ti < len(show_times) else ""
        ti += 1
        shows.append({"title": e["title"], "venue": "Wonder Ballroom",
                      "neighborhood": "Eliot/Boise", "address": "128 NE Russell St",
                      "date": e["date"], "time": showtime, "venueUrl": tix,
                      "imageUrl": img_by_url.get(slug.split("?")[0], ""),
                      "age": age_by_url.get(slug.split("?")[0], "")})
    return shows
# ---- Holocene (holocene.org/events/) -----------------------------------------
# Each event: a title <h2> linking to /event/... with an etix ticket link whose
# slug ends -portland-holocene, a "Day, Mon DD" date line, "Doors: X pm", and an
# optional presenter line. Same etix-slug approach as Mississippi/Polaris.
HOLO_DATE = re.compile(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\b')

def parse_holocene(html, today):
    soup = BeautifulSoup(html, "html.parser")
    img_by_url = _img_map_by_event_url(soup)  # 60/60 on the captured page
    text = clean(soup.get_text(" "))
    events = {}
    order = []
    for a in soup.find_all("a", href=True):
        if "/event/" not in a["href"]:
            continue
        slug = a["href"].split("?")[0]
        txt = clean(a.get_text())
        if slug not in events:
            events[slug] = {"title": None, "tix": None}
            order.append(slug)
        if txt and txt.lower() != "more info" and not events[slug]["title"]:
            events[slug]["title"] = txt
        if "etix.com" in a["href"] and "-holocene" in a["href"] and not events[slug]["tix"]:
            events[slug]["tix"] = a["href"]
    # dates appear in document order as "Day, Mon DD" lines; map them to events by order
    dates = HOLO_DATE.findall(text)
    times = re.findall(r'Doors?:?\s*([\d:]+\s*[apAP][mM])', text)
    shows = []
    di = 0
    for slug in order:
        e = events[slug]
        if not e["title"]:
            continue
        date_iso = None
        showtime = ""
        if di < len(dates):
            _, mon, day = dates[di]
            mo = MONTHS[mon]; d = int(day)
            yr = today.year if mo >= today.month else today.year + 1
            date_iso = f"{yr}-{mo:02d}-{d:02d}"
            if di < len(times):
                showtime = to_time(times[di])
            di += 1
        if not date_iso:
            continue
        shows.append({"title": e["title"], "venue": "Holocene",
                      "neighborhood": "Central Eastside", "address": "1001 SE Morrison St",
                      "date": date_iso, "time": showtime, "venueUrl": e["tix"] or slug,
                      "imageUrl": img_by_url.get((e["tix"] or slug or "").split("?")[0], "")
                                  or img_by_url.get((slug or "").split("?")[0], "")})
    return shows
# ---- Revolution Hall (revolutionhall.com) ------------------------------------
# The events are NOT in the static page and the site does NOT use the
# "Weekday, Month D, YYYY" headings parse_msstudios relies on. Instead the calendar
# loads via a WordPress AJAX endpoint: a POST to admin-ajax.php with action
# crb_get_searched_events_markup and a "feed" param, returning a JSON-encoded HTML
# string of ~30 .event-wrapper blocks per page. We paginate until a short page.
# The building has two rooms; the etix slug (-show-bar-at-revolution-hall vs plain
# -revolution-hall) tells them apart.
REVHALL_AJAX = ("https://www.revolutionhall.com/wp-admin/admin-ajax.php"
                "?action=crb_get_searched_events_markup")
REVHALL_DATE = re.compile(r'([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})')

def _revhall_post_page(page):
    body = (f"feed=all&style=default&page={page}"
            f"&feed_id=feed-primary&query=&page_id=6")
    r = requests.post(REVHALL_AJAX, data=body, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PortlandLive/1.0; listings aggregator)",
        "Content-type": "application/x-www-form-urlencoded"})
    r.raise_for_status()
    return json.loads(r.text)  # endpoint returns the markup as a JSON string

def _revhall_date(dtxt, today):
    low = dtxt.lower()
    if low.startswith("tonight"):
        return today.isoformat()
    if low.startswith("tomorrow"):
        return (today + datetime.timedelta(days=1)).isoformat()
    m = REVHALL_DATE.search(dtxt)
    if not m:
        return None
    mon3 = m.group(1)[:3]
    if mon3 not in MONTHS:
        return None
    mon, day = MONTHS[mon3], int(m.group(2))
    year = int(m.group(3)) if m.group(3) else infer_year(mon, today)
    return f"{year}-{mon:02d}-{day:02d}"

def _revhall_events(markup, today, seen, shows):
    """Parse one chunk of .event-wrapper markup into `shows`; return wrapper count."""
    soup = BeautifulSoup(markup, "html.parser")
    wrappers = soup.select(".event-wrapper")
    for ev in wrappers:
        a = ev.select_one(".event__content h3 a[href]")
        if not a:
            continue
        url = a["href"].split("?")[0]
        slug = url.rsplit("/", 1)[-1]
        venue = ("Revolution Hall (Show Bar)"
                 if "show-bar-at-revolution-hall" in slug else "Revolution Hall")
        df = ev.select_one(".event-date--full")
        date = _revhall_date(clean(df.get_text()) if df else "", today)
        if not date:
            continue
        key = (url, date)
        if key in seen:
            continue
        seen.add(key)
        title = re.sub(r'^SOLD OUT:\s*', '', clean(a.get_text()))
        h4 = ev.select_one(".event__content h4")
        support = re.sub(r'^with\s+', '', clean(h4.get_text()), flags=re.I) if h4 else ""
        st = ev.select_one(".event-doors-showtime")
        showtime = ""
        if st:
            sm = re.search(r'Show:?\s*([\d:]+\s*[ap]m)', clean(st.get_text()), re.I)
            if sm:
                showtime = to_time(sm.group(1))
        # Both rooms share the building address; VENUE_INFO keys the main name.
        nb, addr = VENUE_INFO["Revolution Hall"]
        full = f"{title} (w/ {support})" if support else title
        img = _img_from(ev, "performance-image")
        shows.append({"title": full, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": url,
                      "imageUrl": img, "age": _age_from(ev)})
    return len(wrappers)

def parse_revolutionhall(html, today):
    shows, seen = [], set()
    # The GET'd page embeds page 1; if so, AJAX-paginate from page 2, else from 1.
    page = 2 if _revhall_events(html, today, seen, shows) else 1
    while page <= 15:
        try:
            markup = _revhall_post_page(page)
        except Exception as e:
            print(f"    [revhall] page {page} error {e}")
            break
        if _revhall_events(markup, today, seen, shows) < 30:
            break  # short page = last page
        page += 1
    return shows


def parse_aladdin(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    for ev in soup.select(".event--list-style"):
        a = next((x for x in ev.find_all("a", href=True)
                  if "etix.com/ticket/p/" in x["href"]), None)
        if not a:
            continue
        url = a["href"].split("?")[0]
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        # filter out non-Aladdin cross-listings (True West shows at other rooms)
        if "aladdin" not in slug:
            continue
        df = ev.select_one(".event-date--full")
        date = _revhall_date(clean(df.get_text()) if df else "", today)
        if not date:
            continue
        key = (slug, date)
        if key in seen:
            continue
        seen.add(key)
        te = ev.select_one(".event-title")
        title = clean(te.get_text()) if te else clean(a.get_text())
        title = re.sub(r"^SOLD OUT:\s*", "", title)
        st = ev.select_one(".event-doors-showtime")
        showtime = ""
        if st:
            sm = re.search(r"Show:?\s*([\d:]+\s*[ap]m)", clean(st.get_text()), re.I)
            if sm:
                showtime = to_time(sm.group(1))
        nb, addr = VENUE_INFO["Aladdin Theater"]
        img = _img_from(ev, "performance-image")
        shows.append({"title": title, "venue": "Aladdin Theater",
                      "neighborhood": nb, "address": addr, "date": date,
                      "time": showtime, "venueUrl": url, "imageUrl": img,
                      "age": _age_from(ev)})
    return shows



# Monqui promoter feed -- the only clean route to Crystal Ballroom + McMenamins
# rooms (their own sites/etix pages are bot-walled). Venue comes from the URL
# slug, not the title (titles can say "MOVED TO..."). Listing page has no times.
MONQUI_SKIP = {"wonder-ballroom", "holocene", "revolution-hall", "roseland-theater"}
MONQUI_SLUG_NAME = {
    "crystal-ballroom": "Crystal Ballroom",
    "mcmenamins-edgefield": "McMenamins Edgefield",
    "mcmenamins-grand-lodge-concerts": "McMenamins Grand Lodge",
    "arlene-schnitzer-concert-hall": "Arlene Schnitzer Concert Hall",
    "paramount-theatre": "Paramount Theatre",
    "the-old-church": "The Old Church",
}


# Attribute-tolerant JSON-LD matcher, shared by every parser that reads
# schema.org blocks out of raw HTML. The three JSON-LD parsers below used to
# hardcode r'<script type="application/ld\+json">' -- a pattern that demands the
# tag CLOSE immediately after the type attribute. When Eventbrite moved its
# collection pages to Next.js (Sep 2026) the tag became
#   <script type="application/ld+json" data-next-head="">
# and that pattern matched nothing, so parse_artichoke silently returned 0
# events while the page still served all 42. Any framework adding any attribute
# to the tag takes a venue down the same way, so match the type anywhere in the
# tag instead. _MQ_LD (Monqui) already did this correctly; this is the same
# pattern, named for shared use.
_LD_JSON = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S)
_MQ_LD = _LD_JSON


def _monqui_event_time(url):
    # Fetch a Monqui event detail page and return a to_time()-normalized
    # show time from schema.org JSON-LD startDate (already Pacific-local,
    # offset -0700). Returns (url, "") if no time is available.
    try:
        h = fetch(url)
    except Exception:
        return (url, "", "")
    for m in _MQ_LD.finditer(h):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("@type") == "Event":
            mqimg = d.get("image") or ""
            if isinstance(mqimg, list):
                mqimg = mqimg[0] if mqimg else ""
            if isinstance(mqimg, dict):
                mqimg = mqimg.get("url") or mqimg.get("@id") or ""
            tm = re.search(r"T(\d{2}):(\d{2})", d.get("startDate", ""))
            if tm:
                hh, mm = int(tm.group(1)), tm.group(2)
                ap = "am" if hh < 12 else "pm"
                return (url, to_time(f"{hh % 12 or 12}:{mm} {ap}"), mqimg)
            return (url, "", mqimg)
    return (url, "", "")


def parse_monqui(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    for ev in soup.select(".rhp-event-thumb"):
        a = ev.find("a", class_="url", href=True) or ev.find("a", href=True)
        if not a or "/event/" not in a["href"]:
            continue
        href = a["href"]
        parts = href.split("/event/")[1].split("/")
        if len(parts) < 3:
            continue
        slug, city = parts[1], parts[2]
        if "oregon" not in city.lower():
            continue  # drop Seattle/Tacoma/Bend/Eugene etc.
        if slug in MONQUI_SKIP:
            continue  # already covered by another source
        venue = MONQUI_SLUG_NAME.get(slug, slug.replace("-", " ").title())
        title = a.get("title") or a.get_text()
        title = re.sub(r"^(MOVED TO[^:]*:\\s*|SOLD OUT:\\s*|CANCELLED:\\s*)", "",
                       clean(title), flags=re.I)
        de = ev.find(id="eventDate") or ev.select_one(".singleEventDate")
        if not de:
            continue
        bits = [b.strip() for b in de.get_text("|").split("|") if b.strip()]
        mon = day = None
        for b in bits:
            if b[:3] in MONTHS:
                mon = MONTHS[b[:3]]
            elif b.isdigit():
                day = int(b)
        if not mon or not day:
            continue
        date = f"{infer_year(mon, today)}-{mon:02d}-{day:02d}"
        key = (venue, date, title)
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Portland", ""))
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": "", "venueUrl": href,
                      "imageUrl": "", "age": _age_from(ev) or _age_near(ev)})
    # show times only live on each event detail page; fetch concurrently
    import concurrent.futures
    urls = list({s["venueUrl"] for s in shows})
    times = {}
    mqimages = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for u, t, im in ex.map(_monqui_event_time, urls):
            times[u] = t
            mqimages[u] = im
    for s in shows:
        s["time"] = times.get(s["venueUrl"], "")
        if not s.get("imageUrl"):
            s["imageUrl"] = mqimages.get(s["venueUrl"], "")

    return shows



# ---- Rose Quarter (rosequarter.com) -- Moda Center + Veterans Memorial Coliseum
# + Theater of the Clouds, one Webflow CMS calendar. Venue + event-type live on
# each card as fs-cmsfilter-field attributes. Keep event-type == Music only.
_RQ_VENUES = {"Moda Center", "Veterans Memorial Coliseum", "Theater of the Clouds"}
_RQ_MONABBR = {m: i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_RQ_DATE = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2}),?\s*(\d{4})?")


def _rq_field(card, name):
    d = card.find(attrs={"fs-cmsfilter-field": name})
    return clean(d.get_text(" ")) if d else ""


def _rq_date(txt, today):
    m = _RQ_DATE.search(txt or "")
    if not m:
        return ""
    mon = _RQ_MONABBR.get(m.group(1), 0)
    if not mon:
        return ""
    day = int(m.group(2))
    year = int(m.group(3)) if m.group(3) else infer_year(mon, today)
    return f"{year}-{mon:02d}-{day:02d}"


_RQ_TIME = re.compile(r"^\s*\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?\s*$", re.I)


def parse_rosequarter(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    for a in soup.find_all("a", href=True):
        if "calendar-events" not in a["href"]:
            continue
        card = a.find_parent(["article", "li", "div"])
        if not card:
            continue
        venue = _rq_field(card, "venue")
        if venue not in _RQ_VENUES:
            continue
        if _rq_field(card, "event-type") != "Music":
            continue
        url = a["href"]
        if not url.startswith("http"):
            url = "https://www.rosequarter.com" + url
        dtxt = " ".join(d.get_text(" ") for d in card.select(".date-day, .date-comma"))
        date = _rq_date(dtxt, today)
        if not date:
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            sm = re.search(r"-([a-z]{3})-(\d{1,2})-(\d{4})$", slug)
            if sm:
                mon = _RQ_MONABBR.get(sm.group(1).capitalize(), 0)
                if mon:
                    date = f"{int(sm.group(3))}-{mon:02d}-{int(sm.group(2)):02d}"
        if not date:
            continue
        who = card.select_one(".card-who.artist") or card.select_one(".card-who")
        tour = card.select_one(".card-tour-title")
        artist = clean(who.get_text(" ")) if who else ""
        tourt = clean(tour.get_text(" ")) if tour else ""
        title = artist or tourt
        if tourt and artist and tourt.lower() not in title.lower():
            title = f"{artist}: {tourt}"
        title = re.sub(r"^(SOLD OUT|CANCELLED|POSTPONED)[:\s-]*", "", title, flags=re.I).strip()
        if not title:
            continue
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Lloyd/Rose Quarter", ""))
        # time was hardcoded "" -- every Rose Quarter show shipped without one.
        # The card carries it: .card-date-time appears twice, once holding the
        # sortable date (.date-sort) and once the door time, plus Webflow
        # placeholders marked w-condition-invisible that hold stale values
        # ("11:30 am") and must be skipped. Take the first that is neither and
        # actually looks like a time; a genuinely unannounced show renders
        # "Time: TBD" and correctly stays blank.
        showtime = ""
        for e in card.select(".card-date-time"):
            ecls = " ".join(e.get("class", []))
            if "w-condition-invisible" in ecls or "date-sort" in ecls:
                continue
            etxt = clean(e.get_text(" "))
            if _RQ_TIME.match(etxt):
                showtime = to_time(etxt)
                break
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime,
                      "venueUrl": url,
                      # Every Webflow card carries its poster as <img class="image">;
                      # 32/32 on the captured page.
                      "imageUrl": (card.find("img", src=re.compile(r"^https?://")) or {}).get("src", "")})
    return shows



# ---- Portland'5 (portland5.com) -- Keller Auditorium, Arlene Schnitzer Concert
# Hall, Newmark/Brunish/Winningstad Theatres + Hatfield Hall Rotunda + Main Street
# (Music on Main outdoor series). Static HTML, venue on each .teaser__content card,
# but PAGINATED via ?page=N. Harness passes page 0; we walk the rest ourselves.
P5_BASE = "https://www.portland5.com/events"
_P5_MON = {m: i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}
_P5_DATE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2})")


def _p5_date(txt, today):
    m = _P5_DATE.search(txt or "")
    if not m:
        return ""
    mon = _P5_MON.get(m.group(1), 0)
    if not mon:
        return ""
    day = int(m.group(2))
    ym = re.search(r"(\d{4})", txt)
    year = int(ym.group(1)) if ym else infer_year(mon, today)
    return f"{year}-{mon:02d}-{day:02d}"


def _p5_cards(html, today, out, seen):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".teaser__content")
    for c in cards:
        vn = c.select_one(".teaser__venue-name") or c.select_one(".teaser__venue")
        venue = clean(vn.get_text(" ")) if vn else ""
        # Hatfield Hall Rotunda removed as a tracked venue (closed "0-shows"
        # open item): drop any Portland'5 card that still lists it.
        if venue == "Hatfield Hall Rotunda":
            continue
        t = c.select_one(".teaser__title")
        title = clean(t.get_text(" ")) if t else ""
        a = c.select_one(".teaser__link") or c.find("a", href=True)
        href = a["href"] if a and a.has_attr("href") else ""
        if href and not href.startswith("http"):
            href = "https://www.portland5.com" + href
        b = c.select_one(".teaser__body")
        btxt = clean(b.get_text(" ")) if b else ""
        date = _p5_date(btxt, today)
        # The time was hardcoded "" while sitting in the SAME element the date
        # is read from: "Tuesday, September 15, 2026 7:30 PM". Only some events
        # publish one on the listing -- 7 of 10 on the captured page -- so the
        # rest stay honestly blank rather than being guessed at.
        tm = _P5_TIME.search(btxt)
        showtime = to_time(tm.group(1)) if tm else ""
        if not (venue and title and date):
            continue
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Downtown", ""))
        out.append({"title": title, "venue": venue, "neighborhood": nb,
                    "address": addr, "date": date, "time": showtime,
                    "venueUrl": href, "imageUrl": ""})
    return len(cards)


_P5_TIME = re.compile(r"\b(\d{1,2}:\d{2}\s*[AP]\.?M\.?)", re.I)


def _p5_detail(html):
    """age, time, image from one portland5.com event page.

    The page is a <dl>: <dt class="event-details__detail-key">Age Restriction
    or Recommendation</dt><dd class="event-details__detail-value">All ages
    welcome</dd>, same shape for Doors Open. The poster is the og:image
    (their facebook_share rendition; the venue's own upload). Anything
    unrecognised stays blank."""
    soup = BeautifulSoup(html, "html.parser")
    age, doors, img, date = "", "", "", ""
    # The event page's own date: <div class="event-hero__date">Saturday,
    # September 19, 2026 8:00 PM</div>. The LISTING card for Beck said
    # Tuesday, November 10 while this page, Live Nation, Ticketmaster and
    # the tour's own site all said September 19 (2026-09-15). The event
    # page is the canonical record; when the two disagree it wins.
    hero = soup.select_one(".event-hero__date")
    if hero:
        m = re.search(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", hero.get_text(" ", strip=True))
        if m:
            mon = MONTHS.get(m.group(1)[:3].title())
            if mon:
                date = f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    for dt in soup.select("dt.event-details__detail-key"):
        key = clean(dt.get_text(" ")).lower()
        dd = dt.find_next_sibling("dd")
        val = clean(dd.get_text(" ")) if dd else ""
        if "age" in key and val:
            age = _norm_age(val) or _age_in_text(val)
        elif "doors" in key and val:
            doors = to_time(val)
    og = soup.find("meta", property="og:image")
    if og and og.get("content", "").startswith("http"):
        img = og["content"]
    return age, doors, img, date


def _p5_enrich(rows, today=None):
    """Fetch each event's own page for age, doors and poster.

    The listing carries only title/date and sometimes a time; the detail
    page carries the rest, and it is portland5.com's own page -- not a
    ticketing company's -- so one fetch per event a night is ordinary.
    Any failure leaves that row as the listing had it. Never raises."""
    n_ok = 0
    floor = today.isoformat() if today else ""
    ceil = (today + datetime.timedelta(days=HORIZON_DAYS)).isoformat() if today else ""
    for r in rows:
        u = r.get("venueUrl") or ""
        if "portland5.com/event/" not in u:
            continue
        # The paginated listing runs months ahead; scrape() clips to
        # HORIZON_DAYS afterwards. 144 fetched on the first live run for 82
        # that survived -- fetch only what the feed will keep.
        d = r.get("date") or ""
        if (floor and d < floor) or (ceil and d > ceil):
            continue
        try:
            h = fetch(u)
        except Exception:
            continue
        try:
            age, doors, img, ddate = _p5_detail(h)
        except Exception:
            continue
        if ddate and ddate != r.get("date"):
            print(f"  note: Portland5: listing said {r.get('date')} but the event page says {ddate} -- {r.get('title','')[:40]!r}; using the event page")
            r["date"] = ddate
        if age and not r.get("age"):
            r["age"] = age
        if img and not r.get("imageUrl"):
            r["imageUrl"] = img
        # The listing's time is the SHOW time when present; doors is the
        # fallback only, so a row is never left blank when the page knows.
        if doors and not r.get("time"):
            r["time"] = doors
        n_ok += 1
        time.sleep(0.3)
    if n_ok:
        print(f"  Portland5: enriched {n_ok} row(s) from event pages")


def parse_portland5(html, today):
    out = []
    seen = set()
    _p5_cards(html, today, out, seen)
    page = 1
    while page <= 20:
        try:
            h = fetch(f"{P5_BASE}?page={page}")
        except Exception:
            break
        cnt = _p5_cards(h, today, out, seen)
        if cnt == 0:
            break
        page += 1
        time.sleep(0.5)
    _p5_enrich(out, today)
    return out



# ---- Alberta Rose Theatre (albertarosetheatre.com) -- single venue, rhp-event
# CMS. Each .row.g-0 holds one .rhp-event__info--list (title + /event/ link) and
# one .singleEventDate ("Sun, Jun 07") + .eventDateDetails ("Show: 8 pm").
_AR_MON = {m: i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_AR_DATE = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2})")


def _ar_date(txt, today):
    m = _AR_DATE.search(txt or "")
    if not m:
        return ""
    mon = _AR_MON.get(m.group(1), 0)
    if not mon:
        return ""
    yr = re.search(r"(\d{4})", txt)
    year = int(yr.group(1)) if yr else infer_year(mon, today)
    return f"{year}-{mon:02d}-{int(m.group(2)):02d}"


def parse_albertarose(html, today):
    soup = BeautifulSoup(html, "html.parser")
    img_by_url = _img_map_by_event_url(soup)  # 51/51 on the captured page
    shows = []
    seen = set()
    for info in soup.select(".rhp-event__info--list"):
        row = info.find_parent(class_="row") or info.parent
        a = info.find("a", href=True)
        if not a:
            continue
        te = info.select_one(".rhp-event__title--list")
        title = clean(te.get_text(" ")) if te else clean(a.get_text(" "))
        title = re.sub(r"^(SOLD OUT|CANCELLED|POSTPONED)[:\s-]*", "", title, flags=re.I).strip()
        de = row.select_one(".singleEventDate") if row else None
        date = _ar_date(clean(de.get_text(" ")) if de else "", today)
        if not (title and date):
            continue
        url = a["href"]
        if not url.startswith("http"):
            url = "https://albertarosetheatre.com" + url
        det = (row.select_one(".eventDateDetails") if row else None) or info.select_one(".eventDateDetails")
        showtime = ""
        if det:
            sm = re.search(r"Show:?\s*([\d:]+\s*[ap]m)", clean(det.get_text(" ")), re.I)
            if sm:
                showtime = to_time(sm.group(1))
        venue = "Alberta Rose Theatre"
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("NE/Alberta", ""))
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": url,
                      "imageUrl": img_by_url.get((url or "").split("?")[0], "")})
    return shows



# ---- World Famous Kenton Club (kentonclub.com) -- single venue, plain text.
# The homepage is a Squarespace text block: one <p> per line, a date line
# ("Friday September 25 ($20 cover)") followed by one or two lines of band
# names, then an empty <p> as the separator. No links, no times, no year --
# the kind of calendar a bartender types in. Year is inferred from the month;
# time is honestly blank (see _NO_LISTING_TIME in build_shows.py).
_KC_DATE = re.compile(
    r"^(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2})\b(.*)$", re.I | re.M)
# Lines that are a date slot with nothing on it, not a show.
_KC_NOSHOW = re.compile(r"^\s*(no music|no show|closed|private event)\b", re.I)


def parse_kentonclub(html, today):
    soup = BeautifulSoup(html, "html.parser")
    block = None
    for div in soup.select(".sqs-html-content"):
        if len(_KC_DATE.findall(div.get_text("\n"))) >= 5:
            block = div
            break
    if block is None:
        return []
    venue = "Kenton Club"
    nb, addr = VENUE_INFO.get(venue, ("Kenton", "2025 N Kilpatrick St"))
    shows, seen = [], set()
    date, note, lines = "", "", []

    def flush():
        if not date or not lines:
            return
        title = clean(" / ".join(lines))
        if _KC_NOSHOW.match(title):
            return
        key = (date, title.lower())
        if key in seen:
            return
        seen.add(key)
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": "",
                      "venueUrl": "https://www.kentonclub.com/", "imageUrl": ""})

    for ptag in block.find_all("p"):
        txt = clean(ptag.get_text(" "))
        if not txt:
            flush()
            date, note, lines = "", "", []
            continue
        m = _KC_DATE.match(txt)
        if m:
            flush()
            mon = _ST_MON.get(m.group(1).capitalize(), 0)
            day = int(m.group(2))
            # Not infer_year(): that treats any earlier month as NEXT year,
            # which is right for venues that only post ahead. Kenton leaves
            # last month's shows on the page, so August seen in September is
            # a stale August listing, not August of next year. Only wrap to
            # next year when the month is far enough back that it cannot be
            # a recent leftover (Jan seen in Nov, say).
            year = today.year
            if mon and mon < today.month - 3:
                year += 1
            date = f"{year}-{mon:02d}-{day:02d}" if mon else ""
            note = clean(m.group(3))
            lines = []
            continue
        if date:
            lines.append(txt)
    flush()
    return shows


# ---- Spare Room (spareroomrestaurantandlounge.com) -- single venue, one
# hand-written page per month: /sept2026.htm, /oct2026.htm. Each is a <ul>
# of <li>"Sept. 4th &nbsp; Federale + Black Shelton ... $10 cover."</li>.
# Month comes from the page heading ("September at the Spare Room"); ranges
# like "Sept. 1 - 2" are the recurring karaoke and are skipped. The site
# posts one month at a time, so the source lists this month and next and a
# 404 on next month is normal, not a failure.
_SR_MONTH = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+at the Spare Room", re.I)
_SR_LI = re.compile(r"^\s*[A-Z][a-z]{2,4}\.?\s+(\d{1,2})(?:st|nd|rd|th)?(\s*-\s*\d{1,2})?\s+(.*)$", re.S)
# Karaoke and bingo are not shows -- except Karaoke From Hell, which is a
# live band on stage every Thursday with the crowd singing over it. Nick's
# call (2026-09-15): that one stays in. Its line reads "Karaoke w/ a live
# band featuring Karaoke from Hell"; _SR_KFH lets it through and every
# other karaoke line is still dropped.
_SR_SKIP = re.compile(r"\b(karaoke|bingo)\b", re.I)
_SR_KFH = re.compile(r"karaoke from hell", re.I)
_SR_COVER = re.compile(r"\s*\$\d+\s*cover\.?", re.I)


def _spare_room_urls():
    """This month's and next month's page. The site's own filename style is
    the lowercase month abbreviation it uses in links -- 'sept' for
    September. A 404 on next month is the normal state until they post it."""
    import datetime as _dt
    ab = {1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "june",
          7: "july", 8: "aug", 9: "sept", 10: "oct", 11: "nov", 12: "dec"}
    t = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-8))).date()
    out = []
    for k in (0, 1):
        m = (t.month - 1 + k) % 12 + 1
        y = t.year + ((t.month - 1 + k) // 12)
        out.append(f"https://www.spareroomrestaurantandlounge.com/{ab[m]}{y}.htm")
    return out


def parse_spareroom(html, today):
    soup = BeautifulSoup(html, "html.parser")
    mm = _SR_MONTH.search(soup.get_text(" "))
    if not mm:
        return []
    mon = _ST_MON.get(mm.group(1).capitalize(), 0)
    if not mon:
        return []
    year = today.year
    if mon < today.month - 3:
        year += 1
    venue = "Spare Room"
    nb, addr = VENUE_INFO.get(venue, ("Cully", "4830 NE 42nd Ave"))
    shows, seen = [], set()
    for li in soup.select("li"):
        for sp in li.select("span"):
            sp.decompose()  # the red "$10 cover" span
        txt = clean(li.get_text(" "))
        m = _SR_LI.match(txt)
        if not m:
            continue
        day, rng, rest = int(m.group(1)), m.group(2), clean(m.group(3))
        if rng:
            continue  # "Sept. 1 - 2": the karaoke block, not a show
        title = _SR_COVER.sub("", rest).strip(" .")
        # Link text joins leave "Party Witch , Tai" and "Luchini : a dance".
        title = re.sub(r"\s+([,.:;!?])", r"\1", title)
        if not title or (_SR_SKIP.search(title) and not _SR_KFH.search(title)):
            continue
        date = f"{year}-{mon:02d}-{day:02d}"
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        tm = re.search(r"\b(\d{1,2}(?::\d{2})?\s*[ap]m)\b", title, re.I)
        showtime = to_time(tm.group(1)) if tm else ""
        if tm:
            title = clean(title[:tm.start()] + title[tm.end():]).strip(" .-")
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime,
                      "venueUrl": "https://www.spareroomrestaurantandlounge.com/events.htm",
                      "imageUrl": ""})
    return shows


# ---- Switchback Saloon (switchbacksaloon.com) -- the former Landmark
# Saloon, reopened July 2026. The site embeds two public Google Calendars,
# which Google also serves as iCal feeds: real timestamps, no HTML. The
# "Music Calendar" only holds the July grand-opening shows; the live
# schedule is in "Special Events", where music is prefixed "Live Music:".
# Everything else there (Trivia, Birthday Party, Halloween Party) is not a
# listing. Both feeds are fetched; the title filter does the sorting.
_SB_KEEP = re.compile(r"^\s*(?:live\s*music|dj|\U0001F3B5)\s*:?|concert|record release", re.I)
_SB_STRIP = re.compile(r"^\s*(?:live\s*music|\U0001F3B5)\s*:?\s*", re.I)


def _ics_events(text):
    """Minimal iCal reader: unfold continuation lines, yield (dtstart, summary,
    has_rrule) per VEVENT. Only the fields this parser needs."""
    text = re.sub(r"\r?\n[ \t]", "", text)
    for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        ds = re.search(r"^DTSTART(?:;[^:\n]*)?:(\S+)", blk, re.M)
        sm = re.search(r"^SUMMARY:(.*)$", blk, re.M)
        if not (ds and sm):
            continue
        yield ds.group(1).strip(), clean(sm.group(1)), ("RRULE:" in blk)


def parse_switchback(html, today):
    from zoneinfo import ZoneInfo
    import datetime as _dt
    venue = "Switchback Saloon"
    nb, addr = VENUE_INFO.get(venue, ("Richmond", "4847 SE Division St"))
    pt = ZoneInfo("America/Los_Angeles")
    shows, seen = [], set()
    for dstart, summary, recurs in _ics_events(html or ""):
        if recurs:
            continue  # Trivia / Country Co Op: weekly recurrences, not shows
        if not _SB_KEEP.search(summary):
            continue
        title = _SB_STRIP.sub("", summary).strip(" -:")
        if not title:
            continue
        # 20260919T010000Z (UTC) or 20260922 (all-day)
        m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?$", dstart)
        if not m:
            continue
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4):
            dt = _dt.datetime(y, mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6)),
                              tzinfo=_dt.timezone.utc if m.group(7) else pt).astimezone(pt)
            date, showtime = dt.strftime("%Y-%m-%d"), f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
        else:
            date, showtime = f"{y}-{mo:02d}-{d:02d}", ""
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime,
                      "venueUrl": "https://switchbacksaloon.com/schedule.html",
                      "imageUrl": ""})
    return shows


_SB_ICS = [
    "https://calendar.google.com/calendar/ical/c_2bc82bc83b4a485f7823307cce3239807076c71caf773e8aeceff57c24b2fcb0%40group.calendar.google.com/public/basic.ics",
    "https://calendar.google.com/calendar/ical/c_d49aa8944037b6a8484718e3aa01e21e83f9761c2a8696ba940d82244ac37bde%40group.calendar.google.com/public/basic.ics",
]


# ---- Star Theater (startheaterportland.com) -- single venue, TicketWeb tw-*
# widget on the homepage. Each .tw-section has .tw-name (title),
# .tw-event-date-complete ("June 07, 2026"), .tw-event-time-complete ("9:00 pm").
_ST_MON = {m: i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}
_ST_DATE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s*(\d{4})")


def _st_date(txt):
    m = _ST_DATE.search(txt or "")
    if not m:
        return ""
    mon = _ST_MON.get(m.group(1), 0)
    if not mon:
        return ""
    return f"{int(m.group(3))}-{mon:02d}-{int(m.group(2)):02d}"


def parse_startheater(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    for sec in soup.select(".tw-section"):
        nm = sec.select_one(".tw-name")
        title = clean(nm.get_text(" ")) if nm else ""
        title = re.sub(r"^(SOLD OUT|CANCELLED|POSTPONED)[:\s-]*", "", title, flags=re.I).strip()
        de = sec.select_one(".tw-event-date-complete")
        date = _st_date(clean(de.get_text(" ")) if de else "")
        if not (title and date):
            continue
        te = sec.select_one(".tw-event-time-complete")
        showtime = to_time(clean(te.get_text(" "))) if te else ""
        a = sec.find("a", href=True)
        url = a["href"] if a else "https://startheaterportland.com/"
        venue = "Star Theater"
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Old Town/Chinatown", ""))
        img = _img_from(sec, "i.ticketweb.com")
        # Every .tw-section carries its own TicketWeb link; venueUrl keeps the
        # venue's page and ticketUrl holds the platform link, same split as
        # Dante's and Jack London.
        tl = sec.find("a", href=re.compile(r'ticketweb\.com'))
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime,
                      "venueUrl": url, "ticketUrl": tl["href"] if tl else "",
                      "imageUrl": img})
    return shows



# ---- Jack London Revue (jacklondonrevue.com/calendar) -- single venue, same
# TicketWeb tw-* widget as Star Theater but a different container layout, so we
# anchor on .tw-event-date-complete and climb to the nearest .tw-name.
def parse_jacklondonrevue(html, today):
    soup = BeautifulSoup(html, "html.parser")
    bykey = {}
    venue = "Jack London Revue"
    for de in soup.select(".tw-event-date-complete"):
        cont = de
        nm = None
        for _ in range(6):
            cont = cont.parent
            if cont is None:
                break
            nm = cont.select_one(".tw-name")
            if nm:
                break
        if not (cont and nm):
            continue
        date = _st_date(clean(de.get_text(" ")))
        title = clean(nm.get_text(" "))
        title = re.sub(r"^(SOLD OUT|CANCELLED|POSTPONED)[:\s-]*", "", title, flags=re.I).strip()
        if not (date and title):
            continue
        te = cont.select_one(".tw-event-time-complete")
        showtime = to_time(clean(te.get_text(" "))) if te else ""
        a = cont.find("a", href=True)
        url = a["href"] if a else "https://jacklondonrevue.com/calendar/"
        slug = url.rsplit("/tm-event/", 1)[-1].strip("/") if "/tm-event/" in url else ""
        norm_title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip().lower()
        key = (venue, date, slug or norm_title)
        nb, addr = VENUE_INFO.get(venue, ("Downtown", ""))
        img = _img_from(cont, "i.ticketweb.com")
        # JLR prints the age in the event blurb rather than a dedicated element
        # ("Doors: 7:00pm / Show: 8:00pm / Ages 21+."), so this scans cont's
        # text -- but only while cont holds exactly ONE event name. The walk
        # above stops at the first ancestor containing a .tw-name, and if that
        # ancestor ever wraps several events the text would not belong to this
        # show. Unknown beats attaching a neighbour's door policy.
        # The calendar renders each event TWICE in separate lists: a compact
        # calendar list with no blurb, and a full list where .tw-description
        # carries "Doors: 7:00pm Show: 8:00pm Ages 21+." -- 30 of 56 events on
        # the real page. `cont` stops at the first ancestor holding a .tw-name,
        # which sits BELOW the description in the full list, so climb a little
        # further -- only while the ancestor still holds exactly one event
        # name, so a neighbour's blurb can never be read as this show's.
        age = _age_from(cont)
        if not age:
            box = cont
            for _ in range(4):
                if box is None or getattr(box, "name", None) is None:
                    break
                if len(box.select(".tw-name")) != 1:
                    box = None
                    break
                if box.select_one(".tw-description"):
                    break
                box = box.parent
            if box is not None and len(box.select(".tw-name")) == 1:
                age = _age_in_text(box.get_text(" "))
        # The TicketWeb link sits in .tw-info-price-buy-tix, which lives in
        # the full-list fragment alongside the description -- the same place
        # `box` climbs to for the age. venueUrl stays the venue's own page.
        tixurl = ""
        for scope in (cont, box if 'box' in dir() else None):
            if scope is None:
                continue
            tl = scope.find("a", href=re.compile(r'ticketweb\.com'))
            if tl and tl.get("href"):
                tixurl = tl["href"]
                break
        rec = {"title": title, "venue": venue, "neighborhood": nb,
               "address": addr, "date": date, "time": showtime,
               "venueUrl": url, "ticketUrl": tixurl, "imageUrl": img, "age": age}
        prev = bykey.get(key)
        # JLR renders two date elements per event (one timed, one not);
        # keep one record per (venue,date,title), preferring the one WITH a time.
        # Age rides along the same way imageUrl does: only one of the two
        # fragments carries the blurb, and it is not always the timed one.
        if prev is not None and not rec.get("imageUrl") and prev.get("imageUrl"):
            rec["imageUrl"] = prev["imageUrl"]
        if prev is not None and not rec.get("age") and prev.get("age"):
            rec["age"] = prev["age"]
        if prev is not None and not rec.get("ticketUrl") and prev.get("ticketUrl"):
            rec["ticketUrl"] = prev["ticketUrl"]
        if prev is None or (not prev.get("time") and showtime):
            bykey[key] = rec
        else:
            if not bykey[key].get("imageUrl") and rec.get("imageUrl"):
                bykey[key]["imageUrl"] = rec["imageUrl"]
            if not bykey[key].get("age") and rec.get("age"):
                bykey[key]["age"] = rec["age"]
            if not bykey[key].get("ticketUrl") and rec.get("ticketUrl"):
                bykey[key]["ticketUrl"] = rec["ticketUrl"]

    return list(bykey.values())



# ---- The Get Down (thegetdownpdx.com) -- single venue, Webflow CMS (same family
# as Rose Quarter). Each .day-card-2 has .b-show-2 (show name) / .title and a
# .dayofevent ("Wednesday , Jun 10"); tickets via tixr. No listing time.
_GD_MON = {m: i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_GD_DATE = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2})")


def _gd_date(txt, today):
    m = _GD_DATE.search(txt or "")
    if not m:
        return ""
    mon = _GD_MON.get(m.group(1), 0)
    if not mon:
        return ""
    return f"{infer_year(mon, today)}-{mon:02d}-{int(m.group(2)):02d}"


def parse_getdown(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    venue = "The Get Down"
    for c in soup.select(".day-card-2"):
        sh = c.select_one(".b-show-2") or c.select_one(".title")
        title = clean(sh.get_text(" ")) if sh else ""
        title = re.sub(r"^(SOLD OUT|CANCELLED|POSTPONED)[:\s-]*", "", title, flags=re.I).strip()
        doe = c.select_one(".dayofevent")
        date = _gd_date(clean(doe.get_text(" ")) if doe else "", today)
        if not (title and date):
            continue
        a = c.find("a", href=True)
        if not a:
            sib = c.find_next("a", href=True)
            a = sib if sib and "tixr" in sib.get("href", "") else None
        url = a["href"] if a else "https://thegetdownpdx.com/"
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Central Eastside", ""))
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": "", "venueUrl": url, "imageUrl": ""})
    return shows



# ---- Showdown Saloon (showdownpdx.com) -- single venue, TicketWeb tw-* widget
# variant: each .tw-section has .tw-name, .tw-event-date ("Jun 7") and
# .tw-event-time-complete ("Show: 8:00 pm"). (showdownsaloon.com is bot-walled;
# showdownpdx.com is the clean public site.)
_SD_MON = {m: i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_SD_DATE = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2})")


def _sd_date(txt, today):
    m = _SD_DATE.search(txt or "")
    if not m:
        return ""
    mon = _SD_MON.get(m.group(1), 0)
    if not mon:
        return ""
    return f"{infer_year(mon, today)}-{mon:02d}-{int(m.group(2)):02d}"


def _showdown_page(soup, today, shows, seen):
    """One listing page of showdownpdx.com into `shows`. Returns rows added."""
    venue = "Showdown Saloon"
    added = 0
    for sec in soup.select(".tw-section"):
        nm = sec.select_one(".tw-name")
        title = clean(nm.get_text(" ")) if nm else ""
        title = re.sub(r"^(SOLD OUT|CANCELLED|POSTPONED)[:\s-]*", "", title, flags=re.I).strip()
        de = sec.select_one(".tw-event-date")
        date = _sd_date(clean(de.get_text(" ")) if de else "", today)
        if not (title and date):
            continue
        te = sec.select_one(".tw-event-time-complete")
        showtime = ""
        if te:
            sm = re.search(r"Show:?\s*([\d:]+\s*[ap]m)", clean(te.get_text(" ")), re.I)
            if sm:
                showtime = to_time(sm.group(1))
        a = sec.find("a", href=True)
        url = a["href"] if a else "https://showdownpdx.com/"
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Central Eastside", ""))
        # Same TicketWeb widget as Dante's and Star: poster on i.ticketweb.com,
        # ticket link on ticketweb.com/event, and the age as plain text
        # ("21 and up") with no class of its own -- read from the section's
        # text through the same conservative _age_in_text as everywhere else.
        tl = sec.find("a", href=re.compile(r"ticketweb\.com/event"))
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": url,
                      "ticketUrl": tl["href"] if tl else "",
                      "imageUrl": _img_from(sec, "i.ticketweb.com"),
                      "age": _age_from(sec) or _age_in_text(sec.get_text(" "))})
        added += 1
    return added


def parse_showdown(html, today):
    """showdownpdx.com paginates ten to a page and runs seven pages deep;
    the parser read page one only, so the feed showed 10 shows ending eight
    days out. Follow rel=next until it runs out, capped at 10 pages, with
    the same tolerance as Portland'5: a failed page ends the walk."""
    shows, seen = [], set()
    soup = BeautifulSoup(html, "html.parser")
    _showdown_page(soup, today, shows, seen)
    for _ in range(9):
        nxt = soup.select_one("a[rel=next], a.next")
        href = nxt.get("href") if nxt else None
        if not href or "/page/" not in href:
            break
        try:
            soup = BeautifulSoup(fetch(href), "html.parser")
        except Exception:
            break
        if _showdown_page(soup, today, shows, seen) == 0:
            break
        time.sleep(0.5)
    return shows



# =============================================================================
# DROP-IN REPLACEMENT for parse_laurelthirst in scrape_venues.py
#
# STATUS: NOT RUN LIVE. Authored against ground truth pulled from the live site
# through a browser session; the Python itself has never executed against
# laurelthirst.com. See HANDOFF-laurelthirst.md for the verified/unverified
# split before you trust any of this.
#
# WHAT CHANGED AND WHY
# --------------------
# The old parser read the WordPress CPT route /wp-json/wp/v2/ajde_events, which
# lists event POSTS. Laurelthirst runs residencies, and EventON stores every
# occurrence of a residency inside ONE post. A post-shaped reader therefore
# cannot see repeats, no matter how many pages it walks:
#
#   1. RECURRENCE COLLAPSE - itemprop="startDate" on an event page exposes only
#      the FIRST occurrence. 34 of 98 upcoming occurrences are repeat instances.
#   2. WHOLE-SERIES DISCARD - the range filter tested that single first date, so
#      a series whose instance 0 is past was dropped entirely, taking its live
#      future instances with it (Freak Mountain Ramblers instance 0 = 2026-08-02,
#      which threw away real 8/23 and 8/30 shows).
#   3. WASTED BUDGET - orderby=date is PUBLISH date, so most of the 200-post cap
#      was spent on already-happened events.
#
# This version reads OCCURRENCES from EventON's own calendar endpoint. One
# request per month instead of one request per event post: ~6 requests replacing
# ~200, and every recurrence instance arrives as its own row.
# =============================================================================

# ---- Laurelthirst Public House (laurelthirst.com) ----------------------------
# WordPress + EventON 5.0.13. The calendar is driven by a POST endpoint,
# ?evo-ajax=eventon_get_events, which returns {"status","json","html",...}.
# We read the "html" payload: it contains one .eventon_list_event block per
# OCCURRENCE, each carrying data-time="<start_epoch>-<end_epoch>".
#
# Two field traps, both confirmed against the live site:
#
#   * Use data-time, NOT the "json" array's event_start_unix. event_start_unix
#     is correct only for non-repeating events; for recurrence instances it is
#     wrong (Lewi Longmire instance 2 reports 2026-08-21T01:00 where the real
#     show is 2026-08-20 18:00 - off by 7h and a calendar day). data-time is a
#     true epoch and matches the per-occurrence schema.org startDate every time,
#     including across the 2026-11-01 DST boundary.
#
#   * shortcode[fixed_month] is 1-BASED-PLUS-ONE: fixed_month=9 renders August,
#     13 renders December, 14 rolls over to January of the next year. So
#     fixed_month = calendar_month + 1 + 12*(year - fixed_year).
#     We do not rely on this for correctness - every occurrence is filtered by
#     its own epoch, so a month-index drift can only cost coverage, never
#     produce a wrong date. We also fetch one month past the horizon as margin.
LAUREL_BASE = "https://laurelthirst.com"
LAUREL_CAL = LAUREL_BASE + "/music-calendar/"
LAUREL_AJAX = LAUREL_BASE + "/?evo-ajax=eventon_get_events"
LAUREL_HORIZON_DAYS = 120      # matches the other parsers; scrape() then clips
                               # everything to the global HORIZON_DAYS (90)
LAUREL_PAUSE = 0.6             # seconds between month requests - be a good guest

# The calendar page ships both nonces inline in the evo_general_params object.
# They map to the POST fields CROSSED OVER: params "n" -> field "nonce", and
# params "nonce" -> field "nonceX". Sending them straight through fails with
# {"status":"bad","msg":"Nonce validation failed"}.
_LAUREL_N = re.compile(r'"n"\s*:\s*"([0-9a-zA-Z]+)"')
_LAUREL_NONCE = re.compile(r'"nonce"\s*:\s*"([0-9a-zA-Z]+)"')


def _laurel_pacific():
    """America/Los_Angeles, or a fixed -08:00 if the tz database is missing.

    The fallback is deliberately crude: it can be an hour off during PDT, but a
    missing tzdata must not take the whole venue to zero."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=-8))


def _laurel_nonces(html):
    """Pull (nonce, nonceX) out of the calendar page's evo_general_params blob.

    Scoped to the window right after the variable name so a stray "n": elsewhere
    in 330KB of page source cannot poison it."""
    i = html.find("evo_general_params")
    window = html[i:i + 3000] if i >= 0 else html
    n = _LAUREL_N.search(window)
    nonce = _LAUREL_NONCE.search(window)
    if not (n and nonce):
        return None
    return n.group(1), nonce.group(1)


def _laurel_month(fixed_month, fixed_year, nonce, nonce_x):
    """One month of calendar HTML, or '' on any failure."""
    body = {
        "shortcode[calendar_type]": "default",
        "shortcode[event_count]": "200",
        "shortcode[number_of_months]": "1",
        "shortcode[fixed_month]": str(fixed_month),
        "shortcode[fixed_year]": str(fixed_year),
        "shortcode[hide_past]": "no",
        "shortcode[event_past_future]": "all",
        "shortcode[sort_by]": "sort_date",
        "shortcode[_cver]": "5.0.13",
        "ajaxtype": "switchmonth",
        "nonce": nonce,
        "nonceX": nonce_x,
    }
    try:
        r = requests.post(LAUREL_AJAX, data=body,
                          headers={"User-Agent": _BROWSER_UA,
                                   "X-Requested-With": "XMLHttpRequest",
                                   "Referer": LAUREL_CAL},
                          timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  WARN: laurelthirst month {fixed_month}/{fixed_year} failed: "
              f"{type(e).__name__}: {e}")
        return ""
    if str(data.get("status", "")).upper() != "GOOD":
        print(f"  WARN: laurelthirst month {fixed_month}/{fixed_year} returned "
              f"status={data.get('status')!r} msg={data.get('msg')!r}")
        return ""
    return data.get("html") or ""


def parse_laurelthirst(html, today):
    """Return one row per OCCURRENCE across the horizon.

    `html` is the fetched LAUREL_CAL page - we need it only for the nonces.
    Fails soft: any breakage returns whatever was gathered so far (possibly
    empty) rather than raising, so a dead source cannot abort the run."""
    out = []
    try:
        tz = _laurel_pacific()
        horizon = today + datetime.timedelta(days=LAUREL_HORIZON_DAYS)

        pair = _laurel_nonces(html or "")
        if not pair:
            # Retry once with our own fetch, in case the caller handed us a
            # page without the calendar shortcode on it.
            try:
                pair = _laurel_nonces(fetch(LAUREL_CAL))
            except Exception:
                pair = None
        if not pair:
            print("  WARN: laurelthirst nonces not found on calendar page")
            return out
        nonce, nonce_x = pair

        # Months to walk: current month through one past the horizon.
        base_year = today.year
        months = []
        y, m = today.year, today.month
        while (y, m) <= (horizon.year, horizon.month):
            months.append((m + 1 + 12 * (y - base_year), base_year))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        months.append((m + 1 + 12 * (y - base_year), base_year))   # margin month

        seen = set()
        for idx, (fixed_month, fixed_year) in enumerate(months):
            if idx:
                time.sleep(LAUREL_PAUSE)
            frag = _laurel_month(fixed_month, fixed_year, nonce, nonce_x)
            if not frag:
                continue
            soup = BeautifulSoup(frag, "html.parser")
            for el in soup.select(".eventon_list_event"):
                dt = (el.get("data-time") or "").split("-")
                if not dt or not dt[0].isdigit():
                    continue
                start = int(dt[0])
                ev_id = el.get("data-event_id") or ""
                ri = str(el.get("data-ri") or "").replace("r", "")
                key = (ev_id, ri, start)
                if key in seen:
                    continue
                seen.add(key)

                local = datetime.datetime.fromtimestamp(start, tz)
                d = local.date()
                if not (today <= d <= horizon):
                    continue

                node = el.select_one('[itemprop="name"]')
                raw = ""
                if node is not None:
                    raw = node.get("content") or node.get_text(" ", strip=True) or ""
                title = clean(raw.replace("&amp;", "&"))
                title = re.sub(r"\s+", " ", re.sub(r"[‐-―]", "-", title)).strip()
                if not title:
                    continue

                link = el.select_one('[itemprop="url"]')
                url = (link.get("href") or "").strip() if link is not None else ""
                img_el = el.select_one('[itemprop="image"]')
                img = ""
                if img_el is not None:
                    img = (img_el.get("content") or img_el.get("src") or "").strip()
                if not img:
                    # Laurelthirst does not set a featured image; the poster is
                    # pasted into the event description as an ordinary <img>
                    # from wp-content/uploads. 22 of 28 events carried one in
                    # the captured September month. Anything not their own
                    # upload (an emoji, a tracking pixel) is left alone.
                    desc = el.select_one(".eventon_full_description, .evo_metarow_details")
                    for cand in (desc.find_all("img") if desc else []):
                        src = (cand.get("src") or cand.get("data-src") or "").strip()
                        if "wp-content/uploads" in src:
                            img = src
                            break

                hh, mn = local.hour, local.minute
                tm = "%d:%02d %s" % (hh % 12 or 12, mn, "AM" if hh < 12 else "PM")

                nb, addr = VENUE_INFO.get("Laurelthirst Public House",
                                          ("Kerns", "2958 NE Glisan St"))
                out.append({"title": title, "venue": "Laurelthirst Public House",
                            "neighborhood": nb, "address": addr,
                            "date": d.isoformat(), "time": tm,
                            "venueUrl": url, "imageUrl": img})
    except Exception as e:
        print(f"  WARN: laurelthirst parser aborted: {type(e).__name__}: {e}")
    out.sort(key=lambda s: (s["date"], s["time"], s["title"]))
    return out


def parse_albertastreetpub(html, today):
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today
    try:
        data = json.loads(html)
    except Exception:
        return out
    for e in data.get("upcoming", []):
        sd = e.get("startDate")
        if not sd:
            continue
        dt = datetime.datetime.fromtimestamp(sd / 1000, tz=datetime.timezone.utc).astimezone(_ASP_PDT)
        d = dt.date()
        if not (lower <= d <= horizon):
            continue
        date = d.isoformat()
        tm = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
        title = clean((e.get("title") or "").replace("&amp;", "&"))
        title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip()
        if not title:
            continue
        fu = e.get("fullUrl") or ""
        url = ("https://www.albertastreetpub.com" + fu) if fu.startswith("/") else (fu or "https://www.albertastreetpub.com/music")
        key = (date, title.lower())
        if key in seen:
            continue
        seen[key] = 1
        nb, addr = VENUE_INFO.get("Alberta Street Pub", ("Alberta Arts", "1036 NE Alberta St"))
        out.append({"title": title, "venue": "Alberta Street Pub",
                    "neighborhood": nb, "address": addr,
                    "date": date, "time": tm, "venueUrl": url, "imageUrl": (e.get("assetUrl") or "")})
    return out



def parse_mississippipizza(html, today):
    # Mississippi Pizza & Atlantis Lounge (mississippipizza.com) - WordPress + RHP
    # events plugin. The /calendar/ page server-renders all events as
    # .rhpSingleEvent blocks (no AJAX pagination needed, unlike Revolution Hall).
    soup = BeautifulSoup(html, "html.parser")
    img_by_url = _img_map_by_event_url(soup)  # 34/34 on the captured page
    nb, addr = VENUE_INFO["Mississippi Pizza"]
    shows = []
    for e in soup.select(".rhpSingleEvent"):
        de = e.select_one("#eventDate") or e.select_one(".singleEventDate")
        a = e.select_one("a.url") or e.select_one("a#eventTitle")
        if not de or not a:
            continue
        mm = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", clean(de.get_text()))
        if not mm:
            continue
        mo = MONTHS.get(mm.group(1)[:3].title())
        if not mo:
            continue
        date = f"{int(mm.group(3)):04d}-{mo:02d}-{int(mm.group(2)):02d}"
        h2 = a.select_one("h2")
        title = clean(h2.get_text()) if h2 else clean(a.get("title") or a.get_text())
        if not title:
            continue
        te = e.select_one(".eventDoorStartDate")
        tm = to_time(clean(te.get_text())) if te else ""
        shows.append({"title": title, "venue": "Mississippi Pizza",
                      "neighborhood": nb, "address": addr,
                      "date": date, "time": tm,
                      "venueUrl": a.get("href", ""),
                      "imageUrl": img_by_url.get((a.get("href", "") or "").split("?")[0], ""),
                      "age": _age_from(e)})
    return shows


def parse_bunkbar(html, today):
    # Bunk Bar (shows.bunksandwiches.com) - Next.js App Router. Events are
    # server-rendered into EventCard_* CSS-module divs. Date + start time are
    # emitted in UTC; convert to Pacific (PDT, UTC-7) for the correct local
    # date and time (a late-evening show rolls back one calendar day).
    import datetime as _dt
    soup = BeautifulSoup(html, "html.parser")
    nb, addr = VENUE_INFO["Bunk Bar"]
    shows = []
    for c in soup.select('div[class*="EventCard_eventCard__"]'):
        de = c.select_one('p[class*="EventCard_eventDate__"]')
        h2 = c.find("h2")
        ul = c.find("ul")
        if not de or not h2:
            continue
        mm = re.search(r"([A-Za-z]+)\s+(\d{1,2})", clean(de.get_text()))
        if not mm:
            continue
        mo = MONTHS.get(mm.group(1)[:3].title())
        if not mo:
            continue
        day = int(mm.group(2))
        yr = infer_year(mo, today)
        title = clean(h2.get_text())
        if not title:
            continue
        tt = clean(ul.get_text()) if ul else ""
        tmatch = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", tt)
        if tmatch:
            hh = int(tmatch.group(1)) % 12 + (12 if tmatch.group(3) == "PM" else 0)
            mn = int(tmatch.group(2))
            dt_p = _dt.datetime(yr, mo, day, hh, mn) - _dt.timedelta(hours=7)
            date = dt_p.strftime("%Y-%m-%d")
            tm = dt_p.strftime("%I:%M %p").lstrip("0")
        else:
            date = f"{yr:04d}-{mo:02d}-{day:02d}"
            tm = ""
        a = h2.find_parent("a") or c.find("a", href=True)
        url = a.get("href") if a and a.get("href") else "https://shows.bunksandwiches.com/"
        if url.startswith("/"):
            url = "https://shows.bunksandwiches.com" + url
        # Poster: every card carries one, served through Next.js's
        # /_next/image?url=<cdn>&w=... wrapper. Unwrap to the CDN URL so the
        # feed does not depend on their image route or its width parameter.
        img = ""
        im = c.find("img")
        if im is not None:
            src = (im.get("src") or "").strip()
            if "/_next/image" in src and "url=" in src:
                from urllib.parse import urlparse, parse_qs
                src = (parse_qs(urlparse(src).query).get("url") or [""])[0]
            if src.startswith("http"):
                img = src
        shows.append({"title": title, "venue": "Bunk Bar",
                      "neighborhood": nb, "address": addr,
                      "date": date, "time": tm, "venueUrl": url, "imageUrl": img,
                      "age": _age_in_text(c.get_text(" "))})
    return shows


_NOFUN_SKIP = re.compile(r"^\s*(NO FUN KARAOKE|Bridgetown Trivia|CLOSED|Poser Tom'?s Roadshow Arcade)\b", re.I)


def _nofun_html(html, today):
    """No Fun's events page as rendered HTML. Squarespace's ?format=json for
    this site started returning its own "Please Stand By" error page
    (HTTP 200, 3.9 KB) on 2026-09-13 and stayed that way; the HTML page
    kept working. Standard Squarespace event list: .eventlist-event with a
    <time class="event-date" datetime="YYYY-MM-DD">, a start time in
    .event-time-localized-start, the title, a poster, and an excerpt that
    always says "21+". Karaoke, trivia, the arcade night and CLOSED days
    are on the calendar too and are skipped."""
    out, seen = [], set()
    soup = BeautifulSoup(html, "html.parser")
    nb, addr = VENUE_INFO.get("No Fun", ("Buckman", "1709 SE Hawthorne Blvd"))
    horizon = today + datetime.timedelta(days=120)
    for e in soup.select(".eventlist-event"):
        t = e.select_one(".eventlist-title")
        title = clean(t.get_text(" ")) if t else ""
        title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip()
        # Unannounced openers are listed as "• TBA • TBA"; drop the
        # placeholders so the card names the acts that are booked.
        title = re.sub(r"(\s*[•·]\s*TBA)+\s*$", "", title, flags=re.I).strip()
        if not title or _NOFUN_SKIP.search(title):
            continue
        d = e.select_one("time.event-date")
        date = (d.get("datetime") or "").strip()[:10] if d else ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        dd = datetime.date.fromisoformat(date)
        if not (today <= dd <= horizon):
            continue
        st = e.select_one("time.event-time-localized-start")
        tm = to_time(st.get_text(" ", strip=True)) if st else ""
        a = e.select_one(".eventlist-title a, a.eventlist-title-link")
        href = (a.get("href") or "") if a else ""
        url = ("https://www.nofunportland.com" + href) if href.startswith("/") else (href or "https://www.nofunportland.com/events")
        im = e.select_one("img")
        img = ((im.get("data-src") or im.get("src") or "").strip()) if im else ""
        ex = e.select_one(".eventlist-excerpt, .eventlist-description")
        age = _age_in_text(ex.get_text(" ")) if ex else ""
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "No Fun", "neighborhood": nb, "address": addr,
                    "date": date, "time": tm, "venueUrl": url, "imageUrl": img, "age": age})
    return out


def parse_nofun(html, today):
    # No Fun (nofunportland.com) - Squarespace events collection. The
    # /events?format=json endpoint returns an "upcoming" list with startDate
    # epoch ms in UTC; convert to Pacific (PDT) like Alberta Street Pub. Same
    # business as Devil's Dill; address verified at 1709 SE Hawthorne Blvd.
    #
    # 2026-09-15: the JSON endpoint has been serving Squarespace's own error
    # page for three nights (YIELD-ZERO caught it). The rendered HTML page
    # is fine, so that is the source now; this JSON path is kept as the
    # fallback for the day Squarespace fixes theirs.
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today
    if html.lstrip().startswith("<"):
        return _nofun_html(html, today)
    try:
        data = json.loads(html)
    except Exception:
        return out
    nb, addr = VENUE_INFO.get("No Fun", ("Buckman", "1709 SE Hawthorne Blvd"))
    for e in data.get("upcoming", []):
        sd = e.get("startDate")
        if not sd:
            continue
        dt = datetime.datetime.fromtimestamp(sd / 1000, tz=datetime.timezone.utc).astimezone(_ASP_PDT)
        d = dt.date()
        if not (lower <= d <= horizon):
            continue
        date = d.isoformat()
        tm = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
        title = clean((e.get("title") or "").replace("&amp;", "&"))
        title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip()
        if not title:
            continue
        fu = e.get("fullUrl") or ""
        url = ("https://www.nofunportland.com" + fu) if fu.startswith("/") else (fu or "https://www.nofunportland.com/events")
        key = (date, title.lower())
        if key in seen:
            continue
        seen[key] = 1
        out.append({"title": title, "venue": "No Fun",
                    "neighborhood": nb, "address": addr,
                    "date": date, "time": tm, "venueUrl": url, "imageUrl": (e.get("assetUrl") or "")})
    return out


def parse_twilight(html, today):
    # Twilight Cafe & Bar (twilightcafeandbar.com, HoldMyTicket CMS). The
    # /calendar_list page server-renders month-grid <table>s: a th.heading
    # holds "Month YYYY", each td.daywrap has a .daylabel day number and any
    # events as .event-title (+ a .cal_flyer_wrap/.cal_buy link). No showtime
    # is exposed in the grid, so time is left blank. Max one event per cell.
    soup = BeautifulSoup(html, "html.parser")
    nb, addr = VENUE_INFO["Twilight Cafe & Bar"]
    shows, seen = [], set()
    for tbl in soup.find_all("table"):
        head = tbl.select_one("th.heading")
        if not head:
            continue
        mh = re.search(r"([A-Za-z]+)\s+(\d{4})", clean(head.get_text()))
        if not mh:
            continue
        mo = MONTHS.get(mh.group(1)[:3].title())
        yr = int(mh.group(2))
        if not mo:
            continue
        for cell in tbl.select("td.daywrap"):
            dl = cell.select_one(".daylabel")
            if not dl:
                continue
            dm = re.search(r"\d+", dl.get_text())
            if not dm:
                continue
            day = int(dm.group(0))
            for et in cell.select(".event-title"):
                title = clean(et.get_text())
                title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip()
                if not title:
                    continue
                a = cell.select_one(".cal_flyer_wrap a") or cell.select_one("a.cal_buy")
                href = a.get("href") if a and a.get("href") else ""
                if href and not href.startswith("http"):
                    href = "https://twilightcafeandbar.com/" + href.lstrip("/")
                if not href:
                    href = "https://twilightcafeandbar.com/calendar_list"
                date = f"{yr:04d}-{mo:02d}-{day:02d}"
                key = (date, title.lower())
                if key in seen:
                    continue
                seen.add(key)
                img = _bump(_img_from(a, "flyers2"))
                shows.append({"title": title, "venue": "Twilight Cafe & Bar",
                              "neighborhood": nb, "address": addr,
                              "date": date, "time": "", "venueUrl": href, "imageUrl": img})
    return shows


def parse_pdxlive(html, today):
    # Pioneer Courthouse Square / PDX Live summer concert series. pdx-live.com
    # runs the WLCR WordPress theme (same family as Mississippi Studios); its
    # /wp-json/wlcr/v1/events/raw endpoint returns a clean JSON list. Each
    # event's start.local already holds the correct local date+time, and
    # venue.name is authoritative (we only keep Pioneer Courthouse Square).
    out, seen = [], set()
    try:
        data = json.loads(html)
    except Exception:
        return out
    if not isinstance(data, list):
        return out
    for e in data:
        nm = e.get("name")
        title = clean(nm.get("text")) if isinstance(nm, dict) else clean(str(nm or ""))
        title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip()
        st = e.get("start") or {}
        loc = st.get("local") if isinstance(st, dict) else None
        if not title or not loc:
            continue
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", loc)
        if not m:
            continue
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        hh, mn = int(m.group(4)), int(m.group(5))
        tm = "%d:%02d %s" % (hh % 12 or 12, mn, "AM" if hh < 12 else "PM")
        ven = e.get("venue")
        vname = clean(ven.get("name")) if isinstance(ven, dict) else ""
        if vname and "pioneer courthouse" not in vname.lower():
            continue
        nb, addr = VENUE_INFO["Pioneer Courthouse Square"]
        url = e.get("url") or "https://pdx-live.com/"
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "Pioneer Courthouse Square",
                    "neighborhood": nb, "address": addr,
                    "date": date, "time": tm, "venueUrl": url, "imageUrl": ((e.get("logo") or {}).get("url") or "")})
    return out

# ---- Wix Events sites (Tomorrow's Verse, The Ruins) -- browserless, two tiers.
#
# History: the first Tomorrow's Verse parser regex-hunted an "instance" token
# in the page and POSTed it to the Wix Events query API with a bare
# requests.post(). That returned 401/428 on every run, so the venue scraped
# zero for weeks. Two things were wrong, found by driving the site from a
# browser in Sep 2026: the token it wanted lives in the SSR'd warmup blob (its
# payload is not the base64 JSON the regex filter demanded, so it was never
# picked), and the API refuses requests that arrive without the cookies the
# page response sets (428 Precondition Required with no cookies; 200 with
# them, even with no Authorization header at all).
#
# So, two tiers, cheapest first:
#   1. WARMUP. Every Wix page ships <script id="wix-warmup-data"> with the
#      events widget's first page of events already in it -- full objects,
#      no request beyond the page GET. For a small calendar (The Ruins:
#      hasMore=false) this is everything.
#   2. API, only when the warmup says hasMore. The page is fetched in a
#      requests.Session so its cookies carry into the POST, plus the warmup
#      instance as Authorization and the XSRF cookie mirrored as a header.
#      Any failure here falls back to the warmup events with a WARN --
#      strictly better than the zero this venue produced before.
#
# Event URLs are /event-details/<slug> on both sites (the old parser built
# /events/<slug>, which 404s).
_WIX_EVENTS_APPDEF = "140603ad-af8d-84a5-2c80-a0f60cb47351"  # Wix Events appDefId
_WIX_WARMUP_RE = re.compile(r'<script[^>]*id="wix-warmup-data"[^>]*>(.*?)</script>', re.S)

def _tz(tzid):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tzid or "America/Los_Angeles")
    except Exception:
        return _ASP_PDT

def _wix_warmup_events(html):
    """(events, instance, has_more) from the page's warmup blob; ([], None, False) if absent."""
    m = _WIX_WARMUP_RE.search(html or "")
    if not m:
        return [], None, False
    try:
        data = json.loads(m.group(1))
    except Exception:
        return [], None, False
    app = (data.get("appsWarmupData") or {}).get(_WIX_EVENTS_APPDEF) or {}
    for widget in app.values():
        if not isinstance(widget, dict):
            continue
        ev = widget.get("events")
        if isinstance(ev, dict) and isinstance(ev.get("events"), list):
            # The warmup's `instance` is a bare token string on some sites and
            # a dict ({instance, instanceId, appDefId, ...}) on others --
            # theruins.org ships the first shape, youenjoymybeer.com the
            # second. Handing the dict straight to the Authorization header
            # raises InvalidHeader and falls back to the warmup page, which is
            # what kept Tomorrow's Verse at 20 instead of its full calendar.
            inst = widget.get("instance")
            if isinstance(inst, dict):
                inst = inst.get("instance")
            if not isinstance(inst, str):
                inst = None
            return ev["events"], inst, bool(ev.get("hasMore"))
    return [], None, False

def _wix_fresh_instance(sess, origin, headers):
    """A live Wix Events instance token from the site's dynamic model, or None."""
    try:
        r = sess.get(origin + "/_api/v2/dynamicmodel", headers=headers, timeout=30)
        if r.status_code != 200:
            return None
        inst = ((r.json().get("apps") or {}).get(_WIX_EVENTS_APPDEF) or {}).get("instance")
        return inst if isinstance(inst, str) and inst else None
    except Exception as e:
        print(f"  WARN: Wix dynamicmodel fetch failed ({origin}): {type(e).__name__}: {e}; "
              f"falling back to the warmup token")
        return None


def _wix_all_events(page_url, prefetched_html):
    """Every scheduled event for one Wix Events site (see tiers above)."""
    origin = re.match(r"https?://[^/]+", page_url).group(0)
    sess = requests.Session()
    headers = {"User-Agent": _BROWSER_UA}
    html = prefetched_html
    try:
        r = sess.get(page_url, headers=headers, timeout=30)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        print(f"  WARN: Wix page re-fetch failed ({page_url}): {type(e).__name__}: {e}; using the first fetch")
    initial, instance, has_more = _wix_warmup_events(html)
    if not initial and not has_more:
        raise RuntimeError(f"Wix: no wix-warmup-data events block in {page_url}")
    if not has_more:
        return initial
    api = origin + "/_api/wix-events-web/v1/events/query"
    h = dict(headers)
    h["Content-Type"] = "application/json"
    # The warmup instance is NOT safe to send. The page is served through a
    # CDN cache (the response sets an `ssr-caching` cookie), so the warmup
    # blob -- token included -- is frozen at whenever that cache was rendered.
    # Diagnosed 2026-09-14: the page's token carried signDate 2026-09-13T05:34,
    # 36 hours old, and the API answered 401. It had worked the night before
    # only because the cache happened to be fresh then.
    #
    # /_api/v2/dynamicmodel is what the Wix client itself calls to bootstrap
    # app instances, is never served from the page cache, and returned a token
    # signed to the second. One extra GET, in the same session so cookies
    # carry. The warmup token stays as the fallback if this fails.
    fresh = _wix_fresh_instance(sess, origin, headers)
    if fresh:
        instance = fresh
    if instance:
        h["Authorization"] = instance
    xsrf = sess.cookies.get("XSRF-TOKEN")
    if xsrf:
        h["x-xsrf-token"] = xsrf
    raw, offset = [], 0
    try:
        while True:
            # DETAILS is the fieldset that carries mainImage; FULL alone does
            # not. Probed live 2026-09-15: FULL -> 20 keys, no image; DETAILS
            # -> 22 keys, image present. The warmup blob always had it, which
            # is why the parser already read mainImage while the feed showed
            # 0/76 -- the API tier serves nearly every row.
            body = json.dumps({"limit": 100, "offset": offset, "fieldset": ["FULL", "DETAILS"],
                               "filter": {"status": ["SCHEDULED", "STARTED"]}})
            resp = sess.post(api, headers=h, data=body, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            page = resp.json()
            evs = page.get("events") or []
            raw.extend(evs)
            total = page.get("total", len(raw))
            offset += len(evs)
            if not evs or offset >= total or len(raw) >= 2000:
                break
        return raw if raw else initial
    except Exception as e:
        print(f"  WARN: Wix events API failed ({origin}): {type(e).__name__}: {e}; "
              f"using the {len(initial)} warmup events")
        _DEGRADED_ORIGINS.add(origin)
        return initial

def _wix_rows(raw, venue, origin, today):
    if origin in _DEGRADED_ORIGINS:
        DEGRADED_VENUES.add(venue)
    """Wix event objects (warmup or API shape -- they differ only in status
    encoding and startDate millis) -> show dicts."""
    nb, addr = VENUE_INFO.get(venue, ("", ""))
    out, seen = [], set()
    for e in raw:
        st = e.get("status")
        if st not in (0, "SCHEDULED", "STARTED", None):
            continue
        cfg = (e.get("scheduling") or {}).get("config") or {}
        sd = cfg.get("startDate")
        if not sd or cfg.get("scheduleTbd"):
            continue
        try:
            iso = re.sub(r"\.\d+Z$", "Z", str(sd)).replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(iso).astimezone(_tz(cfg.get("timeZoneId")))
        except Exception:
            continue
        date = dt.date().isoformat()
        tm = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
        title = clean(e.get("title") or "")
        title = re.sub(r"\s+", " ", re.sub(r"[‐-―]", "-", title)).strip()
        if not title:
            continue
        slug = e.get("slug") or ""
        url = origin + "/event-details/" + slug if slug else origin
        mi = e.get("mainImage") or {}
        img = mi.get("url") or (("https://static.wixstatic.com/media/" + mi["id"]) if mi.get("id") else "")
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": venue, "neighborhood": nb, "address": addr,
                    "date": date, "time": tm, "venueUrl": url, "imageUrl": img})
    return out

_TV_EVENTS_PAGE = "https://www.youenjoymybeer.com/events"

def parse_tomorrowsverse(html, today):
    raw = _wix_all_events(_TV_EVENTS_PAGE, html)
    return _wix_rows(raw, "Tomorrow's Verse", "https://www.youenjoymybeer.com", today)

_RUINS_PAGE = "https://www.theruins.org/music-calendar"

def parse_theruins(html, today):
    # The Ruins, Hood River (Columbia Gorge) -- Wix Events. Small calendar;
    # the warmup blob has carried every upcoming show (hasMore=false) each
    # time it was checked, so tier 2 is rarely reached.
    raw = _wix_all_events(_RUINS_PAGE, html)
    return _wix_rows(raw, "The Ruins", "https://www.theruins.org", today)


# ---- Trout Lake Hall (troutlakehall.com) -- Squarespace + Event Calendar App, browserless.
# The Squarespace site itself has no events collection (its /?format=json is a
# plain page titled "Shows"). The calendar is a third-party embed,
# eventcalendarapp.com, mounted by a website-component block. Two ids are in
# the homepage HTML -- data-widgetuuid on the container and window.eventCalId
# in the inline script beside it -- and the widget's own feed is a plain GET:
#   https://api.eventcalendarapp.com/events?id=<calId>&widgetUuid=<uuid>&inAdminPanel=false
# JSON: {events:[...], pages:{current,total,nextPage}}; utcStartTime is epoch
# SECONDS with a per-event IANA timezone. 15 per page, follow nextPage.
# Both ids are required: without id the API answers 403.
_TLH_HOME = "https://www.troutlakehall.com/"
_TLH_API = "https://api.eventcalendarapp.com/events"
# Not shows. The hall's calendar also carries its own closures and community
# nights; the site-wide classifier does not know these titles, so they are
# dropped here. Open mics are kept -- they are live music.
_TLH_SKIP = re.compile(r"closed|private event|bingo|boo-o|gift-o|game night|trivia|cook-off", re.I)

def _tlh_ids(html):
    m_uuid = re.search(r'data-widgetuuid="([0-9a-fA-F-]{36})"', html or "")
    m_id = re.search(r'window\.eventCalId\s*=\s*["\']?(\d+)', html or "")
    return (m_id.group(1) if m_id else None), (m_uuid.group(1) if m_uuid else None)

def _tlh_rows(pages, today):
    nb, addr = VENUE_INFO["Trout Lake Hall"]
    out, seen = [], set()
    for page in pages:
        for e in (page.get("events") or []):
            ts = e.get("utcStartTime")
            title = re.sub(r"\s+", " ", clean(e.get("summary") or "")).strip()
            if not ts or not title or _TLH_SKIP.search(title):
                continue
            try:
                dt = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).astimezone(_tz(e.get("timezone")))
            except Exception:
                continue
            date = dt.date().isoformat()
            tm = "" if e.get("isAllDayEvent") else "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
            key = (date, title.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "venue": "Trout Lake Hall", "neighborhood": nb, "address": addr,
                        "date": date, "time": tm,
                        "venueUrl": e.get("ticketsLink") or _TLH_HOME,
                        "imageUrl": e.get("image") or e.get("thumbnail") or ""})
    return out

def parse_troutlakehall(html, today):
    cal_id, uuid = _tlh_ids(html)
    if not (cal_id and uuid):
        raise RuntimeError("Trout Lake Hall: eventcalendarapp ids (window.eventCalId / data-widgetuuid) not found in page HTML")
    url = f"{_TLH_API}?id={cal_id}&widgetUuid={uuid}&inAdminPanel=false"
    headers = {"User-Agent": _BROWSER_UA, "Referer": _TLH_HOME, "Origin": _TLH_HOME.rstrip("/")}
    pages, n = [], 0
    while url and n < 10:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        j = r.json()
        pages.append(j)
        n += 1
        pg = j.get("pages") or {}
        nxt = pg.get("nextPage")
        url = nxt if (nxt and (pg.get("current") or 0) < (pg.get("total") or 0)) else None
    return _tlh_rows(pages, today)


# ---- Cascades Amphitheater (Ridgefield, WA) -- Live Nation / Ticketmaster, browserless.
# First non-Oregon venue (regional destination amphitheater). Event data is server-rendered
# into the Next.js __next_f RSC stream in the venue page HTML (no API key / token needed).
_CASCADES_URL = "https://www.livenation.com/venue/KovZpZAJld6A/cascades-amphitheater-events"


def _cascades_field(field, seg):
    m = re.search(r'\\"' + field + r'\\":\\"(.*?)\\"', seg)
    return m.group(1) if m else None


def _cascades_unesc(v):
    if not v:
        return ""
    v = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), v)
    return clean(v)


def _cascades_flight(html):
    """Reassemble the Next.js RSC stream: concat all self.__next_f.push([N,"..."])
    string chunks into one decoded 'flight' text. Robust (no regex field-plucking)."""
    chunks = []
    for m in re.finditer(r'self\.__next_f\.push\(\[\d+,', html):
        j = m.end()
        if j >= len(html) or html[j] != '"':
            continue
        k = j + 1
        buf = ['"']
        while k < len(html):
            c = html[k]
            buf.append(c)
            if c == '\\':
                if k + 1 < len(html):
                    buf.append(html[k + 1])
                k += 2
                continue
            if c == '"':
                break
            k += 1
        try:
            chunks.append(json.loads(''.join(buf)))
        except Exception:
            pass
    return ''.join(chunks)


def _cascades_enclosing_obj(text, pos):
    """Return the smallest balanced {...} substring enclosing position `pos`."""
    i = pos
    depth = 0
    while i >= 0:
        c = text[i]
        if c == '}':
            depth += 1
        elif c == '{':
            if depth == 0:
                break
            depth -= 1
        i -= 1
    if i < 0:
        return None
    start = i
    depth = 0
    instr = False
    esc = False
    j = start
    while j < len(text):
        c = text[j]
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            instr = not instr
        elif not instr:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[start:j + 1]
        j += 1
    return None


def _cascades_image_map(flight):
    """Build {image_id: images[]} by json.loads-ing each wrapper object that holds
    an 'images' array and an 'id'. The id equals the concert's discovery_id."""
    img_map = {}
    for m in re.finditer(r'"images":\[', flight):
        sub = _cascades_enclosing_obj(flight, m.start())
        if not sub:
            continue
        try:
            obj = json.loads(sub)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get('id') and isinstance(obj.get('images'), list):
            img_map.setdefault(obj['id'], obj['images'])
    return img_map


def _cascades_pick_image(images):
    """Pick TABLET_LANDSCAPE_LARGE_16_9; fall back to any other *_16_9; then ''."""
    by_id = {}
    for v in images:
        if isinstance(v, dict) and v.get('identifier'):
            by_id.setdefault(v['identifier'], v.get('url') or '')
    if 'TABLET_LANDSCAPE_LARGE_16_9' in by_id:
        return by_id['TABLET_LANDSCAPE_LARGE_16_9']
    for ident, url in by_id.items():
        if ident.endswith('16_9') and url:
            return url
    return ''


def parse_cascades(html, today):
    """Parse Live Nation venue page (__next_f RSC payload) for Cascades Amphitheater.

    Images are joined deterministically: each concert object carries a `discovery_id`,
    and the RSC payload holds image-wrapper objects keyed by an `id` that equals that
    discovery_id. We reassemble the RSC chunks, json.loads the image wrappers, and look
    up each concert's poster by discovery_id (no fuzzy/slug/name matching).
    """
    idxs = [m.start() for m in re.finditer(r'\\"start_date_local\\"', html)]
    if not idxs:
        raise RuntimeError("Cascades: no event data (start_date_local) found in page HTML")
    bounds = idxs + [len(html)]
    # Robust, JSON-parsed image collection keyed by discovery_id (image wrapper 'id').
    flight = _cascades_flight(html)
    img_map = _cascades_image_map(flight)
    out, seen = [], set()
    for k in range(len(idxs)):
        seg = html[max(0, idxs[k] - 1500):bounds[k + 1]]
        name = _cascades_unesc(_cascades_field("name", seg))
        date = _cascades_field("start_date_local", seg)   # YYYY-MM-DD, local
        tl   = _cascades_field("start_time_local", seg)   # HH:MM:SS, 24h local
        slug = _cascades_field("slug", seg)
        if not name or not date or not tl:
            continue
        low = name.lower()
        # Non-concert / upsell entries: parking, VIP packages, season tickets.
        if ("season ticket" in low or "season pass" in low or "parking" in low
                or "premium season" in low or "not a concert" in low):
            continue
        if date < today.isoformat():
            continue
        try:
            hh, mm = int(tl.split(":")[0]), int(tl.split(":")[1])
        except (ValueError, IndexError):
            continue
        tm = to_time("%d:%02d%s" % (hh % 12 or 12, mm, "am" if hh < 12 else "pm"))
        title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", name)).strip()
        disc = _cascades_field("discovery_id", seg)
        # Deterministic image join: concert.discovery_id == image wrapper.id
        img = ""
        if disc and disc in img_map:
            img = _cascades_pick_image(img_map[disc])
        if disc and slug:
            url = "https://www.livenation.com/event/" + disc + "/" + slug
        else:
            url = _CASCADES_URL
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "Cascades Amphitheater",
                    "neighborhood": "Ridgefield, WA",
                    "address": "17200 NE Delfel Rd, Ridgefield, WA 98642",
                    "date": date, "time": tm, "venueUrl": url, "imageUrl": img})
    return out


# ---- The Goodfoot (thegoodfoot.com) -- WALLED, headless tier -----------------
# Cloudflare challenges every path on this site, REST API and iCal included
# (verified Sep 2026). The site runs WordPress + The Events Calendar, whose JSON
# API is the cleanest possible source -- so the headless fetcher clears the
# challenge on the homepage, then reads /wp-json/tribe/events/v1/events in the
# same browser session with the clearance cookie. Structured data, no HTML
# scraping, no fragile selectors.
#
# The `html` argument is ignored: this parser does its own fetch. It's the
# `walled` flag on the SOURCES entry that routes it here instead of fetch().
GOODFOOT_HOME = "https://www.thegoodfoot.com/"
GOODFOOT_API = ("https://www.thegoodfoot.com/wp-json/tribe/events/v1/events"
                "?per_page=50&start_date=now")

# Goodfoot has a music room downstairs and a pub upstairs; the pub's trivia and
# hangout nights come through the same API. Drop the recognizable pub-only
# formats. Comedy is deliberately NOT filtered: "Laugh Basement" is a real
# recurring stand-up night and belongs in the Comedy section, not the trash.
_GOODFOOT_NONMUSIC = re.compile(
    r"triviology|trivia|pub\s*quiz|upstairs\s*pub|bingo|karaoke", re.I)

def parse_goodfoot(html, today):
    from fetch_headless import fetch_headless_json
    import html as _html
    data = fetch_headless_json(GOODFOOT_HOME, GOODFOOT_API)
    events = data.get("events", []) if isinstance(data, dict) else []
    nb, addr = VENUE_INFO.get("The Goodfoot", ("Buckman", "2845 SE Stark St"))
    out, seen = [], set()
    for ev in events:
        # The API returns entity-encoded titles ("&#038;"); decode here so the
        # intermediate file is clean rather than relying on a later pass.
        title = clean(_html.unescape(re.sub(r"<[^>]+>", "", ev.get("title") or "")))
        start = ev.get("start_date") or ""          # "2026-09-05 21:00:00"
        if not title or len(start) < 10:
            continue
        if _GOODFOOT_NONMUSIC.search(title):
            continue
        date = start[:10]
        tm = ""
        try:
            hh, mm = int(start[11:13]), int(start[14:16])
            ampm = "AM" if hh < 12 else "PM"
            h12 = hh % 12 or 12
            tm = f"{h12}:{mm:02d} {ampm}"
        except (ValueError, IndexError):
            pass
        url = (ev.get("url") or GOODFOOT_HOME).split("?")[0]
        img = ""
        image = ev.get("image")
        if isinstance(image, dict):
            img = image.get("url") or ""
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "The Goodfoot", "neighborhood": nb,
                    "address": addr, "date": date, "time": tm,
                    "venueUrl": url, "imageUrl": img})
    return out


# ---- Music Millennium (musicmillennium.com/InStore) -- WALLED, headless -----
# AWS WAF challenges every path (verified Sep 2026); the headless tier clears
# it. No JSON here -- the in-store list is a plain server-rendered table, which
# is fine because it's regular: a <th> date header ("Wednesday, September  9",
# no year, sometimes doubled spaces), then a <td colspan=4> title row, then a
# detail row carrying the /Event/N link. Times are NOT on the listing page and
# fetching each event page through Chromium isn't worth it for a record store,
# so time is left blank. Listening parties are kept: they're real in-store
# events for the same crowd.
MM_URL = "https://musicmillennium.com/InStore"
_MM_DATE = re.compile(r"(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s+([A-Z][a-z]+)\s+(\d{1,2})")

def parse_musicmillennium(html, today):
    from fetch_headless import fetch_headless
    page = fetch_headless(MM_URL, wait_s=30)
    soup = BeautifulSoup(page, "html.parser")
    nb, addr = VENUE_INFO.get("Music Millennium", ("Kerns", "3158 E Burnside St"))
    out, seen = [], set()
    date, title = "", ""
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        if th:
            m = _MM_DATE.search(_normalize_ws(th.get_text()))
            if m and m.group(2)[:3] in MONTHS:
                mon = MONTHS[m.group(2)[:3]]
                date = f"{infer_year(mon, today)}-{mon:02d}-{int(m.group(3)):02d}"
            title = ""
            continue
        td = tr.find("td", attrs={"colspan": "4"})
        if td:
            title = clean(td.get_text())
            continue
        link = tr.find("a", href=re.compile(r"/Event/\d+"))
        if link and date and title:
            url = "https://musicmillennium.com" + link["href"]
            key = (date, title.lower())
            if key not in seen:
                seen.add(key)
                out.append({"title": title, "venue": "Music Millennium",
                            "neighborhood": nb, "address": addr, "date": date,
                            "time": "", "venueUrl": url, "imageUrl": ""})
            title = ""
    return out


def parse_novapdx(html, today):
    # NOVA PDX (Buckman, 722 E Burnside) -- venue's own Webflow site, Tixr buy-links.
    # .b-venue holds the FULL date with year (e.g. 'June 14, 2026') -- parse directly, no year inference.
    soup = BeautifulSoup(html, "html.parser")
    venue = "NOVA PDX"
    nb, addr = VENUE_INFO.get(venue, ("Central Eastside", ""))
    shows = []
    seen = set()
    for item in soup.select(".w-dyn-item"):
        a = item.find("a", href=True)
        tixr = None
        for link in item.find_all("a", href=True):
            if "tixr.com" in link["href"]:
                tixr = link["href"]
                break
        if not tixr:
            continue
        te = item.select_one(".b-show")
        de = item.select_one(".b-venue")
        if not te or not de:
            continue
        title = clean(te.get_text())
        for pre in ("SOLD OUT", "CANCELLED", "CANCELED", "POSTPONED"):
            if title.upper().startswith(pre):
                title = clean(title[len(pre):].lstrip(" :-"))
        if not title:
            continue
        raw = clean(de.get_text())
        try:
            d = datetime.datetime.strptime(raw, "%B %d, %Y")
        except ValueError:
            continue
        date = d.strftime("%Y-%m-%d")
        if d.date() < today:
            continue
        img = item.find("img")
        image = ""
        if img and img.get("src", "").startswith("http"):
            image = img["src"]
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": "",
                      "venueUrl": tixr, "imageUrl": image})
    return shows


MCMENAMINS_BASE = "https://www.mcmenamins.com/to-do/live-music-events/music-event-calendar"
# McMenamins rooms via the music-event calendar. Crystal Ballroom(2)/Edgefield(3)/
# Grand Lodge(4) are intentionally OMITTED -- they already arrive via parse_monqui;
# including them here would double-list. Kennedy School (6) was previously skipped
# as "mostly non-music"; added Sep 2026 on Nick's call to accept some noise for the
# coverage -- and since this hits the MUSIC calendar specifically, the non-music
# events (movies, trivia) may not surface here at all. The other pubs stay skipped.
MCMENAMINS_VENUES = {
    "55": "White Eagle Saloon",
    "154": "Al's Den",
    "63": "Mission Theater",
    "6": "Kennedy School",
}
# Kennedy School is a pub/hotel whose music-calendar entries are mostly NOT
# music (the first live run was 8-of-10 non-music: building tours, bingo,
# OMSI Science Pub, a film networking night). Rather than pollute a live-music
# feed with "History & Art Tour", drop the recognizable non-music formats by
# title. Applied ONLY to Kennedy School -- White Eagle / Al's Den / Mission are
# music rooms and their entries are trusted as-is. Fragile by nature (a new
# non-music format slips through until it's added here); tune as they appear.
_MCM_NONMUSIC = {
    "Kennedy School": re.compile(
        r"history\s*&\s*art\s*tour|art\s*tour|\btour\b|bingo|science\s*pub|"
        r"\bfilm\b|networking|trivia|showcase|pub\s*quiz|movie|screening",
        re.I),
}
_MCM_PROP_CTRL = "ctl00$MainContent$propertyfilters"


def _mcmenamins_session_get(session, url):
    """GET that seeds the ASP.NET session. The postback below ONLY returns 200 if the
    POST carries the ASP.NET_SessionId + __AntiXsrfToken cookies set by THIS GET and the
    VIEWSTATE tokens from the SAME response -- a bare POST (no shared session) returns
    HTTP 500. So we do GET+POST inside one requests.Session rather than reusing the
    harness's cookie-less fetch()."""
    r = session.get(url, headers={"User-Agent":
        "Mozilla/5.0 (compatible; PortlandLive/1.0; listings aggregator)"}, timeout=30)
    r.raise_for_status()
    return r.text


def _mcmenamins_filter_html(session, token_html, vid):
    """Replay the location-filter __doPostBack. We must POST the form's COMPLETE hidden
    input set -- __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION AND every other
    hidden field (__LASTFOCUS, filterdate, startDate, endDate, code, edl/sdl, ...);
    a partial set 500s. __EVENTTARGET is the location <select> control; its value is the
    venue id. token_html + session cookies must come from the same preceding GET."""
    soup = BeautifulSoup(token_html, "html.parser")
    form = {}
    for inp in soup.select("input"):
        name = inp.get("name")
        if name:
            form[name] = inp.get("value") or ""
    form["__EVENTTARGET"] = _MCM_PROP_CTRL
    form["__EVENTARGUMENT"] = ""
    form[_MCM_PROP_CTRL] = vid
    r = session.post(MCMENAMINS_BASE, data=form, headers={"User-Agent":
        "Mozilla/5.0 (compatible; PortlandLive/1.0; listings aggregator)"}, timeout=30)
    r.raise_for_status()
    return r.text


def _mcmenamins_scroll_html(session, vid, page_size=100):
    """The full list for one venue. The filter postback renders page one of
    ten and a pagination widget that reads `items:N`; each further page is a
    POST to getScrollEvents.aspx -- the same endpoint the widget's
    getPageData() calls. It honours pageSize: asked for 100 with start=1 it
    returned all 61 of White Eagle's events in one fragment (2026-09-15).
    Same card markup as the postback page. Session must be the one that
    just posted the location filter."""
    url = MCMENAMINS_BASE.rsplit("/", 1)[0] + "/getScrollEvents.aspx"
    r = session.post(url, data={"start": 1, "t": "0", "s": "2", "pageSize": page_size,
                                "location": vid, "startDate": ""},
                     headers={"User-Agent": "Mozilla/5.0 (compatible; PortlandLive/1.0; listings aggregator)",
                              "X-Requested-With": "XMLHttpRequest", "Referer": MCMENAMINS_BASE},
                     timeout=30)
    r.raise_for_status()
    return r.text


_PROCESS_MON = {m: i for i, m in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}


def parse_process(html, today):
    """Process (processpdx.club) -- electronic club, 5040 SE Milwaukie.
    Webflow schedule: div.pricing-card-two per event with .showday /
    .showdate ("Sep 19", no year) / .text-block-3 ("10pm - 4am", often
    empty) / .showname / .showartists, and a Resident Advisor ticket link.
    The title is the event name; the artists ride along after a dash so a
    card reads "Acid Cult -- Octo Octa, Phreaker Fighter, ...". Year is
    inferred from the month (they list a month or two out). Club nights:
    21+ per RA listings, no time when the card has none."""
    out, seen = [], set()
    soup = BeautifulSoup(html, "html.parser")
    nb, addr = VENUE_INFO.get("Process", ("Sellwood-Moreland", ""))
    horizon = today + datetime.timedelta(days=120)
    for card in soup.select("div.pricing-card-two"):
        name = card.select_one(".showname"); dt = card.select_one(".showdate")
        if not (name and dt):
            continue
        m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})", dt.get_text(" ", strip=True))
        if not m or m.group(1) not in _PROCESS_MON:
            continue
        mon, day = _PROCESS_MON[m.group(1)], int(m.group(2))
        try:
            d = datetime.date(infer_year(mon, today), mon, day)
        except ValueError:
            continue
        if not (today <= d <= horizon):
            continue
        title = clean(name.get_text(" "))
        artists = card.select_one(".showartists")
        arts = clean(artists.get_text(" ")) if artists else ""
        if arts and arts.lower() != title.lower():
            title = f"{title} \u2014 {arts}"
        tm = ""
        tb = card.select_one(".text-block-3")
        if tb:
            mt = re.match(r"\s*(\d{1,2}(?::\d{2})?\s*[ap]m)", tb.get_text(" ", strip=True), re.I)
            if mt:
                tm = to_time(mt.group(1))
        a = card.select_one("a[href]")
        url = a["href"] if a and a.get("href", "").startswith("http") else "https://www.processpdx.club/"
        key = (d.isoformat(), title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "Process", "neighborhood": nb, "address": addr,
                    "date": d.isoformat(), "time": tm, "venueUrl": url, "imageUrl": "", "age": "21+"})
    return out


_REALM_DAY = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\s*([A-Z][a-z]{2})\s+(\d{1,2})\b")
_REALM_MULTI = re.compile(r"\b([A-Z]{3})\s+(\d{1,2})\s*\+\s*([A-Z]{3})\s+(\d{1,2})\b", re.I)


def parse_realm(html, today):
    """Realm (realmpdx.com, 615 SE Alder) -- electronic club. Elementor
    "ue-event-list-item" per event: .ue-event-list-item-details-title, then
    an attributes line that is the genre plus the date ("HOUSE Sat  Sep 19").
    No time on the listing; doors are late and vary, so time stays blank.
    A run of nights reads "NOV 6 + NOV 7" or "DEC 31 + JAN 1" -- each night
    becomes its own row. Ticket links go to the venue's own page or its
    ticketer. 21+ per the venue. Behind the same TLS-handshake firewall as
    Kelly's, so this source is on the "tls" tier."""
    out, seen = [], set()
    soup = BeautifulSoup(html, "html.parser")
    nb, addr = VENUE_INFO.get("Realm", ("Central Eastside", ""))
    horizon = today + datetime.timedelta(days=200)
    for it in soup.select("div.ue-event-list-item"):
        t = it.select_one(".ue-event-list-item-details-title")
        at = it.select_one(".ue-event-list-item-details-attributes")
        if not (t and at):
            continue
        title = clean(t.get_text(" "))
        if not title:
            continue
        txt = at.get_text(" ", strip=True)
        dates = []
        mm = _REALM_MULTI.search(txt)
        if mm:
            for mon_s, day_s in ((mm.group(1), mm.group(2)), (mm.group(3), mm.group(4))):
                mon = MONTHS.get(mon_s[:3].title())
                if mon:
                    dates.append((mon, int(day_s)))
        else:
            md = _REALM_DAY.search(txt)
            if md and MONTHS.get(md.group(1)):
                dates.append((MONTHS[md.group(1)], int(md.group(2))))
        if not dates:
            continue
        a = it.select_one(".ue-event-list-item-details-cta a[href]")
        url = a["href"] if a and a.get("href", "").startswith("http") else "https://realmpdx.com/events/"
        im = it.select_one("img")
        img = ((im.get("src") or im.get("data-src") or "").strip()) if im else ""
        # A run can straddle New Year, so infer each night's year on its own.
        for mon, day in dates:
            try:
                d = datetime.date(infer_year(mon, today), mon, day)
            except ValueError:
                continue
            if not (today <= d <= horizon):
                continue
            key = (d.isoformat(), title.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "venue": "Realm", "neighborhood": nb, "address": addr,
                        "date": d.isoformat(), "time": "", "venueUrl": url,
                        "imageUrl": img if img.startswith("http") else "", "age": "21+"})
    return out


def parse_havalina(html, today):
    # Havalina (havalinapdx.com), St. Johns - Squarespace events collection.
    # /events?format=json gives an "upcoming" list with epoch-ms startDate
    # (UTC), paginated ~30 items per page via pagination.nextPageUrl. The
    # previous version only ever read page 1, which is why the calendar
    # topped out around 25 days out. This follows nextPageUrl until either
    # the feed says there's no more, or a page's first item (items are
    # date-ordered) is already past our horizon, so a normal run costs only
    # as many requests as the horizon actually needs.
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today
    nb, addr = VENUE_INFO.get("Havalina", ("St. Johns", ""))
    MAX_PAGES = 12   # backstop; a normal 120-day horizon needs far fewer

    def _consume(data):
        for e in data.get("upcoming", []):
            sd = e.get("startDate")
            if not sd:
                continue
            dt = datetime.datetime.fromtimestamp(sd / 1000, tz=datetime.timezone.utc).astimezone(_ASP_PDT)
            d = dt.date()
            if not (lower <= d <= horizon):
                continue
            date = d.isoformat()
            tm = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
            title = clean(e.get("title") or "").replace("&amp;", "&")
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue
            fu = e.get("fullUrl") or ""
            url = ("https://havalinapdx.com" + fu) if fu.startswith("/") else (fu or "https://havalinapdx.com/events")
            key = (date, title.lower())
            if key in seen:
                continue
            seen[key] = 1
            out.append({"title": title, "venue": "Havalina",
                        "neighborhood": nb, "address": addr,
                        "date": date, "time": tm, "venueUrl": url, "imageUrl": (e.get("assetUrl") or "")})

    try:
        data = json.loads(html)
        _consume(data)
        pag = data.get("pagination") or {}
        page_url = pag.get("nextPageUrl") if pag.get("nextPage") else None
        pages = 1
        while page_url and pages < MAX_PAGES:
            full_url = ("https://havalinapdx.com" + page_url) if page_url.startswith("/") else page_url
            if "format=json" not in full_url:
                full_url += ("&" if "?" in full_url else "?") + "format=json"
            page_data = json.loads(fetch(full_url))
            pages += 1
            up = page_data.get("upcoming", [])
            if not up:
                break
            first_sd = up[0].get("startDate")
            if first_sd:
                first_d = datetime.datetime.fromtimestamp(first_sd / 1000, tz=datetime.timezone.utc).astimezone(_ASP_PDT).date()
                if first_d > horizon:
                    break
            _consume(page_data)
            pag = page_data.get("pagination") or {}
            page_url = pag.get("nextPageUrl") if pag.get("nextPage") else None
    except Exception as e:
        print(f"  WARN: havalina parser aborted: {type(e).__name__}: {e}")

    out.sort(key=lambda s: (s["date"], s["time"], s["title"]))
    return out
def parse_starday(ics, today):
    # Starday Tavern (stardaytavern.com), Brentwood-Darlington / aka Genghis
    # Records. The WordPress homepage embeds a public Google Calendar iframe;
    # the events live in that calendar public .ics feed (basic.ics), which we
    # fetch directly. DTSTART is UTC (Z), TZID=, or VALUE=DATE (all-day).
    # Many events are recurring (RRULE) -- we expand each rule into its
    # individual dated occurrences inside the today->horizon window, honoring
    # UNTIL/COUNT and EXDATE, rather than emitting only the literal DTSTART.
    from dateutil import rrule as _rrule
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today
    nb, addr = VENUE_INFO.get("Starday Tavern", ("Brentwood-Darlington", ""))
    # unfold RFC5545 line folding (continuation lines begin with a space/tab)
    text = (ics or "").replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")

    def _unescape(t):
        # RFC5545 TEXT escapes use a SINGLE backslash: \, \; \n \\
        # Process the literal "\\" first via a placeholder so it does not
        # interfere with the comma/semicolon/newline replacements.
        t = t.replace("\\\\", "\x00")
        t = t.replace("\\,", ",").replace("\\;", ";")
        t = t.replace("\\n", " ").replace("\\N", " ")
        return t.replace("\x00", "\\")

    def _local(y, mo, da, hh, mi, isZ):
        # Return a naive Pacific-local datetime for the given wall fields.
        if isZ:
            return datetime.datetime(y, mo, da, hh, mi, tzinfo=datetime.timezone.utc).astimezone(_ASP_PDT).replace(tzinfo=None)
        # TZID=America/Los_Angeles or floating: already Pacific-local
        return datetime.datetime(y, mo, da, hh, mi)

    def _parse_dt(val):
        m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?", val)
        if not m:
            return None, None
        y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4) is None:
            # all-day (VALUE=DATE): date only, no reliable time
            return datetime.datetime(y, mo, da, 0, 0), True
        return _local(y, mo, da, int(m.group(4)), int(m.group(5)), m.group(7) == "Z"), False

    for block in text.split("BEGIN:VEVENT")[1:]:
        block = block.split("END:VEVENT")[0]
        ms = re.search(r"\nSUMMARY(?:;[^:]*)?:(.*)", block)
        md = re.search(r"\nDTSTART([^:\n]*):([0-9TZ]+)", block)
        if not (ms and md):
            continue
        base, all_day = _parse_dt(md.group(2))
        if base is None:
            continue

        raw_title = ms.group(1).strip()
        title = clean(_unescape(raw_title).replace("&amp;", "&"))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue

        # Build the list of occurrence datetimes for this event.
        rr = re.search(r"\nRRULE:(.*)", block)
        if rr:
            rulestr = rr.group(1).strip()
            # rrulestr needs UNTIL in the same (naive-local) frame as dtstart;
            # the feed stores UNTIL in UTC (trailing Z), so convert it.
            def _fix_until(mm):
                um = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?", mm.group(1))
                if not um:
                    return mm.group(0)
                uy, umo, uda = int(um.group(1)), int(um.group(2)), int(um.group(3))
                if um.group(4) is None:
                    return "UNTIL=%04d%02d%02d" % (uy, umo, uda)
                ul = _local(uy, umo, uda, int(um.group(4)), int(um.group(5)), um.group(7) == "Z")
                return "UNTIL=%04d%02d%02dT%02d%02d00" % (ul.year, ul.month, ul.day, ul.hour, ul.minute)
            rulestr = re.sub(r"UNTIL=([0-9TZ]+)", _fix_until, rulestr)
            try:
                rule = _rrule.rrulestr(rulestr, dtstart=base)
                win_s = datetime.datetime.combine(lower, datetime.time.min)
                win_e = datetime.datetime.combine(horizon, datetime.time.max)
                occ_dts = list(rule.between(win_s, win_e, inc=True))
            except Exception:
                occ_dts = [base]
        else:
            occ_dts = [base]

        # EXDATE: collect excluded dates/datetimes to skip.
        ex_dates = set()
        for exm in re.finditer(r"\nEXDATE([^:\n]*):([^\n]*)", block):
            for tok in exm.group(2).split(","):
                em = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?", tok.strip())
                if not em:
                    continue
                ey, emo, eda = int(em.group(1)), int(em.group(2)), int(em.group(3))
                ex_dates.add((ey, emo, eda))
                if em.group(4) is not None:
                    el = _local(ey, emo, eda, int(em.group(4)), int(em.group(5)), em.group(7) == "Z")
                    ex_dates.add((el.year, el.month, el.day, el.hour, el.minute))

        for occ in occ_dts:
            if (occ.year, occ.month, occ.day) in ex_dates:
                continue
            if (occ.year, occ.month, occ.day, occ.hour, occ.minute) in ex_dates:
                continue
            d = occ.date()
            if not (lower <= d <= horizon):
                continue
            tm = "" if all_day else "%d:%02d %s" % (occ.hour % 12 or 12, occ.minute, "AM" if occ.hour < 12 else "PM")
            date = d.isoformat()
            key = (date, title.lower())
            if key in seen:
                continue
            seen[key] = 1
            out.append({"title": title, "venue": "Starday Tavern",
                        "neighborhood": nb, "address": addr,
                        "date": date, "time": tm,
                        "venueUrl": "https://www.stardaytavern.com/", "imageUrl": ""})
    return out


def parse_mcmenamins(html, today):
    # McMenamins' calendar is custom ASP.NET WebForms (NEW pattern): no JSON API, and a
    # plain GET yields only ~9 "today" events. Per-venue lists live behind an ASP.NET
    # __doPostBack on the location <select>. We open our OWN requests.Session (the passed
    # `html` came from a cookie-less fetch and cannot drive the postback), GET once to
    # seed session cookies + VIEWSTATE, then postback per target venue id and parse the
    # server-rendered cards. Crystal Ballroom(2)/Edgefield(3)/Grand Lodge(4) are omitted
    # on purpose -- they already arrive via parse_monqui (including them double-lists).
    out, seen = [], set()
    try:
        session = requests.Session()
        token_html = _mcmenamins_session_get(session, MCMENAMINS_BASE)
    except Exception as e:
        print(f"  WARN: McMenamins seed GET failed: {e}")
        return out
    for vid, vname in MCMENAMINS_VENUES.items():
        try:
            page = _mcmenamins_filter_html(session, token_html, vid)
        except Exception as e:
            print(f"  WARN: McMenamins postback failed for {vname} ({vid}): {e}")
            continue
        # The postback is page one of ten. Every McMenamins room in the feed
        # stopped ~10 shows / two weeks out for that reason (White Eagle 10
        # of 61, found 2026-09-15 via the Ticketmaster comparison). Ask the
        # scroll endpoint for the whole list; keep page one if that fails.
        try:
            full = _mcmenamins_scroll_html(session, vid)
            if full.count("tm-panel-card") >= page.count("tm-panel-card"):
                page = full
        except Exception as e:
            print(f"  WARN: McMenamins scroll failed for {vname} ({vid}); using page one: {e}")
        soup = BeautifulSoup(page, "html.parser")
        nb, addr = VENUE_INFO.get(vname, ("", ""))
        for card in soup.select("div.tm-panel-card.event"):
            a = card.find("a", href=lambda x: x and "/events/" in x)
            if not a:
                continue
            # title = first uk-panel-title; date = uk-panel-title inside tm-card-content
            th = card.select_one("h3.uk-panel-title")
            title = clean(th.get_text(" ", strip=True)) if th else ""
            title = re.sub(r"\^?(SOLD OUT|CANCELL?ED|MOVED TO)[:\s\*].*$", "",
                           title, flags=re.I).strip()
            content = card.select_one("div.tm-card-content")
            dh = content.select_one("h3.uk-panel-title") if content else None
            date_txt = dh.get_text(" ", strip=True) if dh else ""
            tm = card.select_one("p.uk-panel-time")
            time_txt = tm.get_text(" ", strip=True) if tm else ""
            m = re.search(r"([A-Z][a-z]{2})[a-z]*\s+(\d{1,2})", date_txt)
            if not m or not title:
                continue
            mon = MONTHS.get(m.group(1))
            if not mon:
                continue
            yr = infer_year(mon, today)
            try:
                date = datetime.date(yr, mon, int(m.group(2))).isoformat()
            except ValueError:
                continue
            tm_str = to_time(time_txt)
            href = a.get("href") or ""
            url = ("https://www.mcmenamins.com" + href) if href.startswith("/") else href
            # Real art is the teaser div background-image; the <img> is a blank.gif
            # placeholder. cloudfront "genericimage" = no real art -> "".
            img = ""
            teaser = card.select_one("div.uk-panel-teaser")
            if teaser and teaser.get("style"):
                im = re.search(r"url\(([^)]+)\)", teaser["style"])
                if im:
                    cand = im.group(1).strip("'\"")
                    if "genericimage" not in cand:
                        img = cand
            key = (vname, date, title.lower())
            if key in seen:
                continue
            seen.add(key)
            nonmusic = _MCM_NONMUSIC.get(vname)
            if nonmusic and nonmusic.search(title):
                continue
            out.append({"title": title, "venue": vname, "neighborhood": nb,
                        "address": addr, "date": date, "time": tm_str,
                        "venueUrl": url, "imageUrl": img,
                        # The card says it in words: "21 and over at White
                        # Eagle", "Minors welcome until 8pm; 21 and over after".
                        # The conservative reader, same as everywhere else.
                        "age": _age_in_text(card.get_text(" "))})
    return out



def fetch_tls(url, timeout=30):
    """Fetch with Chrome's TLS fingerprint, no browser.

    Some firewalls block on the TLS handshake, not the headers: Python's
    requests looks nothing like Chrome at the connection level, so every
    request gets the block page no matter what User-Agent it sends, while
    a real Chrome passes. curl_cffi speaks Chrome's handshake. Kelly's
    Olympian (2026-09-16): plain requests 403 on every URL, curl_cffi 200
    on all of them -- including the Tribe REST API, so the site moved from
    the headless tier to this one and got its structured source back.

    Sits between browser-headers and Playwright in the bot-wall order."""
    from curl_cffi import requests as cr
    r = cr.get(url, impersonate="chrome", timeout=timeout,
               headers={"Accept-Language": "en-US,en;q=0.9"})
    r.raise_for_status()
    return r.text


def parse_kellys_olympian(html_text, today):
    # Kelly's Olympian (kellysolympian.com), Downtown - WordPress + The Events Calendar.
    # Events live in JSON-LD <script type="application/ld+json"> Event objects (Pacific offset dates).
    import html as _html
    out, seen = [], set()
    horizon = today + datetime.timedelta(days=HORIZON_DAYS)
    lower = today
    nb, addr = VENUE_INFO.get("Kelly's Olympian", ("Downtown", ""))
    # The Events Calendar's REST API (/wp-json/tribe/events/v1/events):
    # one page of structured events -- start_date, title, url, image. The
    # site's firewall blocked it for plain requests; fetch_tls gets in.
    # If what we were handed is HTML instead, fall through to the JSON-LD
    # reader below, which is what the headless path returned.
    if html_text and html_text.lstrip().startswith("{"):
        try:
            data = json.loads(html_text)
        except Exception:
            data = {}
        for e in data.get("events", []) or []:
            title = clean(_html.unescape(e.get("title") or ""))
            title = re.sub(r"\s+", " ", title).strip()
            sd = (e.get("start_date") or "")[:16]
            if not title or len(sd) < 16:
                continue
            try:
                dt = datetime.datetime.strptime(sd, "%Y-%m-%d %H:%M")
            except Exception:
                continue
            d = dt.date()
            if not (lower <= d <= horizon):
                continue
            tm = "" if e.get("all_day") else "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
            img = e.get("image") or ""
            if isinstance(img, dict):
                img = img.get("url", "") or ""
            key = (d.isoformat(), title.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "venue": "Kelly's Olympian", "neighborhood": nb,
                        "address": addr, "date": d.isoformat(), "time": tm,
                        "venueUrl": e.get("url") or "https://kellysolympian.com/events/",
                        "imageUrl": img if str(img).startswith("http") else "",
                        "age": _age_in_text(_html.unescape(e.get("description") or ""))})
        return out
    blocks = _LD_JSON.findall(html_text)
    for b in blocks:
        try:
            data = json.loads(b)
        except Exception:
            continue
        for e in (data if isinstance(data, list) else [data]):
            if not isinstance(e, dict) or e.get("@type") != "Event":
                continue
            sd = e.get("startDate")
            if not sd:
                continue
            try:
                dt = datetime.datetime.fromisoformat(sd.replace("Z", "+00:00"))
            except Exception:
                continue
            if dt.tzinfo:
                dt = dt.astimezone(_ASP_PDT)
            d = dt.date()
            if not (lower <= d <= horizon):
                continue
            title = clean(_html.unescape(e.get("name") or ""))
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue
            date = d.isoformat()
            tm = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
            url = e.get("url") or "https://kellysolympian.com/events/"
            img = e.get("image") or ""
            if isinstance(img, dict):
                img = img.get("url", "")
            key = (date, title.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "venue": "Kelly's Olympian", "neighborhood": nb,
                        "address": addr, "date": date, "time": tm,
                        "venueUrl": url, "imageUrl": img})
    return out


_BARREL_SKIP = re.compile(r"\b(email list|mailing list|newsletter|gift card|merch|donate|donation|rental|private event)\b", re.I)


# Karaoke and cornhole nights carry the "weekly" category; the Matinee
# category is a real (all-ages, 4pm) show and stays.
_HEADLINERS_SKIP_CAT = {"weekly"}
_HEADLINERS_SKIP = re.compile(r"\b(karaoke|cornhole|trivia|bingo|poker|open mic night)\b", re.I)


def parse_headliners(html, today):
    """The Headliners Club (Lake Oswego, 17880 SW McEwan) -- The Events
    Calendar REST API, same plugin as Kelly's. 239 events on file; the
    parser walks pages until one starts past the horizon. Karaoke and
    cornhole are categorised "weekly" and skipped; the "Matinee" category
    is a real 4pm all-ages show. Age comes from the title where the venue
    says it."""
    import html as _html
    out, seen = [], set()
    nb, addr = VENUE_INFO.get("The Headliners Club", ("Lake Oswego", ""))
    horizon = today + datetime.timedelta(days=120)
    try:
        data = json.loads(html)
    except Exception:
        return out
    pages = [data]
    nxt = data.get("next_rest_url")
    for _ in range(5):
        if not nxt:
            break
        try:
            more = json.loads(fetch(nxt))
        except Exception as e:
            print(f"  note: Headliners: page fetch stopped ({type(e).__name__})")
            break
        pages.append(more)
        first = (more.get("events") or [{}])[0].get("start_date", "")[:10]
        if first and first > horizon.isoformat():
            break
        nxt = more.get("next_rest_url")
    for page in pages:
        for e in page.get("events") or []:
            cats = {(c.get("name") or "").lower() for c in (e.get("categories") or [])}
            if cats & _HEADLINERS_SKIP_CAT:
                continue
            title = clean(_html.unescape(e.get("title") or ""))
            title = re.sub(r"\s+", " ", title).strip()
            if not title or _HEADLINERS_SKIP.search(title):
                continue
            sd = (e.get("start_date") or "")[:16]
            if len(sd) < 16:
                continue
            try:
                dt = datetime.datetime.strptime(sd, "%Y-%m-%d %H:%M")
            except Exception:
                continue
            d = dt.date()
            if not (today <= d <= horizon):
                continue
            tm = "" if e.get("all_day") else "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
            img = e.get("image") or ""
            if isinstance(img, dict):
                img = img.get("url", "") or ""
            blob = title + " " + re.sub(r"<[^>]+>", " ", _html.unescape(e.get("description") or ""))[:400]
            key = (d.isoformat(), title.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "venue": "The Headliners Club", "neighborhood": nb, "address": addr,
                        "date": d.isoformat(), "time": tm,
                        "venueUrl": e.get("url") or "https://theheadlinersclub.com/",
                        "imageUrl": img if str(img).startswith("http") else "",
                        "age": _age_in_text(blob)})
    return out


def parse_barrelroom(html, today):
    """Barrel Room (120 NW Couch) -- their own site went away; the live
    calendar is their Eventbrite organizer page, which embeds the listing
    as an "upcomingEvents" JSON array (id, name, url, start_date,
    start_time, image). Mailing-list and merch "events" that organizers
    park on these pages are skipped by name. 21+ per the venue."""
    import html as _html
    out, seen = [], set()
    nb, addr = VENUE_INFO.get("Barrel Room", ("Old Town/Chinatown", ""))
    horizon = today + datetime.timedelta(days=120)
    m = re.search(r'"upcomingEvents":\s*\[', html)
    if not m:
        return out
    i, depth = m.end() - 1, 0
    for j in range(i, len(html)):
        if html[j] == "[":
            depth += 1
        elif html[j] == "]":
            depth -= 1
            if depth == 0:
                raw = html[i:j + 1]
                break
    else:
        return out
    try:
        events = json.loads(raw.encode().decode("unicode_escape"))
    except Exception:
        try:
            events = json.loads(raw)
        except Exception as e:
            print(f"  WARN: Barrel Room: upcomingEvents unparsable: {type(e).__name__}")
            return out
    for e in events:
        if not isinstance(e, dict) or e.get("is_cancelled"):
            continue
        title = clean(_html.unescape(e.get("name") or ""))
        if not title or _BARREL_SKIP.search(title):
            continue
        date = (e.get("start_date") or "")[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        d = datetime.date.fromisoformat(date)
        if not (today <= d <= horizon):
            continue
        tm = ""
        st = (e.get("start_time") or "")[:5]
        if re.match(r"^\d{2}:\d{2}$", st) and st != "00:00":
            hh, mm = int(st[:2]), st[3:]
            tm = f"{hh % 12 or 12}:{mm} {'AM' if hh < 12 else 'PM'}"
        img = ((e.get("image") or {}).get("url") or "").strip()
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "Barrel Room", "neighborhood": nb, "address": addr,
                    "date": date, "time": tm,
                    "venueUrl": e.get("url") or "https://www.eventbrite.com/o/barrel-room-80388668013",
                    "imageUrl": img if img.startswith("http") else "", "age": "21+"})
    return out

def parse_arbor(html, today):
    # Arbor Beer Lodge (arborbeerlodge.com), Arbor Lodge / N Interstate - native
    # Squarespace events collection. /events?format=json gives an "upcoming"
    # list with epoch-ms startDate (UTC). Same shape as Havalina/No Fun.
    out, seen = [], set()
    horizon = today + datetime.timedelta(days=HORIZON_DAYS)
    lower = today
    try:
        data = json.loads(html)
    except Exception:
        return out
    nb, addr = VENUE_INFO.get("Arbor Beer Lodge", ("Arbor Lodge", ""))
    for e in data.get("upcoming", []):
        if not isinstance(e, dict):
            continue
        sd = e.get("startDate")
        if not sd:
            continue
        dt = datetime.datetime.fromtimestamp(sd / 1000, tz=datetime.timezone.utc).astimezone(_ASP_PDT)
        d = dt.date()
        if not (lower <= d <= horizon):
            continue
        date = d.isoformat()
        tm = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
        title = clean((e.get("title") or "").replace("&amp;", "&"))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        fu = e.get("fullUrl") or ""
        url = ("https://www.arborbeerlodge.com" + fu) if fu.startswith("/") else (fu or "https://www.arborbeerlodge.com/events")
        img = e.get("assetUrl") or ""
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "Arbor Beer Lodge", "neighborhood": nb,
                    "address": addr, "date": date, "time": tm,
                    "venueUrl": url, "imageUrl": img})
    return out


def parse_artichoke(html_text, today):
    # Artichoke Music (artichokemusic.org), Brooklyn/Powell (SE) - folk/acoustic
    # nonprofit. Events are on Eventbrite; the live-music collection page embeds
    # JSON-LD: an ItemList whose itemListElement[].item are Event @type objects
    # (startDate carries a Pacific offset, e.g. -07:00). today->horizon + dedupe.
    out, seen = [], set()
    horizon = today + datetime.timedelta(days=HORIZON_DAYS)
    lower = today
    nb, addr = VENUE_INFO.get("Artichoke Music", ("Brooklyn", ""))
    blocks = _LD_JSON.findall(html_text)
    evs = []
    for b in blocks:
        try:
            data = json.loads(b)
        except Exception:
            continue
        items = data.get("itemListElement") if isinstance(data, dict) else None
        if isinstance(items, list):
            for it in items:
                obj = it.get("item") if isinstance(it, dict) else None
                if isinstance(obj, dict) and obj.get("@type") == "Event":
                    evs.append(obj)
    for e in evs:
        sd = e.get("startDate")
        if not sd:
            continue
        try:
            dt = datetime.datetime.fromisoformat(sd.replace("Z", "+00:00")).astimezone(_ASP_PDT)
        except Exception:
            continue
        d = dt.date()
        if not (lower <= d <= horizon):
            continue
        date = d.isoformat()
        tm = "%d:%02d %s" % (dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")
        title = clean((e.get("name") or "").replace("&amp;", "&"))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        url = e.get("url") or "https://www.artichokemusic.org/events"
        img = e.get("image") or ""
        if isinstance(img, dict):
            img = img.get("url", "")
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "Artichoke Music", "neighborhood": nb,
                    "address": addr, "date": date, "time": tm,
                    "venueUrl": url, "imageUrl": img})
    return out



# ---- CitySpark (Willamette Week portal) -------------------------------------
# One JSON API -> multiple venues. We pull Ponderosa + The Old Church out of a
# feed that covers the whole metro. The documented {date,pageSize} body is
# IGNORED by the server (it returns a stale fixed week); the live widget really
# sends ISO-UTC Start/End, and the server answers a ~7-day window per request,
# so we step the window forward across the horizon. Each query returns an
# event's NEXT occurrence (often past-anchored / repeated across days), so we
# dedupe by PId and keep only StartUTC >= today. Fetched JSON is untrusted:
# we parse defensively and never execute anything from it.
_CS_URL = "https://portal.cityspark.com/api/events/GetEventsByDay/WillametteWeek"
_CS_BODY = {"ppid": 9934, "lat": 45.5115232, "lng": -122.6783853,
            "distance": 60, "page": 0}
_CS_VENUES = {"Ponderosa Lounge & Grill", "The Old Church"}

def _cs_pacific_dt(start_utc):
    """Parse a CitySpark StartUTC ('2026-08-08T04:00:00Z') into an aware UTC
    datetime, then convert to US/Pacific. Returns None on anything unexpected."""
    if not isinstance(start_utc, str):
        return None
    s = start_utc.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    # US Pacific: PDT (-7) Mar-Nov, PST (-8) otherwise. The feed is summer-
    # heavy; approximate DST by month to avoid a zoneinfo dependency.
    off = -7 if 3 <= dt.month <= 10 else -8
    return dt.astimezone(datetime.timezone(datetime.timedelta(hours=off)))

def _cs_fetch_window(start_date, end_date):
    body = dict(_CS_BODY)
    body["Start"] = start_date.isoformat() + "T00:00:00Z"
    body["End"] = end_date.isoformat() + "T23:59:00Z"
    r = requests.post(_CS_URL, json=body,
                      headers={"User-Agent": "PortlandLive/1.0 (listings aggregator)"},
                      timeout=30)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return []
    out = []
    for bucket in (data.get("Value") or []):
        if isinstance(bucket, dict):
            out.extend(bucket.get("Events") or [])
    return out

def parse_cityspark(_html, today):
    """Ignore the GET body passed by scrape(); drive the CitySpark JSON API
    directly with Start/End windows. Yields show dicts for our two venues."""
    by_pid = {}
    for i in range(0, HORIZON_DAYS + 1, 7):
        s = today + datetime.timedelta(days=i)
        e = today + datetime.timedelta(days=i + 7)
        for ev in _cs_fetch_window(s, e):
            if isinstance(ev, dict) and ev.get("PId") is not None:
                by_pid[ev.get("PId")] = ev   # dedupe by PId
    shows = []
    seen = set()
    for ev in by_pid.values():
        venue = (ev.get("Venue") or "").strip()
        if venue not in _CS_VENUES:
            continue
        pac = _cs_pacific_dt(ev.get("StartUTC"))
        if pac is None or pac.date() < today:          # StartUTC >= today
            continue
        date = pac.date().isoformat()
        title = clean(ev.get("Name") or "")
        if not title:
            continue
        has_time = ev.get("HasTime")
        time = ""
        if has_time:
            h = pac.hour % 12 or 12
            time = "%d:%02d %s" % (h, pac.minute, "AM" if pac.hour < 12 else "PM")
        key = (venue, date, title.lower())            # belt-and-suspenders dedup
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Portland", ""))
        url = ev.get("PrimaryUrl") or ""
        img = ev.get("LargeImg") or ev.get("MediumImg") or ev.get("SmallImg") or ""
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": time,
                      "venueUrl": url if isinstance(url, str) else "",
                      "imageUrl": img if isinstance(img, str) else ""})
    return shows

SOURCES = [
    # CitySpark JSON API (single feed -> 2 venues). The parser ignores the
    # GET body below and drives the POST API itself; the URL is only a cheap
    # liveness fetch so per-source isolation in scrape() behaves normally.
    {"name": "CitySpark (Ponderosa + Old Church)", "parser": parse_cityspark, "may_be_empty": True,
     "urls": ["https://portal.cityspark.com/PortalScripts/WillametteWeek"]},
    {"name": "Havalina (havalinapdx.com)", "parser": parse_havalina, "urls": ["https://havalinapdx.com/events?format=json"]},
    {"name": "Process (processpdx.club)", "parser": parse_process, "urls": ["https://www.processpdx.club/"]},
    {"name": "Realm (realmpdx.com)", "parser": parse_realm, "tls": True, "urls": ["https://realmpdx.com/events/"]},
    {"name": "The Headliners Club (Lake Oswego)", "parser": parse_headliners,
     "urls": ["https://theheadlinersclub.com/wp-json/tribe/events/v1/events?per_page=50"]},
    # Intermittent bot challenge (6 of 10 runs zero by Sep 2026, then fully
    # zero). Plain requests with a browser UA doesn't reliably pass; Chromium
    # does. Parser unchanged -- it just gets its HTML through the headless tier.
    {"name": "Kelly's Olympian (kellysolympian.com)", "parser": parse_kellys_olympian, "tls": True,
     "urls": ["https://kellysolympian.com/wp-json/tribe/events/v1/events?per_page=100"]},
        {"name": "Barrel Room (Eventbrite)", "parser": parse_barrelroom, "urls": ["https://www.eventbrite.com/o/barrel-room-80388668013"]},
    {"name": "Arbor Beer Lodge (arborbeerlodge.com)", "parser": parse_arbor, "urls": ["https://www.arborbeerlodge.com/events?format=json"]},
    {"name": "Artichoke Music (artichokemusic.org)", "parser": parse_artichoke, "urls": ["https://www.eventbrite.com/cc/live-music-artichoke-4657563"]},
    {"name": "Starday Tavern (stardaytavern.com / Genghis Records)", "parser": parse_starday, "urls": ["https://calendar.google.com/calendar/ical/m59vjhvcv0iflpv2iknoqlmuqo%40group.calendar.google.com/public/basic.ics"]},
    {"name": "McMenamins (White Eagle/Al's Den/Mission)", "parser": parse_mcmenamins,
     "urls": ["https://www.mcmenamins.com/to-do/live-music-events/music-event-calendar"]},
    {"name": "NOVA PDX", "parser": parse_novapdx, "urls": ["https://novapdxevents.com/event-calendar"]},
    {"name": "Pioneer Courthouse Square / PDX Live (pdx-live.com)", "parser": parse_pdxlive, "may_be_empty": True, "urls": ["https://pdx-live.com/wp-json/wlcr/v1/events/raw"]},
    {"name": "Twilight Cafe & Bar (twilightcafeandbar.com)", "parser": parse_twilight, "urls": ["https://twilightcafeandbar.com/calendar_list"]},
    {"name": "No Fun (nofunportland.com)", "parser": parse_nofun, "urls": ["https://www.nofunportland.com/events"]},
    {"name": "Bunk Bar (shows.bunksandwiches.com)", "parser": parse_bunkbar, "urls": ["https://shows.bunksandwiches.com/"]},
    {"name": "Mississippi Pizza (mississippipizza.com)", "parser": parse_mississippipizza, "urls": ["https://mississippipizza.com/calendar/"]},
    {"name": "Alberta Street Pub (albertastreetpub.com)", "parser": parse_albertastreetpub, "urls": ["https://www.albertastreetpub.com/music?format=json"]},
    {"name": "Tomorrow's Verse (youenjoymybeer.com)", "parser": parse_tomorrowsverse, "urls": ["https://www.youenjoymybeer.com/events"]},
    {"name": "Cascades Amphitheater (livenation.com)", "parser": parse_cascades, "urls": [_CASCADES_URL]},
    # Columbia Gorge (Sep 2026)
    {"name": "Trout Lake Hall (troutlakehall.com)", "parser": parse_troutlakehall, "urls": [_TLH_HOME]},
    {"name": "The Ruins (theruins.org)", "parser": parse_theruins, "urls": [_RUINS_PAGE]},
    {"name": "Laurelthirst (laurelthirst.com)", "parser": parse_laurelthirst, "urls": ["https://laurelthirst.com/music-calendar/"]},
    {"name": "Showdown Saloon", "parser": parse_showdown, "urls": ["https://showdownpdx.com/"]},
    {"name": "The Get Down", "parser": parse_getdown, "urls": ["https://thegetdownpdx.com/"]},
    {"name": "Jack London Revue", "parser": parse_jacklondonrevue, "urls": ["https://jacklondonrevue.com/calendar/"]},
    {"name": "Star Theater", "parser": parse_startheater, "urls": ["https://startheaterportland.com/"]},
    {"name": "Alberta Rose Theatre", "parser": parse_albertarose, "urls": ["https://albertarosetheatre.com/events/"]},
    {"name": "Portland5 (Keller/Schnitzer/Newmark/etc)", "parser": parse_portland5, "urls": ["https://www.portland5.com/events"]},
    {"name": "Rose Quarter (Moda/Coliseum/TOTC)", "parser": parse_rosequarter, "urls": ["https://www.rosequarter.com/events/event-calendar"]},
    {"name": "Monqui (Crystal/McMenamins)", "parser": parse_monqui,
     "urls": ["https://monqui.com/events/"]},
    {"name": "Aladdin Theater", "parser": parse_aladdin,
     "urls": ["https://www.aladdin-theater.com/"]},
    {"name": "Revolution Hall", "parser": parse_revolutionhall,
     "urls": ["https://revolutionhall.com/"]},
    {"name": "Holocene", "parser": parse_holocene,
     "urls": ["https://www.holocene.org/events/"]},
    {"name": "Wonder Ballroom", "parser": parse_wonder,
     "urls": ["https://wonderballroom.com/events/"]},
    {"name": "Mississippi/Polaris", "parser": parse_msstudios,
     "urls": ["https://mississippistudios.com/"]},
    {"name": "Mammoth NW", "parser": parse_mammoth,
     "urls": ["https://roselandpdx.com/events/"]},
    # Same RHP template and parser as Roseland. The Mammoth feed at
    # roselandpdx.com went Roseland-only, so Hawthorne needs its own URL.
    {"name": "Hawthorne Theatre (hawthornetheatre.com)", "parser": parse_mammoth,
     "urls": ["https://hawthornetheatre.com/events/"]},
    {"name": "Kenton Club (kentonclub.com)", "parser": parse_kentonclub,
     "urls": ["https://www.kentonclub.com/"]},
    {"name": "Spare Room (spareroomrestaurantandlounge.com)", "parser": parse_spareroom,
     "urls": _spare_room_urls(),
     # next month's page is expected to 404 until they post it
     "optional_urls": _spare_room_urls()[1:]},
    {"name": "Switchback Saloon (switchbacksaloon.com)", "parser": parse_switchback,
     "urls": _SB_ICS},
    {"name": "The Goodfoot", "parser": parse_goodfoot, "walled": True,
     "urls": ["https://www.thegoodfoot.com/"]},
    {"name": "Music Millennium", "parser": parse_musicmillennium, "walled": True,
     "urls": [MM_URL]},
    {"name": "Dante's", "parser": parse_dantes,
     "urls": ["https://www.danteslive.com/",
              "https://www.danteslive.com/page/2/",
              "https://www.danteslive.com/page/3/"]},
]

def scrape():
    pacific = datetime.timezone(datetime.timedelta(hours=-8))
    today = datetime.datetime.now(pacific).date()
    horizon = (today + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    lower = today.isoformat()
    out = []
    # YIELD-ZERO detection. "0 shows" has always been printed identically for
    # three completely different situations, and that ambiguity is what let
    # Artichoke serve stale data for four runs: Eventbrite changed a tag, the
    # parser matched nothing, returned [] with no exception, and the line read
    # exactly like a venue with an empty calendar. Nothing warned until
    # DROPPED-TO-0 fired -- by which point the feed had been wrong for days.
    #
    #   fetch failed        -> already loud (WARN, from the except below)
    #   fetched, parsed 0   -> SUSPECT: a live page the parser can no longer read
    #   parsed N, kept 0    -> SUSPECT: every row fell outside the date window
    #   genuinely empty     -> fine, and the only one that should be quiet
    #
    # The middle two are near-certainly bugs and are now reported on the FIRST
    # run rather than the fourth. Sources that legitimately sit empty opt out
    # with {"may_be_empty": True} so the signal stays worth reading.
    zero_reports = []
    for src in SOURCES:
        got = []
        fetched_ok = False
        raw_count = 0
        for url in src["urls"]:
            # Per-venue isolation: a single source throwing (exception, timeout,
            # bot-challenge, shape change) must NOT abort the scrape or lose the
            # other venues. Log loudly and continue.
            try:
                if src.get("walled"):
                    # Headless tier, parser-owned fetch: the parser does its own
                    # navigation (e.g. Goodfoot clears the challenge on the
                    # homepage, then reads the site's JSON API in-session).
                    rows = src["parser"](None, today)
                elif src.get("tls"):
                    # TLS-fingerprint tier: Chrome's handshake without a
                    # browser. For firewalls that block on the connection,
                    # not the headers. Cheaper and steadier than headless.
                    rows = src["parser"](fetch_tls(url), today)
                elif src.get("headless"):
                    # Headless tier, loop-owned fetch: Chromium clears the
                    # challenge and the parser gets ordinary rendered HTML, so
                    # an existing HTML parser needs no changes to move behind a
                    # wall. Kelly's Olympian lived here Sep 2026 until the
                    # TLS tier above got it back onto its JSON API.
                    from fetch_headless import fetch_headless
                    rows = src["parser"](fetch_headless(url), today)
                else:
                    rows = src["parser"](fetch(url), today)
                # Reaching here means the fetch returned real content and the
                # parser ran without raising -- so a zero count below is the
                # parser's verdict on a live page, not a transport failure.
                fetched_ok = True
                rows = rows or []
                raw_count += len(rows)
                got.extend(rows)
            except Exception as e:
                # A source can mark URLs it EXPECTS to 404 -- Spare Room posts
                # one page per month and next month's does not exist until
                # they write it. That is the normal state for weeks at a
                # time, and a WARN every night for it teaches the eye to
                # skip the WARN block. Say it once, quietly, and move on.
                if url in src.get("optional_urls", ()) and "404" in str(e):
                    print(f"  note: {src['name']}: {url.rsplit('/', 1)[-1]} not posted yet (404, expected)")
                else:
                    print(f"  WARN: {src['name']} parser failed: {type(e).__name__}: {e} ({url})")
        got = [s for s in got if lower <= s["date"] <= horizon]
        print(f"  {src['name']}: {len(got)} shows")
        if not got and fetched_ok and not src.get("may_be_empty"):
            if raw_count:
                zero_reports.append(
                    (src["name"], f"parsed {raw_count} row(s) but every one fell outside "
                                  f"today..+{HORIZON_DAYS}d -- stale calendar or a date-parsing bug"))
            else:
                zero_reports.append(
                    (src["name"], "fetched OK but the parser found no events -- "
                                  "the page shape likely changed"))
        out.extend(got)
    return out, zero_reports

_BASELINE_FILE = os.path.join(os.path.dirname(__file__), "venue_baselines.json")
_BASELINE_HISTORY = 10   # rolling window of recent run counts per venue
_ANOMALY_PCT = 0.60      # flag drop/spike beyond +/-60% of trailing average
# Layer 2 - sustained-decline detector. Calibrated against the real 10-run
# windows in venue_baselines.json: these values catch the Laurelthirst-style
# bleed (-23% cumulative) and today flag only Barrel Room (known dead) and
# McMenamins Edgefield (18 -> 6), with zero false positives on flat, noisy,
# rising, or small-venue series.
_DECLINE_MIN_WINDOW = 5   # need a real history before judging a trend
_DECLINE_MIN_AVG = 10     # ignore small venues where +/-2 shows is noise
_DECLINE_MIN_STEPS = 3    # separate declining steps, so one dip cannot trip it
_DECLINE_CUM_PCT = 0.20   # cumulative loss vs the start of the window


# Venues whose count THIS RUN is a known fallback, not a real reading. A parser
# adds itself here when it serves degraded data (e.g. Wix: the API failed and
# the 20-event warmup page was used instead of the full calendar).
#
# check_baselines still compares such a count to history and fires whatever
# alert applies -- but it does NOT append it to the history. Learning from a
# fallback is how Tomorrow's Verse went unnoticed: weeks at 20 (API broken)
# taught the baseline that ~43 was normal, so the recovery to 76 fired as a
# "spike" and the relapse to 20 -- a 74% loss of real data -- looked ordinary.
# The detector was measuring against the broken state. A fallback should be
# judged against health, not become the definition of it.
DEGRADED_VENUES = set()
_DEGRADED_ORIGINS = set()

# Venues whose calendar goes to zero every year on purpose. For these, a
# decline into autumn and a spike in spring are the venue working, not the
# scraper breaking. Their counts are still compared and still learned into
# history -- an off-season IS real data -- but the decline-shaped alerts
# (DROPPED TO 0, drop, SUSTAINED DECLINE) print as expected-seasonal notes
# rather than ALERTs, so the alert block stays worth reading. Edgefield's
# 18 -> 6 in Aug 2026 fired as "possible slow scraper bleed"; it was the
# lawn closing for the year. Spikes are left alone: a season opening is
# worth a glance, and it is one line a year.
SEASONAL_VENUES = {
    "McMenamins Edgefield",      # outdoor concerts, summer only
    "Cascades Amphitheater",     # outdoor, summer only
    "Pioneer Courthouse Square", # summer series
    "The Ruins",                 # Columbia Gorge, seasonal
}


def check_baselines(scraped):
    # S1: per-venue count baseline + zero-drop/anomaly alert. Compares each
    # venue's count this run to its trailing history; loudly flags venues that
    # dropped to 0 (had shows before) or moved >60% vs their average. Seeds
    # silently on first sighting. Updates the rolling history file each run.
    from collections import Counter
    counts = Counter(s.get("venue", "") for s in scraped)
    try:
        hist = json.load(open(_BASELINE_FILE))
    except Exception:
        hist = {}
    alerts = []
    seasonal_notes = []
    venues = set(hist) | set(counts)
    for v in sorted(venues):
        if not v:
            continue
        now = counts.get(v, 0)
        past = hist.get(v, [])
        if past:
            avg = sum(past) / len(past)
            msg = None
            if now == 0 and avg > 0:
                msg = f"{v}: DROPPED TO 0 (trailing avg {avg:.1f})"
                decline = True
            elif avg > 0 and abs(now - avg) / avg > _ANOMALY_PCT:
                direction = "spike" if now > avg else "drop"
                msg = f"{v}: {direction} {now} vs avg {avg:.1f} (>{int(_ANOMALY_PCT*100)}%)"
                decline = direction == "drop"
            if msg:
                (seasonal_notes if (decline and v in SEASONAL_VENUES) else alerts).append(msg)
    # roll the history forward (append this run, cap window); seed new venues
    new_hist = {}
    for v in venues:
        if not v:
            continue
        if v in DEGRADED_VENUES:
            # Carry history forward unchanged: this count is a fallback, not
            # a reading of the venue. Compared above, not learned here.
            new_hist[v] = hist.get(v, [])[-_BASELINE_HISTORY:]
            continue
        new_hist[v] = (hist.get(v, []) + [counts.get(v, 0)])[-_BASELINE_HISTORY:]
    if DEGRADED_VENUES:
        print(f"  baseline: {len(DEGRADED_VENUES)} venue(s) served fallback data this run; "
              f"history NOT updated for: {', '.join(sorted(DEGRADED_VENUES))}")

    # Layer 2: slope-aware sustained-decline detector. The checks above only
    # trip on drop-to-zero or a single-run swing beyond +/-60%, so a slow
    # multi-week bleed slides under both (Laurelthirst went 34 -> 25, about
    # -23%, and never alarmed). This catches a venue that has been quietly
    # eroding: enough separate declining steps to rule out noise, a meaningful
    # cumulative loss, and a big enough venue that +/-2 shows is not just churn.
    for v in sorted(venues):
        if not v:
            continue
        h = new_hist.get(v, [])
        if len(h) < _DECLINE_MIN_WINDOW:
            continue
        prior = h[:-1]
        if not prior or (sum(prior) / len(prior)) < _DECLINE_MIN_AVG:
            continue
        steps = sum(1 for i in range(1, len(h)) if h[i] < h[i - 1])
        start = sum(h[:3]) / 3.0
        if start <= 0:
            continue
        cum = (h[-1] - start) / start
        if steps >= _DECLINE_MIN_STEPS and cum <= -_DECLINE_CUM_PCT:
            (seasonal_notes if v in SEASONAL_VENUES else alerts).append(
                f"{v}: SUSTAINED DECLINE {h[-1]} vs {start:.1f} at window start "
                f"({cum * 100:+.0f}%, {steps} declining steps) -- possible slow scraper bleed")

    if alerts:
        print(f"BASELINE ALERT: {len(alerts)} venue(s) anomalous:")
        for a in alerts:
            print(f"  ALERT: {a}")
    if seasonal_notes:
        print(f"  seasonal (expected, not counted as alerts): {len(seasonal_notes)}")
        for a in seasonal_notes:
            print(f"    season: {a}")
    else:
        print(f"BASELINE: {len([v for v in counts if v])} venues OK, 0 anomalies")
    try:
        with open(_BASELINE_FILE, "w") as f:
            json.dump(new_hist, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"  WARN: could not write baselines: {e}")
    return alerts



# --- Layer 3: retention expiry + per-venue staleness --------------------------
# manual_shows.json retains a venue's last good scrape whenever that venue
# scrapes zero. That is correct for a transient blip (Kelly's Olympian scraped
# zero once and recovered the next run with real data) and wrong for a source
# that is permanently gone (Barrel Room migrated off its old site and served 44
# fossil listings for 32 days, because retention had no expiry).
#
# N is deliberately smaller than _BASELINE_HISTORY: the DROPPED-TO-0 alert fades
# as the trailing average decays toward zero over the window, so retention must
# die while that alert is still audible, not after it has gone silent.
_RETENTION_MAX_ZERO_RUNS = 5   # 5 consecutive zero-scrape runs, vs a 10-run alert window


def _trailing_zeros(hist):
    n = 0
    for x in reversed(hist or []):
        if x == 0:
            n += 1
        else:
            break
    return n


def retention_status(hist):
    """Split tracked venues into (expired, still_retained).

    Only venues that have EVER scraped successfully are eligible to expire -- a
    venue with an all-zero history was never scraped at all, so its entries in
    manual_shows.json are genuinely hand-added and must never be dropped."""
    expired, retained = {}, {}
    for v, h in (hist or {}).items():
        if not v or not h or h[-1] != 0:
            continue
        if not any(x > 0 for x in h):
            continue                      # never scraped -> hand-added, keep forever
        z = _trailing_zeros(h)
        if z >= _RETENTION_MAX_ZERO_RUNS:
            expired[v] = z
        else:
            retained[v] = z
    return expired, retained


def main():
    scraped, zero_reports = scrape()
    check_baselines(scraped)
    # Reported BEFORE the retention/staleness block, because this is the
    # upstream cause of the staleness that block describes -- and unlike
    # DROPPED-TO-0 it fires on the first bad run, not the fourth.
    if zero_reports:
        print(f"YIELD-ZERO: {len(zero_reports)} source(s) returned nothing from a page "
              f"that loaded fine:")
        for name, why in zero_reports:
            print(f"  SUSPECT: {name} -- {why}")
        print("  ^ a source that loads but yields nothing is a parser problem, not an "
              "empty calendar. If a source is legitimately empty (seasonal, closed), "
              'mark it {"may_be_empty": True} in SOURCES so this stays worth reading.')
    scraped_venues = {s["venue"] for s in scraped}
    target = os.path.join(os.path.dirname(__file__), "manual_shows.json")
    try:
        _hist = json.load(open(_BASELINE_FILE))
    except Exception:
        _hist = {}
    _expired, _retained = retention_status(_hist)

    hand = []
    if os.path.exists(target):
        try:
            hand = [s for s in json.load(open(target)).get("shows", [])
                    if s.get("_hand")
                    or (s.get("venue") not in scraped_venues
                        and s.get("venue") not in _expired)]
        except Exception:
            pass

    # Per-venue staleness signal, independent of the decaying DROPPED-TO-0 alert.
    if _expired:
        print(f"RETENTION EXPIRED: {len(_expired)} venue(s) dropped after "
              f"{_RETENTION_MAX_ZERO_RUNS}+ zero-scrape runs (now honest-empty):")
        for v, z in sorted(_expired.items()):
            if v in SEASONAL_VENUES:
                print(f"  EXPIRED: {v} ({z} consecutive zero runs) -- seasonal venue, off-season; "
                      f"nothing to fix, it comes back on its own")
            else:
                print(f"  EXPIRED: {v} ({z} consecutive zero runs) -- source likely dead, fix or remove the parser")
    if _retained:
        print(f"SERVING RETAINED DATA: {len(_retained)} venue(s) are showing a previous "
              f"scrape, not fresh data:")
        for v, z in sorted(_retained.items()):
            print(f"  STALE: {v} ({z}/{_RETENTION_MAX_ZERO_RUNS} zero runs before entries expire)")

    merged = hand + scraped
    with open(target, "w") as f:
        json.dump({"_comment": "Auto-generated by scrape_venues.py + hand-added shows.",
                   "shows": merged}, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(merged)} shows to manual_shows.json "
          f"({len(scraped)} scraped, {len(hand)} hand-added)")

if __name__ == "__main__":
    main()
