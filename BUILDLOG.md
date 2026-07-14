# Build Log

Project history for **portlandlive**, newest first. Append a new entry at the top of the Changelog for each change.

## Changelog

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

- **⚠ Audit (dev) toggle still live / user-visible** — **retained on purpose** for a later re-audit pass after the override layer (e3abb7e); remove once the classifier audit is fully signed off.
- **Scraper feed duplicate rows** — at least one show is emitted more than once (e.g. the "Drag Brunch Hosted by Nicoleonoscopi!" row appears twice). A data-cleaning item to investigate scraper-side, same family as the raw `<span>`-in-title artifact in some feed titles. Not yet addressed.
- **Hatfield Hall 0-shows** — undiagnosed.
- **Kelly's Olympian anti-bot block** — challenge 202.
- **Codespace Python env broken** — requests/urllib3.
- **Coverage audit pending** — Venues directory vs. rated venue list.
- **Venues toggle reset-desync** — when the Venues directory toggle is ON and the user clicks the in-page Refresh/Reset button (not browser refresh), the listing reverts to today's shows BUT the Venues toggle pill stays visually ON; the pill active state is not cleared when reset returns to the default show list. Fix: the reset/refresh handler should clear the Venues view flag (state.venues) and un-highlight the pill so toggle state matches the view shown. — **RESOLVED in d3fa40f.**
- **Band favorites key on full show title** — band hearts match against the full show title, not a separate artist field. Follow-up: introduce a dedicated artist field for cleaner band-level favoriting.
- **My Favorites vs ★ Following pill naming (UX)** — the two share the same heart data but behave differently: *My Favorites* is a collection view (everything hearted, grouped) while *★ Following* is a feed filter (collapse listings to hearted matches). The pill names don't communicate this split. Candidate fix: rename (e.g. "Saved" vs "Following") or eventually merge the two. Display/naming only; no behavior change decided yet.
