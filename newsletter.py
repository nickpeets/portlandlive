"""Weekly email newsletter (Nov 19 2026 design, rebuilt Nov 25 2026).

Nick: a weekly email to every account holder -- the week's shows with a link
to the site, from Rain Or Shows, and it has to look nice. Include Tim's
"Today in Portland Live Music History" (Liner Notes) piece when one went up in
the last week. Thursdays 9am Pacific.

The nightly build calls build() and writes og/newsletter/latest.html (email
HTML: tables + inline styles). Supabase (supabase/schema-newsletter.sql)
fetches it Thursday at 9am and sends it to the Resend "Members" segment as a
broadcast. <meta name="ros-week"> carries the build date so a stale page is
never sent.
"""
import datetime
import html
import os

import tonight_post

SITE = "https://rainorshows.com"
FOREST, RUST, INK, CREAM = "#3d574a", "#b5562b", "#4a3526", "#f3ead7"
ADDRESS = "4822 SW Scholls Ferry Rd, Portland, OR 97225"


def _e(s):
    return html.escape(str(s or ""), quote=True)


def _today_pt():
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).date()


def _night_picks(shows, day, n=3, seen=None):
    """Up to n music shows for one night, biggest room first, one per act."""
    comedy_acts = {tonight_post.headline(x.get("title")).split(" w/ ")[0].lower()
                   for x in shows if x.get("contentType") == "comedy"}
    cands = []
    for s in shows:
        if tonight_post.headline(s.get("title")).split(" w/ ")[0].lower() in comedy_acts:
            continue
        if s.get("date") != day or s.get("outOfTown") or s.get("contentType") in ("comedy", "other"):
            continue
        if tonight_post.SKIP.search(f"{s.get('title', '')} {s.get('venue', '')}"):
            continue
        cands.append((tonight_post._tier(s.get("venue")), -(s.get("buzz") or 0), s.get("title", ""), s))
    cands.sort(key=lambda c: c[:3])
    out = []
    seen = set() if seen is None else seen  # same act once a week
    for c in cands:
        act = tonight_post.headline(c[3].get("title")).split(" w/ ")[0].lower()
        if act in seen:
            continue
        seen.add(act)
        out.append(c[3])
        if len(out) == n:
            break
    return out


def _show_url(s, make_slug):
    return f"{SITE}/show/{make_slug(s)}/?ref=newsletter"


def build(shows, make_slug, here, stories=None, today=None):
    today = today or _today_pt()
    days = [today + datetime.timedelta(days=i) for i in range(7)]
    week_seen = set()
    nights = [(d, _night_picks(shows, d.isoformat(), seen=week_seen)) for d in days]
    nights = [(d, p) for d, p in nights if p]

    # Three photo cards: the biggest show of the week's first three big nights.
    feat, seen = [], set()
    for d, picks in sorted(nights, key=lambda x: (tonight_post._tier(x[1][0].get("venue")), x[0])):
        s = picks[0]
        if s.get("imageUrl") and s.get("title") not in seen:
            feat.append((d, s))
            seen.add(s.get("title"))
        if len(feat) == 3:
            break
    feat.sort(key=lambda x: x[0])

    # Liner Notes published in the last 7 days.
    cutoff = (datetime.datetime.combine(today, datetime.time()) - datetime.timedelta(days=7)).isoformat()
    notes = [r for r in (stories or []) if r.get("status") == "published" and r.get("slug")
             and (r.get("published_at") or "") >= cutoff][:2]

    rng = f"{days[0].strftime('%b %-d')} – {days[-1].strftime('%b %-d')}"
    subject = f"Portland live music this week ({rng})"
    if feat:
        subject = f"This week: {tonight_post.headline(feat[0][1]['title']).split(' w/ ')[0]} and more — Portland live music"

    P = []
    a = P.append
    a('<!DOCTYPE html><html><head><meta charset="utf-8">'
      '<meta name="viewport" content="width=device-width,initial-scale=1">'
      f'<meta name="ros-week" content="{today.isoformat()}">'
      f'<title>{_e(subject)}</title></head>')
    a(f'<body style="margin:0;padding:0;background:{CREAM}">')
    a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CREAM}"><tr><td align="center" style="padding:16px 8px">')
    a('<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:14px;overflow:hidden;font-family:Georgia,\'Times New Roman\',serif;color:' + INK + '">')
    # Header: the "torn flyer" image Nick picked Nov 25 2026 (logo + slab
    # wordmark baked into og/newsletter/header.jpg, since email can't load
    # web fonts), then the week strip.
    a(f'<tr><td style="padding:0;background:#efe2c4"><a href="{SITE}/?ref=newsletter">'
      f'<img src="{SITE}/og/newsletter/header.jpg" width="600" alt="Rain Or Shows \u2014 this week in Portland" '
      f'style="display:block;width:100%;height:auto;border:0;color:{FOREST};font-size:28px;font-weight:bold"></a></td></tr>')
    a(f'<tr><td style="background:{FOREST};padding:10px 24px;text-align:center;font-family:Arial,Helvetica,sans-serif;'
      f'color:{CREAM};font-size:14px;font-weight:bold;letter-spacing:3px;text-transform:uppercase">{_e(rng)}</td></tr>')
    # Featured cards
    if feat:
        a('<tr><td style="padding:20px 16px 4px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>')
        for d, s in feat:
            url = _show_url(s, make_slug)
            a('<td width="33%" valign="top" style="padding:0 6px">'
              f'<a href="{_e(url)}" style="text-decoration:none;color:{INK}">'
              f'<img src="{_e(s["imageUrl"])}" width="176" alt="" style="display:block;width:100%;height:auto;border-radius:10px;border:0">'
              f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:{RUST};font-weight:bold;text-transform:uppercase;margin-top:8px">{_e(d.strftime("%a %b %-d"))}</div>'
              f'<div style="font-size:16px;font-weight:bold;color:{FOREST};line-height:1.2;margin-top:2px">{_e(tonight_post.headline(s["title"]).split(" w/ ")[0])}</div>'
              f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#777;margin-top:2px">{_e(s.get("venue"))}</div></a></td>')
        a('</tr></table></td></tr>')
    # Night by night
    a(f'<tr><td style="padding:18px 24px 4px"><div style="font-size:20px;font-weight:bold;color:{FOREST};border-bottom:2px solid {CREAM};padding-bottom:6px">Night by night</div></td></tr>')
    for d, picks in nights:
        a(f'<tr><td style="padding:12px 24px 0"><div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;font-weight:bold;color:{RUST};text-transform:uppercase;letter-spacing:1px">{_e(d.strftime("%A, %b %-d"))}</div>')
        for s in picks:
            t = f" · {_e(s['time'])}" if s.get("time") else ""
            a(f'<div style="margin:5px 0 0;font-size:15px;line-height:1.35">'
              f'<a href="{_e(_show_url(s, make_slug))}" style="color:{INK};font-weight:bold;text-decoration:none">{_e(tonight_post.headline(s["title"]))}</a>'
              f'<span style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#777"> — {_e(s.get("venue"))}{t}</span></div>')
        a('</td></tr>')
    # Liner Notes
    for r in notes:
        url = f"{SITE}/og/story/{r['slug']}/?ref=newsletter"
        a(f'<tr><td style="padding:22px 24px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CREAM};border-radius:12px"><tr>')
        if r.get("cover_url"):
            a(f'<td width="110" valign="top" style="padding:12px 0 12px 12px"><a href="{_e(url)}"><img src="{_e(r["cover_url"])}" width="98" alt="" style="display:block;border-radius:8px;border:0"></a></td>')
        a(f'<td valign="top" style="padding:12px 14px"><div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;color:{RUST};text-transform:uppercase;letter-spacing:1px">From Liner Notes</div>'
          f'<a href="{_e(url)}" style="display:block;font-size:17px;font-weight:bold;color:{FOREST};text-decoration:none;margin-top:4px;line-height:1.25">{_e(r.get("title"))}</a>'
          f'<a href="{_e(url)}" style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:{RUST}">Read it →</a></td></tr></table></td></tr>')
    # CTA + footer
    a(f'<tr><td align="center" style="padding:26px 24px 8px"><a href="{SITE}/?ref=newsletter" style="background:{RUST};color:#fff;text-decoration:none;font-family:Arial,Helvetica,sans-serif;font-weight:bold;font-size:15px;padding:12px 26px;border-radius:999px;display:inline-block">See every show on Rain Or Shows</a></td></tr>')
    a(f'<tr><td align="center" style="padding:18px 24px 24px;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#999;line-height:1.5">'
      'You’re getting this because you have a Rain Or Shows account. '
      '<a href="{{{RESEND_UNSUBSCRIBE_URL}}}" style="color:#999">Unsubscribe</a><br>'
      f'Rain Or Shows · {ADDRESS}</td></tr>')
    a('</table></td></tr></table></body></html>')

    d = os.path.join(here, "og", "newsletter")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "latest.html"), "w", encoding="utf-8") as f:
        f.write("".join(P))
    print(f"Wrote og/newsletter/latest.html ({len(nights)} nights, {len(feat)} cards, {len(notes)} Liner Notes)")
    return subject
