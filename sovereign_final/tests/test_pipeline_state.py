"""modules/pipeline_state — the lock the scheduler and the dashboard buttons
share (audit O7), and the scheduled-run status the dashboard shows (O4)."""

from datetime import datetime, timedelta, timezone

import pytest

import database
from modules import pipeline_state as ps
from modules.pipeline_state import PipelineBusy, PipelineLock, summarize

UTC = timezone.utc


class TestLock:
    def test_second_holder_is_turned_away(self, full_db):
        with PipelineLock("scheduler"):
            with pytest.raises(PipelineBusy, match="scheduler is running"):
                PipelineLock("dashboard: BAZOS").acquire()
        # Released: the next one gets it.
        with PipelineLock("dashboard: BAZOS"):
            assert database.get_pipeline_lock()["holder"] == "dashboard: BAZOS"
        assert database.get_pipeline_lock() is None

    def test_released_when_the_work_raises(self, full_db):
        with pytest.raises(RuntimeError):
            with PipelineLock("scheduler"):
                raise RuntimeError("scraper blew up")
        assert database.get_pipeline_lock() is None

    def test_a_dead_holder_is_taken_over(self, full_db):
        # A process that died mid-run leaves its row; its heartbeat stops.
        old = (datetime.now(UTC) - timedelta(seconds=ps.STALE_AFTER_S + 5)).isoformat()
        assert database.try_lock_pipeline("scheduler", "dead", ps.STALE_AFTER_S) is None
        conn = full_db()
        conn.execute("UPDATE pipeline_lock SET heartbeat_at=?", (old,))
        conn.commit()
        conn.close()
        with PipelineLock("dashboard: LV"):
            assert database.get_pipeline_lock()["holder"] == "dashboard: LV"
        assert not database.heartbeat_pipeline_lock("dead")

    def test_waits_for_the_holder(self, full_db, monkeypatch):
        calls = []
        real = database.try_lock_pipeline

        def busy_twice(holder, token, stale):
            calls.append(holder)
            return {"holder": "x", "acquired_at": None} if len(calls) < 3 else real(holder, token, stale)
        monkeypatch.setattr(database, "try_lock_pipeline", busy_twice)
        monkeypatch.setattr(ps.time, "sleep", lambda s: None)
        with PipelineLock("scheduler", wait_s=60, poll_s=1):
            pass
        assert len(calls) == 3

    def test_heartbeat_keeps_it_fresh(self, full_db):
        lock = PipelineLock("scheduler")
        lock.acquire()
        try:
            before = database.get_pipeline_lock()["heartbeat_at"]
            assert database.heartbeat_pipeline_lock(lock.token)
            assert database.get_pipeline_lock()["heartbeat_at"] >= before
        finally:
            lock.release()


class TestStatusFile:
    def test_round_trip_and_garbage(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ps, "STATUS_FILE", str(tmp_path / "d" / "s.json"))
        assert ps.read_status() is None
        ps.write_status({"state": "ok", "summary": "🟢1"})
        assert ps.read_status() == {"state": "ok", "summary": "🟢1"}
        (tmp_path / "d" / "s.json").write_text("{not json")
        assert ps.read_status() is None


NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def _st(**kw):
    base = {"state": "ok", "started_at": "2026-10-08T06:00:00+00:00",
            "finished_at": "2026-10-08T06:40:00+00:00", "summary": "🟢3 🟡5",
            "steps": [{"step": "Bazos.sk", "ok": True}]}
    return {**base, **kw}


class TestSummarize:
    def test_nothing_on_record(self):
        assert summarize(None, None, NOW)[0] == "none"

    def test_ok(self):
        level, text = summarize(_st(), None, NOW)
        assert level == "ok" and "06:40" in text and "🟢3" in text

    def test_failed_says_why_and_when_it_retries(self):
        level, text = summarize(_st(state="failed", error="all 3 scrapers failed",
                                    next_retry_at="2026-10-08T07:40:00+00:00"), None, NOW)
        assert level == "error"
        assert "FAILED: all 3 scrapers failed" in text and "07:40" in text

    def test_failed_with_no_retries_left(self):
        _, text = summarize(_st(state="failed", error="x", next_retry_at=None), None, NOW)
        assert "No more retries today" in text

    def test_failed_steps_are_named(self):
        level, text = summarize(_st(steps=[{"step": "Bazos.sk", "ok": True},
                                           {"step": "LV Debt Filter", "ok": False}]),
                                None, NOW)
        assert level == "warning" and "LV Debt Filter" in text

    def test_running_while_the_scheduler_holds_the_lock(self):
        level, _ = summarize(_st(state="running"), {"holder": "scheduler"}, NOW)
        assert level == "running"

    def test_running_without_the_lock_was_interrupted(self):
        level, text = summarize(_st(state="running"), None, NOW)
        assert level == "error" and "never finished" in text

    def test_an_old_success_means_the_scheduler_stopped(self):
        level, text = summarize(_st(), None, NOW + timedelta(days=2))
        assert level == "warning" and "Is the scheduler running?" in text
        assert "8 Oct 06:40" in text

    def test_nothing_on_record_points_at_the_button_too(self):
        # Without Docker no scheduler runs: "the scheduler runs it at 06:00"
        # alone left the dashboard's own run unmentioned.
        _, text = summarize(None, None, NOW)
        assert "RUN EVERYTHING" in text


class TestSummarizeDashboardRun:
    """A full run started from the dashboard's ▶ RUN EVERYTHING (trigger
    "dashboard"): no scheduler stands behind it, so the text points at the
    button rather than at retries or the scheduler."""

    HOLDER = "dashboard: RUN EVERYTHING"

    def _st(self, **kw):
        return _st(trigger="dashboard", holder=self.HOLDER, **kw)

    def test_ok(self):
        level, text = summarize(self._st(), None, NOW)
        assert level == "ok" and text.startswith("Last full run 06:40") and "🟢3" in text

    def test_running_while_the_dashboard_holds_the_lock(self):
        level, text = summarize(self._st(state="running"), {"holder": self.HOLDER}, NOW)
        assert level == "running" and text.startswith("Full run in progress")

    def test_another_dashboard_job_is_not_this_run(self):
        level, text = summarize(self._st(state="running"), {"holder": "dashboard: BAZOS"}, NOW)
        assert level == "error" and "never finished" in text

    def test_running_without_the_lock_was_interrupted(self):
        level, text = summarize(self._st(state="running"), None, NOW)
        assert level == "error" and "never finished" in text
        assert "RUN EVERYTHING" in text and "scheduler" not in text

    def test_failed_says_to_click_again_not_when_it_retries(self):
        level, text = summarize(self._st(state="failed", error="all 3 scrapers failed",
                                         next_retry_at="2026-10-08T07:40:00+00:00"),
                                None, NOW)
        assert level == "error" and "FAILED: all 3 scrapers failed" in text
        assert "RUN EVERYTHING" in text and "Retrying" not in text

    def test_failed_steps_are_named(self):
        level, text = summarize(self._st(steps=[{"step": "LV Debt Filter", "ok": False}]),
                                None, NOW)
        assert level == "warning" and text.startswith("Last full run")
        assert "LV Debt Filter" in text

    def test_a_lock_nobody_keeps_alive_is_not_a_run_in_progress(self):
        # The dashboard's Terminal window closed mid-run: its lock row stays
        # behind, but its heartbeat stops.
        def lock(minutes_ago):
            beat = (NOW - timedelta(minutes=minutes_ago)).isoformat()
            return {"holder": self.HOLDER, "heartbeat_at": beat}
        assert summarize(self._st(state="running"), lock(1), NOW)[0] == "running"
        level, text = summarize(self._st(state="running"), lock(10), NOW)
        assert level == "error" and "never finished" in text

    def test_an_old_run_asks_for_a_new_one_not_for_the_scheduler(self):
        level, text = summarize(self._st(), None, NOW + timedelta(days=2))
        assert level == "warning" and "RUN EVERYTHING" in text
        assert "scheduler" not in text
