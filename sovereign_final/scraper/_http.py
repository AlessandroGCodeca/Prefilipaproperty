"""
scraper/_http.py — shared HTTP helper.

Without SCRAPER_API_KEY every request goes directly to the site (fine on a
home connection). With it, SCRAPER_API_MODE decides (EF4):

  fallback  (the default) each site is read directly first; a site that turns
            the direct read away (HTTP 403 / 407 / 429 / 503, a challenge page,
            a dropped connection) is read again through ScraperAPI, and through
            it for the next ROUTE_TTL_S seconds (the rest of the run). A
            portal that answers your own connection costs no credit.
  always    every request through ScraperAPI (a server whose address every
            portal refuses), as before EF4.
  off       never through ScraperAPI, key or not.
"""
import logging
import os
import sys
import threading
import time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
from config import SCRAPER_API_KEY, SCRAPER_API_MODE

log = logging.getLogger(__name__)

# How long a site that turned a direct read away keeps going through
# ScraperAPI: longer than a run, shorter than the gap to the next one, so
# every daily run tries the cheap way first again.
ROUTE_TTL_S = 6 * 3600
_proxied: dict[str, float] = {}        # host -> when it turned us away
_lock = threading.Lock()               # the portals may be read side by side

# What a site answers when it won't serve this address (not "page not found").
BLOCKED_STATUS = {403, 407, 429, 503}
# A challenge page in place of the content. Checked on short answers only:
# a real listing page can carry a contact form's reCAPTCHA script.
_CHALLENGE = ("captcha", "cf-chl", "just a moment...", "access denied", "_incapsula_",
              "request unsuccessful", "are you a robot")
_CHALLENGE_MAX_BYTES = 20_000

# https: the key rides in the query string, and over plain http it (and every
# URL being scraped) crosses the network in the clear.
SCRAPER_API_BASE = "https://api.scraperapi.com"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "sk-SK,sk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _redacted(exc: requests.RequestException) -> requests.RequestException:
    """The same kind of exception with the ScraperAPI key masked in its text."""
    text = str(exc).replace(SCRAPER_API_KEY, "***")
    try:
        return type(exc)(text)
    except Exception:
        return requests.RequestException(text)


def _mode() -> str:
    """"fallback", "always" or "off"; "off" without a key."""
    if not SCRAPER_API_KEY:
        return "off"
    mode = (SCRAPER_API_MODE or "fallback").strip().lower()
    return mode if mode in ("fallback", "always", "off") else "fallback"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_proxied(url: str) -> bool:
    """Whether a request for `url` goes through ScraperAPI right now."""
    mode = _mode()
    if mode != "fallback":
        return mode == "always"
    with _lock:
        since = _proxied.get(_host(url))
    return since is not None and time.monotonic() - since < ROUTE_TTL_S


def _remember_blocked(url: str, why: str) -> None:
    host = _host(url)
    with _lock:
        fresh = host not in _proxied or time.monotonic() - _proxied[host] >= ROUTE_TTL_S
        _proxied[host] = time.monotonic()
    if fresh:
        log.info(f"{host} turned the direct read away ({why}): reading it through "
                 f"ScraperAPI for the rest of this run")


def blocked(resp) -> str:
    """Why `resp` is a refusal rather than the page ("" when it is the page)."""
    status = getattr(resp, "status_code", 200)
    if status in BLOCKED_STATUS:
        return f"HTTP {status}"
    if status == 200:
        body = getattr(resp, "content", b"") or b""
        if len(body) <= _CHALLENGE_MAX_BYTES:
            low = body.decode("utf-8", "replace").lower()
            hit = next((m for m in _CHALLENGE if m in low), None)
            if hit:
                return f"a challenge page ({hit})"
    return ""


def _direct(url: str, sess: requests.Session, timeout: int) -> requests.Response:
    sess.headers.update(BROWSER_HEADERS)
    return sess.get(url, timeout=timeout)


def _via_scraperapi(url: str, sess: requests.Session, timeout: int,
                    render: bool) -> requests.Response:
    proxy_url = (
        f"{SCRAPER_API_BASE}?api_key={SCRAPER_API_KEY}"
        f"&url={requests.utils.quote(url, safe='')}"
        + ("&render=true" if render else "")
    )
    try:
        return sess.get(proxy_url, timeout=timeout)
    except requests.RequestException as e:
        # requests puts the full URL — api_key included — in its error
        # text, and the pipeline logs that text to logs/scheduler.log.
        raise _redacted(e) from None


def get(url: str, session: requests.Session = None, timeout: int = 20, render: bool = False) -> requests.Response:
    """GET `url`: directly, or through ScraperAPI as SCRAPER_API_MODE says (see
    the module's note). render=True uses ScraperAPI's headless Chrome to run
    the page's JavaScript, which a direct read can't, so it always goes
    through ScraperAPI when there is a key."""
    sess = session or requests.Session()
    mode = _mode()
    if mode == "off":
        return _direct(url, sess, timeout)
    if mode == "always" or render or is_proxied(url):
        return _via_scraperapi(url, sess, timeout, render)
    try:
        resp = _direct(url, sess, timeout)
    except requests.ConnectionError as e:     # dropped or refused: maybe this address
        _remember_blocked(url, type(e).__name__)
        return _via_scraperapi(url, sess, timeout, render)
    why = blocked(resp)
    if not why:
        return resp
    _remember_blocked(url, why)
    return _via_scraperapi(url, sess, timeout, render)


def make_session(warmup_url: str | None = None) -> requests.Session:
    """Create a session, optionally warming up with a homepage request for cookies."""
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    # Cookies only help the direct reads: never spend a ScraperAPI credit on
    # them. A warm-up the site turns away sends the run's requests for that
    # site straight through ScraperAPI, without a wasted direct try each.
    if warmup_url and _mode() != "always" and not is_proxied(warmup_url):
        try:
            resp = _direct(warmup_url, s, 10)
            why = blocked(resp)
            if why and _mode() == "fallback":
                _remember_blocked(warmup_url, why)
            time.sleep(0.5)
        except Exception as e:
            # Only cookies are lost; the real request reports its own error.
            if isinstance(e, requests.ConnectionError) and _mode() == "fallback":
                _remember_blocked(warmup_url, type(e).__name__)
            log.warning(f"Warm-up request to {warmup_url} failed: {e}")
    return s
