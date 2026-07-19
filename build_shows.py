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
import re
import html as _html

_DASHES = re.compile(r"[\u2010-\u2015]")
_TAG_RE = re.compile(r"<[^>]+>")
_NONALNUM = re.compile(r"[^0-9a-z]+")


def clean_title(t):
    # Strip HTML tags and decode entities so raw markup (e.g. a <span> from
    # a source feed) never reaches shows.json. Decode first (entities can
    # reveal tag chars), strip tags, decode again, then collapse whitespace.
    t = _html.unescape(t or "")
    t = _TAG_RE.sub("", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _norm_key(s):
    # Aggressive normalization used ONLY for the dedupe key (not display):
    # strip HTML, dash-normalize, lower, and collapse every run of
    # non-alphanumerics to one space so punctuation/spacing/markup variants
    # of the same title or venue can never form a distinct key.
    s = _TAG_RE.sub("", _html.unescape(s or ""))
    s = _DASHES.sub("-", s).lower()
    return _NONALNUM.sub(" ", s).strip()


def _norm_title(t):
    return _norm_key(t)


def _norm_venue(v):
    return _norm_key(v)

HERE = os.path.dirname(__file__)
MANUAL = os.path.join(HERE, "manual_shows.json")
OUT = os.path.join(HERE, "shows.json")
ARCHIVE = os.path.join(HERE, "archive.json")


# --- Append-only past-show archive -------------------------------------------
# archive.json is an accumulative record of shows that have already happened.
# It only ever GROWS: past shows are merged in before the live feed drops them,
# so their data survives even after the scraper overwrites manual_shows.json.
# Identity is a STABLE SLUG derived from immutable facts (date + venue + title),
# NOT the build's sequential integer id (which is reassigned every run).

_ARCHIVE_SOURCE = "Append-only archive of past shows (accumulated across builds)"
_ARCHIVE_FIELDS = ("title", "venue", "neighborhood", "address",
                   "date", "time", "venueUrl", "imageUrl")


def make_slug(show):
    """Deterministic permanent identity for a show.

    Reuses the existing dedupe normalization (_norm_key -> strip HTML/entities,
    dash-normalize, lowercase, collapse every non-alphanumeric run) so the slug
    is immune to markup/punctuation/whitespace variants, then joins the tokens
    with hyphens to form a URL-safe slug. Same show -> same slug on every run.
    """
    date = (show.get("date", "") or "").strip()
    venue = _norm_key(show.get("venue", ""))
    title = _norm_key(clean_title(show.get("title", "")))
    raw = " ".join(p for p in (date, venue, title) if p)
    slug = re.sub(r"\s+", "-", raw).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


def _snapshot(show, slug):
    rec = {f: show.get(f, "") for f in _ARCHIVE_FIELDS}
    rec["title"] = clean_title(show.get("title", ""))
    rec["slug"] = slug
    return rec


def archive_past_shows(past_shows, generated_iso):
    """Merge past shows into archive.json. Add-only; never remove/overwrite.

    Dedupe is on the stable slug. If two GENUINELY DISTINCT past shows collide
    on slug (same date+venue+title) but differ by time, a disambiguator is
    appended so they don't silently merge. Returns (added, collisions)."""
    data = {"generated": generated_iso, "source": _ARCHIVE_SOURCE, "shows": []}
    if os.path.exists(ARCHIVE):
        try:
            existing = json.load(open(ARCHIVE))
            if isinstance(existing, dict) and isinstance(existing.get("shows"), list):
                data = existing
        except Exception as e:
            print(f"archive.json unreadable, starting fresh: {e}")
            data = {"generated": generated_iso, "source": _ARCHIVE_SOURCE, "shows": []}

    by_slug = {}
    for rec in data.get("shows", []):
        if rec.get("slug"):
            by_slug[rec["slug"]] = rec

    added = 0
    collisions = []
    for s in past_shows:
        if not (s.get("title") and s.get("date")):
            continue
        base = make_slug(s)
        if not base:
            continue
        slug = base
        existing = by_slug.get(slug)
        if existing is not None:
            # Already archived. Only disambiguate if this is a genuinely
            # different show (same date/venue/title, different non-empty time).
            t_new = (s.get("time", "") or "").strip()
            t_old = (existing.get("time", "") or "").strip()
            if t_new and t_old and t_new != t_old:
                n = 2
                cand = f"{base}-{n}"
                while cand in by_slug and not (
                    by_slug[cand].get("time", "").strip() == t_new):
                    n += 1
                    cand = f"{base}-{n}"
                if cand in by_slug:
                    continue  # this exact time already archived under disambig slug
                slug = cand
                collisions.append((base, slug, t_old, t_new))
            else:
                continue  # true duplicate of an already-archived show -> skip
        rec = _snapshot(s, slug)
        by_slug[slug] = rec
        data["shows"].append(rec)
        added += 1

    data["generated"] = generated_iso
    data["source"] = _ARCHIVE_SOURCE
    data["shows"].sort(key=lambda r: (r.get("date", ""), r.get("venue", ""),
                                      r.get("title", ""), r.get("slug", "")))
    with open(ARCHIVE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Archive: +{added} new past show(s), {len(data['shows'])} total in archive.json")
    if collisions:
        print(f"Archive: {len(collisions)} slug collision(s) disambiguated:")
        for base, slug, t_old, t_new in collisions:
            print(f"  COLLIDE base={base!r} -> {slug!r} (times {t_old!r} vs {t_new!r})")
    return added, collisions


_TIME_RE = re.compile(r"^\d{1,2}:\d{2} [AP]M$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JUNK_TITLES = {"buy tickets", "tickets", "menu"}


def validate(shows):
    # Loudly report data-quality issues; never crash the build on a soft issue.
    import datetime as _dt
    from collections import Counter as _C, defaultdict as _dd
    issues = []
    today = _dt.date.today()
    max_future = today + _dt.timedelta(days=730)  # ~2 years out
    _pac = _dt.timezone(_dt.timedelta(hours=-8))
    today_pacific = _dt.datetime.now(_pac).date()
    for s in shows:
        t = (s.get("title") or "").strip()
        v = s.get("venue", "")
        d = s.get("date", "")
        tm = s.get("time", "")
        if not t:
            issues.append(f"empty title @ {v} {d}")
        else:
            if "<" in t or t.lower() in _JUNK_TITLES:
                issues.append(f"junk title {t!r} @ {v} {d}")
            if len(t) > 120:
                issues.append(f"title too long ({len(t)} chars) @ {v} {d}: {t[:40]!r}")
        if not _DATE_RE.match(d):
            issues.append(f"bad date {d!r} @ {v} {t[:40]!r}")
        else:
            try:
                dd = _dt.date.fromisoformat(d)
                if dd.year <= 1970:
                    issues.append(f"epoch/1970 date {d!r} @ {v} {t[:40]!r}")
                elif dd > max_future:
                    issues.append(f"date >2yr out {d!r} @ {v} {t[:40]!r}")
                elif dd < today_pacific:
                    issues.append(f"past-dated show leaked {d!r} @ {v} {t[:40]!r}")
            except ValueError:
                issues.append(f"unparseable date {d!r} @ {v} {t[:40]!r}")
        if tm != "" and not _TIME_RE.match(tm):
            issues.append(f"bad time {tm!r} @ {v} {d} {t[:40]!r}")
    # exact dups + cross-venue collisions
    keys = [(_norm_title(s.get("title","")), s.get("venue",""), s.get("date","")) for s in shows]
    dups = sum(1 for c in _C(keys).values() if c > 1)
    g = _dd(set)
    for s in shows:
        g[(s.get("date",""), _norm_title(s.get("title","")))].add(s.get("venue",""))
    collisions = sum(1 for vs in g.values() if len(vs) > 1)
    if dups:
        issues.append(f"{dups} exact duplicate(s)")
    if collisions:
        issues.append(f"{collisions} cross-venue title/date collision(s)")
    if issues:
        print(f"VALIDATION: {len(shows)} shows, {len(issues)} ISSUE(S):")
        for i in issues:
            print(f"  WARN: {i}")
    else:
        print(f"VALIDATION: {len(shows)} shows OK, 0 issues")
    return issues


def main():
    shows = []
    if os.path.exists(MANUAL):
        try:
            shows = json.load(open(MANUAL)).get("shows", [])
        except Exception as e:
            print(f"manual_shows.json unreadable: {e}")

    # drop past shows
    # Drop past shows using US Pacific time (venues' local zone), not the
    # GitHub runner's UTC clock, (no grace buffer) so a show
    # disappears at Pacific midnight the night it ends.
    pacific = datetime.timezone(datetime.timedelta(hours=-8))
    today_pacific = datetime.datetime.now(pacific).date()
    cutoff = today_pacific.isoformat()
    # Accumulate past shows into the append-only archive BEFORE the live
    # feed drops them. Live feed (shows.json) is unchanged by this step.
    _past = [s for s in shows if s.get("date", "") < cutoff]
    _archive_gen = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    archive_past_shows(_past, _archive_gen)
    shows = [s for s in shows if s.get("date", "") >= cutoff]

    # Sanitize titles: strip HTML tags + decode entities at build time.
    for s in shows:
        if s.get("title"):
            s["title"] = clean_title(s["title"])

    # dedupe on (normalized title, normalized venue, date)
    seen, deduped = {}, []
    time_collisions = []
    for s in shows:
        k = (_norm_title(s.get("title","")),
             _norm_venue(s.get("venue","")),
             s.get("date",""))
        if not (s.get("title") and s.get("date")):
            continue
        if k not in seen:
            seen[k] = s; deduped.append(s)
        else:
            # Same title/venue/date already kept. If BOTH rows carry a
            # non-empty, differing time they may be two real shows that day
            # -> flag instead of silently dropping.
            kept = seen[k]
            t_new = (s.get("time") or "").strip()
            t_old = (kept.get("time") or "").strip()
            if t_new and t_old and t_new != t_old:
                time_collisions.append((s.get("title"), s.get("venue"), s.get("date"), t_old, t_new))
            # Field-merge: the dropped duplicate may carry data the kept row
            # lacks. Adopt the dup's value for any field the kept row left
            # empty so dedupe never discards information (e.g. a missing time,
            # image, or ticket link filled in by a second listing of the show).
            for _f in ("time", "imageUrl", "venueUrl"):
                if not (kept.get(_f) or "").strip() and (s.get(_f) or "").strip():
                    kept[_f] = s[_f]

    deduped.sort(key=lambda s: (s["date"], s.get("venue",""), s.get("title","")))
    for i, s in enumerate(deduped, 1):
        s["id"] = i

    validate(deduped)

    # Surface same title/venue/date rows that differ only by time. These are
    # NOT auto-merged blindly here: the first row is kept, but each conflict
    # is reported so a human can confirm they are not two distinct shows.
    if time_collisions:
        print(f"WARNING: {len(time_collisions)} same-day time collision(s) (kept first, flagged):")
        for ti, ve, da, t_old, t_new in time_collisions:
            print(f"  FLAG: {ti!r} @ {ve!r} {da} kept-time={t_old!r} dropped-time={t_new!r}")

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
