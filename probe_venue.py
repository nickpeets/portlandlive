#!/usr/bin/env python3
"""Crawl a venue's website and report where its events live.

    python3 probe_venue.py https://topazfarm.com [https://another.com ...]
    python3 probe_venue.py --save https://topazfarm.com    # also saves event-bearing pages under fixtures/intake/

Follows every same-site link from the homepage plus sitemap.xml (up to
--max pages, default 60), then for each page reports: Squarespace events
collections (checked as ?format=json), WordPress Events Calendar / EventON,
Google Calendar embeds (with the calendar id decoded), ticketing embeds and
links (Tixr, Eventbrite, Dice, Etix, TicketWeb, Prekindle, Turntable, Ticket
Tailor, KeepAndShare, Bandsintown, Songkick), JSON-LD Event blocks, and how
many upcoming-looking dates the page text carries. Key-shaped strings are
scrubbed from anything saved.
"""
import re, sys, json, base64, os, time, warnings
from urllib.parse import urljoin, urlsplit
import requests
from bs4 import BeautifulSoup
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass

H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
     "Accept": "text/html,application/json,*/*"}
SCRUB = re.compile(r"(?i)AIza[0-9A-Za-z_-]{30,}|(?:api[_-]?key|token)=[A-Za-z0-9_-]{16,}")
MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RX = re.compile(rf"(?i)\b{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?\b|\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b")
EMBEDS = [("tixr.com", "Tixr"), ("eventbrite.com", "Eventbrite"), ("dice.fm", "Dice"), ("etix.com", "Etix"), ("ticketweb.com", "TicketWeb"),
          ("prekindle.com", "Prekindle"), ("turntabletickets.com", "Turntable"), ("tickettailor.com", "Ticket Tailor"), ("keepandshare.com", "KeepAndShare"),
          ("bandsintown.com", "Bandsintown"), ("songkick.com", "Songkick"), ("calendar.google.com", "Google Calendar"), ("tribe-events", "WP Events Calendar"),
          ("evcal_", "WP EventON"), ("wix-events", "Wix Events"), ("seetickets", "See Tickets"), ("showclix", "ShowClix"), ("freshtix", "FreshTix"),
          ("opendate.io", "Opendate"), ("ticketspice", "TicketSpice"), ("simpletix", "SimpleTix"), ("eventim", "Eventim"), ("ra.co", "RA")]
SKIP_RX = re.compile(r"(?i)\.(jpg|jpeg|png|gif|webp|svg|pdf|mp4|mp3|zip|css|js|xml)(\?|$)|/wp-content/|/cdn-cgi/|mailto:|tel:|javascript:|/\d{4}/\d{1,2}/\d{1,2}/|/tag/|/category/|/page/\d+|\?format=")

def fetch(url, timeout=20):
    try:
        r = requests.get(url, headers=H, timeout=timeout, allow_redirects=True)
        return r.status_code, r.text, r.url
    except Exception as e:
        return 0, "", url

def same_site(a, b):
    ha, hb = urlsplit(a).netloc.lower().replace("www.", ""), urlsplit(b).netloc.lower().replace("www.", "")
    return ha == hb

def analyse(url, html):
    out = {"url": url, "flags": [], "gcal": [], "ldjson_events": 0, "dates": 0, "sqs": None, "tribe": None}
    low = html.lower()
    for k, n in EMBEDS:
        if k in low and n not in out["flags"]:
            out["flags"].append(n)
    for m in re.findall(r"src=([^&\"'\s]+)", html):
        if "group.calendar.google.com" in m or (re.fullmatch(r"[A-Za-z0-9+/=_-]{30,}", m) and "calendar" in low):
            cid = m.replace("%40", "@")
            if "@" not in cid:
                try:
                    cid = base64.b64decode(cid + "=" * (-len(cid) % 4)).decode()
                except Exception:
                    continue
            if "calendar.google.com" in cid and cid not in out["gcal"]:
                out["gcal"].append(cid)
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I):
        out["ldjson_events"] += len(re.findall(r'"@type"\s*:\s*"(?:Music)?Event"', m.group(1)))
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" "))
    out["dates"] = len(DATE_RX.findall(text))
    return out

def sqs_check(url):
    code, body, _ = fetch(url.split("?")[0] + "?format=json")
    if code != 200 or not body.strip().startswith("{"):
        return None
    try:
        d = json.loads(body)
    except Exception:
        return None
    t = (d.get("collection") or {}).get("typeName")
    if t == "events" or "upcoming" in d:
        return {"type": t, "upcoming": len(d.get("upcoming") or []), "past": len(d.get("past") or [])}
    return {"type": t, "items": len(d.get("items") or [])} if t else None

def tribe_check(base):
    code, body, _ = fetch(base.rstrip("/") + "/wp-json/tribe/events/v1/events?per_page=50")
    if code == 200 and body.strip().startswith("{"):
        try:
            d = json.loads(body); return {"events": len(d.get("events") or []), "total": d.get("total")}
        except Exception:
            return None
    return None

def crawl(start, maxpages=60, save=False):
    code, home, final = fetch(start)
    if code != 200 or not home:
        print(f"\n### {start}: homepage {code}"); return
    base = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}"
    is_sqs = "squarespace" in home.lower()
    is_wp = "wp-content" in home.lower()
    print(f"\n### {base}  ({'Squarespace' if is_sqs else 'WordPress' if is_wp else 'custom'}; {len(home)} bytes)")
    todo, seen = [final], set()
    scode, sm, _ = fetch(base + "/sitemap.xml")
    if scode == 200:
        todo += [u for u in re.findall(r"<loc>([^<]+)</loc>", sm) if same_site(u, base)]
    if is_wp:
        t = tribe_check(base)
        if t: print(f"   WP Events Calendar API: {t}")
    hits = []
    known_colls = set()
    while todo and len(seen) < maxpages:
        u = todo.pop(0).split("#")[0].rstrip("/") or base
        if u in seen or not same_site(u, base) or SKIP_RX.search(u): continue
        # inside a collection we've already identified? skip its item pages
        pth = re.sub(r"https?://[^/]+", "", u)
        if any(pth.startswith(c + "/") for c in known_colls): continue
        seen.add(u)
        c, h, f = (200, home, final) if u == final else fetch(u)
        if c != 200 or not h: continue
        s = BeautifulSoup(h, "html.parser")
        for a in s.find_all("a", href=True):
            nu = urljoin(f, a["href"]).split("#")[0]
            if same_site(nu, base) and nu not in seen and not SKIP_RX.search(nu): todo.append(nu)
        info = analyse(f, h)
        if is_sqs:
            info["sqs"] = sqs_check(f)
            if info["sqs"] and info["sqs"].get("type") in ("events", "events-stacked", "blog", "gallery", "products"):
                known_colls.add(re.sub(r"https?://[^/]+", "", f).rstrip("/"))
        interesting = info["flags"] or info["gcal"] or info["ldjson_events"] or info["dates"] >= 3 or (info["sqs"] and info["sqs"].get("upcoming") is not None)
        if interesting:
            hits.append(info)
            path = re.sub(r"https?://[^/]+", "", f) or "/"
            bits = []
            if info["sqs"]: bits.append("SQS " + json.dumps(info["sqs"]))
            if info["gcal"]: bits.append("GCAL " + ", ".join(info["gcal"]))
            if info["ldjson_events"]: bits.append(f"ld+json events={info['ldjson_events']}")
            if info["flags"]: bits.append("embeds: " + ", ".join(info["flags"]))
            bits.append(f"dates={info['dates']}")
            print(f"   {path:36s} {' | '.join(bits)}")
            if save:
                os.makedirs("fixtures/intake", exist_ok=True)
                name = re.sub(r"[^a-z0-9]+", "-", (urlsplit(base).netloc.replace("www.", "") + path).lower()).strip("-")[:70]
                open(f"fixtures/intake/{name}.html", "w", encoding="utf-8").write(SCRUB.sub("SCRUBBED", h))
                if info["sqs"] and info["sqs"].get("upcoming") is not None:
                    _, jb, _ = fetch(f.split("?")[0] + "?format=json")
                    open(f"fixtures/intake/{name}.json", "w", encoding="utf-8").write(SCRUB.sub("SCRUBBED", jb))
        time.sleep(0.2)
    if not hits:
        print(f"   crawled {len(seen)} pages: no events, calendars, embeds or dated text found")
    else:
        print(f"   crawled {len(seen)} pages; {len(hits)} with something")
    sys.stdout.flush()

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    save = "--save" in sys.argv
    mx = 60
    for a in sys.argv[1:]:
        if a.startswith("--max="): mx = int(a.split("=")[1])
    for u in args:
        crawl(u if u.startswith("http") else "https://" + u, maxpages=mx, save=save)
