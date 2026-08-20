# =============================================================================
# DROP-IN REPLACEMENT for parse_laurelthirst in scrape_venues.py
#
# STATUS: NOT RUN LIVE. Authored against ground truth pulled from the live site
# through a browser session; the Python itself has never executed against
# laurelthirst.com. See HANDOFF-laurelthirst.md for the verified/unverified
# split before you trust any of this.
#
# WHAT CHANGED AND WHY
# --------------------
# The old parser read the WordPress CPT route /wp-json/wp/v2/ajde_events, which
# lists event POSTS. Laurelthirst runs residencies, and EventON stores every
# occurrence of a residency inside ONE post. A post-shaped reader therefore
# cannot see repeats, no matter how many pages it walks:
#
#   1. RECURRENCE COLLAPSE - itemprop="startDate" on an event page exposes only
#      the FIRST occurrence. 34 of 98 upcoming occurrences are repeat instances.
#   2. WHOLE-SERIES DISCARD - the range filter tested that single first date, so
#      a series whose instance 0 is past was dropped entirely, taking its live
#      future instances with it (Freak Mountain Ramblers instance 0 = 2026-08-02,
#      which threw away real 8/23 and 8/30 shows).
#   3. WASTED BUDGET - orderby=date is PUBLISH date, so most of the 200-post cap
#      was spent on already-happened events.
#
# This version reads OCCURRENCES from EventON's own calendar endpoint. One
# request per month instead of one request per event post: ~6 requests replacing
# ~200, and every recurrence instance arrives as its own row.
# =============================================================================

# ---- Laurelthirst Public House (laurelthirst.com) ----------------------------
# WordPress + EventON 5.0.13. The calendar is driven by a POST endpoint,
# ?evo-ajax=eventon_get_events, which returns {"status","json","html",...}.
# We read the "html" payload: it contains one .eventon_list_event block per
# OCCURRENCE, each carrying data-time="<start_epoch>-<end_epoch>".
#
# Two field traps, both confirmed against the live site:
#
#   * Use data-time, NOT the "json" array's event_start_unix. event_start_unix
#     is correct only for non-repeating events; for recurrence instances it is
#     wrong (Lewi Longmire instance 2 reports 2026-08-21T01:00 where the real
#     show is 2026-08-20 18:00 - off by 7h and a calendar day). data-time is a
#     true epoch and matches the per-occurrence schema.org startDate every time,
#     including across the 2026-11-01 DST boundary.
#
#   * shortcode[fixed_month] is 1-BASED-PLUS-ONE: fixed_month=9 renders August,
#     13 renders December, 14 rolls over to January of the next year. So
#     fixed_month = calendar_month + 1 + 12*(year - fixed_year).
#     We do not rely on this for correctness - every occurrence is filtered by
#     its own epoch, so a month-index drift can only cost coverage, never
#     produce a wrong date. We also fetch one month past the horizon as margin.
LAUREL_BASE = "https://laurelthirst.com"
LAUREL_CAL = LAUREL_BASE + "/music-calendar/"
LAUREL_AJAX = LAUREL_BASE + "/?evo-ajax=eventon_get_events"
LAUREL_HORIZON_DAYS = 120      # matches the other parsers; scrape() then clips
                               # everything to the global HORIZON_DAYS (90)
LAUREL_PAUSE = 0.6             # seconds between month requests - be a good guest

# The calendar page ships both nonces inline in the evo_general_params object.
# They map to the POST fields CROSSED OVER: params "n" -> field "nonce", and
# params "nonce" -> field "nonceX". Sending them straight through fails with
# {"status":"bad","msg":"Nonce validation failed"}.
_LAUREL_N = re.compile(r'"n"\s*:\s*"([0-9a-zA-Z]+)"')
_LAUREL_NONCE = re.compile(r'"nonce"\s*:\s*"([0-9a-zA-Z]+)"')


def _laurel_pacific():
    """America/Los_Angeles, or a fixed -08:00 if the tz database is missing.

    The fallback is deliberately crude: it can be an hour off during PDT, but a
    missing tzdata must not take the whole venue to zero."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=-8))


def _laurel_nonces(html):
    """Pull (nonce, nonceX) out of the calendar page's evo_general_params blob.

    Scoped to the window right after the variable name so a stray "n": elsewhere
    in 330KB of page source cannot poison it."""
    i = html.find("evo_general_params")
    window = html[i:i + 3000] if i >= 0 else html
    n = _LAUREL_N.search(window)
    nonce = _LAUREL_NONCE.search(window)
    if not (n and nonce):
        return None
    return n.group(1), nonce.group(1)


def _laurel_month(fixed_month, fixed_year, nonce, nonce_x):
    """One month of calendar HTML, or '' on any failure."""
    body = {
        "shortcode[calendar_type]": "default",
        "shortcode[event_count]": "200",
        "shortcode[number_of_months]": "1",
        "shortcode[fixed_month]": str(fixed_month),
        "shortcode[fixed_year]": str(fixed_year),
        "shortcode[hide_past]": "no",
        "shortcode[event_past_future]": "all",
        "shortcode[sort_by]": "sort_date",
        "shortcode[_cver]": "5.0.13",
        "ajaxtype": "switchmonth",
        "nonce": nonce,
        "nonceX": nonce_x,
    }
    try:
        r = requests.post(LAUREL_AJAX, data=body,
                          headers={"User-Agent": _BROWSER_UA,
                                   "X-Requested-With": "XMLHttpRequest",
                                   "Referer": LAUREL_CAL},
                          timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  WARN: laurelthirst month {fixed_month}/{fixed_year} failed: "
              f"{type(e).__name__}: {e}")
        return ""
    if str(data.get("status", "")).upper() != "GOOD":
        print(f"  WARN: laurelthirst month {fixed_month}/{fixed_year} returned "
              f"status={data.get('status')!r} msg={data.get('msg')!r}")
        return ""
    return data.get("html") or ""


def parse_laurelthirst(html, today):
    """Return one row per OCCURRENCE across the horizon.

    `html` is the fetched LAUREL_CAL page - we need it only for the nonces.
    Fails soft: any breakage returns whatever was gathered so far (possibly
    empty) rather than raising, so a dead source cannot abort the run."""
    out = []
    try:
        tz = _laurel_pacific()
        horizon = today + datetime.timedelta(days=LAUREL_HORIZON_DAYS)

        pair = _laurel_nonces(html or "")
        if not pair:
            # Retry once with our own fetch, in case the caller handed us a
            # page without the calendar shortcode on it.
            try:
                pair = _laurel_nonces(fetch(LAUREL_CAL))
            except Exception:
                pair = None
        if not pair:
            print("  WARN: laurelthirst nonces not found on calendar page")
            return out
        nonce, nonce_x = pair

        # Months to walk: current month through one past the horizon.
        base_year = today.year
        months = []
        y, m = today.year, today.month
        while (y, m) <= (horizon.year, horizon.month):
            months.append((m + 1 + 12 * (y - base_year), base_year))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        months.append((m + 1 + 12 * (y - base_year), base_year))   # margin month

        seen = set()
        for idx, (fixed_month, fixed_year) in enumerate(months):
            if idx:
                time.sleep(LAUREL_PAUSE)
            frag = _laurel_month(fixed_month, fixed_year, nonce, nonce_x)
            if not frag:
                continue
            soup = BeautifulSoup(frag, "html.parser")
            for el in soup.select(".eventon_list_event"):
                dt = (el.get("data-time") or "").split("-")
                if not dt or not dt[0].isdigit():
                    continue
                start = int(dt[0])
                ev_id = el.get("data-event_id") or ""
                ri = str(el.get("data-ri") or "").replace("r", "")
                key = (ev_id, ri, start)
                if key in seen:
                    continue
                seen.add(key)

                local = datetime.datetime.fromtimestamp(start, tz)
                d = local.date()
                if not (today <= d <= horizon):
                    continue

                node = el.select_one('[itemprop="name"]')
                raw = ""
                if node is not None:
                    raw = node.get("content") or node.get_text(" ", strip=True) or ""
                title = clean(raw.replace("&amp;", "&"))
                title = re.sub(r"\s+", " ", re.sub(r"[‐-―]", "-", title)).strip()
                if not title:
                    continue

                link = el.select_one('[itemprop="url"]')
                url = (link.get("href") or "").strip() if link is not None else ""
                img_el = el.select_one('[itemprop="image"]')
                img = ""
                if img_el is not None:
                    img = (img_el.get("content") or img_el.get("src") or "").strip()

                hh, mn = local.hour, local.minute
                tm = "%d:%02d %s" % (hh % 12 or 12, mn, "AM" if hh < 12 else "PM")

                nb, addr = VENUE_INFO.get("Laurelthirst Public House",
                                          ("Kerns", "2958 NE Glisan St"))
                out.append({"title": title, "venue": "Laurelthirst Public House",
                            "neighborhood": nb, "address": addr,
                            "date": d.isoformat(), "time": tm,
                            "venueUrl": url, "imageUrl": img})
    except Exception as e:
        print(f"  WARN: laurelthirst parser aborted: {type(e).__name__}: {e}")
    out.sort(key=lambda s: (s["date"], s["time"], s["title"]))
    return out


# -----------------------------------------------------------------------------
# ALSO CHANGE, in the SOURCES list, so the page we are handed is the one that
# actually carries evo_general_params (saves a redundant fetch):
#
#   {"name": "Laurelthirst (laurelthirst.com)", "parser": parse_laurelthirst,
#    "urls": ["https://laurelthirst.com/music-calendar/"]},
#
# (was ["https://www.laurelthirst.com/"])
# -----------------------------------------------------------------------------
