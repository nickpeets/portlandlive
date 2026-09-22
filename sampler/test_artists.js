// Artist-resolver regression cases (Sep 21 2026). node sampler/test_artists.js
const R = require('./artist-resolver.js');
const cases = require('./artist-cases.json');
let bad = 0;
for (const [title, venue, want] of cases) {
  const d = R.deriveArtist(title, venue);
  const got = d.isArtist ? d.artist : null;
  const ok = (got || null) === (want || null);
  if (!ok) { bad++; console.log(`  FAIL ${JSON.stringify(title)} -> ${JSON.stringify(got)} (want ${JSON.stringify(want)}; ${d.reason})`); }
}
console.log(bad ? `${bad} ARTIST FAILURE(S) of ${cases.length}` : `ARTISTS ALL PASS (${cases.length})`);
process.exit(bad ? 1 : 0);
