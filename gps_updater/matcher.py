from __future__ import annotations

import bisect
import logging
import math
from datetime import timedelta
from typing import Any

from gps_updater.models import MatchResult, MatchStatus, MediaRecord, TrackPoint

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M = 6_371_000.0


def match_all(
    media_records: list[MediaRecord],
    track_points: list[TrackPoint],
    config: dict[str, Any],
) -> list[MatchResult]:
    """Match every MediaRecord against the trackpoint database."""
    results = []
    for record in media_records:
        results.append(_match_one(record, track_points, config))
    return results


def match_one(
    record: MediaRecord,
    track_points: list[TrackPoint],
    config: dict[str, Any],
) -> MatchResult:
    """Match a single MediaRecord against the trackpoint database."""
    return _match_one(record, track_points, config)


def _match_one(
    record: MediaRecord,
    track_points: list[TrackPoint],
    config: dict[str, Any],
) -> MatchResult:
    matching_cfg = config["matching"]

    if record.capture_time is None:
        return MatchResult(
            media=record,
            status=MatchStatus.SKIPPED,
            matched_lat=None,
            matched_lon=None,
            matched_elevation=None,
            interpolation_ratio=None,
            distance_to_existing_meters=None,
            reason="No timestamp available",
        )

    if not track_points:
        return MatchResult(
            media=record,
            status=MatchStatus.FAILED,
            matched_lat=None,
            matched_lon=None,
            matched_elevation=None,
            interpolation_ratio=None,
            distance_to_existing_meters=None,
            reason="Trackpoint database is empty",
        )

    t = record.capture_time
    timestamps = [p.timestamp for p in track_points]

    # Boundary checks
    if t < track_points[0].timestamp:
        return _handle_boundary(
            record, track_points[0], matching_cfg["on_photo_before_track"], "before track", matching_cfg
        )
    if t > track_points[-1].timestamp:
        return _handle_boundary(
            record, track_points[-1], matching_cfg["on_photo_after_track"], "after track", matching_cfg
        )

    # Find surrounding points
    idx = bisect.bisect_left(timestamps, t)

    if track_points[idx].timestamp == t:
        # Exact match
        pt = track_points[idx]
        return _build_matched(record, pt.latitude, pt.longitude, pt.elevation, 0.0, matching_cfg)

    # idx is the first point after t
    p1 = track_points[idx - 1]
    p2 = track_points[idx]

    gap_seconds = (p2.timestamp - p1.timestamp).total_seconds()
    gap_threshold = matching_cfg["track_gap_threshold_seconds"]

    if gap_seconds > gap_threshold:
        on_gap = matching_cfg["on_track_gap"]
        gap_h = int(gap_seconds) // 3600
        gap_m = (int(gap_seconds) % 3600) // 60
        gap_s = int(gap_seconds) % 60
        if gap_h > 0:
            gap_human = f"{gap_h}h {gap_m}m"
        elif gap_m > 0:
            gap_human = f"{gap_m}m {gap_s}s"
        else:
            gap_human = f"{gap_s}s"

        if on_gap == "skip":
            return MatchResult(
                media=record,
                status=MatchStatus.SKIPPED,
                matched_lat=None,
                matched_lon=None,
                matched_elevation=None,
                interpolation_ratio=None,
                distance_to_existing_meters=None,
                reason=f"track gap — falls in a {gap_human} gap in GPS recording",
            )
        if on_gap == "warn":
            logger.debug(
                "%s: falls in a %s gap in GPS recording — skipping",
                record.path.name,
                gap_human,
            )
            return MatchResult(
                media=record,
                status=MatchStatus.WARNED,
                matched_lat=None,
                matched_lon=None,
                matched_elevation=None,
                interpolation_ratio=None,
                distance_to_existing_meters=None,
                reason=f"track gap — falls in a {gap_human} gap in GPS recording",
            )
        # interpolate: fall through

    ratio = (t - p1.timestamp).total_seconds() / (p2.timestamp - p1.timestamp).total_seconds()
    lat = p1.latitude + ratio * (p2.latitude - p1.latitude)
    lon = p1.longitude + ratio * (p2.longitude - p1.longitude)

    elevation: float | None = None
    if p1.elevation is not None and p2.elevation is not None:
        elevation = p1.elevation + ratio * (p2.elevation - p1.elevation)
    elif p1.elevation is not None:
        elevation = p1.elevation

    return _build_matched(record, lat, lon, elevation, ratio, matching_cfg)


def _build_matched(
    record: MediaRecord,
    lat: float,
    lon: float,
    elevation: float | None,
    ratio: float,
    matching_cfg: dict[str, Any],
) -> MatchResult:
    distance: float | None = None

    if record.has_existing_gps and record.existing_lat is not None and record.existing_lon is not None:
        distance = haversine(record.existing_lat, record.existing_lon, lat, lon)
        threshold = matching_cfg["existing_gps_distance_threshold_meters"]
        on_existing = matching_cfg["on_existing_gps"]

        if on_existing == "skip":
            return MatchResult(
                media=record,
                status=MatchStatus.SKIPPED,
                matched_lat=lat,
                matched_lon=lon,
                matched_elevation=elevation,
                interpolation_ratio=ratio,
                distance_to_existing_meters=distance,
                reason="already has GPS — skipped (on_existing_gps=skip)",
            )

        if on_existing == "warn":
            if distance > threshold:
                logger.debug(
                    "%s already has GPS (%.6f, %.6f) — track point is %.0fm away",
                    record.path.name,
                    record.existing_lat,
                    record.existing_lon,
                    distance,
                )
            return MatchResult(
                media=record,
                status=MatchStatus.WARNED,
                matched_lat=lat,
                matched_lon=lon,
                matched_elevation=elevation,
                interpolation_ratio=ratio,
                distance_to_existing_meters=distance,
                reason=f"already has GPS — {distance:.0f}m from track point",
            )

        # overwrite: fall through to MATCHED

    return MatchResult(
        media=record,
        status=MatchStatus.MATCHED,
        matched_lat=lat,
        matched_lon=lon,
        matched_elevation=elevation,
        interpolation_ratio=ratio,
        distance_to_existing_meters=distance,
        reason=None,
    )


def _format_duration(total_s: int) -> str:
    d = total_s // 86400
    h = (total_s % 86400) // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    if d >= 2:
        return f"{d} days"
    if d == 1:
        return "1 day" if h == 0 else f"1 day {h}h"
    if h > 0:
        return f"{h}h {m}m" if m else f"{h}h"
    if m > 0:
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{s}s"


def _handle_boundary(
    record: MediaRecord,
    nearest_point: TrackPoint,
    behavior: str,
    label: str,
    matching_cfg: dict[str, Any],
) -> MatchResult:
    delta = abs(record.capture_time - nearest_point.timestamp)
    gap_str = _format_duration(int(delta.total_seconds()))

    if label == "before track":
        category = "before track start"
        human = f"taken {gap_str} before GPS recording started"
        max_seconds_key = "on_photo_before_track_max_seconds"
    else:
        category = "after track end"
        human = f"taken {gap_str} after GPS recording ended"
        max_seconds_key = "on_photo_after_track_max_seconds"

    reason = f"{category} — {human}"

    if behavior == "skip":
        return MatchResult(
            media=record,
            status=MatchStatus.SKIPPED,
            matched_lat=None,
            matched_lon=None,
            matched_elevation=None,
            interpolation_ratio=None,
            distance_to_existing_meters=None,
            reason=reason,
        )

    if behavior == "nearest":
        max_seconds = matching_cfg.get(max_seconds_key, 60)
        if delta.total_seconds() <= max_seconds:
            pt = nearest_point
            logger.debug("%s: %s — using nearest endpoint", record.path.name, human)
            return MatchResult(
                media=record,
                status=MatchStatus.MATCHED,
                matched_lat=pt.latitude,
                matched_lon=pt.longitude,
                matched_elevation=pt.elevation,
                interpolation_ratio=None,
                distance_to_existing_meters=None,
                reason=f"{reason} — used nearest endpoint",
            )
        # beyond threshold: fall through to warn

    logger.debug("%s: %s — skipping", record.path.name, human)
    return MatchResult(
        media=record,
        status=MatchStatus.WARNED,
        matched_lat=None,
        matched_lon=None,
        matched_elevation=None,
        interpolation_ratio=None,
        distance_to_existing_meters=None,
        reason=reason,
    )


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two lat/lon points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return _EARTH_RADIUS_M * 2 * math.asin(math.sqrt(a))


def meters_to_display(meters: float, units: str) -> str:
    if units == "imperial":
        feet = meters * 3.28084
        if feet >= 5280:
            return f"{feet / 5280:.2f} mi"
        return f"{feet:.0f} ft"
    if meters >= 1000:
        return f"{meters / 1000:.2f} km"
    return f"{meters:.0f} m"
