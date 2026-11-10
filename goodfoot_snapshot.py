#!/usr/bin/env python3
"""Write goodfoot_snapshot.json from The Goodfoot's .ics export, as read by a
web reader (Nov 10 2026). Cloudflare walls GitHub's runner from the site, so
the daily feed-health task fetches

    https://thegoodfoot.com/tec-events-overview/list/?ical=1
    https://thegoodfoot.com/tec-events-overview/list/?ical=1&tribe-bar-date=<day after the last DTSTART>

and pipes the events in as tab-separated lines, copied verbatim from the
VEVENTs:

    DTSTART<TAB>SUMMARY<TAB>URL<TAB>ATTACH<TAB>[price from DESCRIPTION]

e.g.  20261110T200000<TAB>GREATERKIND (8pm Doors)<TAB>https://thegoodfoot.com/events/greaterkind-8pm-doors-4/<TAB>https://.../IMG_0305-scaled.jpeg<TAB>[$8]

    python3 goodfoot_snapshot.py --fetched 2026-11-10 < events.tsv

A row that matches a show already in shows.json (same date and title once
punctuation is dropped) keeps that row's title and poster, which came from the
site's own API -- the .ics flattens dashes and has PDF posters. scrape_venues
validates every row again before using it.
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def key(date, title):
    return date, re.sub(r"[^a-z0-9]+", "", title.lower())


def ics_unescape(s):
    return re.sub(r"\\([,;\\])", r"\1", s).replace("\\n", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetched", default=datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=-8))).date().isoformat())
    ap.add_argument("--out", default=os.path.join(HERE, "goodfoot_snapshot.json"))
    a = ap.parse_args()
    known = {}
    try:
        for s in json.load(open(os.path.join(HERE, "shows.json")))["shows"]:
            if s.get("venue") == "The Goodfoot":
                known[key(s["date"], s["title"])] = s
    except Exception:
        pass
    events, seen, bad = [], set(), 0
    for line in sys.stdin:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3 or not re.fullmatch(r"\d{8}T\d{6}", parts[0].strip()):
            if line.strip() and not line.startswith("DTSTART"):
                bad += 1
            continue
        d = parts[0].strip()
        start = f"{d[:4]}-{d[4:6]}-{d[6:8]} {d[9:11]}:{d[11:13]}:{d[13:15]}"
        title = ics_unescape(parts[1])
        url = parts[2].strip()
        img = parts[3].strip() if len(parts) > 3 else ""
        price = parts[4].strip() if len(parts) > 4 else ""
        price = price[1:-1] if price.startswith("[") and price.endswith("]") else price
        if price in ("?", "-") or "?" in price:
            price = ""
        k = key(start[:10], title)
        if k in seen:
            continue
        seen.add(k)
        old = known.get(k)
        if old:
            title = old["title"]
            img = old.get("imageUrl") or img
        if not re.search(r"\.(jpe?g|png|webp|gif)$", img, re.I):
            img = ""
        events.append({"start_date": start, "title": title, "url": url,
                       "image": {"url": img} if img else False, "cost": price})
    events.sort(key=lambda e: e["start_date"])
    json.dump({"fetched": a.fetched,
               "source": "https://thegoodfoot.com/tec-events-overview/list/?ical=1 (web reader)",
               "events": events}, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(f"goodfoot_snapshot.json: {len(events)} events, {events[0]['start_date'][:10] if events else '-'}"
          f" to {events[-1]['start_date'][:10] if events else '-'}; {len(known)} known titles matched against;"
          f" {bad} unreadable line(s)")


if __name__ == "__main__":
    main()
