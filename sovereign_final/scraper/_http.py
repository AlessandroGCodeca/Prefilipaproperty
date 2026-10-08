"""
scraper/_http.py — shared HTTP helper
Routes requests through ScraperAPI when SCRAPER_API_KEY is set,
otherwise makes direct requests (works fine on residential IPs).
"""
import logging
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
from config import SCRAPER_API_KEY

log = logging.getLogger(__name__)

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


def get(url: str, session: requests.Session = None, timeout: int = 20, render: bool = False) -> requests.Response:
    """Make a GET request, routing through ScraperAPI if key is configured.
    render=True uses ScraperAPI's headless Chrome to execute JavaScript (needed for SPAs).
    """
    sess = session or requests.Session()
    if SCRAPER_API_KEY:
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
    else:
        sess.headers.update(BROWSER_HEADERS)
        return sess.get(url, timeout=timeout)


def make_session(warmup_url: str = None) -> requests.Session:
    """Create a session, optionally warming up with a homepage request for cookies."""
    import time
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    if warmup_url and not SCRAPER_API_KEY:
        try:
            get(warmup_url, session=s, timeout=10)
            time.sleep(0.5)
        except Exception as e:
            # Only cookies are lost; the real request reports its own error.
            log.warning(f"Warm-up request to {warmup_url} failed: {e}")
    return s
