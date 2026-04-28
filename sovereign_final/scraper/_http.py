"""
scraper/_http.py — shared HTTP helper
Routes requests through ScraperAPI when SCRAPER_API_KEY is set,
otherwise makes direct requests (works fine on residential IPs).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
from config import SCRAPER_API_KEY

SCRAPER_API_BASE = "http://api.scraperapi.com"

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


def get(url: str, session: requests.Session = None, timeout: int = 20) -> requests.Response:
    """Make a GET request, routing through ScraperAPI if key is configured."""
    sess = session or requests.Session()
    if SCRAPER_API_KEY:
        proxy_url = f"{SCRAPER_API_BASE}?api_key={SCRAPER_API_KEY}&url={requests.utils.quote(url, safe='')}"
        return sess.get(proxy_url, timeout=timeout)
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
        except Exception:
            pass
    return s
