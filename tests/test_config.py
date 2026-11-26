import json

from app.config import Settings, data_dir


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / "config.json"
    settings = Settings(
        api_key="sk-test-12345678",
        base_url="https://api.deepseek.com/",
        model="deepseek-chat",
        default_deck="Cardiology",
        default_tags="cardiology, lecture-3",
    )
    settings.save(path)

    loaded = Settings.load(path)
    assert loaded.api_key == "sk-test-12345678"
    assert loaded.base_url == "https://api.deepseek.com/"
    assert loaded.default_deck == "Cardiology"
    assert loaded.default_tags == "cardiology, lecture-3"


def test_public_view_hides_key():
    settings = Settings(api_key="sk-secret-9876")
    public = settings.public()
    assert public["has_key"] is True
    assert public["key_hint"] == "9876"
    assert "api_key" not in public


def test_update_validates_urls():
    settings = Settings()
    try:
        settings.update({"base_url": "not a url"})
    except ValueError as exc:
        assert "http" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    settings.update({"base_url": "https://example.com/v1", "model": "deepseek-chat"})
    assert settings.base_url == "https://example.com/v1"


def test_update_can_clear_key():
    settings = Settings(api_key="sk-test")
    settings.update({"clear_api_key": True})
    assert settings.api_key == ""


def test_data_dir_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANKI_SCRIBE_DATA", str(tmp_path))
    assert data_dir() == tmp_path


def test_a_damaged_config_falls_back_to_the_last_good_copy(tmp_path, monkeypatch):
    """A crash during a save must not cost the API key."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / "config.json"
    Settings(api_key="sk-first-key").save(path)
    Settings(api_key="sk-second-key").save(path)  # the backup now holds the first

    path.write_text('{ "api_key": "sk-broken', encoding="utf-8")
    assert Settings.load(path).api_key == "sk-first-key"


def test_an_unreadable_config_is_quarantined_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / "config.json"
    path.write_text("not json at all", encoding="utf-8")

    settings = Settings.load(path)
    assert settings.api_key == ""
    assert not path.exists()
    assert any("corrupt" in item.name for item in tmp_path.iterdir())


def test_data_fingerprint_identifies_the_folder(monkeypatch, tmp_path):
    from app.config import data_fingerprint

    monkeypatch.setenv("ANKI_SCRIBE_DATA", str(tmp_path))
    first = data_fingerprint()
    monkeypatch.setenv("ANKI_SCRIBE_DATA", str(tmp_path / "other"))
    assert data_fingerprint() != first
