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
            if len(between) > 60:
                break
        seg = clean(" ".join(getattr(el, "string", "") or "" for el in between
                             if getattr(el, "string", None)))
        sm = re.search(r'Show:\s*([\d:]+\s*[ap]m)', seg, re.I)
        if sm:
            showtime = to_time(sm.group(1))
        wm = re.search(r'\bwith\s+(.+?)(?:\s+All Ages|\s+\d+\+|\s+Doors:|$)', seg)
        if wm:
            support = clean(wm.group(1))

        nb, addr = VENUE_INFO.get(venue, ("Portland", ""))
        full = f"{title} (w/ {support})" if support else title
        shows.append({"title": full, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix, "imageUrl": ""})

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
        btext = clean(block.get_text(" "))
        sm = re.search(r'Show:\s*([\d:]+\s*[ap]m)', btext, re.I)
        showtime = to_time(sm.group(1)) if sm else ""
        tlink = block.find("a", href=re.compile(r'ticketweb\.com'))
        tix = tlink["href"] if tlink else url
        nb, addr = VENUE_INFO["Dante's"]
        shows.append({"title": title, "venue": "Dante's", "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix, "imageUrl": ""})
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
            shows.append({"title": full, "venue": venue, "neighborhood": nb,
                          "address": addr, "date": cur_date, "time": showtime, "venueUrl": url, "imageUrl": ""})
    return shows


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
            shows.append({"title": full, "venue": venue, "neighborhood": nb,
                          "address": addr, "date": cur_date, "time": showtime, "venueUrl": url, "imageUrl": ""})
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
                      "date": e["date"], "time": showtime, "venueUrl": tix, "imageUrl": ""})
    return shows
# ---- Holocene (holocene.org/events/) -----------------------------------------
# Each event: a title <h2> linking to /event/... with an etix ticket link whose
# slug ends -portland-holocene, a "Day, Mon DD" date line, "Doors: X pm", and an
# optional presenter line. Same etix-slug approach as Mississippi/Polaris.
HOLO_DATE = re.compile(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\b')

def parse_holocene(html, today):
    soup = BeautifulSoup(html, "html.parser")
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
                      "date": date_iso, "time": showtime, "venueUrl": e["tix"] or slug, "imageUrl": ""})
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
                      "address": addr, "date": date, "time": showtime, "venueUrl": url, "imageUrl": img})
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
                      "time": showtime, "venueUrl": url, "imageUrl": img})
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


_MQ_LD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S)


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
                      "address": addr, "date": date, "time": "", "venueUrl": href, "imageUrl": ""})
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
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": "", "venueUrl": url, "imageUrl": ""})
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
        date = _p5_date(clean(b.get_text(" ")) if b else "", today)
        if not (venue and title and date):
            continue
        key = (venue, date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        nb, addr = VENUE_INFO.get(venue, ("Downtown", ""))
        out.append({"title": title, "venue": venue, "neighborhood": nb,
                    "address": addr, "date": date, "time": "", "venueUrl": href, "imageUrl": ""})
    return len(cards)


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
                      "address": addr, "date": date, "time": showtime, "venueUrl": url, "imageUrl": ""})
    return shows



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
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": url, "imageUrl": img})
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
        rec = {"title": title, "venue": venue, "neighborhood": nb,
               "address": addr, "date": date, "time": showtime, "venueUrl": url, "imageUrl": img}
        prev = bykey.get(key)
        # JLR renders two date elements per event (one timed, one not);
        # keep one record per (venue,date,title), preferring the one WITH a time.
        if prev is not None and not rec.get("imageUrl") and prev.get("imageUrl"):
            rec["imageUrl"] = prev["imageUrl"]
        if prev is None or (not prev.get("time") and showtime):
            bykey[key] = rec
        elif not bykey[key].get("imageUrl") and rec.get("imageUrl"):
            bykey[key]["imageUrl"] = rec["imageUrl"]

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


def parse_showdown(html, today):
    soup = BeautifulSoup(html, "html.parser")
    shows = []
    seen = set()
    venue = "Showdown Saloon"
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
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": url, "imageUrl": ""})
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
                      "venueUrl": a.get("href", ""), "imageUrl": ""})
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
        shows.append({"title": title, "venue": "Bunk Bar",
                      "neighborhood": nb, "address": addr,
                      "date": date, "time": tm, "venueUrl": url, "imageUrl": ""})
    return shows


def parse_nofun(html, today):
    # No Fun (nofunportland.com) - Squarespace events collection. The
    # /events?format=json endpoint returns an "upcoming" list with startDate
    # epoch ms in UTC; convert to Pacific (PDT) like Alberta Street Pub. Same
    # business as Devil's Dill; address verified at 1709 SE Hawthorne Blvd.
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today
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

# ---- Tomorrow's Verse (youenjoymybeer.com) -- Wix Events app, browserless.
# Two-step chain: (1) GET the events page and pull the wix-events "instance"
# token out of the SSR'd HTML (signed fresh per request), (2) POST it to the
# Wix Events query API to get a clean JSON event list. Recurring series come
# back as individual dated rows -- we keep each as its own dated show.
_TV_APPDEF = "140603ad-af8d-84a5-2c80-a0f60cb47351"  # Wix Events appDefId
_TV_EVENTS_PAGE = "https://www.youenjoymybeer.com/events"
_TV_QUERY_API = "https://www.youenjoymybeer.com/_api/wix-events-web/v1/events/query"
_TV_INSTANCE_RE = re.compile(r'"instance":"([\w-]+\.[\w-]+)"')

def _tv_instance_token(html):
    """Find the wix-events app instance token in the events page HTML.
    Tolerant of surrounding JSON: scan every "instance":"a.b" candidate and
    keep the one whose base64 payload decodes to the wix-events appDefId."""
    import base64
    for tok in _TV_INSTANCE_RE.findall(html):
        try:
            payload = tok.split(".", 1)[1]
            payload += "=" * (-len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            continue
        if data.get("appDefId") == _TV_APPDEF:
            return tok
    return None

def parse_tomorrowsverse(html, today):
    # `html` is the GET of _TV_EVENTS_PAGE supplied by fetch() in scrape().
    try:
        from zoneinfo import ZoneInfo
    except Exception:
        ZoneInfo = None
    token = _tv_instance_token(html)
    if not token:
        raise RuntimeError("Tomorrow's Verse: wix-events instance token not found in page HTML")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PortlandLive/1.0; listings aggregator)",
        "Authorization": token,
        "Content-Type": "application/json",
    }
    raw = []
    offset = 0
    while True:
        body = json.dumps({"limit": 100, "offset": offset, "fieldset": ["FULL"],
                           "filter": {"status": ["SCHEDULED", "STARTED"]}})
        resp = requests.post(_TV_QUERY_API, headers=headers, data=body, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        evs = page.get("events", []) or []
        raw.extend(evs)
        total = page.get("total", len(raw))
        offset += len(evs)
        if not evs or offset >= total or len(raw) >= 2000:
            break
    venue = "Tomorrow's Verse"
    nb, addr = VENUE_INFO.get(venue, ("Beaumont-Wilshire", "4605 NE Fremont St, Portland, OR 97213"))
    out, seen = [], set()
    for e in raw:
        cfg = (e.get("scheduling") or {}).get("config") or {}
        sd = cfg.get("startDate")
        if not sd:
            continue
        try:
            dt = datetime.datetime.strptime(sd, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc)
        except Exception:
            continue
        tzid = cfg.get("timeZoneId") or "America/Los_Angeles"
        if ZoneInfo is not None:
            try:
                dt = dt.astimezone(ZoneInfo(tzid))
            except Exception:
                dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=-8)))
        else:
            dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=-8)))
        date = dt.date().isoformat()
        ampm = "am" if dt.hour < 12 else "pm"
        tm = to_time("%d:%02d%s" % (dt.hour % 12 or 12, dt.minute, ampm))
        title = clean(e.get("title") or "")
        title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip()
        if not title:
            continue
        slug = e.get("slug") or ""
        url = "https://www.youenjoymybeer.com/events/" + slug if slug else _TV_EVENTS_PAGE
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": venue, "neighborhood": nb, "address": addr,
                    "date": date, "time": tm, "venueUrl": url, "imageUrl": ""})
    return out



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
                        "venueUrl": url, "imageUrl": img})
    return out



def parse_kellys_olympian(html_text, today):
    # Kelly's Olympian (kellysolympian.com), Downtown - WordPress + The Events Calendar.
    # Events live in JSON-LD <script type="application/ld+json"> Event objects (Pacific offset dates).
    import html as _html
    out, seen = [], set()
    horizon = today + datetime.timedelta(days=HORIZON_DAYS)
    lower = today
    nb, addr = VENUE_INFO.get("Kelly's Olympian", ("Downtown", ""))
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_text, re.S)
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


def parse_barrelroom(html_text, today):
    # Barrel Room (barrelroompdx.com), Old Town/Chinatown - Squarespace + Eventbrite.
    # JSON-LD is a single Place object whose "Events" list holds Event @type objects (UTC startDate).
    # High volume (weekly residencies); today->horizon window + (date,title) dedupe trims it.
    import html as _html
    out, seen = [], set()
    horizon = today + datetime.timedelta(days=HORIZON_DAYS)
    lower = today
    nb, addr = VENUE_INFO.get("Barrel Room", ("Old Town/Chinatown", ""))
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_text, re.S)
    evs = []
    for b in blocks:
        try:
            data = json.loads(b)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("Events"), list):
            evs.extend(data["Events"])
        elif isinstance(data, list):
            evs.extend([x for x in data if isinstance(x, dict) and x.get("@type") == "Event"])
        elif isinstance(data, dict) and data.get("@type") == "Event":
            evs.append(data)
    for e in evs:
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
        url = e.get("url") or "https://www.barrelroompdx.com/events"
        img = e.get("image") or ""
        if isinstance(img, dict):
            img = img.get("url", "")
        key = (date, title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "venue": "Barrel Room", "neighborhood": nb,
                    "address": addr, "date": date, "time": tm,
                    "venueUrl": url, "imageUrl": img})
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
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_text, re.S)
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
    {"name": "CitySpark (Ponderosa + Old Church)", "parser": parse_cityspark,
     "urls": ["https://portal.cityspark.com/PortalScripts/WillametteWeek"]},
    {"name": "Havalina (havalinapdx.com)", "parser": parse_havalina, "urls": ["https://havalinapdx.com/events?format=json"]},
    {"name": "Kelly's Olympian (kellysolympian.com)", "parser": parse_kellys_olympian, "urls": ["https://kellysolympian.com/events/"]},
    {"name": "Barrel Room (barrelroompdx.com)", "parser": parse_barrelroom, "urls": ["https://www.barrelroompdx.com/events"]},
    {"name": "Arbor Beer Lodge (arborbeerlodge.com)", "parser": parse_arbor, "urls": ["https://www.arborbeerlodge.com/events?format=json"]},
    {"name": "Artichoke Music (artichokemusic.org)", "parser": parse_artichoke, "urls": ["https://www.eventbrite.com/cc/live-music-artichoke-4657563"]},
    {"name": "Starday Tavern (stardaytavern.com / Genghis Records)", "parser": parse_starday, "urls": ["https://calendar.google.com/calendar/ical/m59vjhvcv0iflpv2iknoqlmuqo%40group.calendar.google.com/public/basic.ics"]},
    {"name": "McMenamins (White Eagle/Al's Den/Mission)", "parser": parse_mcmenamins,
     "urls": ["https://www.mcmenamins.com/to-do/live-music-events/music-event-calendar"]},
    {"name": "NOVA PDX", "parser": parse_novapdx, "urls": ["https://novapdxevents.com/event-calendar"]},
    {"name": "Pioneer Courthouse Square / PDX Live (pdx-live.com)", "parser": parse_pdxlive, "urls": ["https://pdx-live.com/wp-json/wlcr/v1/events/raw"]},
    {"name": "Twilight Cafe & Bar (twilightcafeandbar.com)", "parser": parse_twilight, "urls": ["https://twilightcafeandbar.com/calendar_list"]},
    {"name": "No Fun (nofunportland.com)", "parser": parse_nofun, "urls": ["https://www.nofunportland.com/events?format=json"]},
    {"name": "Bunk Bar (shows.bunksandwiches.com)", "parser": parse_bunkbar, "urls": ["https://shows.bunksandwiches.com/"]},
    {"name": "Mississippi Pizza (mississippipizza.com)", "parser": parse_mississippipizza, "urls": ["https://mississippipizza.com/calendar/"]},
    {"name": "Alberta Street Pub (albertastreetpub.com)", "parser": parse_albertastreetpub, "urls": ["https://www.albertastreetpub.com/music?format=json"]},
    {"name": "Tomorrow's Verse (youenjoymybeer.com)", "parser": parse_tomorrowsverse, "urls": ["https://www.youenjoymybeer.com/events"]},
    {"name": "Cascades Amphitheater (livenation.com)", "parser": parse_cascades, "urls": [_CASCADES_URL]},
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
    for src in SOURCES:
        got = []
        for url in src["urls"]:
            # Per-venue isolation: a single source throwing (exception, timeout,
            # bot-challenge, shape change) must NOT abort the scrape or lose the
            # other venues. Log loudly and continue.
            try:
                if src.get("walled"):
                    # Headless tier: the parser owns its own fetch (see
                    # fetch_headless.py). fetch() would only get the
                    # challenge page back.
                    got.extend(src["parser"](None, today))
                else:
                    got.extend(src["parser"](fetch(url), today))
            except Exception as e:
                print(f"  WARN: {src['name']} parser failed: {type(e).__name__}: {e} ({url})")
        got = [s for s in got if lower <= s["date"] <= horizon]
        print(f"  {src['name']}: {len(got)} shows")
        out.extend(got)
    return out

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
    venues = set(hist) | set(counts)
    for v in sorted(venues):
        if not v:
            continue
        now = counts.get(v, 0)
        past = hist.get(v, [])
        if past:
            avg = sum(past) / len(past)
            if now == 0 and avg > 0:
                alerts.append(f"{v}: DROPPED TO 0 (trailing avg {avg:.1f})")
            elif avg > 0 and abs(now - avg) / avg > _ANOMALY_PCT:
                direction = "spike" if now > avg else "drop"
                alerts.append(f"{v}: {direction} {now} vs avg {avg:.1f} (>{int(_ANOMALY_PCT*100)}%)")
    # roll the history forward (append this run, cap window); seed new venues
    new_hist = {}
    for v in venues:
        if not v:
            continue
        new_hist[v] = (hist.get(v, []) + [counts.get(v, 0)])[-_BASELINE_HISTORY:]

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
            alerts.append(
                f"{v}: SUSTAINED DECLINE {h[-1]} vs {start:.1f} at window start "
                f"({cum * 100:+.0f}%, {steps} declining steps) -- possible slow scraper bleed")

    if alerts:
        print(f"BASELINE ALERT: {len(alerts)} venue(s) anomalous:")
        for a in alerts:
            print(f"  ALERT: {a}")
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
    scraped = scrape()
    check_baselines(scraped)
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
                    if s.get("venue") not in scraped_venues
                    and s.get("venue") not in _expired]
        except Exception:
            pass

    # Per-venue staleness signal, independent of the decaying DROPPED-TO-0 alert.
    if _expired:
        print(f"RETENTION EXPIRED: {len(_expired)} venue(s) dropped after "
              f"{_RETENTION_MAX_ZERO_RUNS}+ zero-scrape runs (now honest-empty):")
        for v, z in sorted(_expired.items()):
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
