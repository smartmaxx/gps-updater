# Technical Specification — gps-updater v1

## Purpose

`gps-updater` is a command-line utility that matches GPS coordinates from a reference source to a set of media files (photos and videos) and writes those coordinates into the media metadata. Matching is performed by timestamp: for each target media file, the application finds the corresponding position on the reference track at the time the media was captured and interpolates the GPS coordinates.

The reference source (`--reference`) accepts GPX track files, GPS-tagged media files (photos or videos with coordinates already embedded), or any folder containing a mix of both. This allows a GPS-equipped device (phone, dedicated logger) to act as a reference track for geotagging media from a device without GPS.

---

## Version 1 Scope

Included in v1:

- CLI-only interface
- Reference source scanning: GPX files, GPS-tagged media files, or mixed folders (single file or folder, optionally recursive)
- Media file scanning (single file or folder, optionally recursive)
- Image support: JPEG, HEIC, RAW formats (CR2, ARW, NEF, DNG, and others supported by ExifTool)
- Video support: MP4, MOV, and other formats supported by ExifTool
- GPS coordinate writing (latitude, longitude, altitude — all configurable)
- Camera profile plugin system (JSON files)
- JSONC configuration file with auto-discovery
- Dry-run mode
- Backup control with configurable output and backup directories
- Live two-line progress display via `rich`
- Optional log file

Excluded from v1 (see FUTURE_IDEAS.md):

- GUI or TUI
- XMP sidecar file writing
- Reverse geocoding
- Online plugin registry
- Structured output stream for GUI integration
- Standalone binary packaging

---

## External Dependencies

The application checks for these tools at startup and exits with a clear installation message if any are missing.


| Tool                   | Purpose                                      | Install                                      |
| ---------------------- | -------------------------------------------- | -------------------------------------------- |
| ExifTool (Phil Harvey) | Reading and writing all image/video metadata | [https://exiftool.org](https://exiftool.org) |
| Python 3.10+           | Runtime                                      | [https://python.org](https://python.org)     |


Python package dependencies declared in `pyproject.toml`:

- `click` — CLI framework
- `rich` — terminal output and progress display
- `gpxpy` — GPX file parsing
- `tzdata` — IANA timezone database (for named timezone resolution on all platforms)

---

## Supported Platforms

macOS, Linux, Windows. All path handling must use `pathlib`. No platform-specific shell assumptions.

---

## CLI Interface

Commands take no prefix. Boolean parameters accept `true` / `false` (and `yes` / `no`, `1` / `0`) — the `--no-` prefix form is not used. Parameter values may be passed as `--option=value` or `--option value`; both forms are accepted.

### Commands

```
gps-updater run [OPTIONS]
gps-updater init-config [OPTIONS]
gps-updater show-config [OPTIONS]
gps-updater list-plugins [--config=PATH]
```

`run` is the primary command. `init-config` and `show-config` accept the same full option set as `run`; any options that affect configuration are applied before writing or displaying the config. Options that are only meaningful during a run (`--reference`, `--media`, `--dry-run`, `--verbose`, `--quiet`, `--disable-rich-ui`, `--log`) are accepted but ignored by `init-config` and `show-config`.

### Shared Options (all commands except `list-plugins`)


| Parameter                             | Type                | Default         | Description                                                                                                                       |
| ------------------------------------- | ------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `--reference=PATH[,PATH...]`          | string              | —               | GPS reference: one or more comma-separated paths — GPX files, GPS-tagged media files, or folders containing any mix of both      |
| `--media=PATH`                        | path                | —               | Media file or folder to geotag. May be the same path as `--reference` (see same-folder behaviour below)                          |
| `--timezone=TZ`                       | string              | system timezone | Timezone of the camera clock. Accepts named zones (`Europe/Warsaw`), abbreviations (`CET`), and offsets (`+2`, `+2:00`, `+02:00`) |
| `--time-offset-seconds=N`             | integer             | `0`             | Camera clock drift correction in seconds. Positive = camera was ahead of real time                                                |
| `--config=PATH`                       | path                | auto-discovered | Explicit config file path                                                                                                         |
| `--recursive=BOOL`                    | boolean             | `true`          | Recurse into subfolders when scanning                                                                                             |
| `--dry-run`                           | flag                | false           | Parse and match but write nothing                                                                                                 |
| `--create-backup=BOOL`                | boolean             | from config     | Create a backup copy of each original before writing                                                                              |
| `--preserve-file-date=BOOL`           | boolean             | from config     | Keep the file modification date unchanged after writing GPS                                                                       |
| `--output-dir=PATH`                   | path                | from config     | Write geotagged files here instead of modifying originals in place                                                                |
| `--backup-dir=PATH`                   | path                | from config     | Copy originals here as `<stem>_original.<ext>` before writing                                                                     |
| `--units=VALUE`                       | `metric`|`imperial` | from config     | Distance unit for warnings and output                                                                                             |
| `--verbose`                           | flag                | false           | Show per-file status lines instead of live progress display                                                                       |
| `--quiet`                             | flag                | false           | Suppress all console output except errors                                                                                         |
| `--disable-rich-ui`, `--plain-output` | flag                | false           | Disable rich progress display; use plain output                                                                                   |
| `--log=PATH`                          | path                | from config     | Write log to this file (enables logging for this run)                                                                             |

### `run`-only Options


| Parameter | Type | Default | Description                               |
| --------- | ---- | ------- | ----------------------------------------- |
| `--force` | flag | false   | Overwrite existing GPS in media files     |

`--reference` and `--media` are required for `run`. `--verbose` and `--quiet` are mutually exclusive; if both are passed, `--verbose` takes precedence.

### `init-config`-only Options


| Parameter       | Default              | Description                              |
| --------------- | -------------------- | ---------------------------------------- |
| `--output=PATH` | `./gps-updater.json` | Where to write the generated config file |
| `--force`       | false                | Overwrite if the file already exists     |

### Timezone Resolution

The `--timezone` value (or the `time.timezone` config key) is resolved in this order:

1. IANA named zone: `Europe/Warsaw`, `America/New_York`, `UTC`, etc. — resolved via `zoneinfo`
2. Common abbreviations: `CET`, `EST`, `PST`, etc. — resolved via a built-in abbreviation table (abbreviations are ambiguous; the table maps to the most common IANA zone for each)
3. Numeric offset: `+2`, `+02`, `+2:00`, `+02:00`, `-05:30` — parsed to a fixed `timezone` object

If `--timezone` is omitted and no value is set in config, the system local timezone is used. A notice is printed at startup indicating which timezone was applied.

`--timezone` is the fallback of last resort. It is not applied to a file when any of the following are present and usable: a GPS timestamp in the reference media (`GPSDateStamp` + `GPSTimeStamp`, already UTC), an `OffsetTimeOriginal` field in the media EXIF, or a timezone-aware timestamp in a GPX file. It is only applied when none of those sources provide a timezone.

### Same-folder Behaviour

When `--reference` and `--media` resolve to the same path, the application scans the path once and automatically splits the files:

- Files that have GPS coordinates embedded → treated as reference track points; never written to.
- Files without GPS coordinates → treated as targets; processed and written to normally.

In this mode, `matching.on_existing_gps` does not apply to the reference files because they are excluded from the write queue entirely.

---

## Configuration File

### Format

JSONC — standard JSON extended with `//` line comments and `/* */` block comments. Run `init-config` to generate a fully annotated starting file. The parser strips comments before parsing, so the file is valid JSON once comments are removed.

### Naming Convention for Keys with Units

Any configuration key whose value is a quantity must include the unit name as a suffix. Examples: `offset_seconds`, `threshold_meters`, `threshold_seconds`. This applies to both config file keys and CLI parameter names.

### Auto-discovery Order (lowest to highest priority)

1. `~/.config/gps-updater/config.json` (user home)
2. `./gps-updater.json` (current working directory)
3. Path specified via `--config=PATH` (overrides all)

All discovered files are merged, with higher-priority values overriding lower ones. CLI flags override any config file value. Unknown keys in config files are warned and stripped before merging — they never appear in the resolved config.

### Schema

```jsonc
{
  "schema_version": 1,

  "time": {
    "timezone": null,          // IANA name, abbreviation, or offset. null = system timezone.
    "offset_seconds": 0        // Clock drift correction. Positive = camera was ahead.
  },

  "scan": {
    "recursive": true,         // Recurse into subfolders.
    "plugins_dir": null        // Extra camera profiles directory. null = built-ins only.
  },

  "matching": {
    "on_existing_gps": "warn",                      // "warn" | "skip" | "overwrite"
    "existing_gps_distance_threshold_meters": 50,
    "on_duplicate_trackpoint": "prefer_accuracy",   // "use_first" | "warn_skip" | "prefer_accuracy"
    "on_photo_before_track": "warn",                // "warn" | "skip" | "nearest"
    "on_photo_before_track_max_seconds": 60,        // Max seconds for "nearest" to apply
    "on_photo_after_track": "warn",                 // "warn" | "skip" | "nearest"
    "on_photo_after_track_max_seconds": 60,         // Max seconds for "nearest" to apply
    "track_gap_threshold_seconds": 300,
    "on_track_gap": "warn"                          // "interpolate" | "warn" | "skip"
  },

  "output": {
    "write_elevation": true,
    "write_gps_datetime": true,
    "create_backup": true,
    "backup_dir": null,        // null = next to originals
    "output_dir": null,        // null = modify originals in place
    "preserve_file_date": true,
    "units": "metric"          // "metric" | "imperial"
  },

  "logging": {
    "enabled": false,
    "log_append": false,       // false = overwrite log file on each run
    "file": "./gps-updater.log",
    "level_file": "DEBUG",     // "DEBUG" | "INFO" | "WARNING" | "ERROR"
    "level_console": "WARNING" // "DEBUG" | "INFO" | "WARNING" | "ERROR"
  }
}
```

### Config Key Reference

`**time.timezone**` — timezone of the camera clock. Accepts the same formats as `--timezone`. When null, the system local timezone is used.

`**time.offset_seconds**` — integer seconds added after timezone conversion to correct for camera clock drift. Positive = camera was ahead of real time.

`**scan.recursive**` — whether to scan subfolders when a folder path is given. Default is `true`.

`**scan.plugins_dir**` — additional directory to scan for camera profile plugins, in addition to the standard locations.

`**matching.on_existing_gps**` — behavior when a media file already has GPS coordinates.

- `warn` — show the file in the summary with a counter; keep existing GPS
- `skip` — silently keep existing GPS
- `overwrite` — replace the existing coordinates

`**matching.existing_gps_distance_threshold_meters**` — when `on_existing_gps` is `warn`, suppress the warning if the existing GPS is within this many meters of the interpolated track point.

`**matching.on_duplicate_trackpoint**` — behavior when two GPX trackpoints share the same timestamp.

- `warn_skip` — warn and skip both points for that timestamp
- `use_first` — use the point parsed first (file order)
- `prefer_accuracy` — use the point with the lower HDOP value (better accuracy); fall back to `use_first` if neither point has accuracy data

`**matching.on_photo_before_track**` / `**matching.on_photo_after_track**` — behavior when a media timestamp falls outside the GPX track's time range.

- `warn` — count in the summary; skip the file
- `skip` — silently skip
- `nearest` — assign coordinates of the nearest track endpoint, provided the photo is within `on_photo_before_track_max_seconds` / `on_photo_after_track_max_seconds` of the boundary; beyond that threshold, falls back to `warn`

`**matching.on_photo_before_track_max_seconds**` / `**matching.on_photo_after_track_max_seconds**` — when `on_photo_before/after_track` is `nearest`, only snap to the endpoint if the photo is within this many seconds of the track boundary. Photos further than this fall back to `warn`. Default is `60`.

`**matching.track_gap_threshold_seconds**` — consecutive trackpoint gap larger than this value is treated as a track discontinuity.

`**matching.on_track_gap**` — behavior when a media timestamp falls inside a track gap.

- `interpolate` — interpolate across the gap regardless of its size
- `warn` — count in the summary; skip the file
- `skip` — silently skip

`**output.write_elevation**` — write altitude from the GPS track if available.

`**output.write_gps_datetime**` — write the GPS timestamp EXIF field in addition to coordinates.

`**output.create_backup**` — create a backup copy of the original file before writing GPS. The backup is named `<stem>_original.<ext>` (e.g. `IMG_0001_original.jpg`). When `backup_dir` is set, backups are placed there mirroring the original subfolder structure; otherwise next to the originals.

`**output.backup_dir**` — directory where backup copies are written. `null` = place backups next to the originals. Subfolder structure is mirrored.

`**output.output_dir**` — directory where geotagged output files are written. `null` = modify the original files in place. Subfolder structure is mirrored.

`**output.preserve_file_date**` — when true, passes `-P` to ExifTool so the file modification date is unchanged after writing GPS metadata.

`**output.units**` — `metric` (meters, km) or `imperial` (feet, miles) for all user-facing distance output.

`**logging.enabled**` — when false, no log file is written. The `--log=PATH` CLI flag enables logging for a single run regardless of this setting.

`**logging.log_append**` — when false (default), the log file is overwritten at the start of each run. When true, new log entries are appended to the existing file.

`**logging.file**` — path of the log file when logging is enabled.

`**logging.level_file**` — log level written to the file. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`.

`**logging.level_console**` — log level shown in the console. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`.

---

## Camera Profile Plugin System

### Purpose

Camera profiles correct for known per-model quirks: which EXIF timestamp field is authoritative, whether the camera stores time in UTC or local time, whether the device has its own embedded GPS, and which metadata field is used for video creation time.

### Plugin File Format

Each plugin is a JSON file. File name is arbitrary; the `make` and `model` fields are used for matching.

```json
{
  "schema_version": 1,
  "make": "GoPro",
  "model": ["HERO9 Black", "HERO10 Black", "HERO11 Black"],
  "datetime_field_priority": ["DateTimeOriginal", "CreateDate"],
  "datetime_is_utc": true,
  "default_timezone_offset": null,
  "has_embedded_gps": true,
  "on_embedded_gps": "warn",
  "video_timestamp_source": "CreateDate",
  "reference_timestamp_source": "gps_timestamp",
  "notes": "GoPro stores DateTimeOriginal in UTC. Video files contain embedded GPS tracks."
}
```

### Plugin Fields


| Field                        | Type             | Description                                                                                                                                         |
| ---------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`             | integer          | Plugin format version                                                                                                                               |
| `make`                       | string           | Matches EXIF `Make` field (case-insensitive)                                                                                                        |
| `model`                      | string or array  | Matches EXIF `Model` field (case-insensitive, substring match)                                                                                      |
| `datetime_field_priority`    | array of strings | EXIF fields to try in order for the capture timestamp (used when this file is a target)                                                             |
| `datetime_is_utc`            | boolean          | True if the camera stores time in UTC rather than local time                                                                                        |
| `default_timezone_offset`    | string or null   | Hint for cameras that always ship with a fixed zone                                                                                                 |
| `has_embedded_gps`           | boolean          | Whether this device typically records its own GPS                                                                                                   |
| `on_embedded_gps`            | string or null   | Per-camera override for `matching.on_existing_gps`; null means use global config                                                                    |
| `video_timestamp_source`     | string or null   | ExifTool field name to use for video creation time                                                                                                  |
| `reference_timestamp_source` | string           | Which timestamp to use when this file acts as a GPS reference. `gps_timestamp` (default) uses `GPSDateStamp`+`GPSTimeStamp` (UTC). `datetime_original` uses `DateTimeOriginal` + timezone fallback. |
| `notes`                      | string           | Human-readable description of known quirks                                                                                                          |


### Plugin Discovery Order

1. Bundled plugins (shipped with the application, in `plugins/` inside the package) — lowest priority
2. `~/.config/gps-updater/plugins/` (user home plugins)
3. `./plugins/` relative to the current working directory
4. Path specified in `scan.plugins_dir` config key — highest user priority

User-supplied plugins always override bundled plugins for the same make/model match. No warning is emitted for bundled-vs-user conflicts; this override is expected and intentional.

If two user-supplied plugins (from any user plugin location, across all user directories) match the same make/model, a warning is printed and the first one encountered in discovery order is used. The warning identifies both conflicting files.

### Bundled Profiles (v1)


| Make     | Model(s)                  | Key Quirks                                                   |
| -------- | ------------------------- | ------------------------------------------------------------ |
| GoPro    | HERO9/10/11/12 Black      | UTC timestamp, embedded GPS in video                         |
| DJI      | Mavic 3, Mini 3, Air 2S   | UTC timestamp, embedded GPS in video                         |
| Apple    | iPhone (all)              | `OffsetTimeOriginal` present on iOS 14+; GPS always embedded |
| Sony     | a6000–a7 series           | No timezone in EXIF                                         |
| Canon    | EOS R, M, and DSLR series | No timezone in EXIF                                         |
| Nikon    | Z series, D series        | No timezone in EXIF                                         |
| Fujifilm | X series                  | No timezone; check `FujifilmMaker` date field               |
| Samsung  | Galaxy series             | Inconsistent timezone presence across models                 |
| Google   | Pixel series              | `OffsetTimeOriginal` generally present                       |


---

## Behavior Specification Summary

### Startup

1. Check ExifTool is available on PATH; exit with install instructions if not.
2. Discover and merge config files.
3. Validate all required parameters (input paths for `run`).
4. Resolve and log the timezone being used (system default or explicit).
5. Load and index camera plugins.
6. Report configuration summary unless `--quiet`.

### Processing Order

1. Scan the reference source (`--reference`): parse GPX files and extract track points from GPS-tagged media files. Merge into a unified, sorted, deduplicated trackpoint database.
2. Scan the media source (`--media`): build the list of target files to geotag. In same-folder mode, files that contributed reference track points in step 1 are excluded from the target list.
3. For each target media file, find or interpolate the GPS position and apply it.
4. Print summary.

### Output and Backup

When `output_dir` is set, geotagged files are written there and originals are not modified. Subfolder structure relative to the `--media` path is preserved.

When `backup_dir` is set, originals are copied there as `<stem>_original.<ext>` before writing. Subfolder structure is preserved. When neither `output_dir` nor `backup_dir` is set and `create_backup` is true, the backup is placed next to the original.

Both `output_dir` and `backup_dir` are excluded from all scans even if they are nested inside the reference or media paths.

### Console Output

Unless `--quiet`, the console shows:

- Startup summary: ExifTool version, timezone in use, plugin count, config source
- Track summary after scanning the reference: point count, date/time range, duration
- Media summary after scanning media: file counts, timestamp range, files without timestamps, files with existing GPS
- Live two-line display during matching: running counters (matched, outside range, in gap, existing GPS, no timestamp, errors) on the first line and a progress bar on the second. In `--verbose` mode, per-file status lines are shown instead.
- Progress bar during writing
- Summary table at completion

Log file (when enabled) records everything at the configured level, including timestamps and full file paths. The log file is overwritten on each run unless `logging.log_append` is true.
