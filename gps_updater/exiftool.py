from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BATCH_SIZE = 200


class ExifToolError(Exception):
    pass


def read_metadata(paths: list[Path]) -> list[dict[str, Any]]:
    """
    Read EXIF metadata for a list of files using ExifTool batch mode.
    Returns a list of dicts, one per file, in the same order as paths.
    """
    if not paths:
        return []

    results: list[dict[str, Any]] = []
    for i in range(0, len(paths), _BATCH_SIZE):
        batch = paths[i : i + _BATCH_SIZE]
        results.extend(_run_read(batch))
    return results


def write_gps(
    path: Path,
    lat: float,
    lon: float,
    elevation: float | None,
    gps_datetime: str | None,
    preserve_file_date: bool = True,
    output_path: Path | None = None,
    backup_path: Path | None = None,
) -> None:
    """
    Write GPS coordinates (and optionally elevation and GPS datetime) to a file.

    output_path: if set, write the modified file here and leave the original
                 untouched; the caller is responsible for creating parent dirs.
    backup_path: if set, copy the original here before writing; the caller is
                 responsible for creating parent dirs and for the filename.

    Raises ExifToolError on failure.
    """
    import shutil

    if backup_path is not None:
        try:
            shutil.copy2(path, backup_path)
        except OSError as exc:
            raise ExifToolError(f"Cannot create backup for {path}: {exc}") from exc

    lat_ref = "N" if lat >= 0 else "S"
    lon_ref = "E" if lon >= 0 else "W"

    args = [
        "exiftool",
        f"-GPSLatitude={abs(lat)}",
        f"-GPSLatitudeRef={lat_ref}",
        f"-GPSLongitude={abs(lon)}",
        f"-GPSLongitudeRef={lon_ref}",
    ]

    if elevation is not None:
        alt_ref = 0 if elevation >= 0 else 1
        args += [
            f"-GPSAltitude={abs(elevation)}",
            f"-GPSAltitudeRef={alt_ref}",
        ]

    if gps_datetime is not None:
        date_part, time_part = gps_datetime.split(" ")
        args += [
            f"-GPSDateStamp={date_part}",
            f"-GPSTimeStamp={time_part}",
        ]

    if output_path is not None:
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError as exc:
                raise ExifToolError(f"Cannot remove existing output file {output_path}: {exc}") from exc
        args += ["-o", str(output_path)]
    else:
        args.append("-overwrite_original")

    if preserve_file_date:
        args.append("-P")

    args.append(str(path))

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise ExifToolError(f"ExifTool timed out writing to {path}")
    except Exception as exc:
        raise ExifToolError(f"ExifTool subprocess error for {path}: {exc}") from exc

    if result.returncode != 0:
        raise ExifToolError(
            f"ExifTool failed for {path}: {result.stderr.strip() or result.stdout.strip()}"
        )


def _run_read(paths: list[Path]) -> list[dict[str, Any]]:
    args = ["exiftool", "-json", "-charset", "utf8", "-n"] + [str(p) for p in paths]
    try:
        result = subprocess.run(args, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ExifToolError("ExifTool timed out reading metadata")
    except Exception as exc:
        raise ExifToolError(f"ExifTool subprocess error: {exc}") from exc

    if result.returncode not in (0, 1):
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise ExifToolError(f"ExifTool read failed: {stderr}")

    stdout = result.stdout.decode("utf-8", errors="replace")
    if not stdout.strip():
        return [{} for _ in paths]

    try:
        parsed: list[dict[str, Any]] = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ExifToolError(f"ExifTool returned invalid JSON: {exc}") from exc

    # ExifTool may omit entries for files it could not read; pad to match input length
    if len(parsed) < len(paths):
        parsed.extend([{} for _ in range(len(paths) - len(parsed))])

    return parsed
