#!/usr/bin/env python3
"""Offline harness for the rewritten parse_laurelthirst.

Runs the parser with the HTTP layer mocked, against markup rebuilt to the shape
observed on the live site (single-quoted itemprop attrs, double-quoted data-*,
one .eventon_list_event block per occurrence).

This proves the PARSING is right. It cannot prove the NETWORK path is right —
see HANDOFF-laurelthirst.md section 5.

Usage, after splicing parse_laurelthirst_v2.py over the existing parser:
    python3 test_laurelthirst_v2.py /workspaces/portlandlive
"""
import sys, os, datetime, types

REPO = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, REPO)
import scrape_venues as S

FAILS = []


CHECKS = []


def check(label, got, want):
    ok = got == want
    CHECKS.append(ok)
    print("  %-52s %s   (got %r)" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        FAILS.append("%s: got %r want %r" % (label, got, want))


def block(ev_id, ri, start, end, slug, name, img=""):
    imgattr = ' content="%s"' % img if img else ''
    return (
        '<div id="event_%s_%s" class="eventon_list_event evo_eventtop scheduled  event clrW" '
        'data-event_id="%s" data-ri="%sr" data-time="%s-%s" data-colr="#e1f500" '
        "itemscope itemtype='http://schema.org/Event'>"
        '<div class="evo_event_schema" style="display:none" >'
        "<a itemprop='url'  href='https://laurelthirst.com/events/%s/'></a>"
        "<meta itemprop='image'%s />"
        "<meta itemprop='startDate' content=\"2026-8-19T18:00-7:00\" />"
        "<span itemprop='name'>%s</span>"
        '</div></div>'
    ) % (ev_id, ri, ev_id, ri, start, end, slug, imgattr, name)


PAGE = ('var evo_general_params = {"is_admin":"","ajaxurl":"x",'
        '"n":"13bdef93bf","nonce":"a5f82c6731","evo_v":"5.0.13"};')

AUG19_1800 = 1787187600      # verified live: 2026-08-19 6:00 PM PDT
AUG20_1800 = 1787274000      # verified live: instance 2 of a residency
TODAY = datetime.date(2026, 8, 19)

MONTHS = {
    9: (block(13145, 0, AUG19_1800, AUG19_1800 + 10800, 'scott-law-band-32', 'Scott Law Band')
        + block(13128, 2, AUG20_1800, AUG20_1800 + 10800,
                'lewi-longmire-60/var/ri-2.l-L1', 'Lewi Longmire &amp; the Left Coast Roasters')),
    # same occurrence twice -> dedupe must collapse it
    10: (block(13203, 0, 1788800400, 1788811200, 'freak-mountain-ramblers-51', 'Freak Mountain Ramblers')
         + block(13203, 0, 1788800400, 1788811200, 'freak-mountain-ramblers-51', 'Freak Mountain Ramblers')),
    # far beyond the 120-day horizon -> must be dropped
    11: block(99999, 0, 1799000000, 1799010000, 'way-out-there', 'Way Out There'),
}

calls = []


class _R:
    def __init__(self, d): self._d = d
    def raise_for_status(self): pass
    def json(self): return self._d


def fake_post(url, data=None, headers=None, timeout=None):
    calls.append(data)
    return _R({"status": "GOOD", "html": MONTHS.get(int(data["shortcode[fixed_month]"]), "")})


print("== happy path ==")
S.requests = types.SimpleNamespace(post=fake_post)
S.time = types.SimpleNamespace(sleep=lambda n: None)
rows = S.parse_laurelthirst(PAGE, TODAY)

for r in rows:
    print("     %s  %-8s | %s" % (r["date"], r["time"], r["title"]))

check("row count (4 blocks, 1 dupe, 1 out of horizon)", len(rows), 3)
check("recurrence instance kept with its own date", rows[1]["date"], "2026-08-20")
check("epoch -> Pacific wall clock", rows[0]["time"], "6:00 PM")
check("HTML entity decoded in title", "&" in rows[1]["title"], True)
check("nonce field  = params 'n'", calls[0]["nonce"], "13bdef93bf")
check("nonceX field = params 'nonce'", calls[0]["nonceX"], "a5f82c6731")
check("fixed_month sequence starts at month+1", calls[0]["shortcode[fixed_month]"], "9")
check("months walked (5 + 1 margin)", len(calls), 6)
check("schema is exactly the 8 standard fields", sorted(rows[0].keys()),
      ["address", "date", "imageUrl", "neighborhood", "time", "title", "venue", "venueUrl"])
check("venue name", rows[0]["venue"], "Laurelthirst Public House")
check("neighborhood", rows[0]["neighborhood"], "Kerns")
check("rows sorted by date", [r["date"] for r in rows], sorted(r["date"] for r in rows))

print("\n== fail-soft paths (none may raise, all must return []) ==")


def soft(label, post, page=PAGE):
    S.requests = types.SimpleNamespace(post=post)
    try:
        got = S.parse_laurelthirst(page, TODAY)
        check(label, got, [])
    except Exception as e:
        CHECKS.append(False)
        print("  %-52s FAIL  RAISED %s" % (label, type(e).__name__))
        FAILS.append("%s raised %s" % (label, type(e).__name__))


def _throw(exc):
    def f(*a, **k):
        raise exc
    return f


soft("nonce validation rejected", lambda *a, **k: _R({"status": "bad", "msg": "Nonce validation failed"}))
soft("HTTP error", _throw(OSError("connection reset")))
soft("response is not JSON", _throw(ValueError("no json")))
soft("empty html payload", lambda *a, **k: _R({"status": "GOOD", "html": ""}))
soft("payload is not event markup", lambda *a, **k: _R({"status": "GOOD", "html": "<div>maintenance</div>"}))
soft("block missing data-time",
     lambda *a, **k: _R({"status": "GOOD", "html": '<div class="eventon_list_event" data-event_id="1" data-ri="0r"></div>'}))
S.fetch = lambda u: "no params here"
soft("no nonces anywhere", lambda *a, **k: _R({"status": "GOOD", "html": ""}), page="<html>nothing</html>")

print("\n%s  (%d checks, %d failures)" % ("ALL PASS" if not FAILS else "FAILURES", len(CHECKS), len(FAILS)))
for f in FAILS:
    print("   -", f)
sys.exit(1 if FAILS else 0)
