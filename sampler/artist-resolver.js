/*
 * artist-resolver.js  —  PortlandLive artist sampler (STANDALONE PROTOTYPE)
 *
 * LIVE: index.html loads this for every Listen button (sampleFor(title, venue)).
 * Pure, dependency-free, browser + Node compatible. Regression cases in
 * artist-cases.json (node sampler/test_artists.js); nightly audit in
 * artist-audit.js (printed by the build).
 * Static-Pages-safe: no network calls here, no secrets, no API tokens.
 *
 * deriveArtist(title) -> { artist, isArtist, confidence, mediaType, reason }
 *   artist     : derived headliner name (or null)
 *   isArtist   : false => Tier 3 (non-artist event: trivia/karaoke/open mic/etc.)
 *   confidence : 'clean' => safe for a music embed (Tier 1); 'noisy' => search links (Tier 2)
 *   mediaType  : 'music' | 'spoken' (comedians/talks -> 'spoken' => never auto music-embed)
 *
 * sampleFor(title) -> resolution object the UI consumes. <<< FUTURE INTEGRATION POINT >>>
 *   index.html could later import this file and call sampleFor(row.title) to open a
 *   modal / new tab. DO NOT call from the live site yet.
 */

// Whole-title / dominant markers that mean NOT an artist booking (Tier 3).
var NON_ARTIST = [
  'trivia','quiz night','karaoke','open mic','open jam','bingo','music bingo',
  'comedy show','comedy night','stand-up','standup','drag brunch','drag show',
  'dj night','silent disco','line dancing','salsa night','speed dating',
  'paint night','game night','book club','story slam'
];
// Generic recurring "social" labels. BUGFIX (a): only reject when the generic term
// IS essentially the whole derived name, not when it is a substring of a real band
// name (e.g. "...Fantastic Happy Hour Band" must NOT be rejected).
var GENERIC = [
  'wednesday social','night social','happy hour','jam session','social club',
  'dance party','live music & dancing','live music and dancing','live music'
];
// Spoken-word / non-music acts: still derive a name (good for search) but never
// auto music-embed. BUGFIX (b).
var SPOKEN = [
  'in conversation',' live in portland',' comedy',' stand up',' standup',
  ' a conversation',' speaks',' book tour',' lecture',' podcast',' storytelling'
];

// Trailing-noise patterns that make a derived name "noisy" (Tier 2, not Tier 1).
var NOISE = /[:!]|\bhosted by\b|\bvariety show\b|\bvs\b|\bpresents?\b|\banniversary\b|\bspectacle\b|\bchampionships?\b|\bplay(s)?\b/i;

// ---- Series labels (Sep 21 2026, Nick: "Music Mondays W/ Richard Gans" sent
// YouTube to "Music Mondays"). A venue's recurring night often leads the title
// ("Whiskey Wednesday with ...", "Live Music: ...", "PJCE Happy Hour Jazz w/
// ..."). When the part before a separator is such a label, the act is the part
// after it; when the label trails ("... - Jazz Titan Thursdays"), the act is
// the part before.
var DAYS = '(?:mon|tues?|wednes|thurs?|fri|satur|sun)days?';
var LABEL = new RegExp('\\b' + DAYS + '\\b|\\bni(?:ght|te)s?\\s*[!.]*$|\\bnight (?:special|social)\\b|\\w*fest\\b|\\bresidency\\b|\\blive music\\b|\\blive from\\b|' +
  '\\bhappy[- ]hour\\b|\\bsuperjam\\b|\\bvaudeville\\b|\\bsounds of\\b|\\bseries\\b|\\bshowcase\\b|\\bpresents?\\b|' +
  '\\bspecial\\b|\\bsocial\\b|\\bbrunch\\b|\\bjam session\\b|\\bopen stage\\b|\\bfest(ival)?\\b|' +
  '^live\\s+(?:music|bluegrass|jazz|blues|country|folk|band|dj)\\b|^djs?$', 'i');
function isLabel(s){
  s = (s || '').trim();
  if (!s) return false;
  // "WEDNESDAY 13" is a band: a weekday followed by a number is a name.
  if (new RegExp('^' + DAYS + '\\s+\\d', 'i').test(s)) return false;
  return LABEL.test(s);
}
// Whole-title nights with no act at all.
var WHOLE_NIGHT = new RegExp('^(?:' + DAYS + '\\s+\\S+|\\S+\\s+' + DAYS + ')$', 'i');
var NIGHT_END = /\b(night|party|social|scaries|brewfest|oktoberfest|festival|fest)\s*[!.]*$/i;
// Bill separators: headliner is the FIRST act before any of these.
var BILL_SPLIT = /\s+(?:with|feat\.?|featuring|ft\.?|and\s+(?:special\s+)?guests?)\s+|\s+w\/\s*|\s*(?:\/\/?|\+|&|,|•|\u00b7|\||\s\*\s)\s*/i;
// Series separators: the first of these splits "label: act" or "act - label".
var SERIES_SPLIT = /\s*:\s+|\s+\|\s+|\s+[-\u2013\u2014]+\s+|\s+presented by\s+|\s+presents?\b\s*[-\u2013\u2014:]*\s*|\s+(?:with|featuring|feat\.?)\s+|\s+w\/\s*/i;
// Tails that are about the night, not the act.
var TAILS = [
  /\s+(?:and|&)\s+(?:dance\s+)?lessons\b.*$/i,
  /[’']s\s+(?:\w+\s+){0,2}jam\b.*$/i,                          // "Kevin Selfe's Blues Jam"
  /\s+(?:vocal\s+)?(?:jazz|blues|bluegrass|old[- ]time|funk|soul)?\s*jam\b.*$/i,  // "Ron Steen Vocal Jazz Jam"
  /\s+listening party\b.*$/i,
  /\s+record release\b.*$/i, /\s+album release\b.*$/i,
  /\s+happy[- ]hour\b.*$/i, /\s+residency\b.*$/i,
  /\s+[-\u2013\u2014]\s*showcase\b.*$/i,
  /[’']s$/i,                                                    // "JOHN SCOFIELD'S"
  /\s+on vocals\b.*$/i,
  /\s*[-\u2013]\s*live music\b.*$/i,                         // "Mango Twist- Live Music & Dancing!"
  /\s*-\s*performing\b.*$/i, /\s+performs?\b.*$/i,
  /\s+live$/i                                                  // "Tree Frogs Live (at Tomorrow's Verse)"
];
// What's left after a series label that still isn't an act.
var NOT_ACT = /^(?:cigars?|dominos?|music|dancing|food|drinks|games|djs?|friends|special guests?|guests?|tba|tbd|and more|lessons?|karaoke)$/i;

function stripPromo(s){
  s = s.replace(/\([^)]*\)/g, ' ').replace(/\[[^\]]*\]/g, ' ');
  s = s.replace(/["\u201c\u201d][^"\u201c\u201d]*["\u201c\u201d]/g, ' ');       // quoted show titles
  s = s.replace(/\s+[-\u2013\u2014]\s*(?:ages\s+)?(?:all ages|21\+|18\+)(?:\s+event)?\s*$/i, ' ');
  s = s.replace(/^\s*moved to [^:]+:\s*/i, ' ');
  s = s.replace(/^\s*(?:canceled|cancelled|postponed|sold out|moved)\s*[:!\-\u2013]+\s*/i, ' ');
  s = s.replace(/\bdoors\s+\d{1,2}(?::\d\d)?\s*[ap]m\b/ig, ' ');
  s = s.replace(/[-\u2013:]\s*[^-\u2013:]*\b(tour|all ages|seated show|phase\s*\d+|record release|album release|matinee)\b.*$/i, ' ');
  s = s.replace(/\b(tour|all ages|21\+|18\+|free|sold out|early show|late show)\b\!*/ig, ' ');
  return s;
}
function cleanup(s){
  return s.replace(/\s{2,}/g,' ').replace(/^[\s\-\u2013\u2014:,&\/!]+|[\s\-\u2013\u2014:,&\/!]+$/g,'').trim();
}
function stripVenue(s, venue){
  if (!venue) return s;
  var v = venue.replace(/^the\s+/i, '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return s.replace(new RegExp('\\s+at\\s+(?:the\\s+)?' + v + '\\b', 'i'), '');
}
function stripTails(s){
  var prev;
  do { prev = s; for (var i = 0; i < TAILS.length; i++) s = s.replace(TAILS[i], ''); s = cleanup(s); } while (s !== prev);
  return s;
}
function none(reason){ return {artist:null,isArtist:false,confidence:null,mediaType:null,reason:reason}; }

function deriveArtist(rawTitle, venue){
  var title = (rawTitle||'').toString();
  var low = title.toLowerCase();
  for (var i=0;i<NON_ARTIST.length;i++){
    if (low.indexOf(NON_ARTIST[i])>=0) return none('non-artist:'+NON_ARTIST[i]);
  }
  if (/dance party|oktoberfest|brewfest/i.test(title)) return none('non-artist:party');
  var work = cleanup(stripVenue(stripPromo(title), venue));
  // Series label on one side of the first series separator.
  var m = SERIES_SPLIT.exec(work);
  if (m) {
    var left = cleanup(work.slice(0, m.index)), right = cleanup(work.slice(m.index + m[0].length));
    var byBill = /^\s+(?:w\/|with|featuring|feat\.?)\s+$/i.test(m[0]);
    if (isLabel(left) && right) work = right;
    else if (isLabel(right) && left) work = left;
    // "Artist - Tour Name", "Artist: Show Title": the act leads.
    else if (!byBill && left) work = left;
  } else if (WHOLE_NIGHT.test(work) || (NIGHT_END.test(work) && !/listening party/i.test(work) && !BILL_SPLIT.test(work) && work.split(/\s+/).length <= 5)) {
    return none('series-only');
  }
  var hadBill = BILL_SPLIT.test(work);
  var head = cleanup(work.split(BILL_SPLIT)[0]).replace(/^the music of\s+/i,'').trim();
  head = stripTails(head);
  if (!head || head.length < 2) return none('empty-after-clean');
  var letters = (head.match(/[a-z]/ig)||[]).length;
  if (letters < 2) return none('no-letters');
  var headLow = head.toLowerCase();
  if (NOT_ACT.test(head)) return none('placeholder');
  if (!hadBill && NIGHT_END.test(head) && !/listening party/i.test(head) && head.split(/\s+/).length <= 5 && isLabel(head)) return none('series-only');
  for (var g=0; g<GENERIC.length; g++){
    if (headLow === GENERIC[g]) return none('generic-exact:'+GENERIC[g]);
  }
  if (isLabel(head) && WHOLE_NIGHT.test(head)) return none('series-only');
  var mediaType = 'music';
  for (var sp=0; sp<SPOKEN.length; sp++){
    if (low.indexOf(SPOKEN[sp].trim())>=0){ mediaType='spoken'; break; }
  }
  var confidence = (mediaType==='music' && !NOISE.test(head) && head.length<=40) ? 'clean' : 'noisy';
  return {artist:head, isArtist:true, confidence:confidence, mediaType:mediaType, reason:'derived'};
}

function buildLinks(artist){
  var q = encodeURIComponent(artist||'');
  return {
    youtube: 'https://www.youtube.com/results?search_query='+q,
    spotify: 'https://open.spotify.com/search/'+q,
    apple:   'https://music.apple.com/search?term='+q
  };
}
// YouTube no-auth embed: an embedded search-results playlist. Static-safe, no API key.
function youtubeEmbedUrl(artist){
  return 'https://www.youtube.com/embed?listType=search&list='+encodeURIComponent(artist||'');
}

// <<< FUTURE INTEGRATION POINT (do not call from live site yet) >>>
function sampleFor(title, venue){
  var d = deriveArtist(title, venue);
  if (!d.isArtist)
    return {title:title, tier:3, artist:null, mediaType:null, reason:d.reason, embed:null, links:null};
  var links = buildLinks(d.artist);
  if (d.confidence==='clean')
    return {title:title, tier:1, artist:d.artist, mediaType:d.mediaType, reason:d.reason,
            embed:{type:'youtube', url:youtubeEmbedUrl(d.artist)}, links:links};
  return {title:title, tier:2, artist:d.artist, mediaType:d.mediaType, reason:d.reason, embed:null, links:links};
}

var __api = {deriveArtist:deriveArtist, buildLinks:buildLinks,
             youtubeEmbedUrl:youtubeEmbedUrl, sampleFor:sampleFor};
if (typeof module!=='undefined' && module.exports){
  module.exports = __api;                 // Node / future bundler import
} else if (typeof window!=='undefined'){
  window.deriveArtist = deriveArtist;     // browser globals for sampler/index.html
  window.buildLinks = buildLinks;
  window.youtubeEmbedUrl = youtubeEmbedUrl;
  window.sampleFor = sampleFor;
  window.ArtistResolver = __api;
}
