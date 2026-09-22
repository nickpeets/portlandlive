// Nightly artist audit (Sep 21 2026). node sampler/artist-audit.js shows.json
// For every music show: which act the Listen links (and, later, artist
// tracking) would use. Flags names that still look like a series label, a
// venue, or a whole bill, so the resolver can be taught before anyone sees it.
const fs = require('fs');
const R = require('./artist-resolver.js');
const d = JSON.parse(fs.readFileSync(process.argv[2] || 'shows.json', 'utf8'));
const shows = (d.shows || d).filter(x => x.contentType !== 'comedy');
const SUS = /\b(mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|series|showcase|residency|happy hour|brunch|social|live music|live from|sounds of|presents|anniversary|benefit|fundraiser)\b/i;
const tiers = {1: 0, 2: 0, 3: 0}, flags = [], seen = new Set();
for (const x of shows) {
  const r = R.sampleFor(x.title, x.venue); tiers[r.tier]++;
  if (r.tier === 3 || seen.has(x.title)) continue; seen.add(x.title);
  const a = r.artist || '', why = [];
  const m = a.match(SUS); if (m) why.push('label "' + m[0] + '"');
  const vn = (x.venue || '').toLowerCase().replace(/^the /, '');
  if (vn && a.toLowerCase().includes(vn)) why.push('venue name');
  if (a.split(/\s+/).length > 7) why.push('long');
  if (why.length) flags.push(`      [${why.join(', ')}] ${x.venue} | ${x.title.slice(0, 60)} -> ${a.slice(0, 40)}`);
}
console.log(`  Artist audit: ${shows.length} music shows -> ${tiers[1]} clean act, ${tiers[2]} rough act, ${tiers[3]} no act; ${flags.length} name(s) need a look`);
flags.slice(0, 25).forEach(l => console.log(l));
