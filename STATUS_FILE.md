# Understanding the Status File

The status file is a plain-text report generated after each run. It is more concise than the
log but more detailed than the terminal summary. Its main purpose is to help you understand
what happened to every file that was not tagged, and what you can do about it.

Enable it by setting `logging.status_file` in your config:

```jsonc
{
  "logging": {
    "status_file": "./gps-updater-status.txt"
  }
}
```

Or pass it as part of a config file — there is no CLI flag for it because it is meant to
persist across runs.

---

## File structure

The report has five sections: run parameters, reference source, media scanned, results
summary, and the unmatched files detail.

### Run parameters

```
GPS-UPDATER STATUS REPORT
========================================
Run: 2026-04-28 11:47 UTC
Reference: /Users/sm/Documents/trips/2026/Gpx, /Users/sm/Pictures/2026-trip/immich
Media: /Users/sm/Pictures/2026-trip
Timezone: Europe/Warsaw
Dry run: yes — no files were modified
```

If `Dry run: yes` appears, nothing was written to disk. All counts reflect what would have
happened. Remove `--dry-run` and re-run when you are satisfied.

### Reference source

```
REFERENCE SOURCE
  80145 track points total
    80145 from GPX files
    0 from GPS-tagged media files
  Time range: 2026-04-19 08:23 – 2026-04-23 18:29 UTC
  Duration: 154h 6m
```

The time range is the window where the tool can assign coordinates. Any photo taken outside
this window will appear in the "before track start" or "after track end" groups below.

### Media scanned

```
MEDIA SCANNED
  1671 photos, 24 videos
  Timestamps: 2026-04-19 06:12 – 2026-04-23 19:04 UTC
```

If the timestamp range of your media extends beyond the reference source time range, that
tells you immediately that some files will be unmatched.

### Results summary

```
RESULTS
  Photos tagged:                1532
  Videos tagged:                  18
  GPS written (total):          1550
  Outside track range:           145  (145 before start, 0 after end)
  In track gap:                    0
  No timestamp:                    0
  Failed:                          0
  Total:                        1695
```

All lines in this section correspond to the groups in the unmatched files section below.

---

## Unmatched files

This is the most actionable part of the report. Each group comes with a plain-language
explanation and a concrete suggestion.

### Before track start

```
Before track start (145 files)
  These files were captured before your GPS track began.
  Gaps range from 0m 45s to 2h 11m before track start.
  To snap all of them to the track start, set:
    on_photo_before_track=nearest  on_photo_before_track_max_seconds=7871

  IMG_0001.jpg  (2026-04-19 06:12 UTC, 2h 11m before start)
  IMG_0002.jpg  (2026-04-19 06:15 UTC, 2h 8m before start)
  ...
```

**What this means.** Your GPS recording started later than your first photo. Common causes:

- You took photos at the hotel before going out with the GPS device.
- The GPS device took time to acquire a signal and you did not wait.
- The camera clock and the GPS device clock are not in sync (see `time.offset_seconds`).

**Options.**

Set `on_photo_before_track=nearest` to assign the coordinates of the first track point to all
files within a configurable window. The window is controlled by
`on_photo_before_track_max_seconds`. The status file tells you the exact value needed to
cover all unmatched files in this group.

If you need accurate coordinates rather than the start-of-track approximation, the only
option is to provide a GPX file or GPS-tagged reference media that covers the earlier period.

### After track end

Symmetric to before track start. The suggestions and options are identical but apply to the
end of your recording. Config keys: `on_photo_after_track` and
`on_photo_after_track_max_seconds`.

### In track gap

```
In track gap (12 files)
  These files fall inside a gap in GPS recording where no track points exist.
  Current gap threshold: 300s.
  To interpolate across gaps, set on_track_gap=interpolate.
  To increase the gap threshold, raise track_gap_threshold_seconds.

  IMG_0201.jpg  (2026-04-20 14:32 UTC  track gap — falls in a 45m gap in GPS recording)
  ...
```

**What this means.** There is a stretch of time in your GPS track where no points were
recorded — the device lost signal, was switched off, or ran out of battery. Any photo taken
during that stretch cannot be accurately placed.

**Options.**

Set `on_track_gap=interpolate` to linearly interpolate coordinates between the two surrounding
track points. This gives you a plausible position rather than nothing, but accuracy depends
on how large the gap is. A 5-minute gap on a straight road is fine; a 2-hour gap is not.

If the gap is small and caused by momentary signal loss, raising `track_gap_threshold_seconds`
will cause those gaps to be interpolated automatically without triggering the gap policy.

If the gap is large and you have a second GPS source that covers it (a phone log, a different
device), add it to your `--reference` paths.

### Already have GPS

```
Already have GPS (8 files)
  These files already have GPS coordinates embedded.
  To overwrite them, set on_existing_gps=overwrite or pass --force.
  To skip them silently, set on_existing_gps=skip.

  IMG_0301.jpg  (already has GPS — 12m from track point)
  ...
```

**What this means.** The file already has GPS metadata from the camera (phones and some
action cameras embed GPS directly). The distance shown is between the existing coordinates
and the coordinates the tool would assign from the track.

**Options.**

If the existing GPS is accurate (e.g., from a phone), leave the default (`on_existing_gps=warn`)
or set `on_existing_gps=skip` to exclude these files silently.

If you prefer the track coordinates (e.g., the camera GPS is less accurate than your dedicated
device), set `on_existing_gps=overwrite` or pass `--force`.

### No timestamp

```
No timestamp (3 files)
  These files have no usable timestamp in EXIF and cannot be matched.
  Check if the camera clock was set correctly, or if the files have been
  stripped of metadata.

  IMG_0401.jpg
  ...
```

**What this means.** The tool could not find a date/time field in the file's metadata.
Nothing can be done automatically. Possible causes:

- The camera clock was never set.
- The file was edited by software that stripped EXIF data.
- The file format is unusual and the relevant field has a non-standard name.

You can assign coordinates manually using ExifTool:

```bash
exiftool -GPSLatitude=52.2297 -GPSLatitudeRef=N \
         -GPSLongitude=21.0122 -GPSLongitudeRef=E \
         IMG_0401.jpg
```

### Failed

Files where processing raised an error — typically an ExifTool write failure. The reason
string describes the specific error. These files are untouched.

---

## Common workflows

### "Most of my files matched but some were taken before I turned on the GPS"

```jsonc
{
  "matching": {
    "on_photo_before_track": "nearest",
    "on_photo_before_track_max_seconds": 3600
  }
}
```

This snaps files taken up to 1 hour before the track starts to the first track point.
Files taken more than 1 hour before are still warned. Adjust the threshold to match the
gap shown in the status file.

### "I lost GPS signal for 20 minutes while walking through a tunnel"

```jsonc
{
  "matching": {
    "on_track_gap": "interpolate",
    "track_gap_threshold_seconds": 600
  }
}
```

This linearly interpolates coordinates for photos in gaps up to 10 minutes. Gaps longer
than 10 minutes still trigger the gap policy. Adjust `track_gap_threshold_seconds` to your
tolerance for interpolation error.

### "My camera has built-in GPS but it is less accurate than my dedicated tracker"

```jsonc
{
  "matching": {
    "on_existing_gps": "overwrite"
  }
}
```

Or pass `--force` on the command line for a one-off override.
