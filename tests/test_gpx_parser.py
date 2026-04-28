from datetime import datetime, timezone
from pathlib import Path

import pytest

from gps_updater.gpx_parser import build_database, _deduplicate, _parse_file
from gps_updater.models import TrackPoint

FIXTURES = Path(__file__).parent / "fixtures"


def _tp(h: int, m: int, s: int, lat: float, lon: float, hdop: float | None = None) -> TrackPoint:
    return TrackPoint(
        timestamp=datetime(2026, 3, 21, h, m, s, tzinfo=timezone.utc),
        latitude=lat,
        longitude=lon,
        elevation=None,
        hdop=hdop,
        pdop=None,
        source_file=Path("/tmp/track.gpx"),
    )


# ------------------------------------------------------------------ file parsing

def test_parse_utc_file():
    points = _parse_file(FIXTURES / "sample_utc.gpx")
    assert points is not None
    assert len(points) == 3
    assert points[0].timestamp == datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)
    assert points[0].latitude == pytest.approx(50.0)
    assert points[0].hdop == pytest.approx(1.2)


def test_parse_offset_file_normalizes_to_utc():
    points = _parse_file(FIXTURES / "sample_offset.gpx")
    assert points is not None
    # 12:00:00+02:00 == 10:00:00Z
    assert points[0].timestamp == datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_no_timestamps_returns_none():
    points = _parse_file(FIXTURES / "no_timestamps.gpx")
    assert points is None


def test_parse_nonexistent_file_returns_none(tmp_path):
    points = _parse_file(tmp_path / "nonexistent.gpx")
    assert points is None


# ------------------------------------------------------------------ build_database

def test_build_database_single_file():
    db = build_database(FIXTURES / "sample_utc.gpx", recursive=False, on_duplicate="use_first")
    assert len(db) == 3
    # verify sorted order
    for i in range(len(db) - 1):
        assert db[i].timestamp <= db[i + 1].timestamp


def test_build_database_folder(tmp_path):
    import shutil
    shutil.copy(FIXTURES / "sample_utc.gpx", tmp_path / "a.gpx")
    shutil.copy(FIXTURES / "sample_offset.gpx", tmp_path / "b.gpx")
    db = build_database(tmp_path, recursive=False, on_duplicate="use_first")
    assert len(db) == 4
    for i in range(len(db) - 1):
        assert db[i].timestamp <= db[i + 1].timestamp


def test_build_database_empty_folder_returns_empty(tmp_path):
    db = build_database(tmp_path, recursive=False, on_duplicate="use_first")
    assert db == []


def test_build_database_all_rejected_returns_empty():
    db = build_database(FIXTURES / "no_timestamps.gpx", recursive=False, on_duplicate="use_first")
    assert db == []


# ------------------------------------------------------------------ deduplication

def test_dedup_no_duplicates():
    points = [
        _tp(10, 0, 0, 50.0, 20.0),
        _tp(10, 0, 5, 50.1, 20.1),
    ]
    result = _deduplicate(points, "use_first")
    assert len(result) == 2


def test_dedup_use_first():
    t = datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)
    p1 = TrackPoint(t, 50.0, 20.0, None, None, None, Path("/a.gpx"))
    p2 = TrackPoint(t, 51.0, 21.0, None, None, None, Path("/b.gpx"))
    result = _deduplicate([p1, p2], "use_first")
    assert len(result) == 1
    assert result[0].latitude == 50.0


def test_dedup_warn_skip():
    t = datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)
    p1 = TrackPoint(t, 50.0, 20.0, None, None, None, Path("/a.gpx"))
    p2 = TrackPoint(t, 51.0, 21.0, None, None, None, Path("/b.gpx"))
    result = _deduplicate([p1, p2], "warn_skip")
    assert len(result) == 0


def test_dedup_prefer_accuracy_picks_lower_hdop():
    t = datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)
    p_good = TrackPoint(t, 50.0, 20.0, None, 1.0, None, Path("/a.gpx"))
    p_bad = TrackPoint(t, 51.0, 21.0, None, 5.0, None, Path("/b.gpx"))
    result = _deduplicate([p_bad, p_good], "prefer_accuracy")
    assert len(result) == 1
    assert result[0].hdop == 1.0


def test_dedup_prefer_accuracy_falls_back_to_first_when_no_hdop():
    t = datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)
    p1 = TrackPoint(t, 50.0, 20.0, None, None, None, Path("/a.gpx"))
    p2 = TrackPoint(t, 51.0, 21.0, None, None, None, Path("/b.gpx"))
    result = _deduplicate([p1, p2], "prefer_accuracy")
    assert result[0].latitude == 50.0
