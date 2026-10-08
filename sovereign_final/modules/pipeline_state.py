"""
modules/pipeline_state.py — who is running the pipeline, and how the last
scheduled run went.

Two processes run pipeline work against one database: the scheduler (daily at
06:00) and the dashboard's sidebar buttons. Nothing stopped both from
scraping a portal or checking LVs at the same time. PipelineLock is a lock
they both take. It lives in the database they already share: SQLite's own
locking works across the two Docker containers, a lock file would not on
every platform. The holder refreshes a heartbeat while it works, so a lock
left behind by a process that died frees itself after STALE_AFTER_S.

The scheduler also writes STATUS_FILE at the start and end of every attempt,
failed or not, so the dashboard can show when the pipeline last ran and
whether it worked. A pipeline whose every scraper failed used to be recorded
as done, and nothing on the dashboard said so.
"""

import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import database
from config import DATA_DIR

log = logging.getLogger("sovereign")

STATUS_FILE   = os.path.join(DATA_DIR, "pipeline_status.json")
HEARTBEAT_S   = 30
STALE_AFTER_S = 300
# A successful run older than this means the scheduler isn't running.
OVERDUE_AFTER = timedelta(hours=30)


# ── Lock ──────────────────────────────────────────────────────────────────────
class PipelineBusy(Exception):
    """Someone else holds the pipeline lock."""

    def __init__(self, lock: dict):
        self.lock = lock
        super().__init__(describe_lock(lock))


def describe_lock(lock: dict) -> str:
    return (f"{lock.get('holder') or 'Another run'} is running "
            f"(since {_short_time(lock.get('acquired_at'))})")


class PipelineLock:
    """`with PipelineLock("scheduler"):` — raises PipelineBusy when the lock
    is still held by someone else after `wait_s` seconds."""

    def __init__(self, holder: str, wait_s: float = 0, poll_s: float = 15):
        self.holder, self.wait_s, self.poll_s = holder, wait_s, poll_s
        self.token = uuid.uuid4().hex
        self._stop = threading.Event()
        self._beat: threading.Thread | None = None

    def acquire(self) -> None:
        deadline = time.monotonic() + self.wait_s
        while True:
            busy = database.try_lock_pipeline(self.holder, self.token, STALE_AFTER_S)
            if busy is None:
                break
            left = deadline - time.monotonic()
            if left <= 0:
                raise PipelineBusy(busy)
            time.sleep(min(self.poll_s, left))
        self._beat = threading.Thread(target=self._heartbeat, daemon=True,
                                      name="pipeline-lock-heartbeat")
        self._beat.start()

    def release(self) -> None:
        self._stop.set()
        try:
            database.unlock_pipeline(self.token)
        except Exception as e:
            # Not fatal: the heartbeat has stopped, so the row goes stale and
            # the next run takes it over.
            log.warning(f"Couldn't release the pipeline lock: {e}")

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            try:
                if not database.heartbeat_pipeline_lock(self.token):
                    log.warning("Pipeline lock lost: it went stale and was taken over.")
                    return
            except Exception as e:
                log.warning(f"Pipeline lock heartbeat failed: {e}")

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


# ── Scheduled-run status ──────────────────────────────────────────────────────
def read_status() -> dict | None:
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def write_status(status: dict) -> None:
    """Write atomically: the dashboard reads this file while it changes."""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    tmp = f"{STATUS_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATUS_FILE)


def _parse(iso: str | None) -> datetime | None:
    try:
        when = datetime.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None
    return when if when and when.tzinfo else None


def _short_time(iso: str | None, now: datetime | None = None) -> str:
    """'06:42' today, else '7 Oct 06:42' — in the time zone the run wrote."""
    when = _parse(iso)
    if not when:
        return "?"
    now = now.astimezone(when.tzinfo) if now else datetime.now(when.tzinfo)
    if when.date() == now.date():
        return when.strftime("%H:%M")
    return f"{when.day} {when.strftime('%b %H:%M')}"


def summarize(status: dict | None, lock: dict | None,
              now: datetime | None = None) -> tuple[str, str]:
    """(level, text) describing the last scheduled run, for the dashboard.
    level is 'ok', 'running', 'warning' or 'error'; 'none' when no run is
    on record."""
    if not status:
        return ("none", "No scheduled run on record yet. The scheduler (started "
                        "with the dashboard in Docker) runs the pipeline daily at 06:00.")
    def when(key):
        return _short_time(status.get(key), now)

    state = status.get("state")
    if state == "running":
        if lock and (lock.get("holder") or "").startswith("scheduler"):
            return "running", f"Scheduled run in progress (started {when('started_at')})."
        return ("error", f"The scheduled run started {when('started_at')} never "
                         f"finished — the scheduler stopped mid-run. It runs again "
                         f"at its next start or at 06:00.")
    if state == "failed":
        retry = status.get("next_retry_at")
        then = (f"Retrying at about {when('next_retry_at')}." if retry else
                "No more retries today — check the scheduler log (logs/scheduler.log).")
        return ("error", f"Scheduled run {when('finished_at')} FAILED: "
                         f"{status.get('error') or 'unknown error'}. {then}")
    failed = [s["step"] for s in status.get("steps", []) if not s.get("ok")]
    finished = _parse(status.get("finished_at"))
    ref = now or datetime.now(finished.tzinfo if finished else None)
    if finished and ref - finished > OVERDUE_AFTER:
        return ("warning", f"Last scheduled run {when('finished_at')} — none since. "
                           f"Is the scheduler running?")
    if failed:
        return ("warning", f"Last scheduled run {when('finished_at')}: done, but "
                           f"{len(failed)} step(s) failed — {', '.join(failed)}.")
    return "ok", f"Last scheduled run {when('finished_at')}: {status.get('summary') or 'done'}."
