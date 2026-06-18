# Build Log

Project history for **portlandlive**, newest first. Append a new entry at the top of the Changelog for each change.

## Changelog

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

## Open Items

- **⚠ Audit (dev) toggle still live / user-visible** — remove once the classifier audit is done.
- **Hatfield Hall 0-shows** — undiagnosed.
- **Kelly's Olympian anti-bot block** — challenge 202.
- **Codespace Python env broken** — requests/urllib3.
- **Coverage audit pending** — Venues directory vs. rated venue list.
- **Venues toggle reset-desync** — when the Venues directory toggle is ON and the user clicks the in-page Refresh/Reset button (not browser refresh), the listing reverts to today's shows BUT the Venues toggle pill stays visually ON; the pill active state is not cleared when reset returns to the default show list. Fix: the reset/refresh handler should clear the Venues view flag (state.venues) and un-highlight the pill so toggle state matches the view shown.
