# Handover: Sound Effects Cataloging Script

## Context

I've downloaded the Sonniss GDC royalty-free sound effects bundle (~7.5GB, thousands of WAV files) into:

```
warlocktable/soundeffects/
```

The files are nested in per-vendor subfolders, with descriptive filenames like `BN_Intensity by Design_016 High Pitch Tone Osc Crunchy.wav` and `EFX SD Metal plate thunder 01 C.M.wav`. Many also carry embedded broadcast-WAV metadata (BWF `bext` description, or iXML / Soundminer fields) with a longer text description.

I need to find roughly 30-40 short one-shot sound effects to use as audio stingers for NFC card triggers on a physical table controller. Auditioning thousands of files by hand isn't viable. So I want a script that catalogs everything into a single CSV I can hand to an assistant for filtering, so I only have to actually listen to a shortlist.

**This is a control system, not a game.** The sounds are just audio cues that fire when a card is tapped. No game logic is involved anywhere.

## What to build

A Python script, `catalog_sfx.py`, that recursively walks `warlocktable/soundeffects/`, analyzes every audio file, and writes `sfx_catalog.csv`.

### Columns needed

**Identification**
- `path` — path relative to the soundeffects root
- `filename` — basename without extension
- `folder` — immediate parent folder (usually the vendor/library name, which is useful signal)
- `size_mb`

**Basic audio properties**
- `duration_sec`
- `samplerate`
- `channels`

**Acoustic features** — these are what make filtering possible without listening:
- `peak` and `rms_db` — overall level
- `spectral_centroid_hz` — brightness. Low means dark/rumbly, high means bright/hissy. Probably the single most useful column.
- `attack_ms` — time from onset to peak. Short means percussive one-shot; long means a swell or riser.
- `decay_sec` — roughly how long the tail runs after the peak
- `is_oneshot` — boolean heuristic: short duration, single clear transient, decays to silence
- `crest_factor` — peak over RMS. High means punchy and transient, low means sustained or compressed.
- `low_energy_ratio` / `high_energy_ratio` — proportion of energy below ~250Hz and above ~4kHz. Helps separate impacts from shimmers.

**Embedded metadata** (extract if present, blank if not)
- `bwf_description`
- `bwf_originator`
- `ixml_description`

### Requirements

- Handle thousands of files without loading them all into memory. Read only what's needed for analysis — for long files, analyzing the first ~30 seconds is fine, but record the true full duration.
- Skip and log unreadable/corrupt files rather than crashing. Write a `catalog_errors.log`.
- Print progress — this will take a while and shouldn't look like a hang. Show a running count and a rough ETA.
- Support resuming: if `sfx_catalog.csv` already exists, skip files already in it unless `--force` is passed.
- Add `--limit N` for testing on a small subset first.
- Handle non-WAV files if any are present (flac, mp3, aiff), and note the format in a column.

### Suggested libraries

`soundfile` or `pedalboard.io` for reading audio, `numpy` for the feature math. `pedalboard` is already installed in this project from the entity voice work. Avoid heavyweight dependencies like librosa if the features can be computed directly with numpy FFTs — they can.

For BWF/iXML metadata, the `bext` chunk can be parsed directly from the WAV header without an extra dependency; `soundfile` may also expose some of it.

### Output

A single `sfx_catalog.csv` at `warlocktable/soundeffects/sfx_catalog.csv`, one row per file, ready to hand to an assistant for filtering.

Also print a short summary at the end: total files cataloged, total duration, breakdown by folder, and how many were flagged `is_oneshot`.

## Notes

- Nothing here needs to run on the Raspberry Pi. This is a one-time laptop-side job.
- The CSV is the deliverable. Nothing gets copied, renamed, or moved — the library stays as-is.
- Filenames in these bundles are genuinely descriptive, so preserving them exactly (no normalization, no lowercasing) matters for the filtering step.
