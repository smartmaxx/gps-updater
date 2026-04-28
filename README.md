# gps-updater

Match GPX tracks to photos and videos and write GPS coordinates into media metadata.

## Requirements

- Python 3.10+
- [ExifTool](https://exiftool.org) — must be on your PATH

Install ExifTool:

- macOS: `brew install exiftool`
- Linux: `sudo apt install libimage-exiftool-perl`
- Windows: `winget install OliverBetz.ExifTool`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

## Quick start

```bash
gps-updater run --reference=./tracks --media=./photos --timezone=Europe/Warsaw
```

The `--timezone` parameter accepts:

- IANA names: `Europe/Warsaw`, `America/New_York`, `UTC`
- Abbreviations: `CET`, `EST`, `PST`
- Offsets: `+2`, `+02:00`, `-05:30`

If omitted, the system local timezone is used and a notice is printed.

## Commands

All commands accept the full set of options. Passing options to `show-config` or `init-config` resolves and shows or writes the configuration with those overrides applied.

### `run`

```
gps-updater run [OPTIONS]

Options:
  --reference=PATH[,PATH...]    GPS reference: one or more comma-separated paths —
                                GPX files, GPS-tagged media files, or folders (required)
  --media=PATH                  Media file or folder (required)
  --timezone=TZ                 Camera timezone (default: system)
  --time-offset-seconds=N       Clock drift correction in seconds
  --config=PATH                 Config file path
  --recursive=BOOL              Recurse into subfolders (true/false, default: true)
  --dry-run                     Parse and match without writing
  --force                       Overwrite existing GPS coordinates
  --create-backup=BOOL          Create backup files before writing (true/false)
  --preserve-file-date=BOOL     Keep file modification date unchanged (true/false)
  --output-dir=PATH             Write geotagged files here instead of modifying originals
  --backup-dir=PATH             Copy originals here as <name>_original.<ext> before writing
  --units=metric|imperial       Distance unit for output
  --verbose                     Per-file output in console (replaces live progress display)
  --quiet                       Suppress all output except errors
  --disable-rich-ui             Plain line-by-line output (no progress bars)
  --plain-output                Alias for --disable-rich-ui
  --log=PATH                    Write log to file
```

In normal mode the console shows a two-line live display during matching: running counters on the first line and a progress bar on the second. `--verbose` switches to per-file status lines instead. `--quiet` suppresses everything except errors.

Backup files are named `<stem>_original.<ext>` (e.g. `IMG_0001_original.jpg`). When `--output-dir` is set, geotagged copies are written there and originals are not modified.

### `init-config`

Generate a configuration file with comments explaining every parameter:

```bash
gps-updater init-config --output=gps-updater.json
```

Pass any `run` options to have the generated file reflect those values:

```bash
gps-updater init-config --output=gps-updater.json \
  --timezone=Europe/Warsaw --create-backup=false --output-dir=./geotagged
```

The generated file uses JSONC format (`//` line comments). Edit it and place it in
`./gps-updater.json` or `~/.config/gps-updater/config.json` for automatic discovery.

### `show-config`

Display the fully resolved configuration (all sources merged, CLI overrides applied):

```bash
gps-updater show-config --reference=./tracks --media=./photos --create-backup=false
```

### `list-plugins`

List all loaded camera profiles:

```bash
gps-updater list-plugins
```

## Configuration

Configuration is read from (lowest to highest priority):

1. `~/.config/gps-updater/config.json`
2. `./gps-updater.json`
3. Path given via `--config=PATH`
4. CLI flags

All keys have sensible defaults — the config file is optional. The format is JSONC: standard JSON plus `//` line comments. Run `init-config` to generate a fully annotated starting file.

See `SPEC.md` for the full configuration schema and all available keys.

## Visual verification

Before committing to a final run — especially for large batches — it is worth checking that
coordinates were assigned correctly. See [VISUAL_VERIFICATION.md](VISUAL_VERIFICATION.md)
for a step-by-step guide covering:

- **gpx.studio** — browser-based, no install, overlay the export GPX on your original track.
- **digiKam** — open-source desktop app, shows tagged photos as pins on a live map.
- **GPXSee** — lightweight desktop GPX viewer for quick route and waypoint inspection.

The recommended workflow is to run with `--dry-run` first, inspect the export GPX, then
re-run without `--dry-run` once the positions look correct.

## Status file

After a run the tool can write a human-readable status report listing every unmatched file
grouped by reason, with concrete configuration suggestions for the next run. Enable it:

```jsonc
{
  "logging": {
    "status_file": "./gps-updater-status.txt"
  }
}
```

See [STATUS_FILE.md](STATUS_FILE.md) for a full explanation of each section and common
remediation workflows.

## Camera profiles

Camera-specific settings (timestamp field priority, UTC storage, embedded GPS) are
stored as JSON files in the `plugins/` directory. Nine profiles are bundled:
GoPro, DJI, Apple iPhone, Sony Alpha, Canon EOS, Nikon, Fujifilm X, Samsung Galaxy,
Google Pixel.

To add a custom profile, create a JSON file following the schema in `SPEC.md` and
place it in `~/.config/gps-updater/plugins/` or `./plugins/`.

## Multiple timezones

If your photos were taken across multiple timezones, run the tool once per group:

```bash
gps-updater run --reference=./tracks --media=./paris  --timezone=Europe/Paris
gps-updater run --reference=./tracks --media=./nyc    --timezone=America/New_York
```

## Supported formats

Images: JPEG, HEIC, CR2, CR3, ARW, NEF, NRW, DNG, RAF, ORF, RW2, PEF, SRW, X3F

Videos: MP4, MOV, AVI, MKV, MTS, M2TS, 3GP

## Running tests

```bash
pip install pytest
pytest
```
