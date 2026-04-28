import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from gps_updater.matcher import haversine, match_all, meters_to_display
from gps_updater.models import MatchStatus, MediaRecord, TrackPoint


def _tp(dt: datetime, lat: float, lon: float, ele: float | None = None, hdop: float | None = None) -> TrackPoint:
    return TrackPoint(
        timestamp=dt,
        latitude=lat,
        longitude=lon,
        elevation=ele,
        hdop=hdop,
        pdop=None,
        source_file=Path("/tmp/track.gpx"),
    )


def _rec(dt: datetime | None, has_gps: bool = False, lat: float | None = None, lon: float | None = None) -> MediaRecord:
    return MediaRecord(
        path=Path("/tmp/photo.jpg"),
        capture_time=dt,
        capture_time_raw=None,
        timezone_applied=None,
        has_existing_gps=has_gps,
        existing_lat=lat,
        existing_lon=lon,
        camera_make=None,
        camera_model=None,
        camera_profile=None,
        is_video=False,
    )


def _cfg(**overrides) -> dict:
    base = {
        "matching": {
            "on_existing_gps": "warn",
            "existing_gps_distance_threshold_meters": 50,
            "on_duplicate_trackpoint": "prefer_accuracy",
            "on_photo_before_track": "warn",
            "on_photo_before_track_max_seconds": 60,
            "on_photo_after_track": "warn",
            "on_photo_after_track_max_seconds": 60,
            "track_gap_threshold_seconds": 300,
            "on_track_gap": "warn",
        },
        "output": {"units": "metric"},
    }
    base["matching"].update(overrides)
    return base


def _utc(h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 3, 21, h, m, s, tzinfo=timezone.utc)


# ------------------------------------------------------------------ haversine

def test_haversine_same_point():
    assert haversine(50.0, 20.0, 50.0, 20.0) == 0.0


def test_haversine_known_distance():
    # Warsaw to Berlin is roughly 520 km
    d = haversine(52.2297, 21.0122, 52.5200, 13.4050)
    assert 510_000 < d < 530_000


def test_haversine_symmetry():
    d1 = haversine(10.0, 20.0, 11.0, 21.0)
    d2 = haversine(11.0, 21.0, 10.0, 20.0)
    assert math.isclose(d1, d2)


# ------------------------------------------------------------------ interpolation

def test_exact_match():
    t = _utc(10, 0, 0)
    points = [_tp(t, 50.0, 20.0, 200.0)]
    results = match_all([_rec(t)], points, _cfg())
    assert results[0].status == MatchStatus.MATCHED
    assert results[0].matched_lat == 50.0
    assert results[0].matched_lon == 20.0
    assert results[0].interpolation_ratio == 0.0


def test_interpolation_midpoint():
    p1 = _tp(_utc(10, 0, 0), 50.0, 20.0)
    p2 = _tp(_utc(10, 0, 10), 50.1, 20.1)
    t = _utc(10, 0, 5)
    results = match_all([_rec(t)], [p1, p2], _cfg())
    r = results[0]
    assert r.status == MatchStatus.MATCHED
    assert math.isclose(r.matched_lat, 50.05, abs_tol=1e-9)
    assert math.isclose(r.matched_lon, 20.05, abs_tol=1e-9)
    assert math.isclose(r.interpolation_ratio, 0.5, abs_tol=1e-9)


def test_elevation_interpolated():
    p1 = _tp(_utc(10, 0, 0), 50.0, 20.0, ele=100.0)
    p2 = _tp(_utc(10, 0, 10), 50.0, 20.0, ele=200.0)
    t = _utc(10, 0, 5)
    results = match_all([_rec(t)], [p1, p2], _cfg())
    assert math.isclose(results[0].matched_elevation, 150.0)


def test_elevation_none_when_missing():
    p1 = _tp(_utc(10, 0, 0), 50.0, 20.0, ele=None)
    p2 = _tp(_utc(10, 0, 10), 50.0, 20.0, ele=None)
    t = _utc(10, 0, 5)
    results = match_all([_rec(t)], [p1, p2], _cfg())
    assert results[0].matched_elevation is None


# ------------------------------------------------------------------ boundary

def test_before_track_warn():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    results = match_all([_rec(_utc(9, 0, 0))], points, _cfg(on_photo_before_track="warn"))
    assert results[0].status == MatchStatus.WARNED


def test_before_track_skip():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    results = match_all([_rec(_utc(9, 0, 0))], points, _cfg(on_photo_before_track="skip"))
    assert results[0].status == MatchStatus.SKIPPED


def test_before_track_nearest_within_window():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    # 30 seconds before track start — within the 60-second default window
    results = match_all([_rec(_utc(9, 59, 30))], points, _cfg(on_photo_before_track="nearest"))
    assert results[0].status == MatchStatus.MATCHED
    assert results[0].matched_lat == 50.0


def test_before_track_nearest_beyond_window():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    # 1 hour before track start — beyond the 60-second window, falls back to warn
    results = match_all([_rec(_utc(9, 0, 0))], points, _cfg(on_photo_before_track="nearest"))
    assert results[0].status == MatchStatus.WARNED


def test_before_track_nearest_custom_window():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    # 1 hour before; window raised to cover it
    results = match_all(
        [_rec(_utc(9, 0, 0))],
        points,
        _cfg(on_photo_before_track="nearest", on_photo_before_track_max_seconds=3601),
    )
    assert results[0].status == MatchStatus.MATCHED
    assert results[0].matched_lat == 50.0


def test_after_track_nearest_within_window():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    # 30 seconds after track end — within the 60-second default window
    results = match_all([_rec(_utc(10, 0, 30))], points, _cfg(on_photo_after_track="nearest"))
    assert results[0].status == MatchStatus.MATCHED


def test_after_track_nearest_beyond_window():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    # 1 hour after track end — beyond window, falls back to warn
    results = match_all([_rec(_utc(11, 0, 0))], points, _cfg(on_photo_after_track="nearest"))
    assert results[0].status == MatchStatus.WARNED


# ------------------------------------------------------------------ no timestamp

def test_no_timestamp_skipped():
    points = [_tp(_utc(10, 0, 0), 50.0, 20.0)]
    results = match_all([_rec(None)], points, _cfg())
    assert results[0].status == MatchStatus.SKIPPED
    assert "No timestamp" in results[0].reason


# ------------------------------------------------------------------ gap

def test_gap_warn():
    p1 = _tp(_utc(10, 0, 0), 50.0, 20.0)
    p2 = _tp(_utc(10, 10, 0), 50.1, 20.1)  # 600s gap
    t = _utc(10, 5, 0)
    results = match_all([_rec(t)], [p1, p2], _cfg(track_gap_threshold_seconds=300, on_track_gap="warn"))
    assert results[0].status == MatchStatus.WARNED


def test_gap_interpolate():
    p1 = _tp(_utc(10, 0, 0), 50.0, 20.0)
    p2 = _tp(_utc(10, 10, 0), 50.0, 20.0)
    t = _utc(10, 5, 0)
    results = match_all([_rec(t)], [p1, p2], _cfg(track_gap_threshold_seconds=300, on_track_gap="interpolate"))
    assert results[0].status == MatchStatus.MATCHED


# ------------------------------------------------------------------ existing GPS

def test_existing_gps_warn_above_threshold():
    p = _tp(_utc(10, 0, 0), 50.0, 20.0)
    # existing GPS is far away
    rec = _rec(_utc(10, 0, 0), has_gps=True, lat=51.0, lon=21.0)
    results = match_all([rec], [p], _cfg(on_existing_gps="warn", existing_gps_distance_threshold_meters=50))
    assert results[0].status == MatchStatus.WARNED
    assert results[0].distance_to_existing_meters > 50


def test_existing_gps_skip():
    p = _tp(_utc(10, 0, 0), 50.0, 20.0)
    rec = _rec(_utc(10, 0, 0), has_gps=True, lat=50.0, lon=20.0)
    results = match_all([rec], [p], _cfg(on_existing_gps="skip"))
    assert results[0].status == MatchStatus.SKIPPED


def test_existing_gps_overwrite():
    p = _tp(_utc(10, 0, 0), 50.0, 20.0)
    rec = _rec(_utc(10, 0, 0), has_gps=True, lat=51.0, lon=21.0)
    results = match_all([rec], [p], _cfg(on_existing_gps="overwrite"))
    assert results[0].status == MatchStatus.MATCHED


# ------------------------------------------------------------------ units

def test_meters_to_display_metric():
    assert meters_to_display(42.0, "metric") == "42 m"
    assert "km" in meters_to_display(1500.0, "metric")


def test_meters_to_display_imperial():
    assert "ft" in meters_to_display(10.0, "imperial")
    assert "mi" in meters_to_display(2000.0, "imperial")
