"""
dashboard/messages.py — what a failure means and what to do about it (D12).

A portal's "HTTP 403" or a geocoder's "ConnectTimeout" says what failed, not
what to do. next_step() turns the usual ones into one plain sentence; the
technical text is still shown beside it, for a bug report.
"""

from __future__ import annotations

import re

_STEPS = (
    # (pattern in the error text, what it means and what to do)
    (r"\b(401|403)\b|forbidden|captcha|cloudflare|access denied",
     "The site turned the scraper away; it may be blocking automated visits. The next "
     "daily run tries again. If it fails three days running, run TEST SITES under "
     "DIAGNOSTICS in the sidebar."),
    (r"\b429\b|too many requests|rate.?limit",
     "The site asked for fewer visits. Nothing to do: the next daily run tries again."),
    (r"\b404\b|not found",
     "The page wasn't there. The portal may have changed its addresses, and the scraper "
     "will need an update if it keeps happening."),
    (r"\b5\d\d\b|bad gateway|service unavailable|internal server error",
     "The site was down. Nothing to do: the next daily run tries again."),
    (r"timeout|timed out|connect|name resolution|getaddrinfo|network|unreachable|ssl",
     "No answer. Check that this computer is online; if it is, the site was slow and the "
     "next run tries again."),
    (r"api.?key|request_denied|unauthori[sz]ed|invalid.?key|no key",
     "A key is missing or refused. Check it in .env (the setup list on TODAY shows which), "
     "then restart the dashboard."),
)


def next_step(error) -> str:
    """One sentence on what to do about `error` (an exception, an HTTP status
    code or a message); "" when it isn't one of the usual ones."""
    if error is None or error == "":
        return ""
    text = f"{type(error).__name__} {error}" if isinstance(error, BaseException) else str(error)
    low = text.lower()
    for pattern, step in _STEPS:
        if re.search(pattern, low):
            return step
    return ""
