# Future Ideas and Roadmap

This file captures ideas that are out of scope for v1 but should not be forgotten.
v1 is a CLI-only utility. Everything below is post-v1.

---

## GUI / TUI

A graphical or terminal UI that lets the user:
- Select multiple input folders individually
- Assign a timezone to each folder independently (solving the multi-timezone batch problem without manual re-runs)
- Preview matched coordinates on a map before writing
- See unmatched photos and manually assign or skip them
- Drag-and-drop GPX files onto photo batches

This directly addresses the core usability pain point: currently, if photos span multiple timezones, the user must split them into batches and run the tool separately for each. A GUI could make that a first-class workflow.

Candidate frameworks: Textual (TUI, Python), Tauri (cross-platform GUI with a thin Rust shell), or a simple web UI served locally.

---

## Per-folder / Per-batch Configuration in GUI

Related to the GUI idea: the ability to set a per-folder config override — timezone, time offset, camera profile, GPS gap tolerance — without editing a global config file. The CLI equivalent would be a `--batch-config` flag pointing to a lightweight per-run override file.

---

## Camera Plugin System Evolution

v1 ships with a static set of bundled JSON camera profiles and supports user-supplied plugins in a well-known directory. Future improvements:

- Online plugin registry: a community-maintained repository of camera profiles that users can pull from
- Auto-detection of new camera models from EXIF and auto-suggestion to contribute a profile
- Plugin versioning: profiles may need updating when manufacturers change firmware behavior
- Plugins for specific camera lines that already embed GPS (GoPro, DJI, newer iPhones, Garmin) to define how their existing GPS data should be handled (skip, merge, prefer-camera, prefer-track)

Once the camera profile JSON schema has stabilized through real-world testing, create a dedicated `CAMERA_RESEARCH.md` file documenting the per-model investigation: known EXIF quirks, timestamp field behavior, embedded GPS characteristics, and firmware version differences for each supported make/model. This is intentionally deferred until the schema stops changing.

---

## DJI and GoPro Special Handling

These devices record their own GPS tracks embedded in video files. Future versions could:
- Detect the embedded GPS and optionally extract it as a GPX file
- Cross-validate embedded GPS against an external GPX track
- Merge or prefer one source over the other based on quality metrics (point density, accuracy fields)

---

## XMP Sidecar Support

RAW workflows (Lightroom, Capture One, Darktable) use `.xmp` sidecar files alongside `.cr2`, `.arw`, `.nef` etc. Writing GPS to the sidecar instead of the raw file is the non-destructive option many photographers prefer. Future versions should detect sidecar files and offer a `--write-xmp-sidecar` mode.

---

## Accuracy and Quality Metrics

GPX tracks vary in quality. Future improvements:
- Parse and expose HDOP/PDOP/satellite count from GPX where available
- Warn when interpolating over a gap that exceeds a threshold
- Annotate output with a confidence score (e.g., interpolated vs. exact match vs. nearest-endpoint fallback)
- Let the user filter out writes below a confidence threshold

---

## Reverse Geocoding

After assigning coordinates, optionally resolve them to a human-readable location (city, country) and write to IPTC or XMP location fields. Useful for photo library organization. Would require either a local geocoding database (e.g., `reverse_geocoder` Python package) or an optional external API call.

---

## Output Modes

- Write a CSV/JSON report of all matches, skips, and warnings without modifying any files (extends dry-run)
- Export a new GPX file from matched photo timestamps (useful for sharing a "photo track")
- Bulk rename files by GPS-derived location or date

---

## Units of Measurement

v1 supports metric and imperial via a config key and CLI flag. Future improvement: auto-detect the user's locale and default accordingly rather than always defaulting to metric.

---

## Config Schema Versioning

As the config format evolves, the app should detect old config versions and either migrate automatically or warn the user. Add a `"schema_version"` field to the config from day one to enable this.

---

## Output Control Flags in GUI/TUI Context

v1 exposes `--quiet`, `--verbose`, and `--no-progress`. When a GUI/TUI wrapper is built, it should suppress all three and instead consume structured output (JSON event stream or similar) rather than trying to parse rich terminal output. Designing the display layer as a separate concern from the event emitter from the start will make this transition straightforward.

---

## Packaging

- Publish to PyPI so `uv tool install gps-updater` works
- Build standalone binaries via PyInstaller or Nuitka for users who do not want Python
- Homebrew formula and Scoop manifest for easy installation of both the tool and its ExifTool dependency
