from __future__ import annotations

from sqlalchemy.exc import OperationalError

from app.db.concurrent_writes import is_deadlock_error, retry_on_deadlock


def test_is_deadlock_error_detects_message() -> None:
    exc = OperationalError("stmt", {}, Exception("DeadlockDetected: deadlock"))
    assert is_deadlock_error(exc) is True


def test_is_deadlock_error_other_operational() -> None:
    exc = OperationalError("stmt", {}, Exception("connection refused"))
    assert is_deadlock_error(exc) is False


def test_retry_on_deadlock_succeeds_after_failure() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise OperationalError("stmt", {}, Exception("DeadlockDetected"))
        return "ok"

    assert retry_on_deadlock(flaky, max_retries=4, base_delay_sec=0.0) == "ok"
    assert calls["n"] == 2
