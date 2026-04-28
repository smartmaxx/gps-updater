from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from gps_updater import __version__


# ------------------------------------------------------------------ helpers


def _bool_param(value: bool | None, config_key: tuple[str, str], config: dict[str, Any]) -> bool:
    if value is not None:
        return value
    section, key = config_key
    return config.get(section, {}).get(key, True)


def _common_options(func):
    func = click.option(
        "--reference", "reference_str", default=None, type=str,
        help="GPS reference: one or more comma-separated paths (GPX files, GPS-tagged media files, or folders).",
    )(func)
    func = click.option(
        "--media", "media_path", default=None, type=click.Path(path_type=Path),
        help="Media file or folder.",
    )(func)
    func = click.option(
        "--config", "config_path", default=None, type=click.Path(path_type=Path),
        help="Path to a config file (overrides auto-discovery).",
    )(func)
    func = click.option(
        "--timezone", "timezone_str", default=None,
        help="Camera timezone: IANA name, abbreviation, or offset (+02:00). Defaults to system timezone.",
    )(func)
    func = click.option(
        "--time-offset-seconds", "time_offset_seconds", default=None, type=int,
        help="Camera clock drift correction in seconds (positive = camera was ahead).",
    )(func)
    func = click.option(
        "--recursive", default=None, type=bool,
        help="Recurse into subfolders. Accepts true/false.",
    )(func)
    func = click.option(
        "--dry-run", "dry_run", is_flag=True, default=False,
        help="Parse and match but do not write anything.",
    )(func)
    func = click.option(
        "--create-backup", "create_backup", default=None, type=bool,
        help="Create backup files before writing GPS. Accepts true/false.",
    )(func)
    func = click.option(
        "--preserve-file-date", "preserve_file_date", default=None, type=bool,
        help="Keep the file modification date unchanged after writing GPS. Accepts true/false.",
    )(func)
    func = click.option(
        "--output-dir", "output_dir", default=None, type=click.Path(path_type=Path),
        help="Write geotagged files here instead of modifying originals in place.",
    )(func)
    func = click.option(
        "--backup-dir", "backup_dir", default=None, type=click.Path(path_type=Path),
        help="Copy originals here as <name>_original.<ext> before writing.",
    )(func)
    func = click.option(
        "--units", default=None, type=click.Choice(["metric", "imperial"]),
        help="Distance unit for output (metric or imperial).",
    )(func)
    func = click.option(
        "--verbose", is_flag=True, default=False,
        help="Show debug-level output in console.",
    )(func)
    func = click.option(
        "--quiet", is_flag=True, default=False,
        help="Suppress all console output except errors.",
    )(func)
    func = click.option(
        "--disable-rich-ui", "--plain-output", "plain_output", is_flag=True, default=False,
        help="Disable rich progress display; use plain line-by-line output.",
    )(func)
    func = click.option(
        "--log", "log_path", default=None,
        help="Write log to this file (enables logging for this run).",
    )(func)
    return func


def _parse_reference_paths(reference_str: str) -> list[Path]:
    return [Path(p.strip()).expanduser().resolve() for p in reference_str.split(",") if p.strip()]


def _apply_cli_overrides(
    config: dict[str, Any],
    *,
    timezone_str: str | None,
    time_offset_seconds: int | None,
    recursive: bool | None,
    create_backup: bool | None,
    preserve_file_date: bool | None,
    output_dir: Path | None,
    backup_dir: Path | None,
    units: str | None,
) -> None:
    if timezone_str is not None:
        config["time"]["timezone"] = timezone_str
    if time_offset_seconds is not None:
        config["time"]["offset_seconds"] = time_offset_seconds
    if recursive is not None:
        config["scan"]["recursive"] = recursive
    if create_backup is not None:
        config["output"]["create_backup"] = create_backup
    if preserve_file_date is not None:
        config["output"]["preserve_file_date"] = preserve_file_date
    if output_dir is not None:
        config["output"]["output_dir"] = str(output_dir.expanduser().resolve())
    if backup_dir is not None:
        config["output"]["backup_dir"] = str(backup_dir.expanduser().resolve())
    if units is not None:
        config["output"]["units"] = units


# ------------------------------------------------------------------ CLI root


@click.group()
@click.version_option(__version__, prog_name="gps-updater")
def cli() -> None:
    """Match GPX tracks to photos and videos and write GPS coordinates into media metadata."""


# ------------------------------------------------------------------ run


@cli.command()
@click.option("--force", is_flag=True, default=False,
              help="Overwrite existing GPS coordinates in media files.")
@_common_options
def run(
    reference_str: str | None,
    media_path: Path | None,
    config_path: Path | None,
    timezone_str: str | None,
    time_offset_seconds: int | None,
    recursive: bool | None,
    dry_run: bool,
    force: bool,
    create_backup: bool | None,
    preserve_file_date: bool | None,
    output_dir: Path | None,
    backup_dir: Path | None,
    units: str | None,
    verbose: bool,
    quiet: bool,
    plain_output: bool,
    log_path: str | None,
) -> None:
    """Match GPS reference tracks to media files and write GPS coordinates."""
    if reference_str is None:
        print("[ERROR] Missing option '--reference'.", file=sys.stderr)
        sys.exit(2)
    if media_path is None:
        print("[ERROR] Missing option '--media'.", file=sys.stderr)
        sys.exit(2)
    reference_paths = _parse_reference_paths(reference_str)
    if not reference_paths:
        print("[ERROR] '--reference' is empty.", file=sys.stderr)
        sys.exit(2)
    media_path = media_path.expanduser().resolve()
    for rp in reference_paths:
        if not rp.exists():
            print(f"[ERROR] Reference path does not exist: {rp}", file=sys.stderr)
            sys.exit(2)
    if not media_path.exists():
        print(f"[ERROR] Media path does not exist: {media_path}", file=sys.stderr)
        sys.exit(2)

    if verbose and quiet:
        quiet = False

    try:
        _run_pipeline(
            reference_paths=reference_paths,
            media_path=media_path,
            config_path=config_path,
            timezone_str=timezone_str,
            time_offset_seconds=time_offset_seconds,
            recursive=recursive,
            dry_run=dry_run,
            force=force,
            create_backup=create_backup,
            preserve_file_date=preserve_file_date,
            output_dir=output_dir,
            backup_dir=backup_dir,
            units=units,
            verbose=verbose,
            quiet=quiet,
            plain_output=plain_output,
            log_path=log_path,
        )
    except SystemExit:
        raise
    except Exception as exc:
        import logging
        logging.getLogger("gps_updater").error("Unexpected error: %s", exc, exc_info=True)
        sys.exit(3)


def _check_output_dirs(config: dict) -> None:
    import os
    output_cfg = config["output"]
    checks = [
        ("output_dir", output_cfg.get("output_dir")),
        ("backup_dir", output_cfg.get("backup_dir")),
    ]
    errors = []
    for key, raw_path in checks:
        if not raw_path:
            continue
        p = Path(raw_path)
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"  Cannot create {key} '{p}': {exc}")
                continue
        if not os.access(p, os.W_OK):
            errors.append(f"  {key} '{p}' is not writable")
    if errors:
        print("[ERROR] Output directory check failed:")
        for e in errors:
            print(e)
        sys.exit(2)


def _run_pipeline(
    reference_paths: list[Path],
    media_path: Path,
    config_path: Path | None,
    timezone_str: str | None,
    time_offset_seconds: int | None,
    recursive: bool | None,
    dry_run: bool,
    force: bool,
    create_backup: bool | None,
    preserve_file_date: bool | None,
    output_dir: Path | None,
    backup_dir: Path | None,
    units: str | None,
    verbose: bool,
    quiet: bool,
    plain_output: bool,
    log_path: str | None,
) -> None:
    from gps_updater import config as cfg_module
    from gps_updater import deps, logger as log_module, plugins as plugin_module
    from gps_updater import reference_scanner, media_scanner, matcher, writer
    from gps_updater.display import Display, build_summary
    from gps_updater.config import resolve_timezone, timezone_display_name
    from gps_updater.models import MatchStatus

    # 1. Dependency check
    exiftool_version = deps.check_all()

    # 2. Load and merge config
    config = cfg_module.load(config_path)
    cfg_module.validate(config)

    # 3. Apply CLI overrides
    _apply_cli_overrides(
        config,
        timezone_str=timezone_str,
        time_offset_seconds=time_offset_seconds,
        recursive=recursive,
        create_backup=create_backup,
        preserve_file_date=preserve_file_date,
        output_dir=output_dir,
        backup_dir=backup_dir,
        units=units,
    )
    if force:
        config["matching"]["on_existing_gps"] = "overwrite"

    # 4. Resolve timezone
    tz_source = timezone_str or config["time"]["timezone"]
    if tz_source is None and not quiet:
        print("[INFO] No timezone specified — using system timezone")
    tz = resolve_timezone(tz_source)
    tz_name = timezone_display_name(tz)

    # 5. Configure logging
    log_module.configure(config, log_path, verbose, quiet)

    # 6. Load plugins
    loaded_profiles = plugin_module.load_all(config["scan"]["plugins_dir"])

    # 7. Set up display
    display = Display(quiet=quiet, plain=plain_output, verbose=verbose)

    config_sources: list[str] = []
    if config_path:
        config_sources.append(str(config_path))
    display.startup(exiftool_version, tz_name, len(loaded_profiles), config_sources)

    # 8. Validate output/backup directories exist and are writable
    _check_output_dirs(config)

    # 8b. Build the set of directories that must be excluded from all scans
    scan_exclude_dirs: set[Path] = set()
    for _dir_key in ("output_dir", "backup_dir"):
        _dir_val = config["output"].get(_dir_key)
        if _dir_val:
            scan_exclude_dirs.add(Path(_dir_val).resolve())

    # 9. Scan reference source
    display.section("Scanning reference source")
    track_points, reference_file_set, ref_counts = reference_scanner.scan(
        reference_paths=reference_paths,
        media_path=media_path,
        recursive=config["scan"]["recursive"],
        on_duplicate=config["matching"]["on_duplicate_trackpoint"],
        loaded_profiles=loaded_profiles,
        timezone_obj=tz,
        offset_seconds=config["time"]["offset_seconds"],
        exclude_dirs=scan_exclude_dirs or None,
    )

    if not track_points:
        print("[ERROR] No usable track points found in reference source — aborting", file=sys.stderr)
        sys.exit(1)

    display.track_summary(track_points, ref_counts)

    # 10. Scan media files
    display.section("Scanning media files")
    media_records = media_scanner.scan(
        media_path,
        config["scan"]["recursive"],
        tz,
        config["time"]["offset_seconds"],
        loaded_profiles,
        exclude_paths=reference_file_set,
        exclude_dirs=scan_exclude_dirs or None,
    )

    if not media_records:
        print("[ERROR] No media files found — aborting", file=sys.stderr)
        sys.exit(1)

    display.media_summary(media_records)

    # 10. Match
    display.section("Matching timestamps")
    results = []
    if verbose:
        from gps_updater.matcher import meters_to_display
        for record in media_records:
            result = matcher.match_one(record, track_points, config)
            results.append(result)
            detail = result.reason or ""
            if result.distance_to_existing_meters is not None:
                detail += f" ({meters_to_display(result.distance_to_existing_meters, config['output']['units'])})"
            display.file_status(result.media.path, result.status, detail)
    else:
        display.start_match_live(len(media_records))
        for record in media_records:
            result = matcher.match_one(record, track_points, config)
            results.append(result)
            display.update_match_live(result)
        display.stop_match_live()

    # 11. Write
    matched_count = sum(1 for r in results if r.status == MatchStatus.MATCHED)
    if not dry_run:
        display.section("Writing GPS data")
        display.start_progress("Writing", matched_count)
    results = writer.write_all(results, config, dry_run, media_root=media_path, on_progress=display.advance_progress)
    if not dry_run:
        display.stop_progress()

    # 13. Summary
    summary = build_summary(results, dry_run)
    display.summary(summary)

    # 14. Status file
    from gps_updater import report as report_module
    status_file_path = config["logging"].get("status_file")
    if status_file_path:
        report_module.write_status_file(
            path=Path(status_file_path).expanduser().resolve(),
            results=results,
            track_points=track_points,
            summary=summary,
            reference_paths=reference_paths,
            media_path=media_path,
            config=config,
            tz_name=tz_name,
            ref_counts=ref_counts,
            dry_run=dry_run,
        )
        if not quiet:
            display._print(f"Status file: {status_file_path}")

    # 15. Export GPX
    export_gpx_path = config["output"].get("export_gpx")
    if export_gpx_path:
        report_module.write_export_gpx(
            path=Path(export_gpx_path).expanduser().resolve(),
            results=results,
            mode=config["output"].get("export_gpx_mode", "waypoints"),
        )
        if not quiet:
            display._print(f"Export GPX: {export_gpx_path}")

    if summary.failed > 0:
        sys.exit(1)


# ------------------------------------------------------------------ init-config


@cli.command("init-config")
@click.option("--output", "output_path", default="gps-updater.json",
              type=click.Path(path_type=Path),
              help="Where to write the generated config file.")
@click.option("--force", "overwrite", is_flag=True, default=False,
              help="Overwrite if the file already exists.")
@_common_options
def init_config(
    output_path: Path,
    overwrite: bool,
    reference_str: str | None,
    media_path: Path | None,
    config_path: Path | None,
    timezone_str: str | None,
    time_offset_seconds: int | None,
    recursive: bool | None,
    dry_run: bool,
    create_backup: bool | None,
    preserve_file_date: bool | None,
    output_dir: Path | None,
    backup_dir: Path | None,
    units: str | None,
    verbose: bool,
    quiet: bool,
    plain_output: bool,
    log_path: str | None,
) -> None:
    """Generate a default configuration file."""
    import copy
    from gps_updater.config import DEFAULT_CONFIG, write_default

    if output_path.exists() and not overwrite:
        print(f"[ERROR] File already exists: {output_path}")
        print("        Use --force to overwrite.")
        sys.exit(2)

    config = copy.deepcopy(DEFAULT_CONFIG)
    _apply_cli_overrides(
        config,
        timezone_str=timezone_str,
        time_offset_seconds=time_offset_seconds,
        recursive=recursive,
        create_backup=create_backup,
        preserve_file_date=preserve_file_date,
        output_dir=output_dir,
        backup_dir=backup_dir,
        units=units,
    )

    write_default(output_path, config)
    print(f"Config written to {output_path}")


# ------------------------------------------------------------------ show-config


@cli.command("show-config")
@_common_options
def show_config(
    reference_str: str | None,
    media_path: Path | None,
    config_path: Path | None,
    timezone_str: str | None,
    time_offset_seconds: int | None,
    recursive: bool | None,
    dry_run: bool,
    create_backup: bool | None,
    preserve_file_date: bool | None,
    output_dir: Path | None,
    backup_dir: Path | None,
    units: str | None,
    verbose: bool,
    quiet: bool,
    plain_output: bool,
    log_path: str | None,
) -> None:
    """Display the fully resolved configuration."""
    import json
    from gps_updater import config as cfg_module

    config = cfg_module.load(config_path)
    _apply_cli_overrides(
        config,
        timezone_str=timezone_str,
        time_offset_seconds=time_offset_seconds,
        recursive=recursive,
        create_backup=create_backup,
        preserve_file_date=preserve_file_date,
        output_dir=output_dir,
        backup_dir=backup_dir,
        units=units,
    )
    print(json.dumps(config, indent=2))


# ------------------------------------------------------------------ list-plugins


@cli.command("list-plugins")
@click.option("--config", "config_path", default=None, type=click.Path(path_type=Path),
              help="Explicit config file path.")
def list_plugins(config_path: Path | None) -> None:
    """List all loaded camera profiles."""
    from gps_updater import config as cfg_module, plugins as plugin_module

    config = cfg_module.load(config_path)
    profiles = plugin_module.load_all(config["scan"]["plugins_dir"])

    if not profiles:
        print("No camera profiles found.")
        return

    try:
        from rich.table import Table
        from rich.console import Console
        table = Table(title=f"{len(profiles)} camera profile(s)", show_header=True)
        table.add_column("Make")
        table.add_column("Model(s)")
        table.add_column("UTC")
        table.add_column("Embedded GPS")
        table.add_column("Source")
        for p in profiles:
            table.add_row(
                p.make,
                ", ".join(p.model_patterns),
                "yes" if p.datetime_is_utc else "",
                "yes" if p.has_embedded_gps else "",
                p.source_file.name,
            )
        Console().print(table)
    except ImportError:
        print(f"{'Make':<12} {'Model(s)':<30} {'UTC':<5} {'GPS':<5} {'Source'}")
        print("-" * 72)
        for p in profiles:
            models = ", ".join(p.model_patterns)
            print(
                f"{p.make:<12} {models:<30} "
                f"{'yes' if p.datetime_is_utc else '':<5} "
                f"{'yes' if p.has_embedded_gps else '':<5} "
                f"{p.source_file.name}"
            )
