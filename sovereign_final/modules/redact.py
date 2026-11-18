"""
modules/redact.py — keeps the keys in .env out of logs and error messages.

Some services take their key in the URL (Google Geocoding, the Telegram Bot
API, ScraperAPI), and `requests` puts the whole URL into the text of its
errors. A log line or an on-screen warning made from such an error would carry
the key into logs/scheduler.log, a backup of the logs or a screenshot. Every
value of a setting whose name marks it as a secret is masked as "***" before a
log line is written (RedactingFilter on the log handlers) and wherever the
code shows an error's text (redact()).
"""

from __future__ import annotations

import logging
import os
import re

MASK = "***"
# A setting is a secret when its name ends with one of these. HEALTHCHECK_URL
# is one too: whoever has it can report a run that never happened.
_SECRET_NAME = re.compile(r"(_KEY|_TOKEN|_SECRET|_PASSWORD|_API_KEY|HEALTHCHECK_URL)$")
# Shorter values ("1", "true", a chat id) are not masked: they would blank
# out ordinary words and numbers in the log.
MIN_LEN = 8


def secret_values(environ=None) -> list[str]:
    """The values of the secret settings, longest first (a key that contains
    another is masked whole)."""
    env = os.environ if environ is None else environ
    vals = {v.strip() for k, v in env.items()
            if _SECRET_NAME.search(k) and v and len(v.strip()) >= MIN_LEN}
    return sorted(vals, key=len, reverse=True)


def redact(text, environ=None) -> str:
    """`text` with every secret value replaced by ***."""
    s = "" if text is None else str(text)
    for v in secret_values(environ):
        if v in s:
            s = s.replace(v, MASK)
    return s


class RedactingFilter(logging.Filter):
    """Masks the secrets in a record's message (its arguments included)
    before a handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_info[1] is not None:
            # The traceback's last line is the error's text: format it here,
            # masked, so the handler doesn't format the raw one.
            text = logging.Formatter().formatException(record.exc_info)
            record.exc_text, record.exc_info = redact(text), None
        return True


def install(logger: logging.Logger | None = None) -> None:
    """Put the filter on each handler of `logger` (the root logger by
    default). Filters on a handler see every record it writes, whichever
    logger it came from. Safe to call again."""
    for h in (logger or logging.getLogger()).handlers:
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(RedactingFilter())
