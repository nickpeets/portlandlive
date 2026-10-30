"""Search-friendly static pages for Rain Or Shows (Oct 30 2026).

Why this exists: every clean-URL page used to be a 1 KB shell whose first
act was a script redirect to rainorshows.com/#/... Google follows script
redirects, and everything after the # is invisible to it, so all ~7,000 show
and venue pages folded into the homepage -- and the homepage itself has no
listings in its HTML (the app draws them from shows.json). Net effect: Google
had one thin page to rank, and "what's happening in portland tonight" never
found the site.

Now each page is a real page a crawler can read:
  /show/<slug>/       one show: date, time, venue, poster, tickets, other
                      shows that night, and schema.org Event markup (the
                      leaf page Google's events results need)
  /venue/<slug>/      one room: address + every upcoming show
  /venue/             every room we cover
  /show/tonight/      every show in Portland tonight     (rebuilt each run)
  /show/this-week/    the next seven days
  /show/this-weekend/ Friday through Sunday

People who arrive from Facebook/Instagram/etc. (or with ?ref=) still jump
straight into the app, same as before -- the page and the app show the same
show, so nobody is shown something different from what Google indexed.
Everyone else (Google visitors included) gets the page, with a big button
into the app for Who's Going, comments and Miracles.

Everything lands inside show/ and venue/, which the nightly workflow already
commits -- no workflow edit needed. Shared CSS lives at /show/assets/site.css
(not show/_assets: Jekyll drops folders that start with "_").
"""
import datetime
import html as _html
import json
import os
import re

try:
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
except Exception:          # pragma: no cover
    PT = None

SITE = "https://rainorshows.com"

CSS = """:root{--ink:#4a3526;--rust:#b5562b;--rust-d:#8f3f1f;--forest:#3d574a;--water:#3f6555;--cream:#f3ead7;--card:#fbf6ea;--line:#e2d5bb;--muted:#7a6553}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--cream);color:var(--ink);font:17px/1.5 Bitter,Georgia,serif}
a{color:var(--rust-d)}
.top{background:var(--water);color:var(--cream);padding:12px 16px;display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline}
.top .mark{font:22px Bevan,Georgia,serif;color:var(--cream);text-decoration:none;letter-spacing:.5px}
.top nav{display:flex;flex-wrap:wrap;gap:4px 14px;font:500 14px Oswald,Arial,sans-serif;text-transform:uppercase;letter-spacing:.6px}
.top nav a{color:var(--cream);text-decoration:none;opacity:.85}
.top nav a[aria-current]{opacity:1;border-bottom:2px solid var(--cream)}
main{max-width:760px;margin:0 auto;padding:20px 16px 40px}
h1{font:28px/1.2 Bevan,Georgia,serif;color:var(--forest);margin:4px 0 6px}
h2{font:600 15px Oswald,Arial,sans-serif;text-transform:uppercase;letter-spacing:.8px;color:var(--rust);margin:26px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.lede{color:var(--muted);margin-bottom:6px}
.stale{background:#fff3cd;border:1px solid #e0c97a;padding:8px 12px;border-radius:6px;margin:10px 0;font-size:15px}
.cta{display:inline-block;background:var(--rust);color:#fff;text-decoration:none;font:600 15px Oswald,Arial,sans-serif;text-transform:uppercase;letter-spacing:.6px;padding:10px 16px;border-radius:6px;margin:10px 8px 0 0}
.cta.alt{background:var(--forest)}
ul.shows{list-style:none}
ul.shows li{display:grid;grid-template-columns:76px 1fr;gap:2px 12px;padding:10px 0;border-bottom:1px dashed var(--line)}
ul.shows .t{font:600 14px Oswald,Arial,sans-serif;color:var(--rust);padding-top:3px;white-space:nowrap}
ul.shows .n{font-weight:600;color:var(--ink);text-decoration:none}
ul.shows .n:hover{text-decoration:underline}
ul.shows .v{grid-column:2;font-size:15px;color:var(--muted)}
ul.shows .v a{color:var(--muted)}
.chip{display:inline-block;font:500 11px Oswald,Arial,sans-serif;text-transform:uppercase;letter-spacing:.5px;border:1px solid var(--line);border-radius:10px;padding:0 7px;margin-left:6px;vertical-align:2px;color:var(--muted)}
.show{display:grid;gap:18px}
.show img{width:100%;max-width:420px;border-radius:8px;display:block}
.facts{font-size:17px}
.facts div{margin:2px 0}
.venues{columns:2 220px;list-style:none}
.venues li{break-inside:avoid;padding:3px 0}
.venues small{color:var(--muted)}
footer{max-width:760px;margin:0 auto;padding:20px 16px 40px;font-size:14px;color:var(--muted);border-top:1px solid var(--line)}
footer a{color:var(--muted)}
@media(min-width:640px){.show{grid-template-columns:minmax(0,320px) 1fr}}
"""

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m?\.?", re.I)
_ADDR_RE = re.compile(r"^(?P<street>.+?),\s*(?P<city>[^,]+?),\s*(?P<state>[A-Z]{2})\b\s*(?P<zip>\d{5})?")


def esc(x):
    return _html.escape(x or "", quote=True)


def today_pt():
    if PT:
        return datetime.datetime.now(PT).date()
    return datetime.date.today()


def minutes(t):
    m = _TIME_RE.match(t or "")
    if not m:
        if (t or "").strip().lower() == "noon":
            return 12 * 60
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return h * 60 + int(m.group(2) or 0)


def iso_start(s):
    """schema.org startDate with Pacific offset; date only when no time."""
    d = s.get("date") or ""
    try:
        day = datetime.date.fromisoformat(d)
    except Exception:
        return None
    m = minutes(s.get("time"))
    if m is None:
        return d
    dt = datetime.datetime(day.year, day.month, day.day, m // 60, m % 60, tzinfo=PT)
    return dt.isoformat()


def postal(address, venue):
    m = _ADDR_RE.match(address or "")
    if not m:
        return {"@type": "PostalAddress", "streetAddress": address or venue,
                "addressLocality": "Portland", "addressRegion": "OR", "addressCountry": "US"}
    a = {"@type": "PostalAddress", "streetAddress": m["street"].strip(),
         "addressLocality": m["city"].strip(), "addressRegion": m["state"], "addressCountry": "US"}
    if m["zip"]:
        a["postalCode"] = m["zip"]
    return a


def nice_date(d, fmt="%A, %B %-d"):
    try:
        return datetime.date.fromisoformat(d).strftime(fmt)
    except Exception:
        return d or ""


def sort_key(s):
    m = minutes(s.get("time"))
    return (s.get("date") or "", 9999 if m is None else m, (s.get("venue") or "").lower(), s.get("title") or "")


def ticket_link(s):
    """(url, rel). The affiliate link only ever rides the Tickets button."""
    if (s.get("affiliateUrl") or "").startswith("http"):
        return s["affiliateUrl"], "sponsored noopener"
    for k in ("ticketUrl", "venueUrl"):
        if (s.get(k) or "").startswith("http"):
            return s[k], "noopener"
    return None, None


class Pages:
    def __init__(self, show_dir, venue_dir, make_slug, venue_slug, clean_title):
        self.show_dir, self.venue_dir = show_dir, venue_dir
        self.make_slug, self.venue_slug, self.clean_title = make_slug, venue_slug, clean_title
        self.today = today_pt()

    # ---- shared bits -------------------------------------------------
    def head(self, title, desc, canonical, image, app_hash=None, jsonld=None, robots=None, large=False):
        h = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
             f"<title>{esc(title)}</title>",
             f"<meta name=\"description\" content=\"{esc(desc)}\">",
             f"<link rel=\"canonical\" href=\"{esc(canonical)}\">"]
        if robots:
            h.append(f"<meta name=\"robots\" content=\"{robots}\">")
        h += ["<meta property=\"og:type\" content=\"website\">",
              "<meta property=\"og:site_name\" content=\"Rain Or Shows\">",
              f"<meta property=\"og:title\" content=\"{esc(title)}\">",
              f"<meta property=\"og:description\" content=\"{esc(desc)}\">",
              f"<meta property=\"og:image\" content=\"{esc(image)}\">"]
        if "/og/" in (image or ""):
            h.append("<meta property=\"og:image:width\" content=\"1200\"><meta property=\"og:image:height\" content=\"630\">")
        h += [f"<meta property=\"og:url\" content=\"{esc(canonical)}\">",
              f"<meta name=\"twitter:card\" content=\"{'summary_large_image' if large else 'summary'}\">",
              "<link rel=\"icon\" type=\"image/png\" sizes=\"32x32\" href=\"/favicon-32.png\">",
              "<link rel=\"apple-touch-icon\" href=\"/apple-touch-icon.png\">",
              "<meta name=\"theme-color\" content=\"#3f6555\">",
              "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>",
              "<link href=\"https://fonts.googleapis.com/css2?family=Bevan&family=Bitter:wght@400;600&family=Oswald:wght@500;600&display=swap\" rel=\"stylesheet\">",
              "<link rel=\"stylesheet\" href=\"/show/assets/site.css\">"]
        if app_hash:
            # Social visitors go straight into the app, as before. Search
            # visitors and crawlers stay on this page (same show, same facts).
            h.append("<script>(function(){var q=location.search,r=document.referrer||'';"
                     "if(/[?&]ref=/.test(q)||/^https?:\\/\\/([^\\/]*\\.)?(facebook|fb|instagram|messenger|threads|twitter|x|t|reddit|bsky|linkedin)\\.(com|co|net|me|app)(\\/|$)/i.test(r))"
                     f"location.replace({json.dumps(SITE + '/')}+q+{json.dumps(app_hash)});}})();</script>")
        if jsonld:
            h.append("<script type=\"application/ld+json\">"
                     + json.dumps(jsonld, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
                     + "</script>")
        h.append("</head><body>")
        return "".join(h)

    def topbar(self, current=None):
        links = [("tonight", "/show/tonight/", "Tonight"), ("week", "/show/this-week/", "This week"),
                 ("weekend", "/show/this-weekend/", "This weekend"), ("venues", "/venue/", "Venues")]
        nav = "".join(f"<a href=\"{u}\"{' aria-current=\"page\"' if k == current else ''}>{t}</a>" for k, u, t in links)
        return f"<header class=\"top\"><a class=\"mark\" href=\"/\">Rain Or Shows</a><nav>{nav}</nav></header>"

    def footer(self):
        return ("<footer><p>Rain Or Shows lists every night of live music in Portland, OR &mdash; big rooms, bars "
                "and basements &mdash; pulled every morning from the venues&rsquo; own calendars. Always confirm with "
                "the venue before heading out.</p><p style=\"margin-top:8px\"><a href=\"/\">Open the full listings</a> &middot; "
                "<a href=\"/show/tonight/\">Tonight</a> &middot; <a href=\"/show/this-week/\">This week</a> &middot; "
                "<a href=\"/show/this-weekend/\">This weekend</a> &middot; <a href=\"/venue/\">Venues</a> &middot; "
                "<a href=\"/#/submit\">Submit a show</a></p></footer>"
                # Keep ?ref=... on app links so sign-up tracking still works.
                "<script>(function(){var q=location.search;if(!q)return;document.querySelectorAll('a[data-app]')"
                ".forEach(function(a){var h=a.getAttribute('href'),i=h.indexOf('#');a.setAttribute('href',h.slice(0,i<0?h.length:i)+q+(i<0?'':h.slice(i)));});})();</script>"
                "</body></html>")

    def title_of(self, s):
        return self.clean_title(s.get("title") or "")

    def li(self, s, show_date=False, with_venue=True):
        slug = self.make_slug(s)
        t = s.get("time") or ""
        if show_date:
            t = nice_date(s.get("date"), "%a %-m/%-d") + (f"<br>{esc(t)}" if t else "")
        else:
            t = esc(t) or "&mdash;"
        chips = ""
        if s.get("contentType") == "comedy":
            chips += "<span class=\"chip\">Comedy</span>"
        if s.get("age") == "all-ages":
            chips += "<span class=\"chip\">All ages</span>"
        elif s.get("age"):
            chips += f"<span class=\"chip\">{esc(s['age'])}</span>"
        if s.get("price"):
            chips += f"<span class=\"chip\">{esc(s['price'])}</span>"
        if s.get("soldOut"):
            chips += "<span class=\"chip\">Sold out</span>"
        v = ""
        if with_venue:
            vs = self.venue_slug(s.get("venue") or "")
            vn = esc(s.get("venue"))
            v = f"<a href=\"/venue/{vs}/\">{vn}</a>" if vs else vn
            if s.get("neighborhood"):
                v += f" &middot; {esc(s['neighborhood'])}"
        return (f"<li><span class=\"t\">{t}</span><span><a class=\"n\" href=\"/show/{slug}/\">{esc(self.title_of(s))}</a>{chips}</span>"
                + (f"<span class=\"v\">{v}</span>" if v else "") + "</li>")

    def write(self, rel, html):
        path = os.path.join(self.show_dir if rel.startswith("show/") else self.venue_dir,
                            *rel.split("/")[1:], "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    def write_css(self):
        os.makedirs(os.path.join(self.show_dir, "assets"), exist_ok=True)
        with open(os.path.join(self.show_dir, "assets", "site.css"), "w", encoding="utf-8") as f:
            f.write(CSS)

    # ---- one show ----------------------------------------------------
    def event_ld(self, s, slug, image):
        ev = {"@context": "https://schema.org",
              "@type": "ComedyEvent" if s.get("contentType") == "comedy" else "MusicEvent",
              "name": self.title_of(s),
              "startDate": iso_start(s),
              "eventStatus": "https://schema.org/EventScheduled",
              "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
              "location": {"@type": "Place", "name": s.get("venue") or "",
                           "address": postal(s.get("address"), s.get("venue"))},
              "url": f"{SITE}/show/{slug}/",
              "description": f"{self.title_of(s)} at {s.get('venue','')} in Portland, OR on "
                             f"{nice_date(s.get('date'))}" + (f" at {s['time']}" if s.get("time") else "") + "."}
        if image and not image.endswith("/logo_share.png"):
            ev["image"] = [image]
        url, _ = ticket_link(s)
        if url:
            offer = {"@type": "Offer", "url": url,
                     "availability": "https://schema.org/SoldOut" if s.get("soldOut") else "https://schema.org/InStock"}
            p = s.get("price") or ""
            if p.strip().lower() == "free":
                offer.update(price="0", priceCurrency="USD")
            else:
                m = re.search(r"\$(\d+(?:\.\d\d)?)", p)
                if m:
                    offer.update(price=m.group(1), priceCurrency="USD")
            ev["offers"] = offer
        return ev

    def show_page(self, s, image):
        slug = self.make_slug(s)
        title = self.title_of(s)
        venue = s.get("venue") or ""
        upcoming = (s.get("date") or "") >= self.today.isoformat()
        when = nice_date(s.get("date"), "%A, %B %-d, %Y")
        desc = f"{title} at {venue}, Portland, OR \u2014 {when}" + (f", {s['time']}" if s.get("time") else "")
        if s.get("price"):
            desc += f". {s['price']}"
        if s.get("age"):
            desc += ". All ages" if s["age"] == "all-ages" else f". {s['age']}"
        desc += "."
        head = self.head(f"{title} at {venue} \u2014 {nice_date(s.get('date'), '%b %-d')} | Rain Or Shows",
                         desc, f"{SITE}/show/{slug}/", image, app_hash=f"#/show/{slug}",
                         jsonld=self.event_ld(s, slug, image) if upcoming and iso_start(s) else None,
                         large=image != f"{SITE}/logo_share.png")
        vs = self.venue_slug(venue)
        facts = [f"<div><strong>{esc(when)}</strong>" + (f" &middot; {esc(s['time'])}" if s.get("time") else "") + "</div>",
                 f"<div><a href=\"/venue/{vs}/\">{esc(venue)}</a>"
                 + (f" &middot; {esc(s['neighborhood'])}" if s.get("neighborhood") else "") + "</div>"]
        if s.get("address"):
            facts.append(f"<div>{esc(s['address'])}</div>")
        extra = []
        if s.get("contentType") == "comedy":
            extra.append("Comedy")
        if s.get("age"):
            extra.append("All ages" if s["age"] == "all-ages" else s["age"])
        if s.get("price"):
            extra.append(s["price"])
        if s.get("soldOut"):
            extra.append("Sold out")
        if extra:
            facts.append(f"<div>{esc(' · '.join(extra))}</div>")
        btns = ""
        url, rel = ticket_link(s)
        if upcoming and url:
            btns += f"<a class=\"cta\" href=\"{esc(url)}\" rel=\"{rel}\">Tickets &amp; info</a>"
        btns += (f"<a class=\"cta alt\" data-app href=\"/#/show/{slug}\">"
                 + ("Who&rsquo;s going &amp; comments" if upcoming else "Photos &amp; who was there") + "</a>")
        img = (f"<img src=\"{esc(image)}\" alt=\"{esc(title)} poster\" loading=\"lazy\">"
               if image and not image.endswith("/logo_share.png") else "")
        if not upcoming:
            facts.insert(0, "<div class=\"lede\">This show has already happened.</div>")
        body = (f"{self.topbar()}<main><div class=\"show\"><div>{img}</div><div>"
                f"<h1>{esc(title)}</h1><div class=\"facts\">{''.join(facts)}</div>{btns}</div></div>")
        # Links out rather than a list of the night's other shows: a list
        # would rewrite thousands of pages every time a night's lineup moved,
        # and git would keep every version. These links never change.
        more = [f"<a href=\"/venue/{vs}/\">More at {esc(venue)}</a>"]
        if upcoming:
            d = s.get("date") or ""
            if d == self.today.isoformat():
                more.insert(0, "<a href=\"/show/tonight/\">Everything in Portland tonight</a>")
            more.append("<a href=\"/show/this-week/\">This week</a>")
            more.append("<a href=\"/show/this-weekend/\">This weekend</a>")
        body += "<p style=\"margin-top:22px\">" + " &middot; ".join(more) + "</p>"
        body += "</main>"
        self.write(f"show/{slug}", head + body + self.footer())

    # ---- one venue ---------------------------------------------------
    def venue_page(self, v, upcoming, image):
        name = v.get("name") or ""
        vs = self.venue_slug(name)
        n = len(upcoming)
        hood = v.get("neighborhood") or ""
        addr = v.get("address") or next((s.get("address") for s in upcoming if s.get("address")), "")
        desc = (f"{n} upcoming show{'s' if n != 1 else ''} at {name}" if n else f"Shows at {name}")
        desc += (f", {addr}" if addr else "") + (f" ({hood})" if hood else "")
        desc += ". Dates, times, ages and tickets, updated every morning."
        ld = {"@context": "https://schema.org", "@type": "MusicVenue", "name": name,
              "url": f"{SITE}/venue/{vs}/", "address": postal(addr, name)}
        head = self.head(f"{name} Portland \u2014 Upcoming Shows & Calendar | Rain Or Shows", desc,
                         f"{SITE}/venue/{vs}/", image, app_hash=f"#/venue/{vs}", jsonld=ld)
        body = (f"{self.topbar('venues')}<main><h1>{esc(name)}</h1>"
                f"<p class=\"lede\">{esc(addr)}{' &middot; ' + esc(hood) if hood else ''}</p>"
                f"<a class=\"cta alt\" data-app href=\"/#/venue/{vs}\">Open in Rain Or Shows</a>")
        if upcoming:
            body += f"<h2>Upcoming shows at {esc(name)}</h2><ul class=\"shows\">"
            body += "".join(self.li(s, show_date=True, with_venue=False) for s in upcoming[:150]) + "</ul>"
        else:
            body += "<p style=\"margin-top:16px\">Nothing on the calendar right now. Check back soon.</p>"
        body += "</main>"
        self.write(f"venue/{vs}", head + body + self.footer())

    def venue_index(self, venues, counts):
        rows = sorted(venues, key=lambda v: re.sub(r"^the\s+", "", (v.get("name") or "").lower()))
        lis = "".join(
            f"<li><a href=\"/venue/{self.venue_slug(v['name'])}/\">{esc(v['name'])}</a>"
            f" <small>{esc(v.get('neighborhood') or '')}{' · ' + str(counts.get(v['name'], 0)) + ' upcoming' if counts.get(v['name']) else ''}</small></li>"
            for v in rows if v.get("name") and self.venue_slug(v["name"]))
        desc = (f"{len(rows)} Portland-area live music venues and comedy rooms, from the Crystal Ballroom to "
                "neighborhood bars, each with its upcoming show calendar.")
        head = self.head("Portland Live Music Venues \u2014 Every Room's Calendar | Rain Or Shows", desc,
                         f"{SITE}/venue/", f"{SITE}/logo_share.png")
        body = (f"{self.topbar('venues')}<main><h1>Portland music venues</h1><p class=\"lede\">{esc(desc)}</p>"
                f"<ul class=\"venues\">{lis}</ul></main>")
        self.write("venue/", head + body + self.footer())

    # ---- hubs --------------------------------------------------------
    def hub(self, key, path, title, h1, desc, rows, by_day, stamp_date=None):
        head = self.head(title, desc, f"{SITE}{path}", f"{SITE}/logo_share.png")
        body = f"{self.topbar(key)}<main><h1>{esc(h1)}</h1><p class=\"lede\">{esc(desc)}</p>"
        if stamp_date:
            # If a build is ever skipped, say so instead of quietly showing yesterday.
            body += (f"<div class=\"stale\" id=\"stale\" hidden>This list is from {esc(nice_date(stamp_date))}. "
                     "<a href=\"/\">See today&rsquo;s shows</a>.</div>"
                     "<script>(function(){try{var d=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles'}).format(new Date());"
                     f"if(d!=={json.dumps(stamp_date)})document.getElementById('stale').hidden=false;}}catch(e){{}}}})();</script>")
        body += "<a class=\"cta alt\" data-app href=\"/\">Open the full listings</a>"
        if not rows:
            body += "<p style=\"margin-top:16px\">No shows listed yet. Check the full listings.</p>"
        elif by_day:
            day = None
            for s in rows:
                if s.get("date") != day:
                    if day is not None:
                        body += "</ul>"
                    day = s.get("date")
                    label = "Tonight" if day == self.today.isoformat() else nice_date(day)
                    n = sum(1 for r in rows if r.get("date") == day)
                    body += f"<h2>{esc(label)} &middot; {n} show{'s' if n != 1 else ''}</h2><ul class=\"shows\">"
                body += self.li(s)
            body += "</ul>"
        else:
            body += "<ul class=\"shows\" style=\"margin-top:12px\">" + "".join(self.li(s) for s in rows) + "</ul>"
        body += "</main>"
        self.write(path.strip("/"), head + body + self.footer())

    def hubs(self, shows):
        local = sorted((s for s in shows if not s.get("outOfTown")), key=sort_key)
        t = self.today
        tiso = t.isoformat()
        tonight = [s for s in local if s.get("date") == tiso]
        week_end = (t + datetime.timedelta(days=6)).isoformat()
        week = [s for s in local if tiso <= (s.get("date") or "") <= week_end]
        # Weekend: Friday-Sunday. On Fri/Sat/Sun it's "today through Sunday".
        wd = t.weekday()  # Mon=0
        start = t if wd >= 4 else t + datetime.timedelta(days=4 - wd)
        sun = start + datetime.timedelta(days=6 - start.weekday())
        weekend = [s for s in local if start.isoformat() <= (s.get("date") or "") <= sun.isoformat()]
        rooms = sorted({s.get("venue") for s in tonight if s.get("venue")},
                       key=lambda v: -sum(1 for s in tonight if s.get("venue") == v))
        sample = ", ".join(rooms[:4])
        day = t.strftime("%A, %B %-d")
        self.hub("tonight", "/show/tonight/",
                 f"Live Music in Portland Tonight \u2014 {t.strftime('%a, %b %-d')} | Rain Or Shows",
                 "What\u2019s happening in Portland tonight",
                 f"{len(tonight)} shows in Portland, OR tonight ({day}): concerts, bar gigs and comedy"
                 + (f" at {sample} and more" if sample else "") + ". Updated every morning.",
                 tonight, by_day=False, stamp_date=tiso)
        self.hub("week", "/show/this-week/",
                 f"Portland Concerts This Week \u2014 {t.strftime('%b %-d')}\u2013"
                 f"{(t + datetime.timedelta(days=6)).strftime('%b %-d')} | Rain Or Shows",
                 "Portland live music this week",
                 f"{len(week)} concerts, shows and comedy nights in Portland, OR over the next seven days, "
                 "night by night. Updated every morning.", week, by_day=True, stamp_date=tiso)
        self.hub("weekend", "/show/this-weekend/",
                 f"Things to Do in Portland This Weekend: Live Music & Comedy \u2014 "
                 f"{start.strftime('%b %-d')}\u2013{sun.strftime('%b %-d')} | Rain Or Shows",
                 "Portland live music this weekend",
                 f"{len(weekend)} shows in Portland, OR from {start.strftime('%A, %B %-d')} through "
                 f"{sun.strftime('%A, %B %-d')}. Updated every morning.", weekend, by_day=True, stamp_date=tiso)
        return len(tonight), len(week), len(weekend)
