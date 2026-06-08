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
    "Roseland Theater": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Peter's Room (Roseland)": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Roseland Ballroom": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Hawthorne Theatre": ("Mt Tabor/Hawthorne", "1507 SE 39th Ave"),
    "Aladdin Theater": ("Brooklyn", "3017 SE Milwaukie Ave"),
    "Crystal Ballroom": ("Downtown", "1332 W Burnside St"),
    "McMenamins Edgefield": ("Troutdale", "2126 SW Halsey St, Troutdale"),
    "McMenamins Grand Lodge": ("Forest Grove", "3505 Pacific Ave, Forest Grove"),
    "Arlene Schnitzer Concert Hall": ("Downtown", "1037 SW Broadway"),
    "Paramount Theatre": ("Downtown", "911 SW Salmon St"),
    "The Old Church": ("Downtown", "1422 SW 11th Ave"),
    "Wonder Ballroom": ("Eliot/Boise", "128 NE Russell St"),
    "Revolution Hall": ("Buckman", "1300 SE Stark St"),
    "Polaris Hall": ("Overlook/N Portland", "635 N Killingsworth Ct"),
    "Mississippi Studios": ("Boise/Mississippi", "3939 N Mississippi Ave"),
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
    "Hatfield Hall Rotunda": ("Downtown", "1111 SW Broadway"),
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


def fetch(url):
    r = requests.get(url, headers={"User-Agent":
        "Mozilla/5.0 (compatible; PortlandLive/1.0; listings aggregator)"}, timeout=30)
    if r.status_code in _CHALLENGE_STATUS:
        raise ChallengeError(f"challenge status {r.status_code} from {url}")
    body = r.text
    for sig in _CHALLENGE_SIGS:
        if sig in body:
            raise ChallengeError(f"challenge signature {sig!r} in body from {url}")
    r.raise_for_status()
    return body

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
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix})

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
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix})
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
                          "address": addr, "date": cur_date, "time": showtime, "venueUrl": url})
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
                      "date": date, "time": showtime, "venueUrl": tix})
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
                          "address": addr, "date": cur_date, "time": showtime, "venueUrl": url})
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
                      "date": e["date"], "time": showtime, "venueUrl": tix})
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
                      "date": date_iso, "time": showtime, "venueUrl": e["tix"] or slug})
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
        shows.append({"title": full, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": url})
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
        shows.append({"title": title, "venue": "Aladdin Theater",
                      "neighborhood": nb, "address": addr, "date": date,
                      "time": showtime, "venueUrl": url})
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
        return (url, "")
    for m in _MQ_LD.finditer(h):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("@type") == "Event":
            tm = re.search(r"T(\d{2}):(\d{2})", d.get("startDate", ""))
            if tm:
                hh, mm = int(tm.group(1)), tm.group(2)
                ap = "am" if hh < 12 else "pm"
                return (url, to_time(f"{hh % 12 or 12}:{mm} {ap}"))
    return (url, "")


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
                      "address": addr, "date": date, "time": "", "venueUrl": href})
    # show times only live on each event detail page; fetch concurrently
    import concurrent.futures
    urls = list({s["venueUrl"] for s in shows})
    times = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for u, t in ex.map(_monqui_event_time, urls):
            times[u] = t
    for s in shows:
        s["time"] = times.get(s["venueUrl"], "")

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
                      "address": addr, "date": date, "time": "", "venueUrl": url})
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
                    "address": addr, "date": date, "time": "", "venueUrl": href})
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
                      "address": addr, "date": date, "time": showtime, "venueUrl": url})
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
        shows.append({"title": title, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": url})
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
        rec = {"title": title, "venue": venue, "neighborhood": nb,
               "address": addr, "date": date, "time": showtime, "venueUrl": url}
        prev = bykey.get(key)
        # JLR renders two date elements per event (one timed, one not);
        # keep one record per (venue,date,title), preferring the one WITH a time.
        if prev is None or (not prev.get("time") and showtime):
            bykey[key] = rec

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
                      "address": addr, "date": date, "time": "", "venueUrl": url})
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
                      "address": addr, "date": date, "time": showtime, "venueUrl": url})
    return shows



# ---- Laurelthirst Public House (laurelthirst.com) ----------------------------
# WordPress + EventON plugin. No single feed lists upcoming events with dates,
# but the WP REST CPT route /wp-json/wp/v2/ajde_events lists event posts
# (newest-published first), and each event PAGE carries clean schema.org
# JSON-LD with itemprop="startDate" (e.g. 2026-6-20T18:00-7:00). We page the
# CPT list and read each event page's startDate concurrently.
LAUREL_BASE = "https://www.laurelthirst.com"
LAUREL_CPT = LAUREL_BASE + "/wp-json/wp/v2/ajde_events"
_LAUREL_SD = re.compile(r"itemprop=['\"]startDate['\"]\s+content=['\"]([^'\"]+)['\"]")
_LAUREL_LD = re.compile(r"application/ld\+json[^>]*>(.*?)</script>", re.S)

def _laurel_event(link):
    try:
        h = fetch(link)
    except Exception:
        return None
    m = _LAUREL_SD.search(h)
    if not m:
        return None
    name = None
    nm = _LAUREL_LD.search(h)
    if nm:
        try:
            name = json.loads(nm.group(1)).get("name")
        except Exception:
            name = None
    return (link, m.group(1), name)

def parse_laurelthirst(html, today):
    import concurrent.futures, urllib.request, urllib.parse
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today - datetime.timedelta(days=1)
    links = []
    for page in range(1, 5):
        url = LAUREL_CPT + "?per_page=50&orderby=date&order=desc&page=%d" % page
        try:
            data = json.loads(fetch(url))
        except Exception:
            break
        if not data:
            break
        for e in data:
            lk = e.get("link", "")
            if lk:
                links.append((lk, e.get("title", {}).get("rendered", "")))
        if len(data) < 50:
            break
    # fetch event pages concurrently for start dates
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_laurel_event, lk): lk for lk, _ in links}
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            if r:
                results[r[0]] = (r[1], r[2])
    for lk, rendered in links:
        if lk not in results:
            continue
        sd, name = results[lk]
        mm = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:T(\d{1,2}):(\d{2}))?", sd or "")
        if not mm:
            continue
        try:
            d = datetime.date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)))
        except ValueError:
            continue
        if not (lower <= d <= horizon):
            continue
        date = d.isoformat()
        tm = ""
        if mm.group(4) is not None:
            hh, mn = int(mm.group(4)), int(mm.group(5))
            tm = "%d:%02d %s" % (hh % 12 or 12, mn, "AM" if hh < 12 else "PM")
        raw = name or rendered or ""
        title = clean(raw.replace("&amp;", "&"))
        title = re.sub(r"\s+", " ", re.sub(r"[\u2010-\u2015]", "-", title)).strip()
        if not title:
            continue
        key = (date, lk or title.lower())
        if key in seen:
            continue
        seen[key] = 1
        nb, addr = VENUE_INFO.get("Laurelthirst Public House", ("Kerns", "2958 NE Glisan St"))
        out.append({"title": title, "venue": "Laurelthirst Public House",
                    "neighborhood": nb, "address": addr,
                    "date": date, "time": tm, "venueUrl": lk})
    return out



# ---- Alberta Street Pub (albertastreetpub.com) ------------------------------
# Squarespace site. The /music events page exposes structured JSON via the
# ?format=json query param: an "upcoming" list of events with title, fullUrl,
# and startDate (epoch milliseconds, UTC). Convert to Pacific local time.
_ASP_PDT = datetime.timezone(datetime.timedelta(hours=-7))  # Portland summer (PDT)

def parse_albertastreetpub(html, today):
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today - datetime.timedelta(days=1)
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
                    "date": date, "time": tm, "venueUrl": url})
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
                      "venueUrl": a.get("href", "")})
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
                      "date": date, "time": tm, "venueUrl": url})
    return shows


def parse_nofun(html, today):
    # No Fun (nofunportland.com) - Squarespace events collection. The
    # /events?format=json endpoint returns an "upcoming" list with startDate
    # epoch ms in UTC; convert to Pacific (PDT) like Alberta Street Pub. Same
    # business as Devil's Dill; address verified at 1709 SE Hawthorne Blvd.
    out, seen = [], {}
    horizon = today + datetime.timedelta(days=120)
    lower = today - datetime.timedelta(days=1)
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
                    "date": date, "time": tm, "venueUrl": url})
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
                shows.append({"title": title, "venue": "Twilight Cafe & Bar",
                              "neighborhood": nb, "address": addr,
                              "date": date, "time": "", "venueUrl": href})
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
                    "date": date, "time": tm, "venueUrl": url})
    return out

SOURCES = [
    {"name": "Pioneer Courthouse Square / PDX Live (pdx-live.com)", "parser": parse_pdxlive, "urls": ["https://pdx-live.com/wp-json/wlcr/v1/events/raw"]},
    {"name": "Twilight Cafe & Bar (twilightcafeandbar.com)", "parser": parse_twilight, "urls": ["https://twilightcafeandbar.com/calendar_list"]},
    {"name": "No Fun (nofunportland.com)", "parser": parse_nofun, "urls": ["https://www.nofunportland.com/events?format=json"]},
    {"name": "Bunk Bar (shows.bunksandwiches.com)", "parser": parse_bunkbar, "urls": ["https://shows.bunksandwiches.com/"]},
    {"name": "Mississippi Pizza (mississippipizza.com)", "parser": parse_mississippipizza, "urls": ["https://mississippipizza.com/calendar/"]},
    {"name": "Alberta Street Pub (albertastreetpub.com)", "parser": parse_albertastreetpub, "urls": ["https://www.albertastreetpub.com/music?format=json"]},
    {"name": "Laurelthirst (laurelthirst.com)", "parser": parse_laurelthirst, "urls": ["https://www.laurelthirst.com/"]},
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
    {"name": "Dante's", "parser": parse_dantes,
     "urls": ["https://www.danteslive.com/",
              "https://www.danteslive.com/page/2/",
              "https://www.danteslive.com/page/3/"]},
]

def scrape():
    pacific = datetime.timezone(datetime.timedelta(hours=-8))
    today = datetime.datetime.now(pacific).date()
    horizon = (today + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    lower = (today - datetime.timedelta(days=1)).isoformat()
    out = []
    for src in SOURCES:
        got = []
        for url in src["urls"]:
            # Per-venue isolation: a single source throwing (exception, timeout,
            # bot-challenge, shape change) must NOT abort the scrape or lose the
            # other venues. Log loudly and continue.
            try:
                got.extend(src["parser"](fetch(url), today))
            except Exception as e:
                print(f"  WARN: {src['name']} parser failed: {type(e).__name__}: {e} ({url})")
        got = [s for s in got if lower <= s["date"] <= horizon]
        print(f"  {src['name']}: {len(got)} shows")
        out.extend(got)
    return out

def main():
    scraped = scrape()
    scraped_venues = {s["venue"] for s in scraped}
    target = os.path.join(os.path.dirname(__file__), "manual_shows.json")
    hand = []
    if os.path.exists(target):
        try:
            hand = [s for s in json.load(open(target)).get("shows", [])
                    if s.get("venue") not in scraped_venues]
        except Exception:
            pass
    merged = hand + scraped
    with open(target, "w") as f:
        json.dump({"_comment": "Auto-generated by scrape_venues.py + hand-added shows.",
                   "shows": merged}, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(merged)} shows to manual_shows.json "
          f"({len(scraped)} scraped, {len(hand)} hand-added)")

if __name__ == "__main__":
    main()
