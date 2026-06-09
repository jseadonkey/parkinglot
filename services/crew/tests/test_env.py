from parking_crew.env import configured_secret_keys, load_crew_env


def test_configured_secret_keys_never_returns_values(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-secret")
    load_crew_env()
    status = configured_secret_keys()
    assert status["SLACK_BOT_TOKEN"] is True
    assert "xoxb" not in str(status)
