from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import zoneinfo


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "time": {
        "timezone": None,
        "offset_seconds": 0,
    },
    "scan": {
        "recursive": True,
        "plugins_dir": None,
    },
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
    "output": {
        "write_elevation": True,
        "write_gps_datetime": True,
        "create_backup": True,
        "backup_dir": None,
        "output_dir": None,
        "preserve_file_date": True,
        "units": "metric",
        "export_gpx": None,
        "export_gpx_mode": "waypoints",
    },
    "logging": {
        "enabled": False,
        "file": "./gps-updater.log",
        "log_append": False,
        "level_file": "DEBUG",
        "level_console": "WARNING",
        "status_file": None,
    },
}

_ENUM_VALIDATORS: dict[tuple[str, str], set[str]] = {
    ("matching", "on_existing_gps"): {"warn", "skip", "overwrite"},
    ("matching", "on_duplicate_trackpoint"): {"warn_skip", "use_first", "prefer_accuracy"},
    ("matching", "on_photo_before_track"): {"warn", "skip", "nearest"},
    ("matching", "on_photo_after_track"): {"warn", "skip", "nearest"},
    ("matching", "on_track_gap"): {"interpolate", "warn", "skip"},
    ("output", "units"): {"metric", "imperial"},
    ("output", "export_gpx_mode"): {"waypoints", "route", "both"},
    ("logging", "level_file"): {"DEBUG", "INFO", "WARNING", "ERROR"},
    ("logging", "level_console"): {"DEBUG", "INFO", "WARNING", "ERROR"},
}

_TIMEZONE_ABBREVIATIONS: dict[str, str] = {
    "UTC": "UTC",
    "GMT": "Etc/GMT",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "EET": "Europe/Helsinki",
    "EEST": "Europe/Helsinki",
    "WET": "Europe/Lisbon",
    "WEST": "Europe/Lisbon",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "AKST": "America/Anchorage",
    "AKDT": "America/Anchorage",
    "HST": "Pacific/Honolulu",
    "IST": "Asia/Kolkata",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "NZST": "Pacific/Auckland",
    "NZDT": "Pacific/Auckland",
}


def load(explicit_path: Path | None = None) -> dict[str, Any]:
    """
    Discover, load, and merge all config files into a resolved dict.
    Priority: defaults < user home < cwd < explicit path.
    """
    config = copy.deepcopy(DEFAULT_CONFIG)

    paths = _discover_files()
    if explicit_path is not None:
        if not explicit_path.exists():
            print(f"[ERROR] Config file not found: {explicit_path}")
            sys.exit(2)
        paths.append(explicit_path)

    for path in paths:
        data = _load_file(path)
        data = _warn_unknown_keys(data, DEFAULT_CONFIG, source=str(path))
        config = _deep_merge(config, data)

    return config


def validate(config: dict[str, Any]) -> None:
    """
    Validate enum values. Exits with code 2 on any failure.
    """
    errors: list[str] = []
    for (section, key), allowed in _ENUM_VALIDATORS.items():
        value = config.get(section, {}).get(key)
        if value is not None and value not in allowed:
            errors.append(
                f"  {section}.{key}: '{value}' is not valid. Allowed: {', '.join(sorted(allowed))}"
            )
    if errors:
        print("[ERROR] Configuration validation failed:")
        for e in errors:
            print(e)
        sys.exit(2)


def resolve_timezone(tz_string: str | None) -> Any:
    """
    Resolve a timezone string to a tzinfo object.
    Accepts IANA names, common abbreviations, and offset strings.
    Returns the system local timezone when tz_string is None.
    """
    if tz_string is None:
        return _system_timezone()

    # IANA named zone
    try:
        return zoneinfo.ZoneInfo(tz_string)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        pass

    # Common abbreviation
    iana = _TIMEZONE_ABBREVIATIONS.get(tz_string.upper())
    if iana is not None:
        try:
            return zoneinfo.ZoneInfo(iana)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            pass

    # Numeric offset: +2, +02, +2:00, +02:00, -05:30
    fixed = _parse_offset(tz_string)
    if fixed is not None:
        return fixed

    print(f"[ERROR] Cannot resolve timezone: '{tz_string}'")
    print("        Accepted formats: IANA name (Europe/Warsaw), abbreviation (CET), offset (+02:00)")
    sys.exit(2)


def timezone_display_name(tz: Any) -> str:
    """Return a human-readable label for a tzinfo object."""
    if isinstance(tz, zoneinfo.ZoneInfo):
        return tz.key
    if isinstance(tz, timezone):
        offset = tz.utcoffset(None)
        total = int(offset.total_seconds())
        sign = "+" if total >= 0 else "-"
        total = abs(total)
        return f"UTC{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"
    return str(tz)


def write_default(output_path: Path, config: dict[str, Any] | None = None) -> None:
    """Write an annotated config (JSONC) to output_path.

    When config is None the built-in defaults are used. Pass a merged/overridden
    config dict to have the file reflect those values while keeping all comments.
    """
    if config is None:
        config = copy.deepcopy(DEFAULT_CONFIG)
    output_path.write_text(_render_annotated_config(config), encoding="utf-8")


def _v(value: Any) -> str:
    """Serialize a single config value to its JSON representation."""
    return json.dumps(value)


def _render_annotated_config(c: dict[str, Any]) -> str:
    t = c["time"]
    s = c["scan"]
    m = c["matching"]
    o = c["output"]
    lg = c["logging"]
    return f"""\
{{
  "schema_version": {_v(c["schema_version"])},

  "time": {{
    // Camera timezone. Accepts IANA name (e.g. Europe/Warsaw), common abbreviation
    // (CET, PST, JST), or fixed offset (+02:00, -05:30).
    // null = use the system timezone.
    "timezone": {_v(t["timezone"])},

    // Camera clock drift correction in seconds.
    // Positive = camera clock was ahead of real time (subtract from photo time).
    // Negative = camera clock was behind real time (add to photo time).
    "offset_seconds": {_v(t["offset_seconds"])}
  }},

  "scan": {{
    // Recurse into subfolders when scanning both the reference source and the
    // media folder.
    "recursive": {_v(s["recursive"])},

    // Path to a folder containing custom camera profile JSON files (plugins).
    // null = use built-in profiles only.
    "plugins_dir": {_v(s["plugins_dir"])}
  }},

  "matching": {{
    // What to do when a media file already has embedded GPS coordinates.
    // "warn"      — keep existing GPS and show a warning in the summary
    // "skip"      — silently keep existing GPS
    // "overwrite" — replace existing GPS with coordinates from the track
    "on_existing_gps": {_v(m["on_existing_gps"])},

    // When on_existing_gps is "warn", only warn if the track point is farther
    // than this many metres from the existing coordinates.
    "existing_gps_distance_threshold_meters": {_v(m["existing_gps_distance_threshold_meters"])},

    // How to handle duplicate timestamps in the GPS track.
    // "use_first"       — keep the first point seen, discard the rest
    // "warn_skip"       — discard duplicates and log a warning
    // "prefer_accuracy" — keep the point with the best HDOP/PDOP value
    "on_duplicate_trackpoint": {_v(m["on_duplicate_trackpoint"])},

    // What to do when a photo was taken before the GPS track started.
    // "warn"    — include in output with a counter in the summary
    // "skip"    — exclude silently
    // "nearest" — assign coordinates of the first track point (within max_seconds; warn if beyond)
    "on_photo_before_track": {_v(m["on_photo_before_track"])},

    // Maximum seconds before track start for "nearest" to apply.
    // Photos further than this fall back to "warn" even when on_photo_before_track is "nearest".
    "on_photo_before_track_max_seconds": {_v(m["on_photo_before_track_max_seconds"])},

    // What to do when a photo was taken after the GPS track ended.
    // "warn"    — include in output with a counter in the summary
    // "skip"    — exclude silently
    // "nearest" — assign coordinates of the last track point (within max_seconds; warn if beyond)
    "on_photo_after_track": {_v(m["on_photo_after_track"])},

    // Maximum seconds after track end for "nearest" to apply.
    // Photos further than this fall back to "warn" even when on_photo_after_track is "nearest".
    "on_photo_after_track_max_seconds": {_v(m["on_photo_after_track_max_seconds"])},

    // A gap larger than this number of seconds between consecutive track points
    // is treated as a GPS outage (signal loss).
    "track_gap_threshold_seconds": {_v(m["track_gap_threshold_seconds"])},

    // What to do when a photo falls inside a GPS gap.
    // "interpolate" — linearly interpolate coordinates between the surrounding points
    // "warn"        — skip with a counter in the summary
    // "skip"        — skip silently
    "on_track_gap": {_v(m["on_track_gap"])}
  }},

  "output": {{
    // Write GPS elevation (altitude above sea level) to the file.
    "write_elevation": {_v(o["write_elevation"])},

    // Write a GPS date/time stamp derived from the matched track point.
    "write_gps_datetime": {_v(o["write_gps_datetime"])},

    // Create a backup copy of each original file before writing GPS.
    // The backup is named <stem>_original.<ext>.
    // If backup_dir is set, backups go there; otherwise next to the originals.
    "create_backup": {_v(o["create_backup"])},

    // Directory for backup copies. null = place backups next to the originals.
    // Accepts an absolute path or a path relative to the working directory.
    "backup_dir": {_v(o["backup_dir"])},

    // Directory where geotagged output files are written.
    // null = modify the original files in place.
    // Accepts an absolute path or a path relative to the working directory.
    "output_dir": {_v(o["output_dir"])},

    // Preserve the file modification date after writing GPS metadata.
    "preserve_file_date": {_v(o["preserve_file_date"])},

    // Distance unit used in log messages and the run summary.
    // "metric"   — metres and kilometres
    // "imperial" — feet and miles
    "units": {_v(o["units"])},

    // Path to write an export GPX file after each run.
    // The file contains matched media files as GPX points, ordered by capture time.
    // Open it in gpx.studio, GPXSee, or digiKam to visually verify coordinates.
    // null = do not generate an export GPX.
    "export_gpx": {_v(o["export_gpx"])},

    // What to write into the export GPX file.
    // "waypoints" — one named <wpt> per file; shows as pins in map apps
    // "route"     — files connected as a <trk> segment; shows the path walked
    // "both"      — waypoints and route track in the same file
    "export_gpx_mode": {_v(o["export_gpx_mode"])}
  }},

  "logging": {{
    // Enable persistent logging to a file. When false, passing --log on the
    // command line still enables logging for that single run.
    "enabled": {_v(lg["enabled"])},

    // Path to the log file. Accepts an absolute path or a path relative to
    // the working directory.
    "file": {_v(lg["file"])},

    // Append to the log file instead of overwriting it on each run.
    "log_append": {_v(lg["log_append"])},

    // Log level written to the file.
    // One of: DEBUG, INFO, WARNING, ERROR
    "level_file": {_v(lg["level_file"])},

    // Minimum log level echoed to the console (only when --verbose is active).
    // One of: DEBUG, INFO, WARNING, ERROR
    "level_console": {_v(lg["level_console"])},

    // Path to write a human-readable status report after each run.
    // The report lists matched and unmatched files, counts by category,
    // and actionable suggestions for improving coverage on the next run.
    // null = do not generate a status file.
    "status_file": {_v(lg["status_file"])}
  }}
}}
"""


def _discover_files() -> list[Path]:
    candidates = [
        Path.home() / ".config" / "gps-updater" / "config.json",
        Path.cwd() / "gps-updater.json",
    ]
    return [p for p in candidates if p.exists()]


def _strip_comments(text: str) -> str:
    """Strip // line comments and /* */ block comments, respecting string literals."""
    result: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    while i < length:
        if in_string:
            ch = text[i]
            result.append(ch)
            if ch == "\\":
                i += 1
                if i < length:
                    result.append(text[i])
            elif ch == '"':
                in_string = False
            i += 1
        else:
            if text[i] == '"':
                in_string = True
                result.append(text[i])
                i += 1
            elif text[i:i + 2] == "//":
                while i < length and text[i] != "\n":
                    i += 1
            elif text[i:i + 2] == "/*":
                i += 2
                while i < length - 1 and text[i:i + 2] != "*/":
                    i += 1
                i += 2
            else:
                result.append(text[i])
                i += 1
    return "".join(result)


def _load_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(_strip_comments(text))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid JSON in config file {path}: {exc}")
        sys.exit(2)
    except OSError as exc:
        print(f"[ERROR] Cannot read config file {path}: {exc}")
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"[ERROR] Config file {path} must contain a JSON object at the top level")
        sys.exit(2)
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _warn_unknown_keys(
    user: dict[str, Any],
    reference: dict[str, Any],
    source: str,
    path: str = "",
) -> dict[str, Any]:
    """
    Recursively warn about keys not present in the reference schema and return
    a copy of user with those keys removed.
    """
    cleaned: dict[str, Any] = {}
    for key, value in user.items():
        current = f"{path}.{key}" if path else key
        if key not in reference:
            print(f"[WARN] Unknown config key '{current}' in {source} — ignored")
        elif isinstance(value, dict) and isinstance(reference.get(key), dict):
            cleaned[key] = _warn_unknown_keys(value, reference[key], source, current)
        else:
            cleaned[key] = value
    return cleaned


def _system_timezone() -> Any:
    import os
    from pathlib import Path

    tz_env = os.environ.get("TZ")
    if tz_env:
        try:
            return zoneinfo.ZoneInfo(tz_env)
        except Exception:
            pass

    try:
        etc_localtime = Path("/etc/localtime")
        if etc_localtime.is_symlink():
            target = str(etc_localtime.resolve())
            if "zoneinfo/" in target:
                tz_name = target.split("zoneinfo/", 1)[1]
                return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        pass

    return datetime.now().astimezone().tzinfo


def _parse_offset(s: str) -> timezone | None:
    import re
    m = re.fullmatch(r"([+-])(\d{1,2})(?::(\d{2}))?", s.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours = int(m.group(2))
    minutes = int(m.group(3)) if m.group(3) else 0
    if hours > 14 or minutes > 59:
        return None
    return timezone(timedelta(seconds=sign * (hours * 3600 + minutes * 60)))
