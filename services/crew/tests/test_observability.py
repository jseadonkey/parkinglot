from parking_crew.observability import langfuse_configured, verify_langfuse_connection


def test_langfuse_not_configured_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert langfuse_configured() is False
    status = verify_langfuse_connection()
    assert status["configured"] is False
    assert status["authenticated"] is False
