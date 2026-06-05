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
import json, os, datetime

HERE = os.path.dirname(__file__)
MANUAL = os.path.join(HERE, "manual_shows.json")
OUT = os.path.join(HERE, "shows.json")

def main():
    shows = []
    if os.path.exists(MANUAL):
        try:
            shows = json.load(open(MANUAL)).get("shows", [])
        except Exception as e:
            print(f"manual_shows.json unreadable: {e}")

    # drop past shows
    today = datetime.date.today().isoformat()
    shows = [s for s in shows if s.get("date", "") >= today]

    # dedupe on (title, venue, date)
    seen, deduped = set(), []
    for s in shows:
        k = (s.get("title","").lower().strip(),
             s.get("venue","").lower().strip(),
             s.get("date",""))
        if k not in seen and s.get("title") and s.get("date"):
            seen.add(k); deduped.append(s)

    deduped.sort(key=lambda s: (s["date"], s.get("venue",""), s.get("title","")))
    for i, s in enumerate(deduped, 1):
        s["id"] = i

    out = {
        "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "Scraped from venue calendars + hand-added listings",
        "shows": deduped,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    venues = len(set(s.get("venue","") for s in deduped))
    print(f"Wrote {len(deduped)} shows across {venues} venues to shows.json")

if __name__ == "__main__":
    main()
