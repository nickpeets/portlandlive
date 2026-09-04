"""
Headless-browser fetch tier for bot-walled venue sites.

WHY THIS EXISTS
A Sep 2026 survey of all 36 scraper sources found only two behind a
JavaScript bot challenge -- but they're two that matter to the site's core
audience: The Goodfoot (Cloudflare, anchors the jam scene) and Music
Millennium (AWS WAF, in-store shows). Both challenge EVERY path, including
REST APIs and iCal feeds, and full browser-like headers don't pass. The only
thing that passes is a real browser executing the challenge JavaScript.

WHAT IT IS NOT
The primary fetch path. scrape_venues.fetch() (plain requests) stays the
default for the 34 open sources. This is opt-in per source via
{"walled": True} in SOURCES, and is deliberately slow, heavy, and isolated:
one Chromium launch per walled source, hard timeouts, and any failure raises
so the per-venue isolation in scrape_all() logs it and moves on -- exactly
like a ChallengeError from the plain path.

THE TRICK
Once a browser has passed the challenge, its cf_clearance cookie is good for
the whole session -- so a SECOND navigation in the same context to a JSON
endpoint (e.g. WordPress's /wp-json/tribe/events/v1/events) returns clean
JSON with no challenge. That means the walled-venue parsers get structured
data, not rendered HTML to scrape. fetch_headless_json() does exactly that.

DEPENDENCY
    pip install playwright && playwright install chromium --with-deps
The CI workflow installs this. Locally, the same two commands.
"""
import json
import time


class HeadlessUnavailable(Exception):
    """playwright isn't installed -- surfaced as a WARN like any other failure."""


class HeadlessChallengeError(Exception):
    """The browser never got past the challenge within the time budget."""


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# Titles the challenge pages use while they're still working. If the page
# still has one of these after the wait, the challenge didn't clear.
_CHALLENGE_TITLES = ("just a moment", "attention required", "checking your browser",
                     "verifying you are human", "access denied")


def _launch(p):
    # Not the default headless mode: Cloudflare fingerprints it. Chromium's
    # newer headless ("--headless=new") presents a normal browser surface and
    # clears the managed challenge in practice. --disable-blink-features hides
    # the navigator.webdriver flag that the challenge script checks first.
    return p.chromium.launch(
        headless=True,
        args=["--headless=new",
              "--disable-blink-features=AutomationControlled",
              "--no-sandbox"],
    )


def _new_context(browser):
    return browser.new_context(
        user_agent=_UA,
        viewport={"width": 1366, "height": 900},
        locale="en-US",
        timezone_id="America/Los_Angeles",
    )


# Markers in the BODY of a challenge page, for responses that have no <title>
# at all -- a JSON endpoint, for instance, which is exactly what we want back.
_CHALLENGE_BODY = ("just a moment", "cf-challenge", "challenge-platform",
                   "checking your browser", "verifying you are human")


def _looks_challenged(page):
    title = (page.title() or "").strip().lower()
    if title:
        return any(t in title for t in _CHALLENGE_TITLES)
    # No title. Real content with no title is normal for JSON/text responses;
    # a challenge page always has one. Confirm via the body to be safe.
    try:
        body = (page.inner_text("body") or "")[:2000].lower()
    except Exception:
        return True   # nothing rendered yet
    if not body.strip():
        return True   # still blank -- keep waiting
    return any(m in body for m in _CHALLENGE_BODY)


def _wait_out_challenge(page, budget_s):
    """Poll until the page stops looking like a challenge page. An empty
    title is NOT a failure by itself -- JSON responses have no title."""
    deadline = time.time() + budget_s
    while time.time() < deadline:
        if not _looks_challenged(page):
            return
        time.sleep(1.0)
    raise HeadlessChallengeError(
        f"challenge did not clear within {budget_s}s (title={page.title()!r})")


def fetch_headless(url, wait_s=25, settle_s=2):
    """Rendered HTML of `url` after the bot challenge clears."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise HeadlessUnavailable("playwright not installed") from e

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = _new_context(browser)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            _wait_out_challenge(page, wait_s)
            time.sleep(settle_s)
            return page.content()
        finally:
            browser.close()


def fetch_headless_json(entry_url, json_url, wait_s=25):
    """Clear the challenge on `entry_url`, then read `json_url` in the same
    session and return the parsed JSON. This is the preferred path: the
    walled venue's own API, reached with the clearance cookie the browser
    just earned."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise HeadlessUnavailable("playwright not installed") from e

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = _new_context(browser)
            page = ctx.new_page()
            page.goto(entry_url, wait_until="domcontentloaded", timeout=45_000)
            _wait_out_challenge(page, wait_s)
            # Same context, so cf_clearance rides along. The JSON endpoint
            # returns raw JSON text in the body; if it's ALSO challenged the
            # title check catches it.
            page.goto(json_url, wait_until="domcontentloaded", timeout=45_000)
            _wait_out_challenge(page, wait_s)
            body = page.inner_text("body")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                # Some servers wrap JSON in <pre>; inner_text usually strips
                # that, but fall back to the raw content just in case.
                raw = page.content()
                start, end = raw.find("{"), raw.rfind("}")
                if start == -1 or end == -1:
                    start, end = raw.find("["), raw.rfind("]")
                return json.loads(raw[start:end + 1])
        finally:
            browser.close()
