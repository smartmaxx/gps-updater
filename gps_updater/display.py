from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any

from gps_updater.models import MatchResult, MatchStatus, MediaRecord, TrackPoint


@dataclass
class RunSummary:
    total: int
    written: int
    photos_written: int
    videos_written: int
    skipped: int
    warned: int
    failed: int
    no_timestamp: int
    before_track: int
    after_track: int
    in_gap: int
    already_has_gps: int
    dry_run: bool


class Display:
    """
    Thin wrapper around rich (or plain output) for progress and status display.
    Constructed once per run and passed through the pipeline.
    """

    def __init__(self, quiet: bool, plain: bool, verbose: bool) -> None:
        self._quiet = quiet
        self._plain = plain
        self._verbose = verbose
        self._rich_available = self._try_import_rich()
        self._progress = None
        self._task_id = None
        self._match_live = None
        self._match_progress = None
        self._match_task = None
        self._match_counters: dict[str, int] = {}

    # ------------------------------------------------------------------ output

    def startup(self, exiftool_version: str, tz_name: str, plugin_count: int, config_sources: list[str]) -> None:
        if self._quiet:
            return
        self._print(f"ExifTool {exiftool_version}  |  timezone: {tz_name}  |  {plugin_count} camera profile(s)")
        if config_sources:
            self._print(f"Config: {', '.join(config_sources)}")

    def section(self, label: str) -> None:
        if self._quiet:
            return
        if self._rich_available and not self._plain:
            from rich import print as rprint
            rprint(f"\n[bold]{label}[/bold]")
        else:
            print(f"\n{label}")

    def track_summary(self, track_points: list[TrackPoint], ref_counts: dict | None = None) -> None:
        if self._quiet or not track_points:
            return
        first = track_points[0].timestamp
        last = track_points[-1].timestamp
        duration = last - first
        total_s = int(duration.total_seconds())
        h = total_s // 3600
        m = (total_s % 3600) // 60
        duration_str = f"{h}h {m}m" if h else f"{m}m"

        date_str = first.strftime("%Y-%m-%d")
        start_str = first.strftime("%H:%M")
        end_str = last.strftime("%H:%M")

        self._print(
            f"  {len(track_points):,} points  |  "
            f"{date_str}  {start_str} – {end_str} UTC  |  "
            f"{duration_str} duration"
        )

        if ref_counts and (ref_counts.get("gpx", 0) > 0 or ref_counts.get("media", 0) > 0):
            parts = []
            if ref_counts.get("gpx"):
                parts.append(f"{ref_counts['gpx']:,} from GPX files")
            if ref_counts.get("media"):
                parts.append(f"{ref_counts['media']:,} from GPS-tagged media")
            self._print("  " + ", ".join(parts))

    def media_summary(self, media_records: list[MediaRecord]) -> None:
        if self._quiet or not media_records:
            return
        images = sum(1 for r in media_records if not r.is_video)
        videos = sum(1 for r in media_records if r.is_video)
        no_ts = sum(1 for r in media_records if r.capture_time is None)
        has_gps = sum(1 for r in media_records if r.has_existing_gps)

        parts = []
        if images:
            parts.append(f"{images} photo{'s' if images != 1 else ''}")
        if videos:
            parts.append(f"{videos} video{'s' if videos != 1 else ''}")
        type_str = ", ".join(parts) if parts else "0 files"

        timestamped = [r for r in media_records if r.capture_time is not None]
        if timestamped:
            times = sorted(r.capture_time for r in timestamped)
            first_date = times[0].strftime("%Y-%m-%d")
            last_date = times[-1].strftime("%Y-%m-%d")
            if first_date == last_date:
                date_range = f"{first_date}  {times[0].strftime('%H:%M')} – {times[-1].strftime('%H:%M')} UTC"
            else:
                date_range = f"{first_date} – {last_date} UTC"
            date_part = f"  |  timestamps: {date_range}"
        else:
            date_part = ""

        extras = []
        if no_ts:
            extras.append(f"{no_ts} without timestamp")
        if has_gps:
            extras.append(f"{has_gps} already have GPS")
        extra_part = f"  |  {', '.join(extras)}" if extras else ""

        self._print(f"  {len(media_records)} files: {type_str}{date_part}{extra_part}")

    def file_status(self, path: Path, status: MatchStatus, detail: str = "") -> None:
        if self._quiet:
            return
        outside_range = detail.startswith("before track start") or detail.startswith("after track end")
        if self._rich_available and not self._plain:
            from rich import print as rprint
            if status == MatchStatus.WARNED and outside_range:
                tag = "[dim]  --  [/dim]"
            else:
                tags = {
                    MatchStatus.MATCHED: "[green]  OK  [/green]",
                    MatchStatus.SKIPPED: "[dim]  --  [/dim]",
                    MatchStatus.WARNED: "[yellow] WARN [/yellow]",
                    MatchStatus.FAILED: "[red] FAIL [/red]",
                }
                tag = tags.get(status, f" {status.value.upper()} ")
            suffix = f"  {detail}" if detail else ""
            rprint(f"  {tag}  {path.name}{suffix}")
        else:
            if status == MatchStatus.WARNED and outside_range:
                tag = " --  "
            else:
                tags = {
                    MatchStatus.MATCHED: " OK  ",
                    MatchStatus.SKIPPED: " --  ",
                    MatchStatus.WARNED: "WARN ",
                    MatchStatus.FAILED: "FAIL ",
                }
                tag = tags.get(status, status.value.upper())
            suffix = f"  {detail}" if detail else ""
            print(f"  {tag}  {path.name}{suffix}")

    def warning(self, message: str) -> None:
        if self._quiet:
            return
        if self._rich_available and not self._plain:
            from rich import print as rprint
            rprint(f"  [yellow]WARN[/yellow]  {message}")
        else:
            print(f"  WARN  {message}")

    def summary(self, s: RunSummary) -> None:
        if self._quiet:
            return
        dry_label = "  [dry-run — no files modified]" if s.dry_run else ""

        rows: list[tuple[str, int, str | None]] = []

        if s.written:
            if s.photos_written > 0 and s.videos_written > 0:
                rows.append(("Photos tagged", s.photos_written, None))
                rows.append(("Videos tagged", s.videos_written, None))
                rows.append(("GPS written (total)", s.written, None))
            elif s.photos_written > 0:
                rows.append(("GPS written", s.written, None))
            elif s.videos_written > 0:
                rows.append(("GPS written (videos)", s.written, None))
            else:
                rows.append(("GPS written", s.written, None))
        elif not s.dry_run:
            rows.append(("GPS written", 0, None))

        if s.before_track or s.after_track:
            parts = []
            if s.before_track:
                parts.append(f"{s.before_track} before start")
            if s.after_track:
                parts.append(f"{s.after_track} after end")
            rows.append(("Outside track range", s.before_track + s.after_track, ", ".join(parts)))

        if s.in_gap:
            rows.append(("In track gap", s.in_gap, None))

        if s.already_has_gps:
            rows.append(("Already have GPS", s.already_has_gps, None))

        if s.no_timestamp:
            rows.append(("No timestamp", s.no_timestamp, None))

        other_warned = s.warned - s.before_track - s.after_track - s.in_gap - s.already_has_gps
        if other_warned > 0:
            rows.append(("Other warnings", other_warned, None))

        if s.skipped:
            rows.append(("Skipped", s.skipped, None))

        if s.failed:
            rows.append(("Failed", s.failed, None))

        rows.append(("Total", s.total, None))

        if self._rich_available and not self._plain:
            from rich.table import Table
            from rich.console import Console
            console = Console()
            table = Table(title=f"Run complete{dry_label}", show_header=False, box=None, padding=(0, 2))
            table.add_column("Status", style="bold", min_width=22)
            table.add_column("Count", justify="right", min_width=6)
            table.add_column("Detail")
            for label, count, note in rows:
                if label in ("GPS written", "Photos tagged", "Videos tagged", "GPS written (total)", "GPS written (videos)"):
                    count_str = f"[green]{count}[/green]" if count else "0"
                elif label == "Failed":
                    count_str = f"[red]{count}[/red]"
                elif label in ("Outside track range", "In track gap", "Already have GPS", "Other warnings"):
                    count_str = f"[yellow]{count}[/yellow]"
                elif label == "Total":
                    count_str = f"[bold]{count}[/bold]"
                else:
                    count_str = str(count)
                note_str = f"[dim]{note}[/dim]" if note else ""
                table.add_row(label, count_str, note_str)
            console.print()
            console.print(table)
        else:
            label_w = max(len(r[0]) for r in rows) + 2
            print(f"\nRun complete{dry_label}")
            for label, count, note in rows:
                note_str = f"  ({note})" if note else ""
                print(f"  {(label + ':'):<{label_w}} {count}{note_str}")

    # ------------------------------------------------------ live match display

    def start_match_live(self, total: int) -> None:
        self._match_counters = {
            "matched": 0, "outside": 0, "gap": 0,
            "existing": 0, "no_ts": 0, "skipped": 0, "failed": 0,
        }
        self._match_live = None
        self._match_progress = None
        self._match_task = None

        if self._quiet or self._verbose:
            return

        if self._rich_available and not self._plain:
            from rich.live import Live
            from rich.progress import Progress, BarColumn, MofNCompleteColumn, TimeElapsedColumn, TextColumn
            self._match_progress = Progress(
                TextColumn("  "),
                BarColumn(bar_width=50),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
            )
            self._match_task = self._match_progress.add_task("", total=total)
            self._match_live = Live(
                self._render_match_group(),
                refresh_per_second=10,
                transient=False,
            )
            self._match_live.start()

    def _render_match_group(self) -> Any:
        from rich.text import Text
        from rich.console import Group as RichGroup
        c = self._match_counters
        parts = []
        if c.get("matched"):
            parts.append(f"[green]matched: {c['matched']}[/green]")
        if c.get("outside"):
            parts.append(f"outside range: {c['outside']}")
        if c.get("gap"):
            parts.append(f"[yellow]in gap: {c['gap']}[/yellow]")
        if c.get("existing"):
            parts.append(f"existing GPS: {c['existing']}")
        if c.get("no_ts"):
            parts.append(f"no timestamp: {c['no_ts']}")
        if c.get("skipped"):
            parts.append(f"skipped: {c['skipped']}")
        if c.get("failed"):
            parts.append(f"[red]failed: {c['failed']}[/red]")
        counter_line = "  " + "  |  ".join(parts) if parts else "  Processing..."
        return RichGroup(Text.from_markup(counter_line), self._match_progress)

    def update_match_live(self, result: MatchResult) -> None:
        if result.status == MatchStatus.MATCHED:
            self._match_counters["matched"] = self._match_counters.get("matched", 0) + 1
        elif result.status == MatchStatus.FAILED:
            self._match_counters["failed"] = self._match_counters.get("failed", 0) + 1
        elif result.status == MatchStatus.SKIPPED:
            reason = result.reason or ""
            if "No timestamp" in reason:
                self._match_counters["no_ts"] = self._match_counters.get("no_ts", 0) + 1
            else:
                self._match_counters["skipped"] = self._match_counters.get("skipped", 0) + 1
        elif result.status == MatchStatus.WARNED:
            reason = result.reason or ""
            if reason.startswith("before track start") or reason.startswith("after track end"):
                self._match_counters["outside"] = self._match_counters.get("outside", 0) + 1
            elif reason.startswith("track gap"):
                self._match_counters["gap"] = self._match_counters.get("gap", 0) + 1
            elif reason.startswith("already has GPS"):
                self._match_counters["existing"] = self._match_counters.get("existing", 0) + 1
            else:
                self._match_counters["skipped"] = self._match_counters.get("skipped", 0) + 1

        if self._quiet or self._verbose:
            return
        if self._rich_available and not self._plain and self._match_live is not None:
            self._match_progress.advance(self._match_task)
            self._match_live.update(self._render_match_group())

    def stop_match_live(self) -> None:
        if self._match_live is not None:
            self._match_live.stop()
            self._match_live = None

    # ------------------------------------------------------ write progress bar

    def start_progress(self, description: str, total: int) -> None:
        if self._quiet or self._plain or not self._rich_available:
            if not self._quiet:
                print(f"{description}...")
            return
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn, TimeElapsedColumn
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=50),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            transient=True,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(description, total=total)

    def advance_progress(self) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.advance(self._task_id)

    def stop_progress(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task_id = None

    # ----------------------------------------------------------------- helpers

    def _print(self, msg: str) -> None:
        if self._rich_available and not self._plain:
            from rich import print as rprint
            rprint(msg)
        else:
            print(msg)

    @staticmethod
    def _try_import_rich() -> bool:
        try:
            import rich  # noqa: F401
            return True
        except ImportError:
            return False


def build_summary(results: list[MatchResult], dry_run: bool) -> RunSummary:
    written = photos_written = videos_written = skipped = warned = failed = no_timestamp = 0
    before_track = after_track = in_gap = already_has_gps = 0

    for r in results:
        if r.status == MatchStatus.MATCHED:
            written += 1
            if r.media.is_video:
                videos_written += 1
            else:
                photos_written += 1
        elif r.status == MatchStatus.SKIPPED:
            reason = r.reason or ""
            if "No timestamp" in reason:
                no_timestamp += 1
            else:
                skipped += 1
        elif r.status == MatchStatus.WARNED:
            warned += 1
            reason = r.reason or ""
            if reason.startswith("before track start"):
                before_track += 1
            elif reason.startswith("after track end"):
                after_track += 1
            elif reason.startswith("track gap"):
                in_gap += 1
            elif reason.startswith("already has GPS"):
                already_has_gps += 1
        elif r.status == MatchStatus.FAILED:
            failed += 1

    return RunSummary(
        total=len(results),
        written=written,
        photos_written=photos_written,
        videos_written=videos_written,
        skipped=skipped,
        warned=warned,
        failed=failed,
        no_timestamp=no_timestamp,
        before_track=before_track,
        after_track=after_track,
        in_gap=in_gap,
        already_has_gps=already_has_gps,
        dry_run=dry_run,
    )
