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
    # "X present(s): The Real Show" -> the part after the colon.
    m2 = re.match(r"^.{2,60}?\spresents?\s*[:\-–—]\s*(.+)$", t, re.I)
    if m2:
        t = m2.group(1).strip()
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


def _http_get(url):
    import requests
    r = requests.get(url, timeout=20, headers={"User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")})
    r.raise_for_status()
    return r.content


def build(shows, make_slug, here, today=None, days=8, fetch=_http_get):
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
        img = None
        try:
            os.makedirs(os.path.join(here, "og", "tonight"), exist_ok=True)
            make_card(s, act, os.path.join(here, "og", "tonight", f"{day}.jpg"), fetch=fetch)
            img = f"{SITE}/og/tonight/{day}.jpg"
        except Exception as e:  # noqa: BLE001
            print(f"WARN tonight card {day}: {e}")
        out.append({"date": day, "act": act, "venue": s.get("venue", ""), "link": link, "image": img,
                    "message": f"TONIGHT: {act} at {s.get('venue', '')}! GO SEE LIVE "
                               + ("COMEDY!" if s.get("contentType") == "comedy" else "MUSIC!")})
    d = os.path.join(here, "og", "tonight")
    os.makedirs(d, exist_ok=True)
    keep = {f"{p['date']}.jpg" for p in out}
    for fn in os.listdir(d):  # old nights' pictures
        if fn.endswith(".jpg") and fn not in keep:
            os.remove(os.path.join(d, fn))
    with open(os.path.join(d, "posts.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": today.isoformat(), "posts": out}, f, indent=1, ensure_ascii=False)
    print(f"Wrote og/tonight/posts.json ({len(out)} nights)")
    return out


# ---------------------------------------------------------------------------
# Instagram picture (Nov 26 2026). Instagram needs an image, not a link: a
# 1080x1350 card per night -- TONIGHT banner, the show's poster, the act and
# venue, "link in bio". Written to og/tonight/<date>.jpg.
# ---------------------------------------------------------------------------
FOREST, RUST, CREAM, INK = (47, 69, 57), (181, 86, 43), (239, 226, 196), (74, 53, 38)


def _font(size):
    from PIL import ImageFont
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "assets", "AlfaSlabOne.ttf"),
              "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _sans(size):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return _font(size)


def _wrap(draw, text, font, width, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=font) > width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def make_card(show, act, path, fetch=None):
    import random
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    W, H = 1080, 1350
    im = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(im)
    # Torn forest banner with TONIGHT
    rnd = random.Random(show.get("date", ""))
    pts = [(0, 0), (W, 0), (W, 190)]
    x = W
    while x > 0:
        x -= rnd.randint(30, 70)
        pts.append((max(x, 0), 190 + rnd.randint(-22, 22)))
    pts.append((0, 190))
    d.polygon(pts, fill=FOREST)
    f = _font(150)
    tw = d.textlength("TONIGHT", font=f)
    d.text(((W - tw) / 2 + 6, 24 + 6), "TONIGHT", font=f, fill=RUST)
    d.text(((W - tw) / 2, 24), "TONIGHT", font=f, fill=CREAM)
    # Poster
    top, box_w, box_h = 250, 900, 720
    poster = None
    if fetch and show.get("imageUrl"):
        try:
            poster = ImageOps.exif_transpose(Image.open(BytesIO(fetch(show["imageUrl"])))).convert("RGB")
        except Exception:
            poster = None
    if poster:
        poster.thumbnail((box_w, box_h), Image.LANCZOS)
        px, py = (W - poster.width) // 2, top + (box_h - poster.height) // 2
        sh = Image.new("RGBA", (poster.width + 40, poster.height + 40), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((20, 20, poster.width + 20, poster.height + 20), fill=(40, 30, 20, 110))
        im.paste(sh.filter(ImageFilter.GaussianBlur(12)), (px - 8, py), sh.filter(ImageFilter.GaussianBlur(12)))
        im.paste(poster, (px, py))
        d.rectangle((px - 1, py - 1, px + poster.width, py + poster.height), outline=FOREST, width=4)
    else:
        d.rectangle((90, top, W - 90, top + box_h), outline=FOREST, width=6)
        fl = _font(110)
        for i, ln in enumerate(_wrap(d, act, fl, box_w - 80, 4)):
            lw = d.textlength(ln, font=fl)
            d.text(((W - lw) / 2, top + 120 + i * 130), ln, font=fl, fill=FOREST)
    # Act + venue
    y = top + box_h + 40
    fa = _font(76 if len(act) < 28 else 60)
    for ln in _wrap(d, act, fa, W - 120, 2):
        lw = d.textlength(ln, font=fa)
        d.text(((W - lw) / 2, y), ln, font=fa, fill=FOREST)
        y += fa.size + 10
    fv = _sans(40)
    v = f"{show.get('venue', '')}" + (f"  ·  {show['time']}" if show.get("time") else "")
    vw = d.textlength(v, font=fv)
    d.text(((W - vw) / 2, y + 8), v, font=fv, fill=INK)
    # Footer strip
    d.rectangle((0, H - 92, W, H), fill=RUST)
    fb = _sans(36)
    t = "RAINOROSHOWS.COM  ·  LINK IN BIO".replace("RAINORO", "RAINOR")
    bw = d.textlength(t, font=fb)
    d.text(((W - bw) / 2, H - 70), t, font=fb, fill=CREAM)
    # Grain
    noise = Image.effect_noise((W, H), 28).convert("L")
    im = Image.composite(im, Image.new("RGB", (W, H), (60, 45, 30)), noise.point(lambda p: 255 if p > 22 else 235))
    im.save(path, "JPEG", quality=88, optimize=True, progressive=True)
    return path
