from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timezone
from pathlib import Path
from typing import Any

from gps_updater.exiftool import write_gps, ExifToolError
from gps_updater.models import MatchResult, MatchStatus

logger = logging.getLogger(__name__)


def write_all(
    results: list[MatchResult],
    config: dict[str, Any],
    dry_run: bool,
    media_root: Path,
    *,
    on_progress: Callable[[], None] | None = None,
) -> list[MatchResult]:
    """
    Write GPS coordinates to all MATCHED results.
    media_root is the path given via --media; it is used to compute relative
    paths when output_dir or backup_dir are set, so that subfolder structure
    is mirrored under those directories.
    Updates result.status to FAILED on write error.
    Returns the updated list.
    """
    output_cfg = config["output"]
    write_elevation = output_cfg["write_elevation"]
    write_gps_dt = output_cfg["write_gps_datetime"]
    create_backup = output_cfg["create_backup"]
    preserve_file_date = output_cfg.get("preserve_file_date", True)
    backup_dir = Path(output_cfg["backup_dir"]) if output_cfg.get("backup_dir") else None
    output_dir = Path(output_cfg["output_dir"]) if output_cfg.get("output_dir") else None

    scan_root = media_root.resolve() if media_root.is_dir() else media_root.resolve().parent

    updated: list[MatchResult] = []
    for result in results:
        if result.status != MatchStatus.MATCHED:
            updated.append(result)
            continue

        src = result.media.path.resolve()

        try:
            rel = src.relative_to(scan_root)
        except ValueError:
            rel = Path(src.name)

        computed_output_path: Path | None = None
        if output_dir is not None:
            computed_output_path = output_dir / rel
            computed_output_path.parent.mkdir(parents=True, exist_ok=True)

        computed_backup_path: Path | None = None
        if backup_dir is not None:
            computed_backup_path = backup_dir / rel.parent / f"{rel.stem}_original{rel.suffix}"
            computed_backup_path.parent.mkdir(parents=True, exist_ok=True)
        elif create_backup and output_dir is None:
            computed_backup_path = src.parent / f"{src.stem}_original{src.suffix}"

        if dry_run:
            logger.info(
                "[dry-run] Would write GPS (%.6f, %.6f) to %s",
                result.matched_lat,
                result.matched_lon,
                computed_output_path or src,
            )
            updated.append(result)
            if on_progress is not None:
                on_progress()
            continue

        gps_dt_str: str | None = None
        if write_gps_dt and result.media.capture_time is not None:
            utc = result.media.capture_time.astimezone(timezone.utc)
            gps_dt_str = utc.strftime("%Y:%m:%d %H:%M:%S")

        try:
            write_gps(
                path=src,
                lat=result.matched_lat,
                lon=result.matched_lon,
                elevation=result.matched_elevation if write_elevation else None,
                gps_datetime=gps_dt_str,
                preserve_file_date=preserve_file_date,
                output_path=computed_output_path,
                backup_path=computed_backup_path,
            )
            logger.debug("Written GPS to %s", computed_output_path or src)
        except ExifToolError as exc:
            logger.error("Failed to write GPS to %s: %s", src, exc)
            result.status = MatchStatus.FAILED
            result.reason = str(exc)

        updated.append(result)
        if on_progress is not None:
            on_progress()

    return updated
