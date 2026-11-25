"""
dashboard/photos.py — a listing's photo for its card (D17) and SATELLITE
VIEWER, fetched by the dashboard's server, never by your browser: the portal
sees the server's address, not yours, and the page shows a copy the server
made itself.

The address comes from a portal's page, which anyone can write, so it is
handled as untrusted:
  - only http(s) on the standard ports, and only to a host whose every
    address is public — never this computer, your network, link-local or
    reserved ranges (checked again on each redirect, at most 3);
  - at most MAX_BYTES read, and only an answer that opens as a picture;
  - re-encoded here as a small JPEG (THUMB_PX on its long side), so what
    reaches the browser is a picture this server made, without the
    original's metadata.

A photo is kept for a week; a failed one is not kept, and isn't tried again
for FAIL_TTL_S, so an open card that can't get one doesn't wait on every
click.
"""

from __future__ import annotations

import io
import ipaddress
import re
import socket
import threading
import time
from urllib.parse import urljoin, urlsplit

import streamlit as st

MAX_BYTES = 6_000_000
THUMB_PX = 640
TIMEOUT_S = 6
FAIL_TTL_S = 600
MAX_REDIRECTS = 3

_failed: dict[str, float] = {}
_lock = threading.Lock()
_URL = re.compile(r"https?://[^\s,;|\"'<>]+", re.I)


class NoPhoto(Exception):
    """No picture: why, in a few words."""


def photo_url(l: dict) -> str:
    """The listing's first photo address ("" when it has none)."""
    for field in ("primary_image_url", "image_urls"):
        m = _URL.search(str(l.get(field) or ""))
        if m:
            return m.group(0)
    return ""


def _public(host: str) -> bool:
    """Whether every address `host` resolves to is a public one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)


def _checked(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise NoPhoto("not a web address")
    if parts.port not in (None, 80, 443):
        raise NoPhoto("an unusual port")
    if not _public(parts.hostname):
        raise NoPhoto("not a public address")
    return url


def _download(url: str) -> bytes:
    import requests

    from scraper._http import BROWSER_HEADERS
    headers = {**BROWSER_HEADERS, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
               "Sec-Fetch-Dest": "image"}
    for _ in range(MAX_REDIRECTS + 1):
        _checked(url)
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT_S, stream=True,
                             allow_redirects=False)
        except requests.RequestException as e:
            raise NoPhoto(f"the portal didn't answer ({type(e).__name__})") from None
        try:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code != 200:
                raise NoPhoto(f"HTTP {r.status_code}")
            body = bytearray()
            for chunk in r.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise NoPhoto("too large")
            return bytes(body)
        finally:
            r.close()
    raise NoPhoto("too many redirects")


def thumbnail(data: bytes) -> bytes:
    """`data` as a JPEG at most THUMB_PX on its long side. NoPhoto when it
    isn't a picture."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = img.convert("RGB")
            img.thumbnail((THUMB_PX, THUMB_PX))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=82, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise NoPhoto("not a picture") from None
    return out.getvalue()


@st.cache_data(ttl=7 * 24 * 3600, max_entries=300, show_spinner=False)
def _photo(url: str) -> bytes:
    return thumbnail(_download(url))


def listing_photo(url: str) -> bytes | None:
    """The photo at `url` as a small JPEG, or None (no address, a refusal,
    not a picture, or a failure in the last FAIL_TTL_S seconds)."""
    if not url:
        return None
    with _lock:
        since = _failed.get(url)
    if since is not None and time.monotonic() - since < FAIL_TTL_S:
        return None
    try:
        return _photo(url)
    except NoPhoto:
        with _lock:
            _failed[url] = time.monotonic()
        return None
