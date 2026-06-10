/*
 * artist-resolver.js  —  PortlandLive artist sampler (STANDALONE PROTOTYPE)
 *
 * NOT wired into the live site. Pure, dependency-free, browser + Node compatible.
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

// Bill separators: headliner is the FIRST act before any of these.
var BILL_SPLIT = /\s+(?:w\/|with|feat\.?|featuring|ft\.?)\s+|\s*(?:\/\/|\+|&|,)\s*/i;
// Trailing-noise patterns that make a derived name "noisy" (Tier 2, not Tier 1).
var NOISE = /[:!]|\bhosted by\b|\bvariety show\b|\bvs\b|\bpresents?\b|\banniversary\b|\bspectacle\b|\bchampionships?\b|\bplay(s)?\b/i;

function stripPromo(s){
  s = s.replace(/\([^)]*\)/g, ' ');
  s = s.replace(/\b(presents?|pres\.)\b.*$/i, ' ');
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
    if (low.indexOf(NON_ARTIST[i])>=0)
      return {artist:null,isArtist:false,confidence:null,mediaType:null,reason:'non-artist:'+NON_ARTIST[i]};
  }
  var work = stripPromo(title);
  var head = cleanup(work.split(BILL_SPLIT)[0]).replace(/^the music of\s+/i,'').trim();
  if (!head || head.length < 2)
    return {artist:null,isArtist:false,confidence:null,mediaType:null,reason:'empty-after-clean'};
  var letters = (head.match(/[a-z]/ig)||[]).length;
  if (letters < 2)
    return {artist:null,isArtist:false,confidence:null,mediaType:null,reason:'no-letters'};
  // BUGFIX (a): generic only rejects if the term equals (≈) the whole derived name.
  var headLow = head.toLowerCase();
  for (var g=0; g<GENERIC.length; g++){
    if (headLow === GENERIC[g])
      return {artist:null,isArtist:false,confidence:null,mediaType:null,reason:'generic-exact:'+GENERIC[g]};
  }
  // BUGFIX (b): spoken-word acts -> derive, but mark as spoken (Tier 2 search links).
  var mediaType = 'music';
  for (var sp=0; sp<SPOKEN.length; sp++){
    if (low.indexOf(SPOKEN[sp].trim())>=0){ mediaType='spoken'; break; }
  }
  // confidence: clean enough for an embed only if no leftover noise AND music.
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
function sampleFor(title){
  var d = deriveArtist(title);
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
