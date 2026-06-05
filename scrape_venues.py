#!/usr/bin/env python3
"""
PortlandLive venue scraper.

Scrapes venues' OWN published calendars (their own show data, published to fill
seats) and writes scripts/manual_shows.json, which build_shows.py merges into
shows.json. Pure HTTP + HTML parsing — no API key, no headless browser.

Covered sources:
  - Mammoth NW / Double Tee (roselandpdx.com): one page lists Roseland, Hawthorne,
    Aladdin, Crystal Ballroom, Wonder, Revolution Hall, Mississippi Studios,
    Holocene, Star Theater, Alberta Rose, and the big halls. Many venues, one fetch.
  - Dante's (danteslive.com): the venue's own TicketWeb-powered calendar, paginated.

Add a venue by writing a parser for its page structure and registering it in
SOURCES. Each site differs; parsers break on redesigns — that's the upkeep cost.

Run:
    pip install requests
    python3 scripts/scrape_venues.py
"""
import re, json, os, sys, datetime

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

MONTHS = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}

HORIZON_DAYS = 90

# venue name -> (neighborhood, address)
VENUE_INFO = {
    "Roseland Theater": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Peter's Room (Roseland)": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Roseland Ballroom": ("Old Town/Chinatown", "8 NW 6th Ave"),
    "Hawthorne Theatre": ("Mt Tabor/Hawthorne", "1507 SE 39th Ave"),
    "Aladdin Theater": ("Brooklyn", "3017 SE Milwaukie Ave"),
    "Crystal Ballroom": ("Downtown", "1332 W Burnside St"),
    "Wonder Ballroom": ("Eliot/Boise", "128 NE Russell St"),
    "Revolution Hall": ("Buckman", "1300 SE Stark St"),
    "Mississippi Studios": ("Boise/Mississippi", "3939 N Mississippi Ave"),
    "Holocene": ("Central Eastside", "1001 SE Morrison St"),
    "Dante's": ("Old Town/Chinatown", "350 W Burnside St"),
    "Star Theater": ("Old Town/Chinatown", "13 NW 6th Ave"),
    "Alberta Rose Theatre": ("Alberta Arts", "3000 NE Alberta St"),
    "Arlene Schnitzer Concert Hall": ("Downtown", "1037 SW Broadway"),
    "Keller Auditorium": ("Downtown", "222 SW Clay St"),
    "Moda Center": ("Lloyd/Rose Quarter", "1 N Center Ct St"),
    "Veterans Memorial Coliseum": ("Lloyd/Rose Quarter", "300 N Winning Way"),
    "Jack London Revue": ("Downtown", "529 SW 4th Ave"),
}

def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def to_time(s):
    m = re.match(r'(\d{1,2})(?::(\d{2}))?\s*([ap])m', s.strip(), re.I)
    if not m:
        return ""
    h = int(m.group(1)); mm = m.group(2) or "00"; ap = m.group(3).upper()
    return f"{h}:{mm} {ap}M"

def infer_year(month, today):
    return today.year + 1 if month < today.month else today.year

def fetch(url):
    r = requests.get(url, headers={"User-Agent": "PortlandLive/1.0 (listings aggregator)"},
                     timeout=30)
    r.raise_for_status()
    return r.text

def html_to_lines(html):
    """Reduce HTML to markdown-ish lines: anchors -> [text](href "title"), keep
    headings, drop the rest. Mirrors how the page reads so link regexes work."""
    html = re.sub(r'<a\b[^>]*?href="([^"]+)"[^>]*?(?:\stitle="([^"]*)")?[^>]*>(.*?)</a>',
                  lambda m: f'[{clean(re.sub("<[^>]+>","",m.group(3)))}]({m.group(1)}'
                            + (f' "{m.group(2)}"' if m.group(2) else '') + ')',
                  html, flags=re.S | re.I)
    html = re.sub(r'<h4[^>]*>(.*?)</h4>', lambda m: "#### " + re.sub("<[^>]+>","",m.group(1)),
                  html, flags=re.S | re.I)
    html = re.sub(r'<h2[^>]*>(.*?)</h2>', lambda m: "## " + re.sub("<[^>]+>","",m.group(1)),
                  html, flags=re.S | re.I)
    html = re.sub(r'<[^>]+>', '\n', html)
    html = html.replace('&amp;', '&').replace('&#8211;', '–').replace('&nbsp;', ' ')
    return [clean(l) for l in html.splitlines() if clean(l)]

# ---- Mammoth NW / Double Tee (roselandpdx.com) -------------------------------
MAMMOTH_DATE = re.compile(
    r'^\[(.+?)\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Z][a-z]{2})\s+(\d{1,2})\]'
    r'\((https://[^\s)]+/event/[^\s)]+)')
MAMMOTH_SHOW = re.compile(r'Show:\s*([\d:]+\s*[ap]m)', re.I)
MAMMOTH_VENUE = re.compile(r'^\[(.+?)\]\(https?://[^\s)]+/venue/')
MAMMOTH_TIX = re.compile(r'^\[(?:Buy Tickets|Sold Out|Tickets)\]\((https?://[^\s)]+)')

def parse_mammoth(lines, today):
    starts = [i for i, l in enumerate(lines) if MAMMOTH_DATE.match(l)]
    shows = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        m = MAMMOTH_DATE.match(block[0])
        title = clean(m.group(1))
        mon = MONTHS[m.group(2)]; day = int(m.group(3))
        date = f"{infer_year(mon, today)}-{mon:02d}-{day:02d}"
        support, showtime, tix, venue = "", "", m.group(4), "Roseland Theater"
        for b in block:
            if b.startswith("#### with"):
                support = clean(b[4:]).removeprefix("with ").strip()
            sm = MAMMOTH_SHOW.search(b)
            if sm:
                showtime = to_time(sm.group(1))
            vm = MAMMOTH_VENUE.match(b)
            if vm and vm.group(1) in VENUE_INFO:
                venue = vm.group(1)
            tm = MAMMOTH_TIX.match(b)
            if tm:
                tix = tm.group(1)
        nb, addr = VENUE_INFO.get(venue, ("Portland", ""))
        full = f"{title} (w/ {support})" if support else title
        shows.append({"title": full, "venue": venue, "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix})
    return shows

# ---- Dante's (danteslive.com) ------------------------------------------------
# Event title line carries an unambiguous date in its title attr: "- DD/MM/YY".
DANTES_EVENT = re.compile(
    r'^\[([^\]]+)\]\((https://www\.danteslive\.com/tm-event/[^\s)]+)'
    r'\s+"[^"]*?-\s*(\d{2})/(\d{2})/(\d{2})"\)$')
DANTES_SHOW = re.compile(r'Show:\s*([\d:]+\s*[ap]m)', re.I)
DANTES_TIX = re.compile(r'^\[(?:Buy Tickets|On Sale[^\]]*)\]\((https://www\.ticketweb\.com[^\s)]+)')

def parse_dantes(lines, today):
    # title lines only (not the [![image](...)] variant)
    idxs = [i for i, l in enumerate(lines)
            if DANTES_EVENT.match(l) and not l.startswith('[![')]
    shows = []
    for idx in idxs:
        m = DANTES_EVENT.match(lines[idx])
        title = clean(m.group(1))
        dd, mm, yy = int(m.group(3)), int(m.group(4)), int(m.group(5))
        date = f"20{yy:02d}-{mm:02d}-{dd:02d}"
        showtime, tix = "", m.group(2)
        for b in lines[idx:idx + 4]:
            sm = DANTES_SHOW.search(b)
            if sm and not showtime:
                showtime = to_time(sm.group(1))
            tm = DANTES_TIX.match(b)
            if tm:
                tix = tm.group(1)
        nb, addr = VENUE_INFO["Dante's"]
        shows.append({"title": title, "venue": "Dante's", "neighborhood": nb,
                      "address": addr, "date": date, "time": showtime, "venueUrl": tix})
    return shows

# ---- Source registry ---------------------------------------------------------
# Each source: list of page URLs + the parser for that site's structure.
SOURCES = [
    {"name": "Mammoth NW", "parser": parse_mammoth,
     "urls": ["https://roselandpdx.com/events/"]},
    {"name": "Dante's", "parser": parse_dantes,
     "urls": ["https://www.danteslive.com/",
              "https://www.danteslive.com/page/2/",
              "https://www.danteslive.com/page/3/"]},
]

def scrape():
    today = datetime.date.today()
    horizon = (today + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    out = []
    for src in SOURCES:
        got = []
        for url in src["urls"]:
            try:
                lines = html_to_lines(fetch(url))
                got.extend(src["parser"](lines, today))
            except Exception as e:
                print(f"  {url}: ERROR {e}")
        got = [s for s in got if s["date"] <= horizon and s["date"] >= today.isoformat()]
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
