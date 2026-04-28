# Visual Verification

After running gps-updater you will want to confirm that the coordinates written to your files
are correct before doing anything irreversible — uploading to a photo service, deleting
originals, or sharing the files.

This page describes three approaches, from quickest to most thorough.

---

## Option 1: Export GPX + gpx.studio (fastest, no install)

**gpx.studio** is a browser-based GPX viewer. Nothing is stored on their servers beyond
the current session. No account required.

**Step 1.** Enable the export GPX feature in your config:

```jsonc
{
  "output": {
    "export_gpx": "./export.gpx",
    "export_gpx_mode": "both"
  }
}
```

`"both"` generates named waypoints (one per file) plus a route track connecting them in
chronological order. This lets you see both where each individual file was tagged and the
path you walked.

`"waypoints"` shows only the pins — useful when you care about individual positions.

`"route"` shows only the connecting line — useful to check that the overall path makes sense.

**Step 2.** Run gps-updater (dry-run is fine — the export GPX is always written):

```bash
gps-updater run --reference=./tracks --media=./photos --dry-run
```

**Step 3.** Go to [gpx.studio](https://gpx.studio), click "Open", and load:

1. Your original GPX track file — this is the ground truth.
2. The `export.gpx` file the tool generated.

Both appear on the map simultaneously. The original track (your actual route) and the
photo waypoints should align closely. If a cluster of waypoints sits somewhere unexpected,
that is a sign of a timezone mismatch or a large clock offset.

**What to look for.**

- Waypoints that land in the right city and area — a quick sanity check.
- Waypoints that follow the track — they should sit on or very close to the track line, not
  off in the water or in a different neighbourhood.
- The route line (if you used `"both"` or `"route"`) should follow the same general path as
  the original track, because both are ordered by time.

---

## Option 2: digiKam (best for seeing the actual photos on a map)

**digiKam** is a free, open-source photo management application available for macOS, Linux,
and Windows. Its map module reads GPS EXIF directly from local files — no import, no cloud
upload.

**Setup (one time).**

1. Install digiKam from [digikam.org](https://www.digikam.org).
2. Add your photo folder to a digiKam collection (File > Add Collection).
3. Switch to the Map view (the globe icon in the left panel).

All photos that have GPS coordinates appear as markers on the map. Clicking a marker shows
the photo. Zooming in shows individual positions; zooming out clusters them by area.

**Workflow.**

Run gps-updater with `--output-dir=./geotagged` to write tagged copies to a separate folder,
then point digiKam at that folder. This lets you verify before touching the originals.

If the positions look correct, run again without `--output-dir` (or with `--force`) to write
to the originals.

**What to look for.**

- Photos appear in the right country, city, and neighbourhood.
- The sequence of photos follows a logical path — walking through streets, not teleporting
  between distant locations.
- Hotels, restaurants, and landmarks match what you remember from the trip.

---

## Option 3: GPXSee (lightweight desktop viewer)

**GPXSee** is a small, fast GPX viewer for macOS, Linux, and Windows. It opens multiple
files simultaneously and overlays them on a map.

Download from [gpxsee.org](https://www.gpxsee.org).

Open your original GPX track and the export GPX side by side. Use this when you want a
desktop tool that does not require setting up a full photo library, or when you are
working with the route and waypoints rather than the actual image content.

---

## Recommended workflow

1. Run with `--dry-run` first. This parses and matches everything without modifying files.
   The export GPX and status file are written even in dry-run mode.

2. Open the export GPX in gpx.studio alongside your original track. Verify the overall
   picture looks right.

3. If something looks wrong, read the status file to identify which files were outside the
   track range or in gaps, and adjust the configuration accordingly.

4. Re-run without `--dry-run` once you are satisfied.

5. Use digiKam to spot-check a sample of the tagged files by browsing the map view.

---

## Common problems and what they look like on the map

**All photos land in the wrong city or country.** The timezone is wrong. The camera clock
was interpreted as a different timezone than intended. Fix: pass the correct `--timezone`.

**Photos are shifted by a consistent time offset (right direction, wrong position along
the route).** The camera clock was fast or slow. Fix: measure the offset and set
`time.offset_seconds`.

**A cluster of photos land at the very start or end of the track.** Those photos were
taken outside the GPS recording window and were snapped to the nearest endpoint using
`on_photo_before/after_track=nearest`. Check the status file to see how far outside they were.

**A group of photos land in an implausible straight line across a gap.** These were
interpolated across a GPS recording gap (`on_track_gap=interpolate`). If the gap was long,
the interpolated positions may be meaningless. Consider setting `on_track_gap=warn` for long
gaps or providing a GPS source that covers the gap.
