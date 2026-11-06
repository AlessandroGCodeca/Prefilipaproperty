"""
modules/fx_rate.py — the EUR/CZK rate, from the Czech National Bank.

Czech listings keep their CZK prices; ranking and the "All markets" view
convert them to EUR with config.CZK_PER_EUR (markets.to_eur). That rate used
to be typed into config.py by hand and went stale. Now:

  - refresh() reads the ČNB daily fixing (denni_kurz.txt, published each
    working day after 14:30 Prague time) and saves it to data/fx_rate.json.
    The scheduler calls it before each run; the dashboard at most hourly.
  - sync() loads that file into config.CZK_PER_EUR / FX_RATE_DATE /
    FX_RATE_SOURCE, so every process (dashboard, scheduler — they share the
    data folder) converts with the newest rate either of them fetched.
  - stale_warning() says so when the rate in use is more than
    FX_STALE_DAYS old (the bank was unreachable for a week, say).

A CZK_PER_EUR set in .env pins the rate: nothing is fetched or loaded over
it, and the staleness warning still applies to its FX_RATE_DATE.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timezone

import config

log = logging.getLogger(__name__)

CNB_URL = ("https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/"
           "kurzy-devizoveho-trhu/denni_kurz.txt")
SOURCE = "ČNB kurzy devizového trhu"
CACHE_PATH = os.path.join(config.DATA_DIR, "fx_rate.json")
FX_STALE_DAYS = 7          # older than this, the dashboard warns
REFETCH_AFTER_S = 6 * 3600  # refresh_if_due(): at most this often
_SYNC_EVERY_S = 60          # sync(): look at the file at most this often

_lock = threading.Lock()
_seen_mtime: float | None = None
_next_sync = 0.0


class FxError(Exception):
    pass


def pinned() -> bool:
    """A CZK_PER_EUR in the environment / .env fixes the rate by hand."""
    return bool((os.getenv("CZK_PER_EUR") or "").strip())


# ── Reading the ČNB file ──────────────────────────────────────────────────────
def parse_cnb(text: str, code: str = "EUR") -> tuple[float, date]:
    """(CZK per 1 unit of `code`, fixing date) from the ČNB daily file:

        05.11.2026 #213
        země|měna|množství|kód|kurz
        EMU|euro|1|EUR|24,290
        ...
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if len(lines) < 3:
        raise FxError("the ČNB file is empty or cut short")
    try:
        fixed = datetime.strptime(lines[0].split()[0], "%d.%m.%Y").date()
    except (ValueError, IndexError):
        raise FxError(f"no date on the ČNB file's first line: {lines[0][:40]!r}") from None
    for line in lines[2:]:
        parts = line.split("|")
        if len(parts) == 5 and parts[3].strip().upper() == code:
            try:
                amount = float(parts[2].replace(" ", ""))
                rate = float(parts[4].replace(" ", "").replace(",", "."))
            except ValueError:
                raise FxError(f"unreadable {code} row in the ČNB file: {line[:60]!r}") from None
            # A misread file (a wrong column, a thousands separator) gives a
            # number far from the euro's 15–40 Kč, which would scramble the
            # combined ranking: refuse it and keep the last rate.
            if amount <= 0 or rate <= 0 or (code == "EUR" and not 15 < rate / amount < 40):
                raise FxError(f"implausible {code} rate in the ČNB file: {line[:60]!r}")
            return rate / amount, fixed
    raise FxError(f"no {code} row in the ČNB file")


def _fetch(timeout: float = 15) -> str:
    import requests
    with requests.Session() as s:
        r = s.get(CNB_URL, timeout=timeout,
                  headers={"User-Agent": "SovereignDashboard/1.0 (exchange rate)"})
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        return r.text


# ── The saved rate ────────────────────────────────────────────────────────────
def _read_cache() -> dict | None:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        rate = float(d["czk_per_eur"])
        date.fromisoformat(d["date"])
        return d if rate > 0 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(d: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)          # a reader never sees half a file


def _apply(d: dict) -> None:
    config.CZK_PER_EUR = float(d["czk_per_eur"])
    config.FX_RATE_DATE = d["date"]
    config.FX_RATE_SOURCE = d.get("source") or SOURCE


def sync(force: bool = False) -> None:
    """Use the newest saved rate. Cheap: looks at the file at most once a
    minute and reads it only when it has changed."""
    global _seen_mtime, _next_sync
    if pinned():
        return
    now = time.monotonic()
    if not force and now < _next_sync:
        return
    _next_sync = now + _SYNC_EVERY_S
    try:
        mtime = os.path.getmtime(CACHE_PATH)
    except OSError:
        return
    if mtime == _seen_mtime and not force:
        return
    with _lock:
        d = _read_cache()
        if d:
            _apply(d)
        _seen_mtime = mtime


def refresh(timeout: float = 15) -> bool:
    """Fetch today's ČNB fixing, save and use it. True when a rate was
    fetched. Never raises: a failure is logged and the last rate stays."""
    if pinned():
        return False
    try:
        rate, fixed = parse_cnb(_fetch(timeout))
    except Exception as e:
        log.warning(f"EUR/CZK: the ČNB rate couldn't be fetched ({type(e).__name__}: {e}); "
                    f"keeping 1 € = {config.CZK_PER_EUR:.3f} Kč of {config.FX_RATE_DATE}")
        return False
    d = {"czk_per_eur": round(rate, 4), "date": fixed.isoformat(), "source": SOURCE,
         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _lock:
        try:
            _write_cache(d)
        except OSError as e:
            log.warning(f"EUR/CZK: the rate couldn't be saved ({e}); using it in this process only")
        _apply(d)
    log.info(f"EUR/CZK: 1 € = {rate:.3f} Kč ({SOURCE}, {fixed.isoformat()})")
    return True


def refresh_if_due(timeout: float = 15) -> bool:
    """refresh() unless a rate was fetched in the last REFETCH_AFTER_S."""
    if pinned():
        return False
    d = _read_cache()
    if d and d.get("fetched_at"):
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(d["fetched_at"])).total_seconds()
            if age < REFETCH_AFTER_S:
                sync()
                return False
        except ValueError:
            pass
    return refresh(timeout)


# ── How old it is ─────────────────────────────────────────────────────────────
def age_days(today: date | None = None) -> int | None:
    """Days since the fixing in use, or None when its date can't be read."""
    try:
        fixed = date.fromisoformat(str(config.FX_RATE_DATE))
    except ValueError:
        return None
    return ((today or date.today()) - fixed).days


def stale_warning(today: date | None = None) -> str | None:
    """A line for the dashboard when the rate is more than FX_STALE_DAYS old."""
    days = age_days(today)
    if days is None:
        return (f"The EUR/CZK rate's date ({config.FX_RATE_DATE!r}) can't be read — "
                f"check FX_RATE_DATE.")
    if days <= FX_STALE_DAYS:
        return None
    how = ("CZK_PER_EUR is set by hand in .env — update it with FX_RATE_DATE, or remove "
           "both to fetch the ČNB rate daily." if pinned() else
           "The ČNB rate couldn't be fetched since — check the internet connection.")
    return (f"The EUR/CZK rate (1 € = {config.CZK_PER_EUR:.3f} Kč) is from "
            f"{config.FX_RATE_DATE}, {days} days ago. Rankings that mix Czech and Slovak "
            f"listings use it. {how}")
