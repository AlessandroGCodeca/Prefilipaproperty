"""
modules/heartbeat.py — tells an outside watcher that the daily run happened.

A stopped scheduler sends nothing, so it cannot report itself: silence looks
the same as "no new deals". A dead man's switch closes that gap. Each run
pings a web address (HEALTHCHECK_URL); the watcher e-mails you when a ping is
late, or at once when the run reports a failure.

  healthchecks.io (free tier): create a check with period 1 day and grace
  3 hours, copy its ping URL (https://hc-ping.com/<uuid>) into .env as
  HEALTHCHECK_URL. Any service that takes the same /start and /fail URLs
  (a self-hosted Healthchecks, for one) works the same way.

Without HEALTHCHECK_URL this does nothing. A ping never fails a run.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

TIMEOUT_S = 10
SIGNALS = ("", "start", "fail")


def url() -> str:
    return (os.getenv("HEALTHCHECK_URL") or "").strip().rstrip("/")


def enabled() -> bool:
    return url().startswith("https://")


def ping(signal: str = "", body: str = "", post=None) -> bool:
    """Send `signal` ("" success, "start", "fail") with `body` as the run's
    log (the watcher shows it). True when the watcher answered 200."""
    if signal not in SIGNALS:
        raise ValueError(signal)
    if not enabled():
        return False
    import requests
    post = post or requests.post
    target = url() + (f"/{signal}" if signal else "")
    try:
        r = post(target, data=(body or "")[:10_000].encode("utf-8"), timeout=TIMEOUT_S)
        ok = getattr(r, "status_code", 0) == 200
        if not ok:
            log.warning(f"Healthcheck {signal or 'success'} ping answered "
                        f"{getattr(r, 'status_code', '?')}")
        return ok
    except Exception as e:
        log.warning(f"Healthcheck {signal or 'success'} ping failed: {type(e).__name__}: {e}")
        return False
