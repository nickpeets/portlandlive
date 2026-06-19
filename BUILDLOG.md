# Build Log

Project history for **portlandlive**, newest first. Append a new entry at the top of the Changelog for each change.

## Changelog

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

## Open Items

- **⚠ Audit (dev) toggle still live / user-visible** — **retained on purpose** for a later re-audit pass after the override layer (e3abb7e); remove once the classifier audit is fully signed off.
- **Scraper feed duplicate rows** — at least one show is emitted more than once (e.g. the "Drag Brunch Hosted by Nicoleonoscopi!" row appears twice). A data-cleaning item to investigate scraper-side, same family as the raw `<span>`-in-title artifact in some feed titles. Not yet addressed.
- **Hatfield Hall 0-shows** — undiagnosed.
- **Kelly's Olympian anti-bot block** — challenge 202.
- **Codespace Python env broken** — requests/urllib3.
- **Coverage audit pending** — Venues directory vs. rated venue list.
- **Venues toggle reset-desync** — when the Venues directory toggle is ON and the user clicks the in-page Refresh/Reset button (not browser refresh), the listing reverts to today's shows BUT the Venues toggle pill stays visually ON; the pill active state is not cleared when reset returns to the default show list. Fix: the reset/refresh handler should clear the Venues view flag (state.venues) and un-highlight the pill so toggle state matches the view shown. — **RESOLVED in d3fa40f.**
