from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gps_updater.display import RunSummary
from gps_updater.models import MatchResult, MatchStatus, TrackPoint

logger = logging.getLogger(__name__)


def write_status_file(
    path: Path,
    results: list[MatchResult],
    track_points: list[TrackPoint],
    summary: RunSummary,
    reference_paths: list[Path],
    media_path: Path,
    config: dict[str, Any],
    tz_name: str,
    ref_counts: dict[str, int],
    dry_run: bool,
) -> None:
    lines: list[str] = []

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("GPS-UPDATER STATUS REPORT")
    lines.append("=" * 40)
    lines.append(f"Run: {now}")
    lines.append(f"Reference: {', '.join(str(p) for p in reference_paths)}")
    lines.append(f"Media: {media_path}")
    lines.append(f"Timezone: {tz_name}")
    if dry_run:
        lines.append("Dry run: yes — no files were modified")
    lines.append("")

    lines.append("REFERENCE SOURCE")
    total_ref = ref_counts.get("gpx", 0) + ref_counts.get("media", 0)
    lines.append(f"  {total_ref:,} track points total")
    if ref_counts.get("gpx"):
        lines.append(f"    {ref_counts['gpx']:,} from GPX files")
    if ref_counts.get("media"):
        lines.append(f"    {ref_counts['media']:,} from GPS-tagged media files")
    if track_points:
        first = track_points[0].timestamp
        last = track_points[-1].timestamp
        total_s = int((last - first).total_seconds())
        h = total_s // 3600
        m = (total_s % 3600) // 60
        dur = f"{h}h {m}m" if h else f"{m}m"
        lines.append(
            f"  Time range: {first.strftime('%Y-%m-%d %H:%M')} – "
            f"{last.strftime('%Y-%m-%d %H:%M')} UTC"
        )
        lines.append(f"  Duration: {dur}")
    lines.append("")

    photos_total = sum(1 for r in results if not r.media.is_video)
    videos_total = sum(1 for r in results if r.media.is_video)
    no_ts = sum(1 for r in results if r.media.capture_time is None)

    lines.append("MEDIA SCANNED")
    parts = []
    if photos_total:
        parts.append(f"{photos_total:,} photos")
    if videos_total:
        parts.append(f"{videos_total:,} videos")
    lines.append(f"  {', '.join(parts) if parts else '0 files'}")
    if no_ts:
        lines.append(f"  {no_ts} files have no timestamp and could not be matched")
    timestamped = [r for r in results if r.media.capture_time is not None]
    if timestamped:
        times = sorted(r.media.capture_time for r in timestamped)
        lines.append(
            f"  Timestamps: {times[0].strftime('%Y-%m-%d %H:%M')} – "
            f"{times[-1].strftime('%Y-%m-%d %H:%M')} UTC"
        )
    lines.append("")

    lines.append("RESULTS")
    label_w = 28
    if summary.photos_written > 0 and summary.videos_written > 0:
        lines.append(f"  {'Photos tagged:':<{label_w}} {summary.photos_written:>6}")
        lines.append(f"  {'Videos tagged:':<{label_w}} {summary.videos_written:>6}")
        lines.append(f"  {'GPS written (total):':<{label_w}} {summary.written:>6}")
    elif summary.videos_written > 0:
        lines.append(f"  {'GPS written (videos):':<{label_w}} {summary.written:>6}")
    else:
        lines.append(f"  {'GPS written:':<{label_w}} {summary.written:>6}")

    if summary.before_track or summary.after_track:
        detail = []
        if summary.before_track:
            detail.append(f"{summary.before_track} before start")
        if summary.after_track:
            detail.append(f"{summary.after_track} after end")
        lines.append(
            f"  {'Outside track range:':<{label_w}} {summary.before_track + summary.after_track:>6}"
            f"  ({', '.join(detail)})"
        )
    if summary.in_gap:
        lines.append(f"  {'In track gap:':<{label_w}} {summary.in_gap:>6}")
    if summary.already_has_gps:
        lines.append(f"  {'Already have GPS:':<{label_w}} {summary.already_has_gps:>6}")
    if summary.no_timestamp:
        lines.append(f"  {'No timestamp:':<{label_w}} {summary.no_timestamp:>6}")
    other_warned = summary.warned - summary.before_track - summary.after_track - summary.in_gap - summary.already_has_gps
    if other_warned > 0:
        lines.append(f"  {'Other warnings:':<{label_w}} {other_warned:>6}")
    if summary.skipped:
        lines.append(f"  {'Skipped:':<{label_w}} {summary.skipped:>6}")
    if summary.failed:
        lines.append(f"  {'Failed:':<{label_w}} {summary.failed:>6}")
    lines.append(f"  {'Total:':<{label_w}} {summary.total:>6}")
    lines.append("")

    _write_unmatched_section(lines, results, track_points, config)

    try:
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        Path(path).expanduser().resolve().write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("Status file written: %s", path)
    except OSError as exc:
        logger.error("Could not write status file %s: %s", path, exc)


def _format_delta(seconds: float) -> str:
    total = int(abs(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}h {m}m" if m else f"{h}h"
    if m > 0:
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{s}s"


def _write_unmatched_section(
    lines: list[str],
    results: list[MatchResult],
    track_points: list[TrackPoint],
    config: dict[str, Any],
) -> None:
    before = [r for r in results if r.status in (MatchStatus.WARNED, MatchStatus.SKIPPED)
              and (r.reason or "").startswith("before track start")]
    after = [r for r in results if r.status in (MatchStatus.WARNED, MatchStatus.SKIPPED)
             and (r.reason or "").startswith("after track end")]
    gaps = [r for r in results if r.status in (MatchStatus.WARNED, MatchStatus.SKIPPED)
            and (r.reason or "").startswith("track gap")]
    no_ts = [r for r in results if r.status == MatchStatus.SKIPPED
             and "No timestamp" in (r.reason or "")]
    has_gps = [r for r in results if r.status in (MatchStatus.WARNED, MatchStatus.SKIPPED)
               and (r.reason or "").startswith("already has GPS")]
    failed = [r for r in results if r.status == MatchStatus.FAILED]

    if not any([before, after, gaps, no_ts, has_gps, failed]):
        lines.append("All files were matched successfully.")
        return

    lines.append("UNMATCHED AND WARNED FILES")
    lines.append("")

    if before:
        track_start = track_points[0].timestamp if track_points else None
        lines.append(f"Before track start ({len(before)} files)")
        lines.append("  These files were captured before your GPS track began.")
        if track_start:
            deltas = [
                (track_start - r.media.capture_time).total_seconds()
                for r in before
                if r.media.capture_time is not None
            ]
            if deltas:
                max_delta = max(deltas)
                lines.append(
                    f"  Gaps range from {_format_delta(min(deltas))} to {_format_delta(max_delta)} before track start."
                )
                current_max = config["matching"].get("on_photo_before_track_max_seconds", 60)
                if max_delta > current_max:
                    lines.append(
                        f"  To snap all of them to the track start, set:"
                        f" on_photo_before_track=nearest  on_photo_before_track_max_seconds={int(max_delta) + 1}"
                    )
        lines.append("")
        for r in sorted(before, key=lambda x: x.media.capture_time or datetime.min.replace(tzinfo=timezone.utc)):
            if r.media.capture_time and track_start:
                delta = _format_delta((track_start - r.media.capture_time).total_seconds())
                lines.append(f"    {r.media.path.name}  ({r.media.capture_time.strftime('%Y-%m-%d %H:%M')} UTC, {delta} before start)")
            else:
                lines.append(f"    {r.media.path.name}")
        lines.append("")

    if after:
        track_end = track_points[-1].timestamp if track_points else None
        lines.append(f"After track end ({len(after)} files)")
        lines.append("  These files were captured after your GPS track ended.")
        if track_end:
            deltas = [
                (r.media.capture_time - track_end).total_seconds()
                for r in after
                if r.media.capture_time is not None
            ]
            if deltas:
                max_delta = max(deltas)
                lines.append(
                    f"  Gaps range from {_format_delta(min(deltas))} to {_format_delta(max_delta)} after track end."
                )
                current_max = config["matching"].get("on_photo_after_track_max_seconds", 60)
                if max_delta > current_max:
                    lines.append(
                        f"  To snap all of them to the track end, set:"
                        f" on_photo_after_track=nearest  on_photo_after_track_max_seconds={int(max_delta) + 1}"
                    )
        lines.append("")
        for r in sorted(after, key=lambda x: x.media.capture_time or datetime.min.replace(tzinfo=timezone.utc)):
            if r.media.capture_time and track_end:
                delta = _format_delta((r.media.capture_time - track_end).total_seconds())
                lines.append(f"    {r.media.path.name}  ({r.media.capture_time.strftime('%Y-%m-%d %H:%M')} UTC, {delta} after end)")
            else:
                lines.append(f"    {r.media.path.name}")
        lines.append("")

    if gaps:
        lines.append(f"In track gap ({len(gaps)} files)")
        lines.append(
            "  These files fall inside a gap in GPS recording where no track points exist."
        )
        lines.append(
            f"  Current gap threshold: {config['matching'].get('track_gap_threshold_seconds', 300)}s."
        )
        lines.append(
            "  To interpolate across gaps, set on_track_gap=interpolate."
        )
        lines.append(
            "  To increase the gap threshold, raise track_gap_threshold_seconds."
        )
        lines.append("")
        for r in sorted(gaps, key=lambda x: x.media.capture_time or datetime.min.replace(tzinfo=timezone.utc)):
            ts_str = r.media.capture_time.strftime("%Y-%m-%d %H:%M UTC") if r.media.capture_time else "no timestamp"
            lines.append(f"    {r.media.path.name}  ({ts_str}  {r.reason})")
        lines.append("")

    if has_gps:
        lines.append(f"Already have GPS ({len(has_gps)} files)")
        lines.append(
            "  These files already have GPS coordinates embedded."
        )
        lines.append(
            "  To overwrite them, set on_existing_gps=overwrite or pass --force."
        )
        lines.append(
            "  To skip them silently, set on_existing_gps=skip."
        )
        lines.append("")
        for r in sorted(has_gps, key=lambda x: x.media.path.name):
            lines.append(f"    {r.media.path.name}  ({r.reason})")
        lines.append("")

    if no_ts:
        lines.append(f"No timestamp ({len(no_ts)} files)")
        lines.append(
            "  These files have no usable timestamp in EXIF and cannot be matched."
        )
        lines.append(
            "  Check if the camera clock was set correctly, or if the files have been stripped of metadata."
        )
        lines.append("")
        for r in no_ts:
            lines.append(f"    {r.media.path.name}")
        lines.append("")

    if failed:
        lines.append(f"Failed ({len(failed)} files)")
        lines.append("  These files failed during processing.")
        lines.append("")
        for r in failed:
            lines.append(f"    {r.media.path.name}  ({r.reason})")
        lines.append("")


def write_export_gpx(
    path: Path,
    results: list[MatchResult],
    mode: str = "waypoints",
) -> None:
    matched = [
        r for r in results
        if r.status == MatchStatus.MATCHED
        and r.matched_lat is not None
        and r.matched_lon is not None
        and r.media.capture_time is not None
    ]
    matched.sort(key=lambda r: r.media.capture_time)

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<gpx version="1.1" creator="gps-updater"')
    lines.append('     xmlns="http://www.topografix.com/GPX/1/1">')

    if mode in ("waypoints", "both"):
        for r in matched:
            lat = r.matched_lat
            lon = r.matched_lon
            name = r.media.path.name
            ts = r.media.capture_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(f'  <wpt lat="{lat:.8f}" lon="{lon:.8f}">')
            lines.append(f"    <name>{_xml_escape(name)}</name>")
            lines.append(f"    <time>{ts}</time>")
            if r.matched_elevation is not None:
                lines.append(f"    <ele>{r.matched_elevation:.2f}</ele>")
            lines.append("  </wpt>")

    if mode in ("route", "both"):
        lines.append("  <trk>")
        lines.append("    <name>Media capture path</name>")
        lines.append("    <trkseg>")
        for r in matched:
            lat = r.matched_lat
            lon = r.matched_lon
            ts = r.media.capture_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(f'      <trkpt lat="{lat:.8f}" lon="{lon:.8f}">')
            lines.append(f"        <time>{ts}</time>")
            if r.matched_elevation is not None:
                lines.append(f"        <ele>{r.matched_elevation:.2f}</ele>")
            lines.append("      </trkpt>")
        lines.append("    </trkseg>")
        lines.append("  </trk>")

    lines.append("</gpx>")

    try:
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("Export GPX written: %s", path)
    except OSError as exc:
        logger.error("Could not write export GPX %s: %s", path, exc)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )
