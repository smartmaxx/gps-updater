import json
from pathlib import Path

import pytest

from gps_updater import plugins as plugin_module
from gps_updater.models import CameraProfile


def _make_profile(make: str, models: list[str], path: Path | None = None) -> CameraProfile:
    return CameraProfile(
        make=make,
        model_patterns=models,
        datetime_field_priority=["DateTimeOriginal"],
        datetime_is_utc=False,
        default_timezone_offset=None,
        has_embedded_gps=False,
        on_embedded_gps=None,
        video_timestamp_source=None,
        reference_timestamp_source="gps_timestamp",
        notes="",
        source_file=path or Path("/tmp/test.json"),
    )


def test_match_exact():
    profiles = [_make_profile("Canon", ["EOS R5"])]
    result = plugin_module.match(profiles, "Canon", "EOS R5")
    assert result is not None
    assert result.make == "Canon"


def test_match_case_insensitive():
    profiles = [_make_profile("SONY", ["ILCE-7M4"])]
    result = plugin_module.match(profiles, "sony", "ilce-7m4")
    assert result is not None


def test_match_substring():
    profiles = [_make_profile("Canon", ["EOS"])]
    result = plugin_module.match(profiles, "Canon", "EOS 5D Mark IV")
    assert result is not None


def test_match_exact_beats_substring():
    exact = _make_profile("Canon", ["EOS R5"])
    substring = _make_profile("Canon", ["EOS"])
    profiles = [substring, exact]
    result = plugin_module.match(profiles, "Canon", "EOS R5")
    assert result is exact


def test_match_no_match():
    profiles = [_make_profile("Canon", ["EOS"])]
    result = plugin_module.match(profiles, "Nikon", "Z7")
    assert result is None


def test_match_none_make_none_model():
    profiles = [_make_profile("Canon", ["EOS"])]
    result = plugin_module.match(profiles, None, None)
    assert result is None


def test_load_file_valid(tmp_path):
    data = {
        "schema_version": 1,
        "make": "TestMake",
        "model": ["ModelA", "ModelB"],
        "datetime_field_priority": ["DateTimeOriginal"],
        "datetime_is_utc": False,
        "notes": "test",
    }
    p = tmp_path / "test.json"
    p.write_text(json.dumps(data))
    profile = plugin_module._load_file(p)
    assert profile is not None
    assert profile.make == "TestMake"
    assert profile.model_patterns == ["ModelA", "ModelB"]


def test_load_file_missing_required_fields(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"make": "X"}))
    profile = plugin_module._load_file(p)
    assert profile is None


def test_load_file_string_model(tmp_path):
    data = {
        "make": "Foo",
        "model": "Bar",
        "datetime_field_priority": ["DateTimeOriginal"],
        "datetime_is_utc": False,
    }
    p = tmp_path / "foo.json"
    p.write_text(json.dumps(data))
    profile = plugin_module._load_file(p)
    assert profile.model_patterns == ["Bar"]


def test_user_overrides_bundled():
    bundled = _make_profile("Canon", ["EOS"], Path("/app/plugins/canon.json"))
    user = _make_profile("Canon", ["EOS"], Path("/home/user/.config/gps-updater/plugins/canon.json"))
    result = plugin_module._merge([bundled], [user])
    matched = plugin_module.match(result, "Canon", "EOS R5")
    assert matched.source_file == user.source_file


def test_user_user_conflict_uses_first(tmp_path, caplog):
    import logging
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    p1.touch()
    p2.touch()
    first = _make_profile("Sony", ["A7"], p1)
    second = _make_profile("Sony", ["A7"], p2)
    with caplog.at_level(logging.WARNING, logger="gps_updater"):
        result = plugin_module._merge([], [first, second])
    matched = plugin_module.match(result, "Sony", "A7")
    assert matched.source_file == p1
    assert any("Conflicting" in r.message for r in caplog.records)


def test_bundled_profiles_load():
    profiles = plugin_module.load_all(None)
    assert len(profiles) >= 9
    makes = {p.make for p in profiles}
    assert "GoPro" in makes
    assert "Apple" in makes
