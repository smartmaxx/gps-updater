from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gps_updater.exiftool import read_metadata, ExifToolError
from gps_updater.models import CameraProfile, MediaRecord
from gps_updater import plugins as plugin_module

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".heic", ".heif",
    ".cr2", ".cr3", ".arw", ".nef", ".nrw",
    ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".x3f",
})
_VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts", ".3gp",
})
_DEFAULT_DATETIME_FIELDS = [
    "DateTimeOriginal",
    "DateTimeDigitized",
    "CreateDate",
    "DateTime",
]


def scan(
    source: Path,
    recursive: bool,
    tz: Any,
    offset_seconds: int,
    loaded_profiles: list[CameraProfile],
    exclude_paths: set[Path] | None = None,
    exclude_dirs: set[Path] | None = None,
) -> list[MediaRecord]:
    """
    Scan source (file or folder) for media files and build MediaRecord list.
    exclude_paths: individual resolved file paths to skip (same-folder mode).
    exclude_dirs: resolved directory paths whose contents are excluded entirely
                  (used to prevent scanning output_dir or backup_dir).
    """
    paths = _collect_files(source, recursive)
    if exclude_paths:
        paths = [p for p in paths if p.resolve() not in exclude_paths]
    if exclude_dirs:
        paths = [p for p in paths if not any(p.resolve().is_relative_to(d) for d in exclude_dirs)]
    if not paths:
        logger.warning("No media files found at: %s", source)
        return []

    logger.debug("Scanning %d media file(s) for metadata", len(paths))

    try:
        metadata_list = read_metadata(paths)
    except ExifToolError as exc:
        logger.error("ExifTool metadata read failed: %s", exc)
        return []

    records: list[MediaRecord] = []
    for path, metadata in zip(paths, metadata_list):
        record = _build_record(path, metadata, tz, offset_seconds, loaded_profiles)
        records.append(record)

    return records


def _collect_files(source: Path, recursive: bool) -> list[Path]:
    all_extensions = _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS
    if source.is_file():
        if source.suffix.lower() in all_extensions:
            return [source]
        logger.debug("Skipping non-media file: %s", source)
        return []
    if source.is_dir():
        pattern = "**/*" if recursive else "*"
        found = []
        for p in sorted(source.glob(pattern)):
            if p.is_file() and p.suffix.lower() in all_extensions:
                found.append(p)
            elif p.is_file() and p.suffix.lower() not in all_extensions:
                logger.debug("Skipping unknown extension: %s", p.suffix)
        return found
    return []


def _build_record(
    path: Path,
    metadata: dict[str, Any],
    tz: Any,
    offset_seconds: int,
    loaded_profiles: list[CameraProfile],
) -> MediaRecord:
    is_video = path.suffix.lower() in _VIDEO_EXTENSIONS
    make: str | None = metadata.get("Make") or metadata.get("DeviceManufacturer")
    model: str | None = metadata.get("Model") or metadata.get("DeviceModelName")

    profile = plugin_module.match(loaded_profiles, make, model)

    capture_time, capture_time_raw, tz_applied = _extract_timestamp(
        path, metadata, tz, offset_seconds, profile, is_video
    )

    has_gps, existing_lat, existing_lon = _extract_existing_gps(metadata)

    return MediaRecord(
        path=path,
        capture_time=capture_time,
        capture_time_raw=capture_time_raw,
        timezone_applied=tz_applied,
        has_existing_gps=has_gps,
        existing_lat=existing_lat,
        existing_lon=existing_lon,
        camera_make=make,
        camera_model=model,
        camera_profile=profile,
        is_video=is_video,
    )


def _extract_timestamp(
    path: Path,
    metadata: dict[str, Any],
    tz: Any,
    offset_seconds: int,
    profile: CameraProfile | None,
    is_video: bool,
) -> tuple[datetime | None, str | None, str | None]:
    fields = (profile.datetime_field_priority if profile else None) or _DEFAULT_DATETIME_FIELDS

    if is_video and profile and profile.video_timestamp_source:
        video_field = profile.video_timestamp_source
        if video_field not in fields:
            fields = [video_field] + list(fields)

    raw: str | None = None
    for field in fields:
        value = metadata.get(field)
        if value and isinstance(value, str) and value.strip():
            raw = value.strip()
            break

    if raw is None:
        logger.debug("No timestamp found for %s", path)
        return None, None, None

    # Check if EXIF carries its own timezone offset (OffsetTimeOriginal etc.)
    exif_offset = (
        metadata.get("OffsetTimeOriginal")
        or metadata.get("OffsetTimeDigitized")
        or metadata.get("OffsetTime")
    )

    # Camera stores in UTC (e.g. GoPro)
    if profile and profile.datetime_is_utc:
        dt = _parse_exif_datetime(raw)
        if dt is None:
            return None, raw, None
        dt = dt.replace(tzinfo=timezone.utc)
        if offset_seconds:
            from datetime import timedelta
            dt = dt - timedelta(seconds=offset_seconds)
        return dt, raw, "UTC (camera profile)"

    if exif_offset:
        dt = _parse_exif_datetime_with_offset(raw, exif_offset)
        if dt is not None:
            if offset_seconds:
                from datetime import timedelta
                dt = dt - timedelta(seconds=offset_seconds)
            logger.debug("Used EXIF OffsetTime for %s: %s", path, exif_offset)
            return dt.astimezone(timezone.utc), raw, f"EXIF offset {exif_offset}"

    dt = _parse_exif_datetime(raw)
    if dt is None:
        logger.warning("Cannot parse timestamp '%s' for %s", raw, path)
        return None, raw, None

    # Localize with the provided timezone, then convert to UTC
    from datetime import timedelta
    localized = dt.replace(tzinfo=tz)
    utc = localized.astimezone(timezone.utc)
    if offset_seconds:
        utc = utc - timedelta(seconds=offset_seconds)

    from gps_updater.config import timezone_display_name
    tz_name = timezone_display_name(tz)
    return utc, raw, tz_name


def _parse_exif_datetime(s: str) -> datetime | None:
    """Parse EXIF datetime string: 'YYYY:MM:DD HH:MM:SS'"""
    import re
    m = re.match(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})", s)
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
        )
    except ValueError:
        return None


def _parse_exif_datetime_with_offset(dt_str: str, offset_str: str) -> datetime | None:
    """Parse EXIF datetime + separate offset string like '+02:00'."""
    import re
    dt = _parse_exif_datetime(dt_str)
    if dt is None:
        return None
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset_str.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    from datetime import timedelta
    offset = timezone(timedelta(hours=sign * int(m.group(2)), minutes=sign * int(m.group(3))))
    return dt.replace(tzinfo=offset)


def _extract_existing_gps(
    metadata: dict[str, Any],
) -> tuple[bool, float | None, float | None]:
    lat = metadata.get("GPSLatitude")
    lon = metadata.get("GPSLongitude")
    if lat is None or lon is None:
        return False, None, None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False, None, None
    if lat_f == 0.0 and lon_f == 0.0:
        return False, None, None

    lat_ref = metadata.get("GPSLatitudeRef", "N")
    lon_ref = metadata.get("GPSLongitudeRef", "E")
    if lat_ref == "S":
        lat_f = -lat_f
    if lon_ref == "W":
        lon_f = -lon_f

    return True, lat_f, lon_f
