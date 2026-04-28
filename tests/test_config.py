import json
import sys
from datetime import timezone, timedelta
from pathlib import Path

import pytest

from gps_updater import config as cfg


def test_default_config_has_all_sections():
    c = cfg.DEFAULT_CONFIG
    assert "time" in c
    assert "scan" in c
    assert "matching" in c
    assert "output" in c
    assert "logging" in c


def test_load_returns_defaults_when_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "_discover_files", lambda: [])
    result = cfg.load()
    assert result["time"]["offset_seconds"] == 0
    assert result["output"]["units"] == "metric"


def test_deep_merge_overrides_nested():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 99}}
    result = cfg._deep_merge(base, override)
    assert result["a"]["x"] == 1
    assert result["a"]["y"] == 99
    assert result["b"] == 3


def test_deep_merge_adds_new_key():
    base = {"a": 1}
    result = cfg._deep_merge(base, {"b": 2})
    assert result["b"] == 2


def test_load_merges_file(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"output": {"units": "imperial"}}))
    monkeypatch.setattr(cfg, "_discover_files", lambda: [config_file])
    result = cfg.load()
    assert result["output"]["units"] == "imperial"
    assert result["output"]["write_elevation"] is True  # default preserved


def test_load_explicit_path(tmp_path):
    config_file = tmp_path / "my.json"
    config_file.write_text(json.dumps({"time": {"offset_seconds": 30}}))
    result = cfg.load(config_file)
    assert result["time"]["offset_seconds"] == 30


def test_load_missing_explicit_path_exits(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        cfg.load(tmp_path / "nonexistent.json")
    assert exc_info.value.code == 2


def test_validate_passes_valid_config():
    c = cfg.load()
    cfg.validate(c)  # should not raise or exit


def test_validate_fails_bad_enum(monkeypatch):
    monkeypatch.setattr(cfg, "_discover_files", lambda: [])
    c = cfg.load()
    c["matching"]["on_existing_gps"] = "invalid_value"
    with pytest.raises(SystemExit) as exc_info:
        cfg.validate(c)
    assert exc_info.value.code == 2


def test_resolve_timezone_iana():
    tz = cfg.resolve_timezone("Europe/Warsaw")
    import zoneinfo
    assert isinstance(tz, zoneinfo.ZoneInfo)


def test_resolve_timezone_abbreviation():
    tz = cfg.resolve_timezone("CET")
    import zoneinfo
    assert isinstance(tz, zoneinfo.ZoneInfo)


def test_resolve_timezone_offset_plus():
    tz = cfg.resolve_timezone("+02:00")
    assert tz.utcoffset(None) == timedelta(hours=2)


def test_resolve_timezone_offset_short():
    tz = cfg.resolve_timezone("+2")
    assert tz.utcoffset(None) == timedelta(hours=2)


def test_resolve_timezone_offset_minus():
    tz = cfg.resolve_timezone("-05:30")
    assert tz.utcoffset(None) == timedelta(hours=-5, minutes=-30)


def test_resolve_timezone_none_returns_something():
    tz = cfg.resolve_timezone(None)
    assert tz is not None


def test_resolve_timezone_invalid_exits():
    with pytest.raises(SystemExit) as exc_info:
        cfg.resolve_timezone("NotATimezone/Bogus")
    assert exc_info.value.code == 2


def test_write_default(tmp_path):
    out = tmp_path / "config.json"
    cfg.write_default(out)
    assert out.exists()
    # write_default produces JSONC (with // comments); strip them before parsing
    data = json.loads(cfg._strip_comments(out.read_text()))
    assert "schema_version" in data
    assert "matching" in data


def test_unknown_top_level_key_is_dropped(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"output": {"units": "imperial"}, "bogus_key": 123}))
    monkeypatch.setattr(cfg, "_discover_files", lambda: [config_file])
    result = cfg.load()
    assert "bogus_key" not in result
    assert "ignored" in capsys.readouterr().out


def test_unknown_nested_key_is_dropped(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"output": {"units": "imperial", "mystery": True}}))
    monkeypatch.setattr(cfg, "_discover_files", lambda: [config_file])
    result = cfg.load()
    assert "mystery" not in result["output"]
    assert result["output"]["units"] == "imperial"
    assert "ignored" in capsys.readouterr().out


def test_known_keys_are_not_dropped(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"matching": {"track_gap_threshold_seconds": 600}}))
    monkeypatch.setattr(cfg, "_discover_files", lambda: [config_file])
    result = cfg.load()
    assert result["matching"]["track_gap_threshold_seconds"] == 600


def test_warn_unknown_keys_returns_cleaned_dict():
    user = {"units": "imperial", "ghost": "value"}
    reference = {"units": "metric"}
    cleaned = cfg._warn_unknown_keys(user, reference, source="test")
    assert "ghost" not in cleaned
    assert cleaned["units"] == "imperial"


def test_warn_unknown_keys_cleans_nested():
    user = {"output": {"units": "imperial", "phantom": 1}}
    reference = {"output": {"units": "metric"}}
    cleaned = cfg._warn_unknown_keys(user, reference, source="test")
    assert "phantom" not in cleaned["output"]
    assert cleaned["output"]["units"] == "imperial"


def test_warn_unknown_keys_warns_top_level(capsys):
    cfg._warn_unknown_keys({"bad": 1}, {}, source="test.json")
    assert "bad" in capsys.readouterr().out


def test_warn_unknown_keys_warns_nested(capsys):
    cfg._warn_unknown_keys(
        {"output": {"bad_nested": 1}},
        {"output": {}},
        source="test.json",
    )
    out = capsys.readouterr().out
    assert "output.bad_nested" in out
