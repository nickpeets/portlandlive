// Act names for a list of shows (Sep 22 2026, Picks buzz). Reads
// [[title, venue], ...] as JSON on stdin, prints [artist-or-null, ...].
// Same resolver the Listen button uses.
const R = require('./artist-resolver.js');
let buf = '';
process.stdin.on('data', d => buf += d);
process.stdin.on('end', () => {
  const rows = JSON.parse(buf || '[]');
  process.stdout.write(JSON.stringify(rows.map(([t, v]) => {
    const d = R.deriveArtist(t, v);
    return d.isArtist ? d.artist : null;
  })));
});
