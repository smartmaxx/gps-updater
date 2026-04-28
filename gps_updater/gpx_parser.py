from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gpxpy
import gpxpy.gpx

from gps_updater.models import TrackPoint

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".heic", ".heif",
    ".cr2", ".cr3", ".arw", ".nef", ".nrw",
    ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".x3f",
}
_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts", ".3gp",
}


def build_database(
    source: Path,
    recursive: bool,
    on_duplicate: str,
) -> list[TrackPoint]:
    """
    Parse all GPX files found at source (file or folder).
    Returns a sorted, deduplicated list of TrackPoints.
    Exits with an error if the resulting database is empty.
    """
    gpx_files = _collect_files(source, recursive)
    if not gpx_files:
        logger.error("No GPX files found at: %s", source)
        return []

    all_points: list[TrackPoint] = []
    for path in gpx_files:
        points = _parse_file(path)
        if points is not None:
            all_points.extend(points)

    if not all_points:
        return []

    all_points.sort(key=lambda p: p.timestamp)
    all_points = _deduplicate(all_points, on_duplicate)
    return all_points


def _collect_files(source: Path, recursive: bool) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.lower() == ".gpx" else []
    if source.is_dir():
        pattern = "**/*.gpx" if recursive else "*.gpx"
        return sorted(source.glob(pattern))
    return []


def _parse_file(path: Path) -> list[TrackPoint] | None:
    """
    Parse a single GPX file. Returns None if the file should be skipped.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        gpx = gpxpy.parse(text)
    except Exception as exc:
        logger.error("Cannot parse GPX file %s: %s", path, exc)
        return None

    points = _extract_track_points(gpx, path)
    if not points:
        points = _extract_waypoints(gpx, path)

    if not points:
        logger.error(
            "GPX file contains no usable track points or waypoints: %s — skipping", path
        )
        return None

    timestamped = [p for p in points if p.timestamp is not None]
    if not timestamped:
        logger.error(
            "GPX file %s contains %d point(s) but none have timestamps — skipping",
            path,
            len(points),
        )
        return None

    skipped = len(points) - len(timestamped)
    if skipped > 0:
        logger.debug("Skipped %d point(s) without timestamps in %s", skipped, path)

    logger.debug("Loaded %d point(s) from %s", len(timestamped), path)
    return timestamped


def _extract_track_points(gpx: gpxpy.gpx.GPX, path: Path) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                tp = _gpx_point_to_trackpoint(pt, path)
                if tp is not None:
                    points.append(tp)
    return points


def _extract_waypoints(gpx: gpxpy.gpx.GPX, path: Path) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for wpt in gpx.waypoints:
        tp = _gpx_point_to_trackpoint(wpt, path)
        if tp is not None:
            points.append(tp)
    return points


def _gpx_point_to_trackpoint(
    pt: Any, path: Path
) -> TrackPoint | None:
    ts: datetime | None = None
    if pt.time is not None:
        ts = pt.time
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

    hdop: float | None = None
    pdop: float | None = None
    if hasattr(pt, "horizontal_dilution") and pt.horizontal_dilution is not None:
        try:
            hdop = float(pt.horizontal_dilution)
        except (ValueError, TypeError):
            pass
    if hasattr(pt, "position_dilution") and pt.position_dilution is not None:
        try:
            pdop = float(pt.position_dilution)
        except (ValueError, TypeError):
            pass

    elevation: float | None = None
    if pt.elevation is not None:
        try:
            elevation = float(pt.elevation)
        except (ValueError, TypeError):
            pass

    return TrackPoint(
        timestamp=ts,
        latitude=float(pt.latitude),
        longitude=float(pt.longitude),
        elevation=elevation,
        hdop=hdop,
        pdop=pdop,
        source_file=path,
    )


def _deduplicate(points: list[TrackPoint], on_duplicate: str) -> list[TrackPoint]:
    """
    Remove duplicate timestamps according to on_duplicate strategy.
    Input must be sorted by timestamp.
    """
    if not points:
        return points

    result: list[TrackPoint] = []
    i = 0
    while i < len(points):
        j = i + 1
        while j < len(points) and points[j].timestamp == points[i].timestamp:
            j += 1

        group = points[i:j]
        if len(group) == 1:
            result.append(group[0])
        else:
            chosen = _resolve_duplicate(group, on_duplicate)
            if chosen is not None:
                result.append(chosen)
        i = j

    return result


def _resolve_duplicate(
    group: list[TrackPoint], on_duplicate: str
) -> TrackPoint | None:
    ts = group[0].timestamp
    files = {str(p.source_file) for p in group}

    if on_duplicate == "warn_skip":
        logger.warning(
            "Duplicate timestamp %s in %d points from %s — skipping all",
            ts.isoformat(),
            len(group),
            ", ".join(files),
        )
        return None

    if on_duplicate == "prefer_accuracy":
        with_hdop = [p for p in group if p.hdop is not None]
        if with_hdop:
            best = min(with_hdop, key=lambda p: p.hdop)
            logger.debug(
                "Duplicate timestamp %s: chose point with HDOP %.2f from %s",
                ts.isoformat(),
                best.hdop,
                best.source_file,
            )
            return best

    # use_first (default fallback)
    logger.debug(
        "Duplicate timestamp %s in %d points — using first", ts.isoformat(), len(group)
    )
    return group[0]
