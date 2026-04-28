# Implementation Tasks — gps-updater v1

Tasks are ordered by dependency. Each group can begin only after the previous group is complete unless noted otherwise.

---

## Group 1 — Project Scaffold

- Initialize `pyproject.toml` with project metadata, Python version constraint (`>=3.11`), and dependencies: `click`, `rich`, `gpxpy`, `pyexiftool`, `tzdata`
- Create package structure: `gps_updater/` with empty `__init__.py` and `__main__.py`
- Add `.gitignore` entries for `__pycache__`, `.venv`, `*.egg-info`, `dist/`, `*.log`, `*_original`
- Verify `uv run -m gps_updater` launches without error (empty main is fine)

---

## Group 2 — Data Models

- Implement `models.py`: `TrackPoint`, `MediaRecord`, `MatchResult`, `MatchStatus`, `CameraProfile` dataclasses as specified in DESIGN.md
- Add `reference_timestamp_source: str` field to `CameraProfile` (default `"gps_timestamp"`)
- Write unit tests for model construction and equality

---

## Group 3 — Dependency Detection

- Implement `deps.py`: check ExifTool availability via subprocess, capture version string
- Check required Python packages are importable
- Print formatted, actionable error messages on failure
- Write tests: mock subprocess to simulate ExifTool present/absent

---

## Group 4 — Configuration

- Implement `config.py`: define the full default config dict using the grouped JSON schema from SPEC.md
- Implement config file discovery: `~/.config/gps-updater/config.json` and `./gps-updater.json`
- Implement config merging (lower-to-higher priority, CLI overrides last); merging must handle nested objects, not just flat keys
- Implement validation: enum value checks for all `on_*` keys, `output.units`, path existence for path values; warn and ignore unknown keys
- Implement timezone resolution: accept named zones (via `zoneinfo`), abbreviations (built-in table), and offset strings (`+2`, `+2:00`, `+02:00`); fall back to system timezone if absent
- Implement `init-config` command: write default grouped config JSON to `--output=PATH`; abort if file exists unless `--force` passed
- Implement `show-config` command: print resolved config as annotated JSON with source of each value
- Write tests: merge logic for nested objects, validation error cases, timezone resolution for all input formats, system timezone fallback

---

## Group 5 — Plugin System

- Create `plugins/` directory with the 9 bundled camera profile JSON files (see SPEC.md bundled profiles table)
- Add `"reference_timestamp_source": "gps_timestamp"` to all 9 bundled plugin JSON files
- Implement `plugins.py`: discover plugins from all four locations
- Implement plugin loading: parse JSON, construct `CameraProfile` objects; load `reference_timestamp_source` with default `"gps_timestamp"` if absent
- Implement `match(make, model)`: case-insensitive, substring model matching, specificity tiebreak
- Handle plugin conflicts: two user-supplied plugins matching the same camera (across any user plugin directories) — warn with both file paths, use the first found; no warning for bundled-vs-user conflicts
- Implement `list-plugins` command: print a table of all loaded profiles with source path
- Write tests: match precedence, case-insensitive match, bundled vs user override

---

## Group 6 — ExifTool Wrapper

- Implement `exiftool.py` wrapping `pyexiftool`: start persistent process, `read_metadata(paths)`, `write_gps(...)`, clean shutdown
- Handle ExifTool subprocess errors: capture stderr, raise typed exception
- Write tests: mock ExifTool process, verify JSON parsing, verify write argument construction

---

## Group 7 — GPX Parser

- Implement `gpx_parser.py`: accept file or folder path, glob `*.gpx` recursively or not
- Parse each GPX file with `gpxpy`, extract all track segments and points
- Normalize timestamps to UTC
- Extract `hdop`, `pdop`, `elevation` where present
- Implement duplicate timestamp handling: `warn_skip`, `use_first`, `prefer_accuracy`
- Sort and return final `list[TrackPoint]`
- Reject files where no points have timestamps: emit error-level message, exclude from trackpoint database, continue with remaining files
- After all GPX files are processed, abort the run if the trackpoint database is empty
- Write tests: single file, multi-file merge, duplicate timestamp all three modes, all-timestamps-missing rejected, partial-timestamps-missing (points without time are skipped, file is not rejected if at least one point has a timestamp)

---

## Group 7b — Reference Scanner

- Implement `reference_scanner.py`: accept a single file or folder path
- Route `.gpx` files to `gpx_parser`
- Route GPS-tagged media files to GPS extraction: read `GPSLatitude`, `GPSLongitude`, `GPSAltitude`; extract timestamp using `reference_timestamp_source` from camera profile (default `"gps_timestamp"`); produce one `TrackPoint` per file
- For `"gps_timestamp"` source: use `GPSDateStamp` + `GPSTimeStamp` (already UTC); fall back to `"datetime_original"` if absent
- For `"datetime_original"` source: use `DateTimeOriginal` with timezone fallback; skip file if absent
- Skip media files with no GPS coordinates (debug-level log)
- Handle same-folder detection: compare resolved absolute paths of `--reference` and `--media`; return the set of file paths consumed as reference sources so the media scanner can exclude them
- After merging all GPX and media track points, apply deduplication and return sorted `list[TrackPoint]`; abort if result is empty
- Write tests: GPX-only input, GPS-media-only input, mixed folder, same-folder split, `reference_timestamp_source` routing, file with GPS skipped if no timestamp available

---

## Group 8 — Media Scanner

- Implement `media_scanner.py`: accept file or folder path, filter by known extensions
- Call ExifTool in batch mode for metadata extraction
- Implement timestamp field priority (camera profile or default)
- Apply timezone offset to produce UTC `capture_time`
- Detect existing GPS coordinates
- Apply camera profile matching via `plugins.py`
- Handle `OffsetTimeOriginal` override when present
- Write tests: timezone offset math, field priority order, existing GPS detection, `OffsetTimeOriginal` override

---

## Group 9 — Matching Algorithm

- Implement `matcher.py`: binary search using `bisect` for surrounding trackpoints
- Implement boundary handling: before-track and after-track config behaviors
- Implement gap detection: compare gap to `track_gap_threshold_seconds`
- Implement linear interpolation: lat, lon, elevation
- Implement Haversine distance calculation (pure Python)
- Implement existing GPS distance check and threshold suppression
- Produce `MatchResult` for every input `MediaRecord`
- Write tests: interpolation math, boundary cases, gap detection, haversine correctness, existing GPS threshold

---

## Group 10 — Writer

- Implement `writer.py`: filter `MatchResult` list to `MATCHED` status
- Implement dry-run mode: log what would be written, skip ExifTool calls
- Construct ExifTool write arguments: lat/lon/ref, elevation, GPS datetime (all conditional on config)
- Pass `-overwrite_original` to ExifTool when `output.create_backup` is false
- Handle ExifTool write failures: update `MatchResult.status` to `FAILED`
- Write tests: dry-run produces no writes, argument construction for all combinations

---

## Group 11 — Logging

- Implement `logger.py`: configure `RichHandler` for console, `FileHandler` for file
- Wire log levels from config
- Ensure `FileHandler` is only added when `logging.enabled` is true or `--log=` flag is passed
- Write tests: verify handlers are present/absent based on config

---

## Group 12 — Display Layer

- Implement `display.py`: define event dataclasses (`ScanStarted`, `ScanProgress`, `ScanComplete`, `MatchWarning`, `RunComplete`)
- Implement `rich`-based progress bar for GPX scan phase
- Implement `rich`-based progress bar for media scan phase
- Implement per-file status output during matching
- Implement summary table at completion
- Implement `--quiet` mode: suppress all output except errors
- Implement `--disable-rich-ui` / `--plain-output` mode: replace progress bars with plain log-style lines
- Implement `--verbose` mode: include debug events in console output

---

## Group 13 — CLI Assembly

- Implement `cli.py`: wire all `click` commands and options using `=` style
- Replace `--gpx=PATH` with `--reference=PATH`; wire to `reference_scanner` instead of `gpx_parser` directly
- Connect `run` command to deps check, config load, plugin load, reference scan, media scan, match, write pipeline
- Implement top-level exception handler: catch unexpected exceptions, log at ERROR, exit code 3
- Validate mutually exclusive flags (`--quiet` and `--verbose`)
- Wire `--recursive=BOOL` as a boolean click option (accepts `true`/`false`/`yes`/`no`/`1`/`0`), not a flag pair
- Wire `--create-backup=BOOL` as a boolean click option
- Print startup notice when timezone defaults to system local (i.e., no `--timezone=` and no `time.timezone` in config)

---

## Group 14 — Integration Testing

- Create `tests/fixtures/` with sample GPX files and sample images with known EXIF timestamps
- Write end-to-end test: run full pipeline on fixtures, verify GPS written correctly
- Write end-to-end test: dry-run produces no file modifications
- Write end-to-end test: existing GPS warning with distance calculation
- Write end-to-end test: photo outside track range, all three `on_photo_before_track` modes
- Write end-to-end test: multi-file GPX merge with overlapping timestamps

---

## Group 15 — Documentation and Polish

- Update `README.md` with install instructions (ExifTool, `uv`), quickstart example, CLI reference
- Document config file format and all keys in `README.md` or link to `SPEC.md`
- Document plugin format and how to write a custom camera profile
- Add `gps-updater --help` output verification to CI (ensures help text does not break)
- Add `CHANGELOG.md` with v1.0.0 entry