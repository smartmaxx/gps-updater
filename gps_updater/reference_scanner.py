from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from gps_updater.models import CameraProfile, TrackPoint
from gps_updater import exiftool
from gps_updater import gpx_parser
from gps_updater import plugins as plugin_registry

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".heic", ".heif",
    ".cr2", ".cr3", ".arw", ".nef", ".nrw",
    ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".x3f",
}
_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts", ".3gp",
}
_MEDIA_EXTENSIONS = _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS


def scan(
    reference_paths: list[Path],
    media_path: Path,
    recursive: bool,
    on_duplicate: str,
    loaded_profiles: list[CameraProfile],
    timezone_obj: Any,
    offset_seconds: int,
    exclude_dirs: set[Path] | None = None,
) -> tuple[list[TrackPoint], set[Path]]:
    """
    Scan the reference sources and return a sorted, deduplicated trackpoint
    database together with the set of file paths that were consumed as
    reference sources (so the media scanner can exclude them).

    Parameters
    ----------
    reference_paths:
        One or more files or folders given via --reference.
    media_path:
        File or folder given via --media (used for same-folder detection).
    recursive:
        Whether to recurse into subfolders.
    on_duplicate:
        Duplicate timestamp policy: "use_first", "warn_skip", "prefer_accuracy".
    loaded_profiles:
        Camera profiles already loaded by plugins.load_all().
    timezone_obj:
        Resolved timezone (datetime.timezone or zoneinfo.ZoneInfo) used as
        fallback when reading datetime_original timestamps.
    offset_seconds:
        Camera clock drift correction applied after timezone conversion.
    """
    media_path = media_path.resolve()
    resolved_reference_paths = [p.resolve() for p in reference_paths]
    same_folder_set = {p for p in resolved_reference_paths if p == media_path}

    gpx_files: list[Path] = []
    media_files: list[Path] = []
    consumed_paths: set[Path] = set()

    for reference_path in resolved_reference_paths:
        if reference_path.is_file():
            ext = reference_path.suffix.lower()
            if ext == ".gpx":
                gpx_files.append(reference_path)
            elif ext in _MEDIA_EXTENSIONS:
                media_files.append(reference_path)
            else:
                logger.warning("Reference file has unrecognised extension: %s", reference_path)
        elif reference_path.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in reference_path.glob(pattern):
                if not child.is_file():
                    continue
                if exclude_dirs and any(child.resolve().is_relative_to(d) for d in exclude_dirs):
                    continue
                ext = child.suffix.lower()
                if ext == ".gpx":
                    gpx_files.append(child)
                elif ext in _MEDIA_EXTENSIONS:
                    media_files.append(child)
        else:
            logger.error("Reference path does not exist: %s", reference_path)

    all_points: list[TrackPoint] = []
    gpx_point_count = 0

    for gpx_file in gpx_files:
        points = gpx_parser._parse_file(gpx_file)
        if points is None:
            logger.error("GPX file rejected (no timestamps): %s", gpx_file)
            continue
        all_points.extend(points)
        gpx_point_count += len(points)
        consumed_paths.add(gpx_file.resolve())

    any_same_folder = bool(same_folder_set)
    media_point_count = 0

    if media_files:
        metadata_list = exiftool.read_metadata(media_files)
        for media_file, meta in zip(media_files, metadata_list):
            lat = meta.get("GPSLatitude")
            lon = meta.get("GPSLongitude")
            if lat is None or lon is None:
                if not any_same_folder:
                    logger.debug("No GPS in reference media file: %s", media_file)
                continue

            make = meta.get("Make")
            model = meta.get("Model")
            profile = plugin_registry.match(loaded_profiles, make, model)

            ref_source = "gps_timestamp"
            if profile is not None:
                ref_source = profile.reference_timestamp_source

            ts = _extract_reference_timestamp(meta, ref_source, timezone_obj, offset_seconds, media_file)
            if ts is None:
                logger.warning("Cannot determine timestamp for reference file: %s", media_file)
                continue

            elevation: float | None = None
            raw_ele = meta.get("GPSAltitude")
            if raw_ele is not None:
                try:
                    elevation = float(raw_ele)
                    ref_val = meta.get("GPSAltitudeRef", 0)
                    if str(ref_val) in ("1", "Below Sea Level"):
                        elevation = -elevation
                except (TypeError, ValueError):
                    elevation = None

            point = TrackPoint(
                timestamp=ts,
                latitude=float(lat),
                longitude=float(lon),
                elevation=elevation,
                hdop=None,
                pdop=None,
                source_file=media_file,
            )
            all_points.append(point)
            media_point_count += 1
            consumed_paths.add(media_file.resolve())

    ref_counts = {"gpx": gpx_point_count, "media": media_point_count}

    if not all_points:
        return [], consumed_paths, ref_counts

    all_points.sort(key=lambda p: p.timestamp)
    deduplicated = gpx_parser._deduplicate(all_points, on_duplicate)
    return deduplicated, consumed_paths, ref_counts


def _extract_reference_timestamp(
    meta: dict[str, Any],
    ref_source: str,
    timezone_obj: Any,
    offset_seconds: int,
    file_path: Path,
) -> datetime | None:
    if ref_source == "gps_timestamp":
        ts = _from_gps_fields(meta)
        if ts is not None:
            return ts
        logger.debug(
            "reference_timestamp_source=gps_timestamp but GPS time fields absent, "
            "falling back to datetime_original for %s",
            file_path,
        )
        return _from_datetime_original(meta, timezone_obj, offset_seconds)

    if ref_source == "datetime_original":
        return _from_datetime_original(meta, timezone_obj, offset_seconds)

    logger.warning("Unknown reference_timestamp_source %r for %s", ref_source, file_path)
    return None


def _from_gps_fields(meta: dict[str, Any]) -> datetime | None:
    date_str = meta.get("GPSDateStamp") or meta.get("GPSDate")
    time_str = meta.get("GPSTimeStamp") or meta.get("GPSTime")
    if not date_str or not time_str:
        return None
    try:
        date_str = str(date_str).replace(":", "-", 2)
        combined = f"{date_str}T{time_str}"
        if "." in time_str:
            fmt = "%Y-%m-%dT%H:%M:%S.%f"
        else:
            fmt = "%Y-%m-%dT%H:%M:%S"
        dt = datetime.strptime(combined, fmt)
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _from_datetime_original(
    meta: dict[str, Any],
    timezone_obj: Any,
    offset_seconds: int,
) -> datetime | None:
    raw = meta.get("DateTimeOriginal") or meta.get("CreateDate")
    if not raw:
        return None
    try:
        raw_str = str(raw)
        if "." in raw_str:
            fmt = "%Y:%m:%d %H:%M:%S.%f"
        else:
            fmt = "%Y:%m:%d %H:%M:%S"
        dt_local = datetime.strptime(raw_str[:19], "%Y:%m:%d %H:%M:%S")

        offset_field = meta.get("OffsetTimeOriginal") or meta.get("OffsetTime")
        if offset_field:
            try:
                sign = 1 if str(offset_field)[0] != "-" else -1
                parts = str(offset_field).lstrip("+-").split(":")
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
                fixed_tz = timezone(sign * timedelta(hours=h, minutes=m))
                dt_aware = dt_local.replace(tzinfo=fixed_tz)
                utc = dt_aware.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
                return utc - timedelta(seconds=offset_seconds)
            except (ValueError, IndexError):
                pass

        dt_aware = dt_local.replace(tzinfo=timezone_obj)
        utc = dt_aware.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
        return utc - timedelta(seconds=offset_seconds)
    except (ValueError, TypeError):
        return None
