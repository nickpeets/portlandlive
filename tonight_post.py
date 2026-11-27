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


def pick(shows, day, recent_acts=(), need_image=False):
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
        if need_image and not s.get("imageUrl"):
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
    out, recent, recent_ig = [], [], []

    def msg(s, act):
        return (f"TONIGHT: {act} at {s.get('venue', '')}! GO SEE LIVE "
                + ("COMEDY!" if s.get("contentType") == "comedy" else "MUSIC!"))

    for i in range(days):
        day = (today + datetime.timedelta(days=i)).isoformat()
        s = pick(shows, day, recent[-14:] + recent_ig[-14:]) or pick(shows, day, recent[-14:])
        if not s:
            continue
        act = headline(s["title"])
        fb_key = act.split(" w/ ")[0].lower()
        recent.append(fb_key)
        entry = {"date": day, "act": act, "venue": s.get("venue", ""),
                 "link": f"{SITE}/show/{make_slug(s)}/", "message": msg(s, act), "image": None}
        # Instagram features a DIFFERENT show than Facebook (Nick, Nov 26
        # 2026): the next-biggest show that night with a poster.
        g = (pick(shows, day, recent_ig[-14:] + recent[-14:], need_image=True)
             or pick(shows, day, recent_ig[-14:] + recent[-14:]))
        if g:
            ig_act = headline(g["title"])
            recent_ig.append(ig_act.split(" w/ ")[0].lower())
            entry.update(ig_act=ig_act, ig_venue=g.get("venue", ""),
                         ig_link=f"{SITE}/show/{make_slug(g)}/", ig_message=msg(g, ig_act))
            try:
                os.makedirs(os.path.join(here, "og", "tonight"), exist_ok=True)
                make_card(g, ig_act, os.path.join(here, "og", "tonight", f"{day}.jpg"), fetch=fetch)
                entry["image"] = f"{SITE}/og/tonight/{day}.jpg"
            except Exception as e:  # noqa: BLE001
                print(f"WARN tonight card {day}: {e}")
        out.append(entry)
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


def _logo(size, color):
    from PIL import Image
    here = os.path.dirname(os.path.abspath(__file__))
    src = Image.open(os.path.join(here, "logo_trans.png")).convert("RGBA")
    src.thumbnail((size, size), Image.LANCZOS)
    out = Image.new("RGBA", src.size, color + (0,))
    out.putalpha(src.getchannel("A"))
    return out


def make_card(show, act, path, fetch=None):
    """1080x1350 Instagram picture, v3 (Nick, Nov 27 2026: too much empty
    space, odd torn border, no logo). Blurred poster fills the background;
    logo + name and the date up top, TONIGHT, the poster as big as the space
    allows, act and venue, GO SEE LIVE MUSIC! / link-in-bio strip; grain."""
    import datetime as _dt
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    W, H = 1080, 1350
    poster = None
    if fetch and show.get("imageUrl"):
        try:
            poster = ImageOps.exif_transpose(Image.open(BytesIO(fetch(show["imageUrl"])))).convert("RGB")
        except Exception:
            poster = None
    if poster:
        bg = ImageOps.fit(poster, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
        im = ImageEnhance.Brightness(bg).enhance(0.38)
    else:
        im = Image.new("RGB", (W, H), FOREST)
        big = _logo(620, (62, 88, 74))  # no poster: big faint logo fills the middle
        im.paste(big, ((W - big.width) // 2, (H - big.height) // 2 - 20), big)
    d = ImageDraw.Draw(im)
    AMBER = (233, 160, 102)

    # Top bar: logo + RAIN OR SHOWS, date pill on the right.
    lg = _logo(92, CREAM)
    im.paste(lg, (44, 34), lg)
    fn = _font(40)
    d.text((150, 58), "RAIN OR SHOWS", font=fn, fill=CREAM)
    try:
        ds = _dt.date.fromisoformat(show.get("date", "")).strftime("%a %b %-d").upper()
    except ValueError:
        ds = ""
    if ds:
        fd = _sans(30)
        dw = d.textlength(ds, font=fd)
        d.rounded_rectangle((W - 44 - dw - 36, 52, W - 44, 104), radius=26, fill=RUST)
        d.text((W - 44 - dw - 18, 61), ds, font=fd, fill=CREAM)

    # Fixed pieces, measured first.
    ft = _font(158)
    fv = _sans(40)
    head, _, opens = act.partition(" w/ ")
    fa = _font(76 if len(head) < 22 else 62 if len(head) < 32 else 52)
    act_lines = _wrap(d, head, fa, W - 100, 2)
    fo = _font(40)
    open_lines = _wrap(d, "with " + opens, fo, W - 120, 1) if opens else []
    v = f"{show.get('venue', '')}" + (f"  \u00b7  {show['time']}" if show.get("time") else "")
    FOOT = 118
    top, t_h = 140, 150
    text_h = len(act_lines) * (fa.size + 6) + len(open_lines) * (fo.size + 8) + 56
    avail = H - FOOT - top - t_h - 30 - 34 - text_h - 30  # poster space
    if poster:
        pw = W  # full bleed for wide posters
        ph = int(poster.height * pw / poster.width)
        if ph < avail:  # wide poster: trim the sides a little to fill more height
            ph = min(avail, int(ph * 1.3))
            poster = ImageOps.fit(poster, (pw, ph), Image.LANCZOS, centering=(0.5, 0.4))
        if ph > avail:
            ph = avail
            pw = int(poster.width * ph / poster.height)
        poster = poster.resize((pw, ph), Image.LANCZOS)
    else:
        pw, ph = 0, 0
    block = t_h + 30 + ph + 34 + text_h
    y = top + max(0, (H - FOOT - top - block - 20) // 2)

    tw = d.textlength("TONIGHT", font=ft)
    d.text(((W - tw) / 2 + 8, y + 8), "TONIGHT", font=ft, fill=RUST)
    d.text(((W - tw) / 2, y), "TONIGHT", font=ft, fill=CREAM)
    y += t_h + 30
    if poster:
        px = (W - pw) // 2
        if pw < W:
            sh = Image.new("L", (pw + 60, ph + 60), 0)
            ImageDraw.Draw(sh).rectangle((30, 30, pw + 30, ph + 30), fill=190)
            im.paste((0, 0, 0), (px - 20, y - 16), sh.filter(ImageFilter.GaussianBlur(16)))
        im.paste(poster, (px, y))
        if pw < W:
            d.rectangle((px - 5, y - 5, px + pw + 4, y + ph + 4), outline=CREAM, width=5)
        else:
            d.line((0, y - 3, W, y - 3), fill=CREAM, width=5)
            d.line((0, y + ph + 2, W, y + ph + 2), fill=CREAM, width=5)
        y += ph + 34
    for ln in act_lines:
        lw = d.textlength(ln, font=fa)
        d.text(((W - lw) / 2 + 4, y + 4), ln, font=fa, fill=(0, 0, 0))
        d.text(((W - lw) / 2, y), ln, font=fa, fill=CREAM)
        y += fa.size + 6
    for ln in open_lines:
        lw = d.textlength(ln, font=fo)
        d.text(((W - lw) / 2, y + 2), ln, font=fo, fill=CREAM)
        y += fo.size + 8
    vw = d.textlength(v, font=fv)
    d.text(((W - vw) / 2, y + 8), v, font=fv, fill=AMBER)

    # Footer: tagline + link in bio.
    d.rectangle((0, H - FOOT, W, H), fill=RUST)
    fg = _font(52)
    g = "GO SEE LIVE MUSIC!"
    gw = d.textlength(g, font=fg)
    d.text(((W - gw) / 2 + 3, H - FOOT + 14 + 3), g, font=fg, fill=(120, 50, 22))
    d.text(((W - gw) / 2, H - FOOT + 14), g, font=fg, fill=CREAM)
    fb = _sans(24)
    t = "RAINORSHOWS.COM  \u00b7  LINK IN BIO"
    bw = d.textlength(t, font=fb)
    d.text(((W - bw) / 2, H - FOOT + 78), t, font=fb, fill=(250, 226, 205))

    # Grain
    noise = Image.effect_noise((W, H), 40).convert("L").point(lambda p: 255 if p > 70 else 0)
    im = Image.composite(im, ImageEnhance.Brightness(im).enhance(0.86), noise)
    im.save(path, "JPEG", quality=88, optimize=True, progressive=True)
    return path
