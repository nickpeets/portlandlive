#!/usr/bin/env python3
"""
Age-field probe.

Finds out which venue pages already publish a per-show age restriction in the
HTML the scrapers are ALREADY fetching. Read-only: fetches, counts, prints.
Touches no repo file and writes nothing.

Why: build_shows.py has a precedence branch for a scraper-supplied `age`, but
no parser emits one, so it never fires. Meanwhile Aladdin's own FAQ says to
check the event page for age, and Revolution Hall lists events as All Ages or
21 and over individually. If that text is in the listing HTML, the parsers can
read it and the feed gets real per-show ages instead of house-policy guesses.

For each source it reports:
  - how many age markers appear in the page at all
  - the surrounding HTML for the first few, so the selector is obvious
Run:  python3 age_probe.py
"""
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Ordered by how many shows each contributes to the feed, so the biggest
# coverage wins get evaluated first.
SOURCES = [
    ("Revolution Hall (+ Show Bar)", "https://revolutionhall.com/", 101),
    ("Aladdin Theater",              "https://www.aladdin-theater.com/", 66),
    ("Holocene",                     "https://www.holocene.org/events/", 59),
    ("Jack London Revue",            "https://jacklondonrevue.com/calendar/", 51),
    ("Star Theater",                 "https://startheaterportland.com/", 50),
    ("Dante's",                      "https://www.danteslive.com/", 49),
    ("Wonder Ballroom",              "https://wonderballroom.com/events/", 49),
    ("Roseland / Mammoth NW",        "https://roselandpdx.com/events/", 41),
    ("Alberta Rose Theatre",         "https://albertarosetheatre.com/events/", 40),
    ("Mississippi / Polaris",        "https://mississippistudios.com/", 30),
    ("Mississippi Pizza",            "https://mississippipizza.com/calendar/", 31),
    ("Monqui (Crystal/McMenamins)",  "https://monqui.com/events/", 18),
]

# Two kinds of signal, kept separate on purpose.
#
# TEXT is the human-readable restriction as printed on the page. Bounded to
# avoid the false positives that make this kind of grep useless: "all ages"
# appears in plenty of marketing copy ("fun for all ages"), and a bare \d+\+
# would match capacities, prices and years.
AGE_TEXT = re.compile(
    r"(?<![$\d.])(?:21\s*(?:\+|and\s+over|&\s+over)|18\s*(?:\+|and\s+over)|"
    r"all\s*ages|minors?\s+(?:with|w/)\s*(?:a\s+)?(?:parent|guardian))",
    re.I)

# MARKUP is a dedicated field name. Far more valuable than the text match: it
# means the venue emits age as structured data, so a parser can read one
# element instead of pattern-matching prose that may change wording.
AGE_MARKUP = re.compile(
    r"(?:eventAgeRestriction|age[-_]?restriction|ageRestriction|"
    r"\"typicalAgeRange\"|data-age|class=\"[^\"]*age[^\"]*\")",
    re.I)


def probe(name, url, shows):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    except Exception as e:
        print(f"  {name:30s} FETCH FAILED: {type(e).__name__}: {e}")
        return
    if r.status_code != 200:
        print(f"  {name:30s} HTTP {r.status_code}")
        return
    h = r.text
    text_hits = AGE_TEXT.findall(h)
    markup_hits = AGE_MARKUP.findall(h)
    verdict = "STRUCTURED" if markup_hits else ("text only" if text_hits else "NOTHING")
    print(f"  {name:30s} {shows:4d} shows   text={len(text_hits):4d}  "
          f"markup={len(markup_hits):4d}   {verdict}")
    # Show the context so the selector is readable at a glance.
    for m in list(AGE_TEXT.finditer(h))[:3]:
        lo, hi = max(0, m.start() - 110), min(len(h), m.end() + 60)
        snippet = re.sub(r"\s+", " ", h[lo:hi]).strip()
        print(f"        ...{snippet}")
    if markup_hits:
        seen, uniq = set(), []
        for mh in markup_hits:
            k = mh.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(mh)
        print(f"        FIELD NAMES: {', '.join(uniq[:6])}")
    print()


def main():
    print("=" * 78)
    print("AGE FIELD PROBE -- what the venue pages already publish per show")
    print("=" * 78)
    print()
    total = sum(s for _, _, s in SOURCES)
    for name, url, shows in SOURCES:
        probe(name, url, shows)
    print("=" * 78)
    print(f"{total} shows across {len(SOURCES)} sources examined "
          f"(~{100*total/1446:.0f}% of the feed)")
    print("STRUCTURED = venue emits a dedicated age field; read it directly.")
    print("text only  = age is in prose; parseable but wording may drift.")
    print("NOTHING    = no per-show age here; needs another route.")
    print("=" * 78)


if __name__ == "__main__":
    main()
