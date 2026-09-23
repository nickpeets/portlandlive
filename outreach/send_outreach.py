#!/usr/bin/env python3
"""Venue outreach emails for Rain Or Shows (Sep 23 2026, Nick).

One short personal email per venue booking team, sent through Resend from
nick@rainorshows.com, 10 a day. Replies go to nick@rainorshows.com (which
forwards to Nick's Gmail).

The list is outreach/venues.csv (built from ROS_venue_outreach.xlsx). Every
email that goes out is written to outreach/sent.csv, and nothing in there is
ever sent again -- run a batch twice and the second run sends nothing.

  python3 outreach/send_outreach.py --list 1            what batch 1 would send (sends nothing)
  python3 outreach/send_outreach.py --test you@x.com     3 samples (plain, giveaway, comedy) to you
  python3 outreach/send_outreach.py --send 1             send batch 1 for real

The Resend API key is read from RESEND_API_KEY, or asked for (not echoed).
"""
import csv, getpass, html, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "venues.csv")
SENT = os.path.join(HERE, "sent.csv")
FROM = "Nick at Rain Or Shows <nick@rainorshows.com>"
REPLY_TO = "nick@rainorshows.com"
SUBMIT = "https://rainorshows.com/#/submit"


def load():
    with open(LIST, newline="") as f:
        return [r for r in csv.DictReader(f)]


def already_sent():
    if not os.path.exists(SENT):
        return set()
    with open(SENT, newline="") as f:
        return {r["to"].lower() for r in csv.DictReader(f)}


def pieces(r):
    venues = [v.strip() for v in r["venues"].split(" + ") if v.strip()]
    links = [u.strip() for u in r["links"].split(" | ") if u.strip()]
    return venues, links


def and_list(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def build(r):
    """(subject, html, text) for one row."""
    venues, links = pieces(r)
    comedy = r["version"].strip().lower() == "comedy"
    giveaway = r["giveaway"].strip().lower() == "yes"
    hi = "Hi " + (r["first_name"].strip() or "there") + ","
    who = r["group"].strip() or and_list(venues)
    subject = (who + " is on Rain Or Shows") if (len(venues) == 1 and not r["group"].strip()) else "Your shows are on Rain Or Shows"

    what = "a free calendar of every live show in Portland, music and comedy," if comedy else "a free calendar of every live show in Portland,"
    if len(venues) == 1:
        where_t = f"{venues[0]}'s shows are already on it{' (in our Comedy section)' if comedy else ''}, with their own page here: {links[0]}"
        where_h = (f"{html.escape(venues[0])}&rsquo;s shows are already on it{' (in our Comedy section)' if comedy else ''}, "
                   f"with their own page here: <a href=\"{links[0]}\">{html.escape(links[0].replace('https://', ''))}</a>")
    else:
        where_t = "Your shows are already on it, and each room has its own page:\n" + "\n".join(f"  {v}: {u}" for v, u in zip(venues, links))
        where_h = ("Your shows are already on it, and each room has its own page:<br>"
                   + "<br>".join(f"&nbsp;&nbsp;<a href=\"{u}\">{html.escape(v)}</a>" for v, u in zip(venues, links)))

    give_t = ("\n\nOne more idea: we run ticket giveaways, and right now it's a pair to The Brothers Comatose at the Aladdin. "
              "We feature the show on the site and on our social media for a few weeks, and people enter by signing up and marking "
              "the shows they're going to. So your show gets promoted to Portland concertgoers the whole time it runs. "
              "All you'd send is a pair of tickets. We handle the entries, the drawing and getting the tickets to the winner. "
              "If there's a show you'd like to push, I'd be glad to set one up.") if giveaway else ""
    give_h = ("<p><strong>One more idea:</strong> we run ticket giveaways, and right now it&rsquo;s a pair to The Brothers Comatose at the Aladdin. "
              "We feature the show on the site and on our social media for a few weeks, and people enter by signing up and marking "
              "the shows they&rsquo;re going to. So your show gets promoted to Portland concertgoers the whole time it runs. "
              "<strong>All you&rsquo;d send is a pair of tickets.</strong> We handle the entries, the drawing and getting the tickets to the winner. "
              "If there&rsquo;s a show you&rsquo;d like to push, I&rsquo;d be glad to set one up.</p>") if giveaway else ""

    text = (f"{hi}\n\n"
            f"I'm Nick. I run Rain Or Shows (rainorshows.com), {what} pulled nightly from the venues' own calendars. {where_t}\n\n"
            "A few things, no strings attached:\n"
            "- It's free, and always will be for venues. No listing fees, no ads.\n"
            "- If anything's wrong (a time, a poster, a cancelled show), reply here or write corrections@rainorshows.com and we'll fix it.\n"
            f"- If a show's missing, anyone can add it here: {SUBMIT}"
            f"{give_t}\n\n"
            f"Thanks for putting on shows in this town.\n\nNick\nRain Or Shows\n\n"
            "If you'd rather not hear from me again, just reply \"no thanks.\"\n")
    body = ("<div style=\"font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55;color:#222;max-width:600px\">"
            f"<p>{html.escape(hi)}</p>"
            f"<p>I&rsquo;m Nick. I run Rain Or Shows (<a href=\"https://rainorshows.com\">rainorshows.com</a>), {html.escape(what)} "
            f"pulled nightly from the venues&rsquo; own calendars. {where_h}</p>"
            "<p>A few things, no strings attached:</p><ul style=\"padding-left:20px\">"
            "<li><strong>It&rsquo;s free, and always will be for venues.</strong> No listing fees, no ads.</li>"
            "<li><strong>If anything&rsquo;s wrong</strong> (a time, a poster, a cancelled show), reply here or write "
            "<a href=\"mailto:corrections@rainorshows.com\">corrections@rainorshows.com</a> and we&rsquo;ll fix it.</li>"
            f"<li><strong>If a show&rsquo;s missing,</strong> anyone can <a href=\"{SUBMIT}\">add it here</a>.</li></ul>"
            f"{give_h}"
            "<p>Thanks for putting on shows in this town.</p>"
            "<p>Nick<br>Rain Or Shows</p>"
            "<p style=\"font-size:12px;color:#888\">If you&rsquo;d rather not hear from me again, just reply &ldquo;no thanks.&rdquo;</p></div>")
    return subject, body, text


def send_one(key, to, subject, body, text, idem):
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": FROM, "to": [to], "reply_to": REPLY_TO, "subject": subject, "html": body, "text": text}).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "Idempotency-Key": idem,
                 "User-Agent": "rainorshows-outreach/1"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}").get("id", "")


def api_key():
    k = os.environ.get("RESEND_API_KEY", "").strip()
    if not k:
        k = getpass.getpass("Resend API key (starts with re_, won't show as you paste): ").strip()
    if not k.startswith("re_"):
        sys.exit("STOP: that doesn't look like a Resend API key (they start with re_).")
    return k


def batch_rows(rows, n):
    done = already_sent()
    out = []
    for r in rows:
        if str(r["batch"]).strip() != str(n):
            continue
        if r["send"].strip().lower() != "yes":
            print(f"  skip  {r['to']:40}  (Send? = No)")
            continue
        if r["to"].lower() in done:
            print(f"  skip  {r['to']:40}  (already sent)")
            continue
        out.append(r)
    return out


def main():
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "--list":
        rows = batch_rows(load(), a[1])
        for r in rows:
            s, _, _ = build(r)
            print(f"  would send  {r['to']:40}  {s}{'  [+giveaway]' if r['giveaway'].lower() == 'yes' else ''}")
        print(f"{len(rows)} email(s) in batch {a[1]}. Nothing was sent.")
        return
    if len(a) == 2 and a[0] == "--test":
        rows = load()
        picks = [next(r for r in rows if r["version"] == "Music" and r["giveaway"] == "No"),
                 next(r for r in rows if r["giveaway"] == "Yes" and " + " in r["venues"]),
                 next(r for r in rows if r["version"] == "Comedy")]
        key = api_key()
        for r in picks:
            s, b, t = build(r)
            eid = send_one(key, a[1], "[TEST for " + r["to"] + "] " + s, b, t, "test-" + r["to"] + "-" + str(time.time()))
            print(f"  test sent  ({r['venues'][:40]})  id={eid}")
        print("Check your inbox: 3 samples (plain, giveaway, comedy). Nothing went to any venue.")
        return
    if len(a) == 2 and a[0] == "--send":
        rows = batch_rows(load(), a[1])
        if not rows:
            print("Nothing to send in batch " + a[1] + ".")
            return
        key = api_key()
        new = not os.path.exists(SENT)
        with open(SENT, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["sent_at", "batch", "to", "venues", "resend_id"])
            for r in rows:
                s, b, t = build(r)
                try:
                    eid = send_one(key, r["to"], s, b, t, "ros-outreach-" + r["to"].lower())
                except urllib.error.HTTPError as e:
                    print(f"  FAILED  {r['to']}: {e.code} {e.read().decode()[:200]}")
                    continue
                w.writerow([datetime.now().isoformat(timespec="seconds"), a[1], r["to"], r["venues"], eid]); f.flush()
                print(f"  sent  {r['to']:40}  {s}")
                time.sleep(1.5)
        print("Done. Logged in outreach/sent.csv -- those addresses will never be emailed again by this script.")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
