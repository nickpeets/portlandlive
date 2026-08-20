# Laurelthirst residency under-catch — diagnosis, design, and what still needs live testing

**Status: NOT SHIPPED. Nothing was committed.** The repo is clean on `main`; the
branch `feat/laurelthirst-residency` was deleted rather than left carrying
unverified scraper code.

---

## 1. The bug, confirmed against the live site

Laurelthirst runs residencies. EventON (v5.0.13) stores every occurrence of a
residency inside **one** post. The current `parse_laurelthirst` reads the
WordPress CPT route `/wp-json/wp/v2/ajde_events`, which lists **posts** — so it
structurally cannot see repeats, no matter how many pages it walks.

Measured on the live calendar, horizon 2026-08-19 → 2026-12-17:

| | count |
|---|---|
| Occurrences the venue actually publishes | **98** |
| Distinct event posts behind them | **64** |
| Repeat instances (invisible to a post-shaped reader) | **34** |
| What the current parser puts in the feed | **48** |

The three failures compound exactly as diagnosed:

1. **Recurrence collapse.** `itemprop="startDate"` on an event page exposes only
   the first occurrence. 22 of the 64 posts are series; 42 are one-offs.
2. **Whole-series discard.** The range filter tested that single first date, so
   a series whose instance 0 is past was dropped entirely — taking live future
   instances with it. Confirmed: **Freak Mountain Ramblers instances 3 and 4 fall
   on 2026-08-23 and 2026-08-30**, both live, both currently thrown away because
   instance 0 is 2026-08-02. Ten of August's 25 occurrences are repeat instances.
3. **Wasted budget.** `orderby=date` is publish date, so most of the 200-post cap
   went on already-happened events.

## 2. The fix

Read **occurrences**, not posts. EventON's own calendar endpoint returns one
`.eventon_list_event` block per occurrence.

* Endpoint: `POST https://laurelthirst.com/?evo-ajax=eventon_get_events`
* ~6 requests (one per month) replacing ~200 — roughly a 30x reduction, and no
  per-event page fetch at all.

### Two traps found the hard way — both are live-confirmed

**(a) The nonces are crossed.** The calendar page ships `evo_general_params` with
keys `n` and `nonce`. They map to POST fields **swapped**: `n` → field `nonce`,
and `nonce` → field `nonceX`. Sending them straight through returns
`{"status":"bad","msg":"Nonce validation failed"}`. Verified both orderings.

**(b) `event_start_unix` is wrong for recurrence instances.** The response also
carries a convenient `json` array — do not use its timestamps. It is correct only
for non-repeating events. For repeats it is off by 7 hours and a calendar day:

| | `event_start_unix` as UTC | `data-time` in LA | schema.org `startDate` |
|---|---|---|---|
| Scott Law Band (instance 0) | 2026-08-19 18:00 | 2026-08-19 18:00 | 18:00 ✓ |
| Lewi Longmire (**instance 2**) | 2026-08-21 **01:00** ✗ | 2026-08-20 18:00 | 18:00 ✓ |

`data-time` is a true epoch and matched the per-occurrence schema **every time**,
including across the 2026-11-01 DST boundary. The parser uses `data-time` only.

**(c) `shortcode[fixed_month]` is offset by one.** `fixed_month=9` renders
*August*; `13` renders December; `14` rolls into January of the next year. The
parser derives it as `month + 1 + 12*(year - fixed_year)` but **does not depend
on it for correctness** — every occurrence is filtered by its own epoch, so an
index drift can only cost coverage, never produce a wrong date. One extra month
is fetched as margin.

## 3. Horizon — note the discrepancy

The parser uses a 120-day internal horizon to match its neighbours
(`parse_albertastreetpub`, `parse_havalina` both use 120). But `scrape()` then
clips **everything** to the global `HORIZON_DAYS = 90`. So:

* parser returns **98**
* what actually lands in the feed: **95** (Laurelthirst has 3 occurrences between
  day 90 and day 120)

Both numbers are worth stating because the venue's "98 upcoming" and the feed's
number will never match while the global clip is 90.

## 4. Expected guardrail behaviour — read this before running the pipeline

Laurelthirst's baseline history is `[33, 31, 31, 31, 30, 29, 27, 25, 48, 48]`,
trailing average **33.3**.

* New count 95 → **+185% vs average → trips the >60% spike alert.**
* This is an **expected one-time correction**, not a regression. It should be
  reported, not suppressed.
* Phase 2 Layer 1 guardrails are unaffected: the total rises (1239 → ~1286), no
  venue drops to zero, so neither `MIN_TOTAL_SHOWS` nor `MAX_NEW_ZERO_VENUES`
  fires.
* Layer 2's sustained-decline detector is a decline-only check — a rise cannot
  trip it.

After the correction lands, the next two runs will still show a large delta
against a trailing average that includes the old 25–48 values; the alert will
quiet on its own once the window fills with the new level.

---

## 5. VERIFIED vs UNVERIFIED — the important part

### Verified against the live site (through a browser session)

- The 98 / 64 / 34 occurrence counts, and per-month distribution (Aug 25, Sep 53,
  Oct 10, Nov 8, Dec 2).
- The endpoint, and that it returns one block per occurrence.
- The crossed-nonce mapping — both orderings tested, only one works.
- `data-time` vs `event_start_unix` divergence on recurrence instances, and
  agreement of `data-time` with schema.org across the DST boundary.
- The `fixed_month` off-by-one, probed across 7 consecutive months.
- That every occurrence carries a usable title (`itemprop="name"`) and a distinct
  permalink (`itemprop="url"`, with `/var/ri-N` markers on repeats) — 98/98
  coverage on both.
- The exact nonce-extraction regexes, run against the real 337KB page source.
- The Freak Mountain Ramblers 8/23 and 8/30 instances.

### Verified only offline, against a replica fixture

The Python was spliced into a copy of `scrape_venues.py` and run with the HTTP
layer mocked, using markup rebuilt to the observed real shape (single-quoted
`itemprop`, double-quoted `data-*`). That exercised: recurrence expansion,
dedupe, the 120-day horizon filter, epoch→Pacific conversion (6:00 PM came out
right), entity decoding, the 8-field schema, the crossed-nonce mapping, the
`fixed_month` sequence (9→14), and eight fail-soft paths (nonce failure, HTTP
throw, non-JSON, empty payload, wrong markup, missing `data-time`, missing title,
no nonces) — all returned empty without raising.

### NOT VERIFIED — must be done before this goes near the pipeline

1. **The parser has never made a real HTTP request.** Everything about live
   behaviour is untested: whether `requests.post` with these headers is accepted,
   whether the site challenges the aggregator UA, real latency, real pagination
   termination.
2. **Nonce lifetime is unknown.** WP nonces typically last ~12–24h and are tied
   to the requesting session. The parser fetches the page and reuses its nonce
   immediately, which *should* be fine — but a cookie requirement between the
   page fetch and the POST would break it, and `fetch()`/`requests.post` here do
   not share a session. **If it fails live, this is the first thing to check** —
   the fix is a `requests.Session()` shared across both calls.
3. **`imageUrl`** — on the sample inspected, `itemprop="image"` was an empty
   `<meta>`. The parser falls back to `""` (same as the old one), but real image
   coverage across 98 rows was never measured.
4. **The end-to-end run**: `python3 scrape_venues.py` then `python3
   build_shows.py`, the resulting Laurelthirst count, the new feed total, and
   what `check_baselines` actually prints.

### Suggested first commands in the Codespace

```bash
cd /workspaces/portlandlive
python3 -c "import requests,bs4;print('deps ok')"     # BUILDLOG lists a broken env as an open item
# splice parse_laurelthirst_v2.py over the existing parser, update the SOURCES url, then:
python3 -c "
import datetime, scrape_venues as S
rows = S.parse_laurelthirst(S.fetch('https://laurelthirst.com/music-calendar/'), datetime.date.today())
print('rows:', len(rows))
from collections import Counter
c = Counter(r['date'][:7] for r in rows); print(sorted(c.items()))
for r in rows[:5]: print(' ', r['date'], r['time'], r['title'][:40])
"
```
Expect ~98 rows and a month distribution close to Aug 25 / Sep 53 / Oct 10 /
Nov 8 / Dec 2. A result near 48 means the occurrence path silently fell back to
post-shaped data; a result of 0 means the nonce path failed — see item 2.

---

## 6. Sweep: do the other residency-heavy rooms have this?

**Offline signal (fully verified, computed from the shipped `shows.json`):** how
far forward each venue's listings reach, against a 90-day horizon.

| Venue | shows | reach | max date | platform |
|---|---|---|---|---|
| Havalina | 36 | **25d** | 2026-09-13 | Squarespace `?format=json` |
| Alberta Street Pub | 30 | **37d** | 2026-09-25 | Squarespace `?format=json` |
| Artichoke Music | 24 | **42d** | 2026-09-30 | Eventbrite collection JSON-LD |
| Laurelthirst *(the known case)* | 48 | **47d** | 2026-10-05 | EventON |
| Mississippi Pizza | 46 | **51d** | 2026-10-09 | WordPress + RHP plugin |
| *healthy comparison* — Starday, No Fun, Revolution Hall, Wonder, Aladdin… | 47–114 | **88–90d** | 2026-11-15/17 | various |

Every healthy venue reaches the full 90 days. These five stop early while
carrying a substantial catalogue — the signature of a source-side cap.

**Findings, with confidence levels:**

- **Alberta Street Pub — CONFIRMED capped, but NOT this bug.** Live check shows
  `?format=json` returns `pagination: {nextPage: true, pageSize: 30}` and exactly
  **30** `upcoming` items ending 2026-09-25, against a `collection.itemCount` of
  3325. The parser reads page 1 and stops. This is a **pagination cap, not
  recurrence collapse** — a different mechanism with the same symptom. *Caveat:*
  walking `?offset=` did not yield more upcoming items, so whether events exist
  beyond 9/25 is still unconfirmed; the calendar-view check was cut short when
  browser access dropped. Needs one more query before anyone writes a fix.

- **Havalina — NOT in the brief, but flag it.** Same Squarespace `upcoming`
  shape as Alberta Street Pub and the **shallowest reach of any venue** (25 days
  on 36 shows). Very likely the same page-1 cap. Worth adding to the fix task.

- **Mississippi Pizza — NOT VERIFIED.** WordPress + RHP events plugin, single
  `/calendar/` page of `.rhpSingleEvent` blocks. Reach 51d on 46 shows. The RHP
  plugin commonly paginates or lazy-loads by month, which would be the same
  family of cap, but I could not confirm it live.

- **Artichoke Music — NOT VERIFIED.** Eventbrite collection page, parsed from
  embedded JSON-LD `ItemList`. Reach 42d on 24 shows. Eventbrite collection pages
  typically server-render only the first tranche and lazy-load the rest, so the
  `ItemList` would carry a partial set — again plausible, not confirmed.

**Net:** the sweep's premise is right that these rooms are under-caught, but the
cause looks like **first-page caps** rather than Laurelthirst's recurrence
collapse. Laurelthirst is the only one of the group on EventON, and recurrence
collapse is an EventON-specific failure. Each of the others needs its own small
fix (follow the pagination), not a copy of this one.

## 7. Files

- `parse_laurelthirst_v2.py` — the drop-in replacement, plus the one-line
  `SOURCES` url change it needs.
- `test_laurelthirst_v2.py` — the offline harness described above; run it after
  splicing to confirm nothing regressed before going live.
