"""E1: configurable llama-server path.

Covers the resolver in core.config (explicit setting > PATH/which > bare
fallback, caching, invalidation) and that core.defaults subprocess calls go
through it.
"""
import json
import pathlib

import pytest


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    """Point settings.json at a temp file and reset the resolver cache."""
    import core.config as CC
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(CC, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(CC, "_server_path_cache", None)
    yield settings_file
    CC._server_path_cache = None


def _write_settings(settings_file: pathlib.Path, data: dict):
    settings_file.write_text(json.dumps(data), encoding="utf-8")


def test_explicit_setting_wins(temp_settings, tmp_path):
    import core.config as CC
    fake = tmp_path / "custom" / "llama-server.exe"
    fake.parent.mkdir()
    fake.write_bytes(b"x")
    _write_settings(temp_settings, {"server_path": str(fake)})
    assert CC.get_server_path() == str(fake)


def test_no_setting_uses_path_which(temp_settings, monkeypatch):
    import core.config as CC
    monkeypatch.setattr(CC.shutil, "which", lambda name: "/opt/bin/llama-server")
    assert CC.get_server_path() == "/opt/bin/llama-server"


def test_no_setting_no_which_falls_back_to_bare_name(temp_settings, monkeypatch):
    import core.config as CC
    monkeypatch.setattr(CC.shutil, "which", lambda name: None)
    assert CC.get_server_path() == "llama-server"


def test_stale_explicit_path_falls_back_to_which(temp_settings, monkeypatch):
    import core.config as CC
    _write_settings(temp_settings, {"server_path": "/gone/llama-server"})
    monkeypatch.setattr(CC.shutil, "which", lambda name: "/usr/local/bin/llama-server")
    assert CC.get_server_path() == "/usr/local/bin/llama-server"


def test_cache_is_used_and_invalidated_by_save(temp_settings, tmp_path, monkeypatch):
    import core.config as CC
    fake = tmp_path / "llama-server.exe"
    fake.write_bytes(b"x")
    _write_settings(temp_settings, {"server_path": str(fake)})
    first = CC.get_server_path()
    # poison the settings file: a cache hit must not re-read it
    _write_settings(temp_settings, {"server_path": "/broken/path"})
    assert CC.get_server_path() == first
    # saving a new path invalidates the cache
    other = tmp_path / "other"
    other.write_bytes(b"x")
    CC.save_server_path(str(other))
    assert CC.get_server_path() == str(other)
    assert json.loads(temp_settings.read_text(encoding="utf-8"))["server_path"] == str(other)


def test_save_and_load_roundtrip(temp_settings, tmp_path):
    import core.config as CC
    fake = tmp_path / "llama-server.exe"
    fake.write_bytes(b"x")
    CC.save_server_path(str(fake))
    assert CC.load_server_path() == str(fake)


def test_fetch_help_text_uses_configured_path(temp_settings, tmp_path, monkeypatch):
    import core.config as CC
    import core.defaults as CD
    fake = tmp_path / "custom-server.exe"
    fake.write_bytes(b"x")
    monkeypatch.setattr(CC, "_server_path_cache", str(fake))
    calls = []

    class _Result:
        stdout = "help text"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(CD.subprocess, "run", fake_run)
    CD.fetch_help_text()
    assert calls and calls[0] == [str(fake), "--help"]


def test_defaults_fall_back_to_bare_name_when_unresolvable(temp_settings, monkeypatch):
    import core.config as CC
    import core.defaults as CD
    monkeypatch.setattr(CC, "_server_path_cache", None)
    monkeypatch.setattr(CC.shutil, "which", lambda name: None)
    calls = []

    class _Result:
        stdout = "help text"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(CD.subprocess, "run", fake_run)
    CD.fetch_help_text()
    assert calls and calls[0][0] == "llama-server"


def test_explicit_server_path_argument_still_wins(temp_settings, tmp_path, monkeypatch):
    """An explicit server_path argument must bypass the resolver (D1 tests rely on this)."""
    import core.defaults as CD
    given = tmp_path / "given"
    given.write_bytes(b"x")
    calls = []

    class _Result:
        stdout = "version: 1 (a)\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(CD.subprocess, "run", fake_run)
    CD.get_server_version(server_path=str(given))
    assert calls and calls[0][0] == str(given)
