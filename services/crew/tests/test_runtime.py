from parking_crew.runtime import is_droplet_runtime, runtime_label


def test_runtime_label_local(monkeypatch) -> None:
    monkeypatch.setenv("PARKINGLOT_RUNTIME", "local")
    assert runtime_label() == "local"
    assert is_droplet_runtime() is False


def test_runtime_label_droplet(monkeypatch) -> None:
    monkeypatch.setenv("PARKINGLOT_RUNTIME", "droplet")
    assert runtime_label() == "droplet"
    assert is_droplet_runtime() is True
