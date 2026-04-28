from datetime import datetime, timezone
from pathlib import Path

from gps_updater.models import CameraProfile, MatchResult, MatchStatus, MediaRecord, TrackPoint


def _dummy_path() -> Path:
    return Path("/tmp/test.jpg")


def test_trackpoint_construction():
    ts = datetime(2026, 3, 21, 10, 0, 0, tzinfo=timezone.utc)
    tp = TrackPoint(
        timestamp=ts,
        latitude=50.0,
        longitude=20.0,
        elevation=200.0,
        hdop=1.5,
        pdop=None,
        source_file=Path("/tmp/track.gpx"),
    )
    assert tp.latitude == 50.0
    assert tp.hdop == 1.5
    assert tp.pdop is None


def test_media_record_construction():
    rec = MediaRecord(
        path=_dummy_path(),
        capture_time=None,
        capture_time_raw=None,
        timezone_applied=None,
        has_existing_gps=False,
        existing_lat=None,
        existing_lon=None,
        camera_make=None,
        camera_model=None,
        camera_profile=None,
        is_video=False,
    )
    assert rec.has_existing_gps is False
    assert rec.is_video is False


def test_match_result_construction():
    rec = MediaRecord(
        path=_dummy_path(),
        capture_time=None,
        capture_time_raw=None,
        timezone_applied=None,
        has_existing_gps=False,
        existing_lat=None,
        existing_lon=None,
        camera_make=None,
        camera_model=None,
        camera_profile=None,
        is_video=False,
    )
    result = MatchResult(
        media=rec,
        status=MatchStatus.SKIPPED,
        matched_lat=None,
        matched_lon=None,
        matched_elevation=None,
        interpolation_ratio=None,
        distance_to_existing_meters=None,
        reason="No timestamp",
    )
    assert result.status == MatchStatus.SKIPPED
    assert result.reason == "No timestamp"


def test_match_status_values():
    assert MatchStatus.MATCHED.value == "matched"
    assert MatchStatus.SKIPPED.value == "skipped"
    assert MatchStatus.WARNED.value == "warned"
    assert MatchStatus.FAILED.value == "failed"
