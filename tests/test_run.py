import run


def test_a_running_instance_anywhere_in_the_range_is_reused(monkeypatch):
    # The first port is free, but an older instance is on a later one. Starting
    # a second process there would share its JSON files and corrupt them.
    monkeypatch.setattr(run, "_is_ours", lambda port: port == 8790)
    monkeypatch.setattr(run, "_is_free", lambda port: True)
    assert run._choose_port() == (8790, True)


def test_first_free_port_is_used_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(run, "_is_ours", lambda port: False)
    monkeypatch.setattr(run, "_is_free", lambda port: port == 8780)
    assert run._choose_port() == (8780, False)


def test_no_free_port_raises(monkeypatch):
    monkeypatch.setattr(run, "_is_ours", lambda port: False)
    monkeypatch.setattr(run, "_is_free", lambda port: False)
    try:
        run._choose_port()
    except RuntimeError as exc:
        assert "free port" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_an_instance_serving_another_data_folder_is_not_adopted(monkeypatch):
    """The bug that looked like lost data: a stray server on a later port was
    adopted and shown instead of the instance holding the real data folder."""
    monkeypatch.setattr(run, "data_fingerprint", lambda: "mine")
    monkeypatch.setattr(
        run, "_health", lambda port: {"app": "anki-scribe", "data": "somewhere-else"}
    )
    assert run._is_ours(8790) is False


def test_an_instance_serving_the_same_data_folder_is_ours(monkeypatch):
    monkeypatch.setattr(run, "data_fingerprint", lambda: "mine")
    monkeypatch.setattr(
        run, "_health", lambda port: {"app": "anki-scribe", "data": "mine"}
    )
    assert run._is_ours(8790) is True


def test_a_server_that_is_not_anki_scribe_is_not_ours(monkeypatch):
    monkeypatch.setattr(run, "data_fingerprint", lambda: "mine")
    monkeypatch.setattr(
        run, "_health", lambda port: {"app": "something-else", "data": "mine"}
    )
    assert run._is_ours(8790) is False
    monkeypatch.setattr(run, "_health", lambda port: None)
    assert run._is_ours(8790) is False
