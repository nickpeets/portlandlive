"""Daily "TONIGHT" Facebook post picker (Nov 25 2026).

Nick: the Page posts "TONIGHT: <act> at <venue>! GO SEE LIVE MUSIC!" every
day at noon, featuring the biggest music show of the night, and must never
miss a day. The nightly build calls build() and writes og/tonight/posts.json
(the next 8 nights). Supabase (supabase/schema-fb-tonight.sql) reads that file
at noon Pacific and posts today's entry to the Page through the Graph API.
"""
import datetime
import json
import os
import re

SITE = "https://rainorshows.com"

# Biggest rooms first. Matched as substrings of the venue name.
TIERS = [
    ["Moda Center", "Veterans Memorial Coliseum", "Keller Auditorium",
     "Arlene Schnitzer", "Providence Park", "Edgefield", "Theater of the Clouds"],
    ["Crystal Ballroom", "Roseland", "Revolution Hall", "Wonder Ballroom",
     "Aladdin", "McMenamins Grand Lodge"],
    ["Polaris Hall", "Mississippi Studios", "Doug Fir", "Alberta Rose",
     "Hawthorne Theatre", "Star Theater", "Dante", "Holocene", "Lola"],
]

# Not a band show: skip for the TONIGHT post.
SKIP = re.compile(r"""(?ix)\b(
    comedy|comedian|stand[\s-]?up|improv|open\s*mic|karaoke|burlesque|drag\b|
    nutcracker|ballet|dance\s+theat|in\s+concert|movie|screening|streaming\s+online|
    die\s+hard|home\s+alone|the\s+moth\b|wait\s+wait|live\s+wire|podcast|
    criminal\s+presents|an\s+evening\s+with\s+peter\s+sagal|lecture|talk\b|
    trivia|bingo|football|watch\s+party|vendor\s+market|yoga|workshop|
    show\s*bar|dj\s+set|silent\s+disco
)""")


# Still skipped for a huge comedy night: not stand-up.
HARD_SKIP = re.compile(r"(?i)\b(in\s+concert|cirque|circus|nutcracker|ballet|podcast|"
                       r"the\s+moth\b|wait\s+wait|live\s+wire|movie|screening|magic)\b")


def _tier(venue):
    for i, names in enumerate(TIERS):
        if any(n.lower() in (venue or "").lower() for n in names):
            return i
    return len(TIERS)


def headline(title):
    """'Saosin: 20 Years of Self-Titled (w/ Silent Planet, Like Moths To
    Flames, & Save Us)' -> 'Saosin w/ Silent Planet, Like Moths To Flames &
    Save Us'."""
    t = re.sub(r"\s+", " ", title or "").strip()
    openers = ""
    m = re.search(r"\((?:w/|with)\s*([^)]*)\)", t, re.I)
    if m:
        openers = m.group(1).strip()
        t = (t[:m.start()] + t[m.end():]).strip()
    elif re.search(r"\sw/\s", t):
        t, openers = re.split(r"\sw/\s", t, maxsplit=1)
    # Tour names / subtitles after ':' or a spaced dash.
    t = re.split(r"\s*:\s|\s+[-–—]\s+", t, maxsplit=1)[0].strip()
    t = re.sub(r"^.{2,40}?\spresents:?\s+", "", t, flags=re.I).strip()
    openers = re.sub(r",\s*&\s*", " & ", openers).strip(" ,")
    if openers.lower() == t.lower():
        openers = ""
    return f"{t} w/ {openers}" if openers else t


def pick(shows, day, recent_acts=()):
    cands = []
    for s in shows:
        if s.get("date") != day or s.get("outOfTown"):
            continue
        comedy = s.get("contentType") == "comedy"
        if s.get("contentType") == "other":
            continue
        # Comedy only when it's a huge act: a top-tier room (Moda, Coliseum,
        # Keller, Schnitz). Nick, Nov 25 2026. Music wins a tie.
        if comedy and _tier(s.get("venue")) > 0:
            continue
        blob = f"{s.get('title', '')} {s.get('venue', '')}"
        if SKIP.search(blob) and not comedy:
            continue
        if comedy and HARD_SKIP.search(blob):
            continue
        act = headline(s.get("title")).split(" w/ ")[0].lower()
        if act in recent_acts:
            continue
        cands.append((_tier(s.get("venue")), comedy, -(s.get("buzz") or 0), s.get("title", ""), s))
    if not cands:
        return None
    cands.sort(key=lambda c: c[:4])
    return cands[0][4]


def build(shows, make_slug, here, today=None, days=8):
    today = today or (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).date()
    out, recent = [], []
    for i in range(days):
        day = (today + datetime.timedelta(days=i)).isoformat()
        s = pick(shows, day, recent[-14:])
        if not s:
            continue
        act = headline(s["title"])
        recent.append(act.split(" w/ ")[0].lower())
        link = f"{SITE}/show/{make_slug(s)}/"
        out.append({"date": day, "act": act, "venue": s.get("venue", ""), "link": link,
                    "message": f"TONIGHT: {act} at {s.get('venue', '')}! GO SEE LIVE "
                               + ("COMEDY!" if s.get("contentType") == "comedy" else "MUSIC!")})
    d = os.path.join(here, "og", "tonight")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "posts.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": today.isoformat(), "posts": out}, f, indent=1, ensure_ascii=False)
    print(f"Wrote og/tonight/posts.json ({len(out)} nights)")
    return out
