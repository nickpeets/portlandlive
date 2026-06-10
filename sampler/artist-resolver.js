/*
 * artist-resolver.js  —  PortlandLive artist sampler (STANDALONE PROTOTYPE)
 *
 * NOT wired into the live site. Pure, dependency-free, browser+Node compatible.
 *
 * deriveArtist(title) -> { artist, isArtist, reason }
 *   Takes a raw show title and tries to extract the HEADLINER artist name.
 *   isArtist=false means the title looks like a non-musical/non-artist event
 *   (trivia, karaoke, open mic, bingo, comedy, generic "night" social) and
 *   should show NO player / "no sample available".
 *
 * buildLinks(artist) -> { youtube, spotify, apple } search URLs (no auth, static-safe).
 *
 * sampleFor(title) -> resolution object the UI consumes. <<< FUTURE INTEGRATION POINT >>>
 *   index.html could later import this file and call sampleFor(row.title) to open
 *   a modal / new tab. DO NOT call from the live site yet.
 */

// Phrases that mark a title as NOT an artist booking (whole-title or dominant signal).
var NON_ARTIST = [
  'trivia','quiz night','karaoke','open mic','open jam','bingo','music bingo',
  'comedy show','comedy night','stand-up','standup','drag brunch','drag show',
  'dj night','silent disco','line dancing','salsa night','speed dating',
  'paint night','game night','book club','story slam'
];
// Generic recurring "social" titles with no named act.
var GENERIC = [
  'wednesday social','night social','happy hour','jam session','social club',
  'dance party','live music & dancing','live music and dancing'
];

// Bill separators: headliner is the FIRST act before any of these.
var BILL_SPLIT = /\s+(?:w\/|with|feat\.?|featuring|ft\.?)\s+|\s*(?:\/\/|\+|&|,)\s*/i;

function stripPromo(s){
  // strip trailing tour/show/promo noise and parentheticals
  s = s.replace(/\([^)]*\)/g, ' ');                 // (w/ Local H, Sparta)
  s = s.replace(/\b(presents?|pres\.)\b.*$/i, ' '); // "X presents ..."
  s = s.replace(/[-\u2013:]\s*[^-\u2013:]*\b(tour|all ages|seated show|phase\s*\d+|live music|record release|album release|residency|matinee)\b.*$/i, ' ');
  s = s.replace(/\b(tour|all ages|21\+|18\+|free|sold out|early show|late show)\b\!*/ig, ' ');
  return s;
}

function cleanup(s){
  return s.replace(/\s{2,}/g,' ').replace(/^[\s\-\u2013:,&\/]+|[\s\-\u2013:,&\/!]+$/g,'').trim();
}

function deriveArtist(rawTitle){
  var title = (rawTitle||'').toString();
  var low = title.toLowerCase();
  for (var i=0;i<NON_ARTIST.length;i++){
    if (low.indexOf(NON_ARTIST[i])>=0) return {artist:null,isArtist:false,reason:'non-artist:'+NON_ARTIST[i]};
  }
  for (var j=0;j<GENERIC.length;j++){
    if (low.indexOf(GENERIC[j])>=0) return {artist:null,isArtist:false,reason:'generic:'+GENERIC[j]};
  }
  var work = stripPromo(title);
  // headliner = first act before a bill separator
  var head = work.split(BILL_SPLIT)[0];
  head = cleanup(head);
  // strip a leading promoter like "Foo presents:" handled in stripPromo; also drop leading "the music of"
  head = head.replace(/^the music of\s+/i,'').trim();
  if (!head || head.length < 2) return {artist:null,isArtist:false,reason:'empty-after-clean'};
  // junk if it is mostly non-letters or a bare generic word
  var letters = (head.match(/[a-z]/ig)||[]).length;
  if (letters < 2) return {artist:null,isArtist:false,reason:'no-letters'};
  return {artist:head,isArtist:true,reason:'derived'};
}

function buildLinks(artist){
  var q = encodeURIComponent(artist||'');
  return {
    youtube: 'https://www.youtube.com/results?search_query='+q,
    spotify: 'https://open.spotify.com/search/'+q,
    apple:   'https://music.apple.com/search?term='+q
  };
}

// <<< FUTURE INTEGRATION POINT (do not call from live site yet) >>>
function sampleFor(title){
  var d = deriveArtist(title);
  if (!d.isArtist) return {title:title, artist:null, isArtist:false, reason:d.reason, links:null};
  return {title:title, artist:d.artist, isArtist:true, reason:d.reason, links:buildLinks(d.artist)};
}

if (typeof module!=='undefined' && module.exports){
  module.exports = {deriveArtist:deriveArtist, buildLinks:buildLinks, sampleFor:sampleFor};
}
