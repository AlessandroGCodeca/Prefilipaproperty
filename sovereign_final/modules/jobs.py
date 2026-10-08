"""
modules/jobs.py — the dashboard's pipeline buttons, run in the background.

A sidebar button used to run its step inside the Streamlit script. The page
froze until the step finished (a scrape or an LV run takes minutes; one
cadastre lookup alone can retry for minutes), a scraper that outran its
timeout crashed the page, and the result message was wiped by the rerun that
followed. Nothing stopped the same step running in the scheduler at the same
time.

Now a click hands the step to a worker thread under the pipeline lock
(modules/pipeline_state) and returns at once. The sidebar polls the job for
its progress and keeps its result on screen until the next job starts.

One job at a time per dashboard process, shared by every browser tab.
"""

import logging
import threading
import time
from dataclasses import dataclass

from modules.pipeline_state import PipelineBusy, PipelineLock

log = logging.getLogger("sovereign")


@dataclass
class Job:
    id: int
    label: str
    started: float
    progress: float | None = None   # 0..1 when the step reports it
    note: str = ""
    finished: float | None = None
    level: str = ""                 # success / info / warning / error, once finished
    message: str = ""

    @property
    def running(self) -> bool:
        return self.finished is None

    def elapsed(self) -> str:
        s = int((self.finished or time.time()) - self.started)
        return f"{s // 60}:{s % 60:02d}"


_guard = threading.Lock()
_job: Job | None = None             # the running job, or the last one to finish
_thread: threading.Thread | None = None
_seq = 0


def current() -> Job | None:
    return _job


def running() -> bool:
    return _job is not None and _job.running


def start(label: str, step) -> str | None:
    """Run `step(progress)` in the background. `step` returns (level,
    message); it may call progress(i, n, note="") as it goes. Returns None
    when the job started, else why it didn't."""
    global _job, _thread, _seq
    with _guard:
        if running():
            return f"{_job.label} is still running — wait for it to finish."
        lock = PipelineLock(f"dashboard: {label}")
        try:
            lock.acquire()
        except PipelineBusy as busy:
            return f"{busy}. Try again when it has finished."
        _seq += 1
        job = Job(id=_seq, label=label, started=time.time())
        _job = job
        _thread = threading.Thread(target=_work, args=(job, step, lock),
                                   daemon=True, name=f"job-{label}")
        _thread.start()
    return None


def _work(job: Job, step, lock: PipelineLock) -> None:
    def progress(i, n, note=""):
        job.progress = min(i / n, 1.0) if n else None
        job.note = f"{i}/{n}" + (f" · {note}" if note else "")

    try:
        level, message = step(progress)
    except Exception as e:
        log.exception(f"Dashboard job {job.label} failed")
        level, message = "error", f"❌ {job.label} failed: {e}"
    finally:
        lock.release()
    job.level, job.message = level, message
    job.finished = time.time()


def wait(timeout: float | None = None) -> Job | None:
    """Block until the current job finishes (tests, and nothing else)."""
    t = _thread
    if t is not None:
        t.join(timeout)
    return _job
