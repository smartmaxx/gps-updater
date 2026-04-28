from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from gps_updater.reference_scanner import (
    scan,
    _from_gps_fields,
    _from_datetime_original,
)
from gps_updater.models import CameraProfile

FIXTURES = Path(__file__).parent / "fixtures"

UTC = timezone.utc


def _make_profile(ref_source: str = "gps_timestamp") -> CameraProfile:
    return CameraProfile(
        make="Test",
        model_patterns=["TestCam"],
        datetime_field_priority=["DateTimeOriginal"],
        datetime_is_utc=False,
        default_timezone_offset=None,
        has_embedded_gps=True,
        on_embedded_gps=None,
        video_timestamp_source=None,
        reference_timestamp_source=ref_source,
        notes="",
        source_file=Path("/tmp/test.json"),
    )


# ------------------------------------------------------------------ _from_gps_fields

def test_from_gps_fields_basic():
    meta = {"GPSDateStamp": "2026:03:21", "GPSTimeStamp": "10:00:00"}
    ts = _from_gps_fields(meta)
    assert ts == datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)


def test_from_gps_fields_alt_keys():
    meta = {"GPSDate": "2026:03:21", "GPSTime": "12:30:00"}
    ts = _from_gps_fields(meta)
    assert ts == datetime(2026, 3, 21, 12, 30, 0, tzinfo=UTC)


def test_from_gps_fields_missing_returns_none():
    assert _from_gps_fields({}) is None
    assert _from_gps_fields({"GPSDateStamp": "2026:03:21"}) is None


# ------------------------------------------------------------------ _from_datetime_original

def test_from_datetime_original_with_system_tz():
    meta = {"DateTimeOriginal": "2026:03:21 12:00:00"}
    tz_plus2 = timezone(timedelta(hours=2))
    ts = _from_datetime_original(meta, tz_plus2, 0)
    assert ts == datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)


def test_from_datetime_original_offset_seconds():
    meta = {"DateTimeOriginal": "2026:03:21 12:00:00"}
    tz_utc = UTC
    ts = _from_datetime_original(meta, tz_utc, 30)
    assert ts == datetime(2026, 3, 21, 11, 59, 30, tzinfo=UTC)


def test_from_datetime_original_exif_offset_overrides_tz():
    meta = {
        "DateTimeOriginal": "2026:03:21 12:00:00",
        "OffsetTimeOriginal": "+02:00",
    }
    tz_utc = UTC
    ts = _from_datetime_original(meta, tz_utc, 0)
    assert ts == datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)


def test_from_datetime_original_missing_returns_none():
    assert _from_datetime_original({}, UTC, 0) is None


# ------------------------------------------------------------------ scan: GPX-only

def test_scan_gpx_only(tmp_path):
    shutil.copy(FIXTURES / "sample_utc.gpx", tmp_path / "track.gpx")
    points, consumed, ref_counts = scan(
        reference_paths=[tmp_path],
        media_path=tmp_path / "media",
        recursive=False,
        on_duplicate="use_first",
        loaded_profiles=[],
        timezone_obj=UTC,
        offset_seconds=0,
    )
    assert len(points) == 3
    assert tmp_path.resolve() / "track.gpx" in consumed
    assert ref_counts["gpx"] == 3
    assert ref_counts["media"] == 0


# ------------------------------------------------------------------ scan: GPS media

def _fake_exiftool_read(paths):
    return [
        {
            "GPSLatitude": 50.0,
            "GPSLongitude": 20.0,
            "GPSAltitude": 100.0,
            "GPSAltitudeRef": 0,
            "GPSDateStamp": "2026:03:21",
            "GPSTimeStamp": "10:00:00",
            "Make": "Test",
            "Model": "TestCam",
        }
        for _ in paths
    ]


def test_scan_gps_media_only(tmp_path):
    media_file = tmp_path / "photo.jpg"
    media_file.write_bytes(b"JFIF")

    with patch("gps_updater.reference_scanner.exiftool.read_metadata", side_effect=_fake_exiftool_read):
        points, consumed, ref_counts = scan(
            reference_paths=[tmp_path],
            media_path=tmp_path / "media",
            recursive=False,
            on_duplicate="use_first",
            loaded_profiles=[_make_profile("gps_timestamp")],
            timezone_obj=UTC,
            offset_seconds=0,
        )

    assert len(points) == 1
    assert points[0].latitude == pytest.approx(50.0)
    assert points[0].timestamp == datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)
    assert media_file.resolve() in consumed
    assert ref_counts["gpx"] == 0
    assert ref_counts["media"] == 1


# ------------------------------------------------------------------ scan: same-folder

def _no_gps_meta(paths):
    return [{} for _ in paths]


def _gps_meta(paths):
    return [
        {
            "GPSLatitude": 52.0,
            "GPSLongitude": 21.0,
            "GPSDateStamp": "2026:03:21",
            "GPSTimeStamp": "10:00:00",
        }
        for _ in paths
    ]


def test_scan_same_folder_split(tmp_path):
    shutil.copy(FIXTURES / "sample_utc.gpx", tmp_path / "track.gpx")
    photo_ref = tmp_path / "ref.jpg"
    photo_ref.write_bytes(b"JFIF")
    photo_target = tmp_path / "target.jpg"
    photo_target.write_bytes(b"JFIF")

    def mock_read(paths):
        result = []
        for p in paths:
            if p.name == "ref.jpg":
                result.append({
                    "GPSLatitude": 52.0,
                    "GPSLongitude": 21.0,
                    "GPSDateStamp": "2026:03:21",
                    "GPSTimeStamp": "11:00:00",
                })
            else:
                result.append({})
        return result

    with patch("gps_updater.reference_scanner.exiftool.read_metadata", side_effect=mock_read):
        points, consumed, ref_counts = scan(
            reference_paths=[tmp_path],
            media_path=tmp_path,
            recursive=False,
            on_duplicate="use_first",
            loaded_profiles=[],
            timezone_obj=UTC,
            offset_seconds=0,
        )

    assert len(points) == 4  # 3 from GPX + 1 from ref.jpg
    assert photo_ref.resolve() in consumed
    assert photo_target.resolve() not in consumed
    assert ref_counts["gpx"] == 3
    assert ref_counts["media"] == 1


# ------------------------------------------------------------------ scan: empty reference

def test_scan_empty_folder_returns_empty(tmp_path):
    points, consumed, ref_counts = scan(
        reference_paths=[tmp_path],
        media_path=tmp_path / "media",
        recursive=False,
        on_duplicate="use_first",
        loaded_profiles=[],
        timezone_obj=UTC,
        offset_seconds=0,
    )
    assert points == []
    assert consumed == set()
    assert ref_counts["gpx"] == 0
    assert ref_counts["media"] == 0
