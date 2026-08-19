# Build Log

Project history for **portlandlive**, newest first. Append a new entry at the top of the Changelog for each change.

## Changelog
### 6ac9884 — Fix pipeline push: stage archive.json + fail run on exhausted push retries

The daily **Refresh listings** workflow reported green every day from 2026-07-19 onward while silently discarding its own work. 32 consecutive runs scraped, built, and committed a fresh feed, then failed to push it — and exited 0 anyway. The live site served 2026-07-18 listings for a month behind an unbroken wall of green checkmarks in Actions.

- **Root cause: the workflow did not know about the file its own build step creates.** The "Commit if changed" step staged an explicit three-file list — `shows.json`, `manual_shows.json`, `venue_baselines.json`. On 2026-07-19 the append-only archive shipped (4d41f78) and `build_shows.py` began writing a fourth file, `archive.json`, on every run: `archive_past_shows()` re-stamps `data["generated"]` and writes unconditionally, so the file is dirty after every build even when zero shows are added. It was never staged, so it sat as an unstaged tracked modification — and `git pull --rebase origin main` refuses to run with unstaged changes (`error: cannot rebase: You have unstaged changes`). Every push attempt died at the rebase, before it ever reached the remote.
- **Timeline is exact.** Last successful bot commit 77e4fb4 (2026-07-18). Archive engine landed 4d41f78 (2026-07-19 05:17 UTC). `main.yml` last modified 2026-06-17 — never updated for the new file. The first scheduled run *after* the archive landed was the first to fail, and every run since failed identically. 32 days of scraped data discarded.
- **Second bug: the retry loop reported success on total failure.** GitHub Actions runs `run:` blocks under `bash -e`, and `set -e` exempts any command that is not the last in an `&&` list. So `git pull --rebase origin main && git push && break` could fail all three attempts without aborting the step — and the last command actually executed was `sleep 5`, exit 0. The step passed, the job went green, and a dead pipeline looked healthy. This is what kept a two-line staging bug invisible for a month: the failure had no alarm attached to it.
- **Fix 1 — stage the fourth file.** `archive.json` added to the explicit add list: `git add shows.json manual_shows.json venue_baselines.json archive.json`. Still an explicit list; never `git add -A`.
- **Fix 2 — exhausted retries now fail the run RED.** A `pushed` flag is set only on the success branch (`if git pull --rebase origin main && git push; then pushed=1; break; fi`), and a guard after the loop emits a `::error::` annotation and `exit 1` when the flag was never set. Retry count and sleep behavior are unchanged — only the terminal outcome. A genuine push failure can never again report success.
- **Verification.** The unstaged-archive rebase block was reproduced against a scratch repo. All four paths of the loop were exercised under `bash -e`: old loop with all 3 attempts failing -> exit 0 (the bug); new loop with all 3 failing -> exit 1 plus annotation; new loop succeeding on attempt 1 -> exit 0; new loop succeeding on attempt 3 after two failures -> exit 0. YAML parses clean (6 steps, both triggers intact) and the run block passes `bash -n`. Shipped alone, on a clean tree, touching only `.github/workflows/main.yml` (1 file, +7/-2).
- **Known side effect (accepted).** `archive.json`'s `generated` timestamp changes every run, so the `git diff --staged --quiet && echo "no changes" && exit 0` early-exit is now effectively dead — the workflow will produce a "Refresh listings" commit daily even when listings are byte-identical. Harmless; logged under Open Items.
- **Landed by hand.** The agent session that diagnosed and verified this fix had read-only git access — its sandbox proxy would not inject a push credential for this repo, and reads passed through anonymously because the repo is public, so clone/fetch/pull all looked healthy while write was never authorized. A `git push --dry-run` gate caught that *before* a commit was created. The change was therefore applied through the GitHub web editor; the diff shown there was confirmed identical (same SHA-256) to the locally verified file before committing.

### 4d41f78 — Append-only show archive: accumulate past shows into archive.json with stable slugs

Stage 0 of permanent show pages: a permanent, accumulative record of past shows that survives scraper churn. build_shows.py regenerates shows.json every run and drops past shows (date < cutoff), and manual_shows.json is overwritten by the scraper, so past shows source data disappears over time. This adds an append-only accumulation engine so history is never lost. Data foundation only; no UI.

- **Append-only accumulation engine.** Before the live feed drops past shows, archive_past_shows() captures every show with date < cutoff and merges it into archive.json. The archive loads its existing contents, indexes them by slug, and only ever appends new entries; it never removes or overwrites existing ones, so it only grows. On first run (or a missing/unreadable file) it initializes an empty {generated, source, shows: []}. Survives manual_shows.json scraper churn.
- **Stable deterministic slug = permanent identity.** Each show identity/URL is make_slug() computed from immutable facts only: date + normalized venue + normalized title, reusing the existing _norm_key/clean_title normalization (strip HTML/entities, dash-normalize, lowercase, collapse non-alphanumerics), joined with hyphens. The build sequential integer id is never part of identity (it is reassigned every build). Same show produces the same slug every run, so re-runs never duplicate. Example: 2026-06-09-the-goodfoot-greaterkind-8pm-doors.
- **Append-only / never-overwrite with collision disambiguation.** Dedupe is on the stable slug, never the id. Two genuinely distinct shows that collide on slug (same date+venue+title) but differ by non-empty time get a base-2 / base-3 disambiguator instead of silently merging; identical repeats are skipped.
- **Self-contained snapshots.** Each archived record stores the full show data (title, venue, neighborhood, address, date, time, venueUrl, imageUrl) plus the slug, so entries survive even after the show vanishes from manual_shows.json.
- **Live feed unchanged.** shows.json output is untouched; past shows are still dropped from the forward-looking feed exactly as before. The archive step only reads the show list before the drop; it does not alter the live feed path.
- **Provenance & validation.** The implementation was found uncommitted from a prior session and was NOT trusted on sight; it was reviewed line-by-line against the Stage 0 spec and proven idempotent before commit: a fresh double-build (deleted archive, rebuilt twice) yielded +28 then +0 with zero duplicate slugs, and every stored slug re-derived identically from make_slug.
- **Known item (not addressed here).** The past/future cutoff uses a fixed UTC-8 offset inherited from the live build, so it is an hour off during PDT. Consistent with the live feed by design; flagged for a future build-wide timezone fix rather than a one-off change in the archive step.

### 0b886f5 — Stub lifecycle: saved→passed→claim→stub

Reworked the Stub Shelf into an explicit saved-show **lifecycle** in the Saved view, built on one principle: **saved (intent) and went (proof) are different states.** A saved show never becomes a stub automatically — only when the user explicitly claims "I was there" — because people don't attend every show they save.

Three states, all inside the Saved view:
- **STATE 1 — upcoming saved:** renders as a normal listing (future date). No stub, no claim button.
- **STATE 2 — passed but unclaimed:** stays saved, still in listing format, grouped under a new **"Did you make it?"** section (below upcoming saved) with a big, prominent primary "I was there" button. Rendered from the favorite key (venue|date|title) via pastSavedSnapshots(), so passed shows survive leaving shows.json.
- **STATE 3 — claimed:** tapping "I was there" mints a stub (authentic Ticketmaster-style card, snapshot { title, venue, neighborhood, address, date, time, mintedAt }, dedupe by title|venue|date) into portlandlive:stubs; the row leaves "Did you make it?" and appears on the Stubs shelf. The listing→stub transformation is the reward. Unclaimed passed shows persist forever — no auto-convert, no age-out.

**Delete everywhere** (all reversible, small unobtrusive controls): upcoming saved and passed-unclaimed both delete via the heart (removes the favorite key); stubs delete via a hover "×" on the stub card (removes from portlandlive:stubs — the show then returns to "Did you make it?" since the favorite is still saved).

**Decisions:** (1) **Day-of card affordance removed** — the inline "I was there" on today's show cards is gone; claiming now lives only in the Saved view, so there is a single minting path (no divergent affordances). A show isn't "went" until it's over. (2) **Claiming leaves the favorite intact** — the stub is a separate store; a claimed show simply moves visually from "Did you make it?" onto the shelf while its stub is what persists.

**Saved-view section order shipped:** Upcoming saved → "Did you make it?" → Stubs shelf (with Make my wall / Export / Import) → Bands → Venues. Bands/Venues (follows, not attendance) sit below the full show lifecycle so the saved→passed→claim→stub narrative stays contiguous at the top. Verified all three states, all three delete paths, reload persistence, no auto-convert/age-out, invitational empty states, and no console errors across toggles + Reset; removed the now-dead iWasThereBtn() helper so no orphaned affordance remains.
### 835b32f — FORCE_MUSIC override: DJ Shadow

Added `"dj shadow"` to **FORCE_MUSIC** in `index.html`. DJ Shadow is a major touring artist (Endtroducing) whose real Crystal Ballroom concert was wrongly caught by the DJ-prefix → Other convention and hidden from the default music-only view. This is exactly what FORCE_MUSIC exists for; the generic DJ-night convention stays correct for actual DJ nights. Verified: the show moves to Music, totals move by exactly 1 (1063 → 1064 music), only DJ Shadow reclassifies (other → music), nothing else shifts; all toggles (Tonight, This Week, Picks, By Neighborhood, Venues, Saved, Comedy, Following) and Reset clean, no console errors. Resolves the DJ Shadow item flagged for review in the prior re-audit; Max Amini (standup in Other) and the Hedwig sing-along tour (kept in Music) stand as previously reasoned — no override.


### 1b6e485 — Retire Audit (dev) toggle; classifier re-audit

The FORCE_MUSIC / FORCE_NON_MUSIC classifier overrides have been live and stable, so this closes the audit open item: one more pass over current data, two conservative override additions, and the dev toggle comes out of the user-facing control bar.

- **Re-audit against current data (1170 shows).** Bucket counts before changes: Music 1063 / Trivia 45 / Other 52 / Comedy 10. Comedy and Trivia buckets were clean (no real music buried — e.g. "Music Bingo" and "Todd Basil: Music Math Death Lasagna (Live Comedy Taping)" carry "music" in the title but are correctly non-music). Skimming Music for leaks surfaced mostly correct band/DJ-set concerts; the "w/ DJ …" and songwriter-open-mic entries are genuinely music and were left alone.
- **Two clear misclassifications fixed (conservative additions).** Added `"greg holden & garrison starr"` to **FORCE_MUSIC** — Greg Holden and Garrison Starr are touring singer-songwriters, and "Greg Holden & Garrison Starr Live in Portland" at Alberta Street Pub was sitting in Other (the keyword classifier defaulted it because neither name is a music keyword). Added `["fly fishing film", "other"]` to **FORCE_NON_MUSIC** — "International Fly Fishing Film Festival" at the Aladdin is a film festival that was leaking into Music. Both fragments were checked to match exactly one event each and nothing else; the two moves cancel in the totals, confirming nothing else shifted.
- **Left in the report, not the lists (ambiguous).** "DJ Shadow" (a named electronic/hip-hop artist, but the app buckets "DJ"-prefixed events as Other by convention); "Max Amini Live in Portland!" (standup currently in Other rather than Comedy — a within-non-music refinement, not a music error); and the two "Hedwig And The Angry Inch … Movie Tour" entries (music-adjacent film screenings currently in Music). These are judgment calls, so per the brief they stay in the report rather than the override lists.
- **Audit (dev) toggle retired from the UI.** Removed the "⚠ Audit (dev)" pill markup and its click handler from the control bar. The audit machinery is intentionally kept for dev use — `auditPanelHtml()` still renders and `state.audit` is now driven by a URL param, so the panel is reachable at `?audit=1` with no user-visible toggle.

Verified against the served page before commit: pill gone from the control bar; the two override targets land in their new buckets (Greg Holden —>music, Fly Fishing Film Festival —>other) with counts otherwise unchanged; `?audit=1` still renders the full audit panel (Music 1063 / Comedy 10 / Trivia 45 / Other 52); all remaining toggles (Tonight, This Week, Picks, By Neighborhood, Venues, Saved, Comedy, Following) plus Reset run clean; grep for `audit-pill` / `auditToggle` returns zero orphans; no console errors.

### 0cd9831 — Stub Wall collage export + stubs JSON backup (export/import with merge)

Phase 2 for the Stub Shelf: turn the collection into something you can take out of the browser. Two additions, both living in the Saved view's shelf section, both self-contained.

- **Stub Wall as a share mechanic.** A "Make my wall" button (shown only when 1+ stubs exist) renders the whole collection to a single `<canvas>` collage — each stub drawn in the same authentic style (deterministic header-band color per title hash, mono caps title/venue/date, aged paper), laid out in a staggered grid with a small seeded rotation per stub (stable across re-renders), on a dark neutral background, with a `REALGOODTIME.COM` + stub-count footer strip. Output is `canvas.toBlob` — PNG (`realgoodtime-wall.png`); it prefers the Web Share API (`navigator.canShare({files})` guard, matching the existing share-to-plan pattern) and falls back to download. Canvas long edge is capped ~2000px — stubs shrink rather than the canvas growing unbounded.
- **Backup because localStorage is fragile.** The shelf lives entirely in `portlandlive:stubs`; a cleared cache or a new device loses it. "Export stubs" downloads the raw array pretty-printed as `portlandlive-stubs.json`. "Import stubs" (always available, even on an empty shelf) parses a file, validates shape (array of objects with at least title/venue/date), skips invalid entries with a count, and **merges** into the existing collection using the same `(title, venue, date)` dedupe identity — it never overwrites or clears what's already there. Malformed files get a friendly toast and change nothing. Feedback stays in the honor-system spirit: "Imported 1 stub (2 already on your shelf) — skipped 1 invalid".

Verified against the served page before commit: wall renders all stubs readably and produces a valid PNG blob; two renders are byte-identical (deterministic layout); share path guarded, download fallback works; export yields valid JSON matching the store; import merges + dedupes (5—>7 from a payload with a dup and two invalids) and survives a malformed file with no state change; empty shelf hides wall/export but keeps import; new classes (`stub-tools`, `stub-tool-btn`, `stub-import-input`) collide with nothing; no console errors across all toggles + Reset. Design principles unchanged — the collection only grows, nothing punishes absence.

### f125ee7 — Add Stub Shelf: 'I was there' minting, snapshot storage, authentic Ticketmaster-style stub rendering

A collectible ticket-stub system. When a user marks a show “I was there,” the app mints a rendered stub into a permanent personal collection stored under the new `portlandlive:stubs` localStorage key.
- **Snapshot-at-mint (past shows leave the feed).** Each stub is a self-contained snapshot — `{ title, venue, neighborhood, address, date, time, mintedAt }` — captured when minted. The build drops past shows from `shows.json`, so the shelf never looks up the live feed to render; it draws entirely from its own stored data. Dedupe is one stub per `(title, venue, date)`; minting twice is a gentle no-op (“Already on your shelf”), never a duplicate.
- **Two minting affordances, where past-show data still exists.** (1) Day-of: an unobtrusive “I was there” control in the card sub-row, shown only for shows dated today (never future). (2) In Saved: a “Past shows” group lists saved shows whose date has passed, parsing the favorite key `venue|date|title` so they can be minted even after leaving the feed; future saved shows get no affordance. Minting never touches the favorites store — stubs and hearts are separate.
- **Shelf location — a section inside the Saved view** (below Shows/Bands/Venues), not a new view. Chosen because it needs no extra pill or mutual-exclusivity branch, it lives where the past-show mint affordances already are, and it renders even when favorites is empty (the empty-favorites early-return still calls the shelf). Newest-first, a plain count line (“2 stubs” — a count, never a goal or progress bar), and an inviting empty state (“Your shelf is empty…”).
- **Authentic Ticketmaster-era stub design** (replaces the removed decorative carnival style; all CSS new and self-contained under `stub-*`/`iwt-*`, grep-confirmed no collision with the removed `tk-*` classes). Aged off-white paper, a solid colored header band with “REALGOODTIME.COM PRESENTS” in white mono caps + a short code, dense monospace uppercase body (title, venue, address, prominent date/time line), a SEC/ROW/ADM columned data block with the neighborhood as a code, edge-crawl digits down the left, and a dashed perforation into a torn-edge tear-off stub. Four header-band colors (deep blue, dark red, dark green, black) assigned deterministically by a hash of the title, so a stub's color never changes between renders.
- **Design principles (non-negotiable).** Nothing punishes absence: no streaks, no days-since counters, no decay. The collection only grows — there is no losing state. Honor system: stubs gate nothing; they're purely sentimental.

Verified against the served page before commit: minted from a today-dated show card and from a past-dated Saved show (the past-Saved case was tested by adding a past-dated favorite key — show data was NOT edited to fake a today show); stubs render with correct snapshotted data in the authentic style; reload persists stubs; minting the same show twice yields no duplicate (gentle feedback); future shows show no affordance; the empty state renders when the store is cleared; reset behavior clean; no console errors across all toggles (Tonight, This Week, Picks, By Neighborhood, Venues, Saved, Comedy, Following, Audit) and Reset.

### 6e5ccbc — Remove Tickets view (pill, view mode, stub rendering, CSS)

Subtraction-only removal of the collectible ticket-stub view. Gone: the "Tickets" control-bar pill and its click handler; the `state.tickets` view mode with its early-return render branch and `ticketsOf()`/`tkVariant()` stub renderer; and the entire fenced stub CSS block (stub card styling, perforation, 4-tone header accents).
- **Reversible-by-design, now removed.** The view was always self-contained and flagged as removable; taking it out required no refactoring elsewhere. Mutual-exclusivity wiring in the Saved, Comedy, Reset, and Following handlers had its `state.tickets` / `#ticketsToggle` references stripped so no handler points at a deleted id.
- **Old decorative stub retrievable in git history.** The original carnival-style decorative stub design remains fully recoverable at its introducing commit `d1d64ad` (“Tickets view toggle (collectible ticket-stub cards)”).
- **For the record — planned replacement design.** The upcoming stub-collection feature will NOT reuse this decorative style. It will render an authentic Ticketmaster-era stub: dense monospace data columns, a presenter band, and a torn perforation end.

Verified against the served page before commit: no Tickets pill in the control bar; both inline `<script>` blocks parse clean; no console errors on load or while exercising every remaining toggle (Tonight, This Week, Picks, By Neighborhood, Saved, Venues, Comedy, Following, Audit) and Reset; grep of `index.html` for `state.tickets`, `ticketsOf`, `ticketsToggle`, `tkVariant`, `tk-*`, `stub`, and `perforation` returns zero. The Audit (dev) toggle, poster lightbox, Saved, Following, Comedy, and hearts are untouched. Line delta: 1558 → 1451 (−107).

### 5569a05 — Rename "My Favorites" pill to "Saved"

A display-only relabel of the favorites pill to clarify the split between the two heart-driven features. Nothing behavioral changed — this is purely the visible button text.

- **Pill relabeled My Favorites → Saved.** The rename communicates the distinction between the two heart-driven views: **Saved** is the collection view (everything you've hearted, grouped by shows/bands/venues), while **★ Following** is the feed filter that collapses the show list to bands & venues you follow.
- **Display text only — internals deliberately untouched.** All state variables, `localStorage` keys, element ids (`myShowsToggle`, class `my-shows`), and internal code comments were left as-is; the comments intentionally retain "My Favorites" as internal terminology documenting the distinction. One-line change in `index.html` (`<span>`), verified in preview with the toggle still functioning.
- **Favorites/Following UX open item RESOLVED.** The confusing shared "favorites" labeling is closed out by this rename.

### ba9c448 — Remove Hatfield Hall Rotunda; add Oregon Zoo

Venue-directory cleanup plus a new manually-maintained venue. Hatfield Hall Rotunda is gone from the scraper, its baseline, and the hand-added data; the Oregon Zoo joins as a manual venue because its event pages are not machine-readable. This entry also honestly records a Rose Quarter false start and resolves a stale open item.

- **Hatfield Hall Rotunda fully removed.** Dropped from `VENUE_INFO` in `scrape_venues.py`, deleted from `venue_baselines.json`, purged from `manual_shows.json`, and a defensive `continue` guard was added to the Portland'5 card parser so it can never re-enter. This closes the standing "Hatfield 0-shows" open item by retiring the venue outright.
- **Rose Quarter scraping already existed — net code change: none.** While adding Rose Quarter support I discovered a working `parse_rosequarter` parser and SOURCES entry already committed. A duplicate parser was briefly added, immediately caught via doubled rows + baseline alerts, and fully reverted (`git checkout`). The pre-existing scraper contributes 20 in-horizon shows (Moda Center 13 / Theater of the Clouds 5 / Veterans Memorial Coliseum 2), neighborhood "Lloyd/Rose Quarter", with Music-tag filtering plus a defensive title blocklist (`vs.`, `Winterhawks`, `Blazers`, `Disney On Ice`, etc.) verified against the live feed.
- **Kelly's Olympian open item RESOLVED.** The live feed already carries the venue (visible as "Kelly's Olympian — Downtown — 20 shows") and the daily Action scrapes it without issue; the old anti-bot note was stale and has been retired.
- **Oregon Zoo added as a manually-maintained venue.** The zoo's event pages are Drupal free-text prose with no structured markup, so scraping was not viable; instead 6 verified 2026 ZooNights headliners were hand-added (Jul 17 Norman Sylvester, Jul 24 Ural Thomas & the Pain, Jul 31 Hit Machine, Aug 7 Garcia Birthday Band, Aug 14 Taken by the Sky, Aug 21 Jujuba Entertainment), all 6:30 PM, address 4001 SW Canyon Rd. Neighborhood "Washington Park" is a new convention — no prior Washington Park entries existed.
- **Coliseum/Moda address discrepancy reviewed, existing config retained.** The task specified Coliseum "300 N Ramsay Way" / Moda "1 N Center Court St", but the already-committed config carries "300 N Winning Way" / "1 N Center Ct St", which match the venue's own ticketing listing; the existing values were kept.

Result after the change: 1146 → 1171 shows (+25) across 49 → 50 venues (+1 Oregon Zoo). Hatfield is absent from the rendered Venues directory.

### 0577e72 — Build hygiene: strip HTML from titles, strengthen dedupe key, merge fields on collision

Tightened the `build_shows.py` scrape/build hygiene so raw markup never reaches `shows.json` and near-duplicate rows can no longer slip through the dedupe. This work was found already staged from a prior session; it was reviewed line-by-line and validated against the live data before committing, then extended with the field-merge fix below.

- **`clean_title()` strips tags + decodes entities, applied before dedupe keying.** Titles are decoded, tag-stripped (`<[^>]+>`), decoded again, and whitespace-collapsed at build time, so a `<span>` (or an entity) from a source feed can't reach `shows.json`. Sanitization runs in the row loop *before* the dedupe key is computed, so the cleaned title also feeds the key.
- **`_norm_key()` makes the dedupe key punctuation/dash/HTML-insensitive.** The `(title, venue, date)` key now strips HTML, dash-normalizes, lowercases, and collapses every run of non-alphanumerics to one space. This closes the class of duplicate that let the "Drag Brunch Hosted by Nicoleonoscopi" show survive as two rows (a markup/punctuation variant produced a distinct key under the old title-only normalization). The source has since been cleaned, so on current data this change removes nothing extra — it is prophylactic.
- **Same-day time-collision FLAG path (flags, never silently merges).** When two rows share the normalized title/venue/date and *both* carry a non-empty, differing `time`, the build prints a `WARNING`/`FLAG` and keeps the first rather than merging — these may be two real shows the same day and need a human to confirm.
- **New: field-merge on collision (keep the most-complete row).** When a duplicate is dropped, any field the kept (first-seen) row left empty is back-filled from the dropped row (currently `time`, `imageUrl`, `venueUrl`). Motivating case: `Mountain Grass Unit @ The Get Down 2026-10-03` existed as an empty-time row plus a `9:00 PM` row; the old logic kept the empty-time row and discarded the time. Now the kept row adopts `9:00 PM` (and the image URL) before the dup is dropped. Dedupe no longer discards information.
- **Known residual edge (logged, acceptable for now).** Two *genuinely distinct* same-title/venue/date shows where one row lacks a `time` would still merge (the FLAG guard only fires when both times are present and differ). Not observed in current data; left as-is intentionally.

Build after the change: 1146 shows across 49 venues, no duplicate-removal beyond the one true dupe, and no time-collision flags. Old vs new total unchanged at 1146; the only content delta vs the prior `shows.json` is the two merged fields on the Mountain Grass Unit row.

### 5d5f348 — Remove artist heart from show cards (entry point only)
Removed the band/artist heart from the show cards while leaving the entire band-favorite data model
and matching logic untouched. This mirrors the earlier venue-heart cleanup: only the entry point on
the card was removed, not the underlying feature.

- **Artist heart removed from both card layouts.** The heart was appended in the shared `titleHtml`
builder (`heartFav(bandFavKey(s.title), s.title, 'band')`), so dropping it there removes the artist
heart from both the imageless (`scard`) and horizontal (`s-body`) card layouts at once.
- **Hearts now live in exactly two places.** Show cards keep their save-heart (`heartBtn(s)`); venues
are heartable only on the venue detail page. There is no longer any way to heart an artist from the UI.
- **Data model deliberately preserved.** `bandFavKey`, the `band::` key format, the Following filter's
band-matching (including `_normTitle` normalization), and the My Favorites view's band display + un-heart
control are all intact. Legacy `band::` favorites still match in the Following filter and remain
un-heartable from My Favorites.
- **Follow-on (not built):** artist-hearting has no entry point pending a future proper artist field
(currently band identity is derived from the show title).

Verified against the served page before commit: no artist hearts on show cards (both layouts), save-heart
still present, venue heart works only on the venue detail page, and the Following filter still matches a
`band::` favorite (incl. case/space-normalized). Audit (dev) toggle left in place.

### 8796ed2 — Favorites foundation: bands + venues + consolidated My Favorites view
Extended favoriting beyond shows to bands and venues, and reworked the saved view into a single grouped surface. Also fixed a pre-existing persistence bug that had silently disabled favorites rehydration.
- **Band + venue favoriting added.** Heart toggles now appear on show cards, in the venue directory, and on the venue detail view (previously only show cards had hearts).
- **"My Shows" reworked into "My Favorites".** Single view now groups saved items into Shows / Bands / Venues sections instead of a shows-only list.
- **Storage model.** Uses the existing `state.favorites` Set persisted to `portlandlive:favorites` in localStorage. Keys are namespaced: `band::<id>`, `venue::<id>`, and bare `<id>` for shows. Existing show-heart entries are preserved as-is (no migration needed).
- **Fixed pre-existing persistence bug (TDZ).** `FAV_KEY` was declared *after* `state`, so the rehydrate-on-load path hit a temporal-dead-zone ReferenceError that was swallowed by the surrounding try/catch — favorites silently never rehydrated across a reload. Moved the `FAV_KEY` declaration above `state`. **Note:** this means show-favorites persistence was actually broken before this commit; it is now genuinely working for the first time.
- **Planned follow-on (not yet built):** a favorites-based filter toggle (show only favorited items in the main listings).

### 605b741 — Comedy toggle wired into the control bar
Added a **Comedy** pill to the control bar, matching the existing view-toggle pattern (same
`<label class="pill">` + `<span class="toggle" id="comedyToggle">` markup as Tickets, placed just
before it). The data layer was already scaffolded: `state.comedy` existed and `filtered()` already
had the content-type gate (`state.comedy` → comedy, else music). This change supplies the missing
UI wiring — markup, click handler, and reset hook — without touching classifier logic.
- ON filters the feed to shows tagged `comedy` (uses the existing classifier tag); OFF returns to
  the default music-only view. Comedy view returns **18 shows** (incl. Ali Wong Live + Off Book,
  correctly tagged via the overrides shipped in e3abb7e).
- Reset wiring matches the corrected reset-desync pattern (the Venues/Tickets fix in d3fa40f):
  reset clears `state.comedy` AND removes the `on` class from the pill, so no desync.
- Interaction: turning Comedy on exits the Venues view and clears the Tickets display so two
  conflicting views are never active at once (mirrors how Venues clears competitors).
Verified against the served page: pill appears + highlights on click; feed filters to 18 comedy
shows; reset reverts to music AND the pill goes inactive; Tonight/Tickets and other toggles still
work. Audit (dev) toggle left in place.


### e3abb7e — Classifier name-based overrides live (initial entries)
The FORCE_MUSIC / FORCE_NON_MUSIC override layer (scaffolded prior) is now populated and runs
after the keyword classifier, taking precedence over it. Initial entries:
- FORCE_MUSIC: `"anja huwe"`, `"xmal"` — forces the Anja Huwe / Xmal Deutschland show (mis-tagged
  Other) back into **Music**. Two fragments target the same Star Theater show to survive the
  feed’s "Deustchland" misspelling; redundant match is harmless.
- FORCE_NON_MUSIC: `["ali wong","comedy"]`, `["off book","comedy"]` — force those two stand-up/
  improv acts out of Music and tag them **comedy** (ready for a future comedy toggle);
  `"poetry slam"`, `"drag brunch"` — force the poetry slam and both drag-brunch shows to **other**.
Bucket counts moved (verified against the served audit panel): Music 955→950, Comedy 16→18,
Trivia 50 (unchanged), Other 66→69; total 1087 conserved. Only the targeted acts moved;
spot-checked that no legitimate band was swept out of Music. The **Audit (dev)** toggle is
**retained** for a later re-audit pass (not removed).


### d1d64ad — Tickets view toggle (collectible ticket-stub cards)
Added a self-contained "Tickets" view toggle to index.html: a control-bar pill that re-renders the currently-filtered show set as collectible ticket-stub cards (perforated stub with date/time, band headline, venue + neighborhood, image; Listen / heart / Who-in actions intact). Four deterministic accent variants (hash of venue|title) give visual variety. OFF restores the normal horizontal-card list unchanged. Fully reversible: state.tickets flag + render branch + ticketsOf()/tkVariant() + fenced /* TICKET MODE START/END */ CSS block. Composes with Tonight/This Week/search/Picks; overrides By-Neighborhood grouping while ON.


### a3ba245 — Search from venue page exits venue + searches all shows
Search initiated while viewing a venue now exits the venue and searches across all shows (mirror of the `openVenue` clear-search behavior). Fixes the Havalina "no results" dead-end.

### dacb4cf — Restored Venues directory toggle
Restored the Venues directory toggle: an alphabetical list of all 48 venues with neighborhood and show count; click a venue to open its detail view. For coverage auditing.

### 1b12762 — Added python-dateutil to workflow deps
Added `python-dateutil` to the workflow dependencies (fixes Starday Tavern 0-shows). The daily GitHub Action runs on a clean ubuntu runner, isolated from the broken codespace conda env (which has a requests/urllib3 break).

### 9bf3862 — Cascade images + expanded lineup
Cascade images now use a deterministic `image.id === discovery_id` join, done via RSC-chunk reassembly and `json.loads` (NOT regex). Expanded Cascade from 8 to 12 concerts (added Riley Green; Rob Zombie/Manson; Mötley/Carnival of Sins; uicideboy uicideboy; filtered out Season Tickets). Surgical patch to `shows.json`; fix code in `scrape_venues.py` for future runs.

### dc1d4e3 — Cascade per-event image scoping + Live Nation URLs
Cascade: per-event image scoping plus Live Nation `/event/<discovery_id>/<slug>` URLs (fixed 404 ticket links).

### d3fa40f — Fix Venues + Tickets toggle reset-desync
Reset/Refresh handler reverted the listing (state.view="shows") but never removed the 'on' class from #venuesToggle, so the Venues pill stayed visually active after reset. Added $('#venuesToggle').classList.remove('on') in the reset handler. While auditing the other control-bar toggles, found Tickets shared the same gap: reset cleared neither state.tickets nor the #ticketsToggle 'on' class — fixed both (state.tickets=false; $('#ticketsToggle').classList.remove('on')). Tonight / This Week / Picks / By Neighborhood / My Shows already cleared their flag and un-highlighted their pill correctly, so no change needed. (Audit (dev) toggle is a temp dev tool and out of scope.) Verified against the live served page (port 8000): toggled Venues on → pill highlighted + venues directory shown; hit reset → list reverted to today's shows AND pill went inactive. Same confirmed for Tickets.

### 1b6f8f7 — 2026 Waterfront Blues Festival added to listings

Hand-added three shows (one per day) for the 2026 Waterfront Blues Festival via `manual_shows.json`, then regenerated `shows.json` with `build_shows.py` (1087 → 1090 shows). Festival runs Thu Jul 2, Fri Jul 3, and Sat Jul 4, 2026 at Tom McCall Waterfront Park / Downtown; each entry starts 1:00 PM with the ticket link https://waterfrontbluesfest.com/tickets. Titles are kept parallel and clean ("Waterfront Blues Festival — Day 1/2/3") with no lineup names or fireworks crammed in — the flat per-show schema has no field for those. A proper festival section is the planned follow-on, where the full lineup, per-act set times, and the Jul 4 fireworks detail will live.

### 3165194 — Favorites filter: Following toggle (hide-style) + venue hearts limited to venue page + normalized band/venue matching
- **"★ Following" filter pill added** — hide-style: collapses the feed to shows by hearted bands OR at hearted venues. Applied *before* sort so time-anchored ordering is preserved.
- **Venue hearts relocated** — now appear ONLY on the venue detail page (removed from show cards and the venue directory). Band hearts remain on show cards. The My Favorites view retains venue chips as an un-heart affordance.
- **Normalized matching** — band/venue matching now runs through `_normTitle` at compare-time (case/whitespace-insensitive); stored key format unchanged, so prior hearts still match.
- **Verified** against the live feed, incl. the Waterfront Blues Festival surfacing via its venue heart.

### 980dc1d — Poster lightbox on show cards
Artwork on show cards now opens a reused dimmed overlay; the image is capped at max 90vw / 90vh with object-fit:contain, and closes via the X button, backdrop click, or Escape. Cards with no art are inert, and stopPropagation guards keep card actions from firing when the poster is clicked.

### 2f90395 — Following clarity: match-reason chips + summary line
Matched cards show a muted reason chip (venue priority on a double-match), computed with the same _normTitle comparison the filter uses. A summary line reads "Following N venues · N bands · N shows" (the band segment is omitted at zero). Display-only; no data-model changes.

## Open Items

- **⚠ Push retry loop green-on-failure — FIXED in 6ac9884.** Kept here as the cautionary note: `run:` blocks execute under `bash -e`, which exempts any command that is not the last in an `&&` list, so the old `git pull --rebase origin main && git push && break` could fail all three attempts while the step's last executed command (`sleep 5`) exited 0. This is the defect that hid the 32-day outage. Any future retry loop in this repo must set an explicit success flag and exit non-zero when it is unset.
- **⚠ Baseline-erosion timer (TIME-CRITICAL)** — `check_baselines()` keeps a 10-entry rolling window per venue and only *warns*; it never blocks a write. origin's `venue_baselines.json` was frozen **healthy** precisely because pushes were failing, so Barrel Room's "DROPPED TO 0" alert still fires. Now that pushes resume, every run appends a `0`; after ~10 successful runs the trailing average reaches 0 and the alert stops firing entirely — erasing the evidence of the regression below. The two parser items must be fixed within **days, not weeks**.
- **⚠ Barrel Room parser 72→0** — the Barrel Room scrape returns 0 shows against a trailing baseline of [77, 76, 76, 71, 71, 71, 71, 71, 70, 70]. A real regression that stayed invisible for 32 days because the pipeline was discarding every run. Surfaced by the audit; not yet fixed.
- **⚠ CitySpark / Ponderosa Lounge & Grill 0-shows** — the CitySpark-backed venue parse yields nothing; Ponderosa's baseline history is all zeros, so it has never successfully scraped. Same family as Barrel Room; surfaced by the audit, not yet fixed.
- **Daily no-op commit from archive.json timestamp** — `archive.json` re-stamps `generated` on every run, so the workflow's "no changes → exit 0" short-circuit never triggers and a commit is created daily even when nothing substantive changed. Cosmetic. Fix if the noise ever matters: exclude the timestamp from change-detection.
- **⚠ Audit (dev) toggle still live / user-visible** — **retained on purpose** for a later re-audit pass after the override layer (e3abb7e); remove once the classifier audit is fully signed off.
- **Scraper feed duplicate rows** — at least one show is emitted more than once (e.g. the "Drag Brunch Hosted by Nicoleonoscopi!" row appears twice). A data-cleaning item to investigate scraper-side, same family as the raw `<span>`-in-title artifact in some feed titles. Not yet addressed.
- **Hatfield Hall 0-shows** — undiagnosed.
- **Kelly's Olympian anti-bot block** — challenge 202.
- **Codespace Python env broken** — requests/urllib3.
- **Coverage audit pending** — Venues directory vs. rated venue list.
- **Venues toggle reset-desync** — when the Venues directory toggle is ON and the user clicks the in-page Refresh/Reset button (not browser refresh), the listing reverts to today's shows BUT the Venues toggle pill stays visually ON; the pill active state is not cleared when reset returns to the default show list. Fix: the reset/refresh handler should clear the Venues view flag (state.venues) and un-highlight the pill so toggle state matches the view shown. — **RESOLVED in d3fa40f.**
- **Band favorites key on full show title** — band hearts match against the full show title, not a separate artist field. Follow-up: introduce a dedicated artist field for cleaner band-level favoriting.
- **My Favorites vs ★ Following pill naming (UX)** — the two share the same heart data but behave differently: *My Favorites* is a collection view (everything hearted, grouped) while *★ Following* is a feed filter (collapse listings to hearted matches). The pill names don't communicate this split. Candidate fix: rename (e.g. "Saved" vs "Following") or eventually merge the two. Display/naming only; no behavior change decided yet.
