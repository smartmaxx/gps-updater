# Design Document — gps-updater v1

## Overview

`gps-updater` is structured as a pipeline with two independent parsing phases feeding into a single matching and write phase. The separation allows each phase to fail, warn, or complete independently, and makes future extension (e.g., GUI integration, parallel processing) straightforward.

```
[--reference path]
    GPX files   --> [GPX Parser]        \
    GPS media   --> [Ref Media Scanner] --> [Trackpoint DB] \
                                                             --> [Matcher] --> [Writer] --> [target files]
[--media path]                                              /
    All media   --> [Media Scanner] --> [Media DB] ---------
    (same-folder: GPS files excluded from Media DB)
```

---

## Project Structure

```
gps_updater/
    __init__.py
    __main__.py             -- entry point: python -m gps_updater
    cli.py                  -- click command definitions and pipeline assembly
    config.py               -- config file discovery, loading, merging, validation, JSONC rendering
    models.py               -- dataclasses: TrackPoint, MediaRecord, MatchResult, CameraProfile
    gpx_parser.py           -- GPX file parsing into TrackPoints
    reference_scanner.py    -- reference source dispatcher: routes GPX files and GPS media
    media_scanner.py        -- media file discovery, EXIF reading via ExifTool
    matcher.py              -- core matching algorithm, interpolation
    writer.py               -- GPS coordinate writing via ExifTool
    plugins.py              -- plugin discovery, loading, camera profile matching
    exiftool.py             -- ExifTool subprocess wrapper (batch read, per-file write)
    display.py              -- rich-based live progress display and summary output
    logger.py               -- logging setup and configuration
    deps.py                 -- external dependency detection

plugins/                  -- bundled camera profiles (JSON files)
    gopro_hero.json
    dji_mavic.json
    apple_iphone.json
    sony_alpha.json
    canon_eos.json
    nikon_z.json
    fujifilm_x.json
    samsung_galaxy.json
    google_pixel.json
```

---

## Data Models (`models.py`)

```python
@dataclass
class TrackPoint:
    timestamp: datetime          # always UTC after normalization
    latitude: float
    longitude: float
    elevation: float | None
    hdop: float | None           # horizontal dilution of precision, if present
    pdop: float | None           # position dilution of precision, if present
    source_file: Path            # which file this came from

@dataclass
class MediaRecord:
    path: Path
    capture_time: datetime | None    # UTC after timezone correction
    capture_time_raw: str | None     # original string from EXIF, for logging
    timezone_applied: str | None     # which offset was used
    has_existing_gps: bool
    existing_lat: float | None
    existing_lon: float | None
    camera_make: str | None
    camera_model: str | None
    camera_profile: CameraProfile | None
    is_video: bool

@dataclass
class MatchResult:
    media: MediaRecord
    status: MatchStatus              # enum: MATCHED, SKIPPED, WARNED, FAILED
    matched_lat: float | None
    matched_lon: float | None
    matched_elevation: float | None
    interpolation_ratio: float | None   # 0.0–1.0, how far between two trackpoints
    distance_to_existing_meters: float | None
    reason: str | None               # human-readable explanation for non-MATCHED status

class MatchStatus(Enum):
    MATCHED = "matched"
    SKIPPED = "skipped"
    WARNED = "warned"
    FAILED = "failed"
```

---

## Dependency Detection (`deps.py`)

Runs at application startup before any other work. Checks:

- ExifTool: `exiftool -ver` subprocess call; capture version string for display

On failure, prints a formatted message with the install command for the missing tool and exits with code 1. Does not raise an exception — this must be human-readable output.

---

## Configuration (`config.py`)

### Loading sequence

```
1. Load ~/.config/gps-updater/config.json  (if exists)
2. Load ./gps-updater.json                 (if exists, merge over step 1)
3. Load --config=PATH file                 (if provided, merge over step 2)
4. Apply CLI flag overrides                (highest priority)
```

Merging is deep for nested objects. Unknown keys in config files are warned and ignored, not rejected — this maintains forward compatibility when reading a config written by a newer version.

### JSONC support

Config files may contain `//` line comments and `/* */` block comments. The loader strips comments before calling `json.loads`. Comments inside string values are not stripped.

### Validation

After merging, validate:

- `matching.on_existing_gps` is one of the allowed enum values
- `matching.on_duplicate_trackpoint` is one of the allowed enum values
- `matching.on_photo_before_track`, `matching.on_photo_after_track`, `matching.on_track_gap` are valid enum values
- `output.units` is one of `metric`, `imperial`

`time.timezone` is not required. If absent, the system local timezone is used and a startup notice is printed.

### `show-config` command

Prints the fully resolved config (after all merges and CLI overrides) as formatted JSON. Accepts the full option set of `run`; config-affecting options are applied before printing.

### `init-config` command

Generates an annotated JSONC file via `_render_annotated_config(config)`, which produces the full schema with `//` comments explaining every key and listing all valid values. CLI overrides are applied to the config dict before rendering, so the generated file reflects any options passed on the command line. Aborts if the output file already exists unless `--force` is passed.

### Shared CLI options

All commands except `list-plugins` share a common `_common_options` decorator that registers the full option set. This means any option accepted by `run` is also accepted by `show-config` and `init-config`. The `run`-specific `--force` flag (overwrite GPS) is defined separately on `run` only; `init-config` has its own `--force` (overwrite output file).

---

## Plugin System (`plugins.py`)

### Discovery

Plugins are discovered from four locations in order. Each location's plugins are loaded into a registry keyed by `(make.lower(), model_pattern.lower())`.

```
1. gps_updater/plugins/         -- bundled, lowest priority
2. ~/.config/gps-updater/plugins/
3. ./plugins/
4. config["scan"]["plugins_dir"]  -- if set, highest user priority
```

User-supplied plugins always override bundled plugins for the same make/model. No warning is emitted for this case.

If two user-supplied plugins from any combination of user plugin directories match the same make/model, a warning is emitted identifying both files, and the first one encountered in discovery order is used.

### Matching

When a `MediaRecord` is created, the scanner calls `plugins.match(make, model)`. Matching is case-insensitive. The `model` field in a plugin can be a string or an array; substring match is used.

### CameraProfile dataclass

```python
@dataclass
class CameraProfile:
    make: str
    model_patterns: list[str]
    datetime_field_priority: list[str]
    datetime_is_utc: bool
    default_timezone_offset: str | None
    has_embedded_gps: bool
    on_embedded_gps: str | None          # None means use global config
    video_timestamp_source: str | None
    reference_timestamp_source: str      # "gps_timestamp" | "datetime_original"
    notes: str
    source_file: Path
```

---

## Reference Scanner (`reference_scanner.py`)

### Purpose

The reference scanner is the entry point for all `--reference` input. It accepts a single path (file or folder) and produces a unified, sorted, deduplicated `list[TrackPoint]` by routing each source to the appropriate parser.

### Routing Logic

For each input item (a single file, or all files found when the input is a folder):

- Extension `.gpx` → pass to `gpx_parser._parse_file`
- Known media extension with existing GPS → extract a single `TrackPoint` from the GPS metadata
- Known media extension without GPS → log at debug level and skip
- Unknown extension → log at debug level and skip

### GPS Media Extraction

For a GPS-tagged media file used as a reference source, the `reference_timestamp_source` field of the camera profile (or the default `"gps_timestamp"`) determines which timestamp is used:

- `"gps_timestamp"`: use `GPSDateStamp` + `GPSTimeStamp` from EXIF (already UTC). If either field is absent, fall back to `"datetime_original"`.
- `"datetime_original"`: use `DateTimeOriginal` with the user-supplied timezone fallback. If absent, the file is skipped.

Each GPS-tagged media file produces exactly one `TrackPoint`.

### Same-Folder Detection

When `--reference` and `--media` resolve to the same absolute path:

- Files that have GPS coordinates embedded → treated as reference track contributors; excluded from the write queue.
- Files without GPS coordinates → treated as targets.

The reference scanner returns the set of file paths consumed as reference sources so the media scanner can exclude them.

### Result

A unified, sorted, deduplicated `list[TrackPoint]` from all reference inputs combined. The deduplication policy (`on_duplicate_trackpoint`) is applied after merging all sources. If the resulting list is empty, the run aborts before the media scan phase begins.

---

## GPX Parsing (`gpx_parser.py`)

### Input

One or more GPX files. If a folder is given, scan for `*.gpx` files (recursively if configured).

### Parsing

Uses `gpxpy`. For each file, extract all tracks, all segments, all points. Each point becomes a `TrackPoint`. Timestamp is normalized to UTC using `gpxpy`'s built-in timezone handling.

### Deduplication

After parsing all files, sort all `TrackPoint` objects by `timestamp`. Then scan for duplicate timestamps:

- Build groups of points sharing the same timestamp.
- For groups of size > 1, apply `config["matching"]["on_duplicate_trackpoint"]`:
  - `warn_skip`: emit a warning, discard all points for that timestamp.
  - `use_first`: keep the first point encountered (file parse order).
  - `prefer_accuracy`: compare `hdop` values; keep the point with the lower (better) HDOP. If both are None or equal, fall back to `use_first`.

### Result

A sorted `list[TrackPoint]` covering the full time range of all input GPX files.

### Timestamp validation

After extracting all points from a file, the parser checks whether any points carry timestamps. If none do, the file is rejected with an error-level message and excluded from the trackpoint database entirely. The run continues with remaining files.

---

## Media Scanning (`media_scanner.py`)

### Input

One or more files or folders. Scanning is recursive if configured.

### File type detection

By file extension. Known image extensions: `jpg`, `jpeg`, `heic`, `heif`, `cr2`, `cr3`, `arw`, `nef`, `nrw`, `dng`, `raf`, `orf`, `rw2`, `pef`, `srw`, `x3f`. Known video extensions: `mp4`, `mov`, `avi`, `mkv`, `mts`, `m2ts`, `3gp`.

### EXIF reading

All EXIF reading is done through the `exiftool.py` wrapper in batch mode: ExifTool is invoked in configurable batch sizes with `-json` output, rather than once per file.

### Exclusions

The scanner accepts two exclusion sets:

- `exclude_paths`: individual file paths to skip (used in same-folder mode to exclude reference files)
- `exclude_dirs`: resolved directory paths whose entire contents are excluded (used to prevent scanning `output_dir` or `backup_dir` if they are nested inside the media path)

### Timestamp extraction

For each file, apply the camera profile's `datetime_field_priority` if a profile matched, otherwise use the default priority: `["DateTimeOriginal", "DateTimeDigitized", "CreateDate", "DateTime"]`.

If the EXIF field `OffsetTimeOriginal` is present, it is used instead of the user-supplied timezone.

---

## Matching Algorithm (`matcher.py`)

### Input

- Sorted `list[TrackPoint]` (trackpoint database)
- `list[MediaRecord]` (media database)
- Config values

### Public API

- `match_all(records, track_points, config)` — batch; returns `list[MatchResult]`
- `match_one(record, track_points, config)` — single record; used by the pipeline for live progress updates

### Per-file matching

For each `MediaRecord` with a valid `capture_time`:

1. **Boundary check**: Is `capture_time` before the first trackpoint or after the last? Apply `on_photo_before_track` or `on_photo_after_track`. When behavior is `nearest`, only snap to the endpoint if the photo is within `on_photo_before/after_track_max_seconds` of the boundary; otherwise fall back to `warn`.
2. **Gap check**: Binary search for the two surrounding trackpoints. If the gap between them exceeds `track_gap_threshold_seconds`, apply `on_track_gap`.
3. **Interpolation**: Linear interpolation of lat, lon, elevation between surrounding points.
4. **Existing GPS handling**: If `has_existing_gps` is True, compute Haversine distance and apply `on_existing_gps`.
5. Return a `MatchResult`.

Per-file logging inside the matcher uses `logger.debug` so it does not appear on the console in normal mode. The summary counters in the display layer capture all the information users need.

### Haversine distance

Pure Python implementation, no external dependency. Returns meters.

---

## Writing (`writer.py`)

### Input

`list[MatchResult]` — processes only entries where `status == MATCHED`.

### Output path resolution

For each matched file, the writer resolves:

- `output_path`: `output_dir / rel` when `output_dir` is set; `None` otherwise (modify in place)
- `backup_path`: `backup_dir / rel.parent / stem_original.ext` when `backup_dir` is set; `src.parent / stem_original.ext` when `create_backup` is true and no `output_dir`; `None` otherwise

`rel` is the file's path relative to the scan root, preserving subfolder structure.

### Backup creation

Backups are created via `shutil.copy2` before the ExifTool write call, named `<stem>_original.<ext>`. ExifTool's own `_original` backup mechanism is never used.

### ExifTool invocation

One subprocess call per file:

```
exiftool -GPSLatitude=<lat> -GPSLatitudeRef=<N|S>
         -GPSLongitude=<lon> -GPSLongitudeRef=<E|W>
         [-GPSAltitude=<ele> -GPSAltitudeRef=<0|1>]  (if write_elevation)
         [-GPSDateStamp=... -GPSTimeStamp=...]         (if write_gps_datetime)
         [-P]                                          (if preserve_file_date)
         [-o output_path | -overwrite_original]
         <source_file>
```

### Progress callback

`write_all` accepts an optional `on_progress` callable that is invoked after each file is processed (written or dry-run skipped). The CLI passes `display.advance_progress` to drive the write progress bar.

---

## ExifTool Wrapper (`exiftool.py`)

A thin subprocess wrapper that:

- Provides `read_metadata(paths)` — batch mode with `-json -charset utf8 -n`, returns list of dicts in input order
- Provides `write_gps(path, lat, lon, elevation, gps_datetime, preserve_file_date, output_path, backup_path)` — one subprocess call per file
- Handles subprocess errors and translates them to `ExifToolError`

Reading is batched in groups of 200 files per ExifTool invocation. Writing is one call per file because each file may have a unique output path.

---

## Display Layer (`display.py`)

Built on `rich`. Completely isolated from business logic — it consumes `MatchResult` objects and scalar events.

### Normal mode (non-verbose, non-quiet)

During matching, a live two-line display is rendered using `rich.live.Live`:

```
  matched: N  |  outside range: N  |  in gap: N  |  existing GPS: N  |  no timestamp: N
  [████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] N/N  0:00:05
```

The counters update in real time as each file is matched. After matching, a separate progress bar is shown during writing.

### Verbose mode

Per-file status lines are printed instead of the live display. Each line shows a status tag (`OK`, `--`, `WARN`, `FAIL`) and the file name.

### Quiet mode

All console output is suppressed except error messages.

### Plain mode (`--disable-rich-ui`)

Rich is not used. Simple text output only.

### Summary table

After writing, a summary table is printed with counts for: GPS written, outside track range (split into before/after), in track gap, already have GPS, no timestamp, other warnings, skipped, failed, total.

---

## Logging (`logger.py`)

Uses Python's standard `logging` module.

Two handlers are configured:

- `RichHandler` (from `rich.logging`) for console output, at the console log level
- `FileHandler` for the log file, at the file log level — only added when logging is enabled or `--log` is passed

The file handler opens the log file in write mode (`"w"`) by default, overwriting any previous contents. When `logging.log_append` is `true`, it opens in append mode (`"a"`).

All module-level loggers use `logging.getLogger(__name__)`. The root application logger is `gps_updater`.

---

## Error Handling Strategy

- Dependency check failures: exit code 1, human-readable message
- Config validation failures: exit code 2, list all errors before exiting
- Missing required options (`--reference`, `--media` for `run`): exit code 2, error message
- GPX parse error on a single file: warn and continue with remaining files
- Media EXIF read failure on a single file: record as `FAILED` in `MatchResult`, continue
- ExifTool write failure on a single file: record as `FAILED`, continue
- Unexpected exceptions: caught at the top level in `cli.py`, logged at ERROR, exit code 3

The application never silently swallows errors. Every failure is either shown to the user or written to the log.

---

## Performance Considerations

- ExifTool batch mode: reading metadata for hundreds or thousands of files in configurable batch sizes (default 200) per subprocess call is orders of magnitude faster than one call per file.
- GPX binary search: trackpoint lookup is O(log n) using `bisect` from the standard library.
- No parallelism in v1. File I/O is the bottleneck; single-threaded with a live progress display is sufficient for the expected scale (thousands of files, not millions).
