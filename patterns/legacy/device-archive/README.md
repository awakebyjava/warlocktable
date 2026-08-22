# Device archive — patterns pulled off the Pixelblaze

Taken 2026-08-22 by `tools/archive_patterns.py`, before pruning the
device's flash.

**Nothing here is built, referenced or uploaded by this project.** These are
copies. The source of truth for the table's own patterns is
`patterns/generated/` (emitted by `tools/patterngen.py`) and
`patterns/` for the two hand-written ones still in use.

## Why it exists

The Pixelblaze's flash was 82% full and the 48 stock demo patterns were most
of it. Removing them was the fix — but *"we can always download them again
from Pixelblaze's library"* is a claim nobody checks until they need it, and
39 of these were then deleted from the device for real. This makes that
reversible from the repo alone, with no internet and no hunting.

## What is here

All 77 patterns that were on the device at the time, not just the deleted
ones — it was cheaper to take everything than to be careful about which
copies mattered. That includes the table's own patterns, which are
duplicated from `patterns/generated/` and can be ignored.

Each file carries a header recording the device's own name for the pattern
and its pattern id. **That matters:** an earlier, more casual archiving run
produced a `legacy/forest.js` that contained a KITT pattern — the filename
was simply wrong, and nothing in the file said so. It went unnoticed for two
days until it blocked a `git mv`. Provenance in the file, not just in the
filename.

## Restoring one

`tools/upload_pattern.py` reads from `patterns/` and `patterns/generated/`,
not from here, so a file needs copying to one of those first — and its
header comment removing, since the device does not need it.

Bear in mind these were written for a general Pixelblaze, not for this
table: they know nothing about the 764-pixel perimeter loop, the corner
rings, or the segment ordering in `warlock-table-led-reference.md`. Most
will run, and most will look wrong on this geometry. That is the reason
they were pruned rather than kept.
