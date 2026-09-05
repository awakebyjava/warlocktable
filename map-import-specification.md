# Warlock Table — Map Import & Scaling Specification

*How arbitrary images become table-correct battle maps. Specced and built
2026-09-05. Phases 1-8 complete and verified on a laptop; **phase 0, the
dependency check on the actual Pi, is still outstanding** -- see §5 and §16.*

Companion to [`display-image-specifications.md`](display-image-specifications.md),
which defines what a finished asset must look like. **That document is the
authority on every number this one consumes** — resolution, grid pitch, safe
area, darkness doctrine. This document defines the tool that produces assets
conforming to it.

---

## 1. What this is for

Today the table's five backgrounds were rendered by hand to spec. This adds
the ability to take a map from anywhere — a Patreon download, a Roll20 export,
a photo of a hand-drawn map taken on an iPhone — and turn it into an asset the
table displays at the correct scale, with a grid that matches the physical
minis standing on it.

Explicitly a **prep-time** tool. It runs on the Pi, is driven from the panel,
and is allowed to take as long as it takes. It is not in the path of anything
that happens during a session.

---

## 2. Three principles

**Manual adjustment is the tool. Auto-detect is a starting guess.**

Every map — detected or not, gridded or not — opens in the same editor with
the full control set live: pan, scale, rotation, brightness, contrast.
Auto-detect's *only* job is to pre-fill those controls with a better starting
point than the identity transform. There is no "automatic mode" a user can
land in and get stuck. Nothing is ever disabled because detection believed it
succeeded. Detection failing is a non-event, not an error state — it means the
sliders start at a neutral guess instead of a good one.

This is a deliberate inversion of the obvious design ("try auto, fall back to
manual"). Auto-detection of grid pitch is unreliable on hand-drawn art, on
photographs, on stylised maps and on anything hex — and a tool that is
confident and wrong is worse than one that is honest and adjustable.

**It is a module, not a change to the table.**

The running application is working and is not to be rewritten to accommodate
this. The integration surface is deliberately tiny (§4) and enumerated
exhaustively in §13.

**Edits are non-destructive.**

The uploaded original is kept forever alongside a small JSON recipe of the
transform. Renders are reproducible from those two things. See §11 for why
this matters more than it appears to.

---

## 3. Pipeline

```
  upload  ──▶  ingest  ──▶  detect  ──▶  EDIT  ──▶  render  ──▶  publish
  (any fmt)    normalise    guess      (manual,     3840x2160    into the
               to RGB       pitch       always)     + grid       library
                            + offset                + vignette
                                 ▲          │
                                 └──────────┘
                              re-open from recipe
```

Only `render` and `publish` are expensive. `edit` operates on a proxy (§7.1),
so the sliders stay responsive on a Pi 4 regardless of source image size.

---

## 4. The integration seam

`FehDisplay` does not know about the five existing backgrounds. It scans the
directories in `config.background_paths` and parses filenames with a regex
([`feh_display.py:112`](warlock/devices/feh_display.py:112)):

```
base[_3840x2160][_grid|_hex].png   ->   base name + overlay variant
```

Anything that lands a correctly-named PNG in a scanned directory becomes a
selectable background. **That is the entire contract.** The map tool's job
ends at "write these files and ask the display to rescan."

This is why no rewrite is needed, and it is a credit to the original design —
the discovery logic was written data-driven on purpose, with the comment
*"adding a third overlay later should be a filename convention, not a code
change."* The same reasoning extends to adding whole new backgrounds.

---

## 5. Dependencies — the real risk, and how it is contained

This project keeps the Pi's pip surface at **exactly one package**
(`pixelblaze-client`, and only with `--no-deps` plus a stub) because of the
mini-racer/V8 episode documented in [`deploy/README.md`](deploy/README.md).
Image processing is precisely the kind of dependency that could repeat that
mistake. It must not.

**The Pi is Raspberry Pi OS Bullseye, Python 3.9.2, ARM.**

### The resolution: apt, not pip

`install.sh` creates the venv with `--system-site-packages` on purpose, so
that system-installed packages are visible to the service
([`install.sh:139`](deploy/install.sh:139)) — the existing comment says this
exists for *"pygame, RPi.GPIO and spidev … slow or painful to build from
source on ARM."* Imaging belongs in exactly that category.

| Need | How | Why not pip |
|---|---|---|
| Image processing | `apt install python3-pil` | Pillow from pip on ARM/py3.9 may build from source. The apt build is prebuilt, tested against this OS, and already the platform's blessed path. |
| HEIC decode | `apt install libheif-examples`, shell out to `heif-convert` | `pillow-heif` wheel availability on Bullseye/py3.9/ARM is not guaranteed. A subprocess has **zero** Python dependency risk, and the codebase already shells out to `feh` and `xrandr`. |

**Adding zero pip packages to the Pi is a hard requirement of this spec.**
If `python3-pil` proves insufficient for something, the answer is to write the
operation by hand, not to reach for pip.

### Verification is step one of the build

Before any feature code is written, confirm on the actual Pi:

```bash
sudo apt install -y python3-pil libheif-examples
python3 -c "from PIL import Image, ImageEnhance, ImageDraw, ImageOps; print(Image.__version__)"
command -v heif-convert
```

**Do not use `heif-convert --help`** -- Debian's libheif 1.11 has no such
option and answers with `invalid option`, which reads as a failure when the
binary is in fact fine. Its usage is
`heif-convert [-q quality 0..100] <filename> <output>`, which is exactly how
`ingest.py` invokes it.

**VERIFIED ON THE PI, 2026-09-05:** Pillow **8.1.2**, libheif **1.11.0**,
`heif-convert` present. The 8.1 floor this package was written against is
confirmed as the real one, not a guess.

**Tested with a real photo, and it does not** -- see §6. The binary works;
the file is simply newer than the library. Not a blocker for JPEG or PNG.

### Write for the old Pillow, not the new one

Bullseye's `python3-pil` is **Pillow 8.1.2 on Python 3.9**. A laptop is likely
running Pillow 12 on Python 3.12, and the gap contains real traps:

| Do not use | Use instead | Why |
|---|---|---|
| `Image.Resampling.BICUBIC` | `Image.BICUBIC` | The `Resampling` enum is Pillow 9.1+. The bare constants work on **both** 8.1 and 12 — verified. |
| `Image.ANTIALIAS` | `Image.LANCZOS` | Removed in Pillow 10. |
| `match`, `X | Y` at runtime, `dict[str, int]` unevaluated | 3.9 syntax, `typing.Dict`, `from __future__ import annotations` | Python 3.9.2 on the Pi. |

**The laptop is the more permissive environment, so it will not catch these.**
Every module in `warlock/mapimport/` is written to the 3.9 / Pillow 8.1 floor
deliberately, even where a newer idiom would read better.

---

## 6. Ingest

### Accepted inputs

PNG, JPEG, WebP, HEIC/HEIF, and BMP/TIFF if Pillow reads them. Rejected with a
clear message otherwise — not silently.

### HEIC handling

iPhone uploads go through `heif-convert` to a temporary PNG, then join the
normal path.

### The limit found on the actual table, 2026-09-05

**Bullseye's libheif is 1.11.0 (2020), and it cannot read a current iPhone
photo.** Tested with a real file; it fails with:

```
Could not read HEIF/AVIF file: Invalid input: Unspecified:
Metadata not correctly assigned to image
```

Parsing that file's container shows why — it carries:

| Box / item | What it is |
|---|---|
| `tmap` | ISO 21496-1 HDR gain map (iOS 18 HDR photos) |
| `grid` | the picture stored as HEVC tiles assembled into a grid |
| `grpl` | entity grouping tying the HDR pair together |
| brands | `mif1 MiHB MiHE MiPr miaf heic` |

libheif only learned `tmap` in **1.18** (2024). 1.11 parses the container,
meets metadata it has no model for, and stops.

**There is no code fix, and we are not chasing one.** Upgrading means
building libheif from source on 32-bit ARM — which is the mini-racer pattern
this project exists to avoid — and `pillow-heif` is worse: it publishes no
armv7l wheels, so pip would build the same library from source. **This Pi is
armhf**, confirmed from apt output.

What this is *not*: "HEIC is unsupported". Older HEICs decode on 1.11 fine.
This file is newer than the decoder.

The practical routes out, all off the Pi:

1. **Upload through the panel from an iPhone or iPad.** iOS's file picker
   generally transcodes HEIC to JPEG on the way into a web form, so the
   table may never see a HEIC at all. *This is the path that matters and it
   is the one to test.*
2. Screenshot the photo and upload that.
3. `Settings → Camera → Formats → Most Compatible` for JPEG capture.

`ingest.py` detects this specific failure and says all of the above. It is
kept distinct from "the converter is not installed", because telling someone
to install a package they already have is the worst possible answer.

### Two traps that remain, whatever the decoder

1. **EXIF orientation.** iPhone photos are frequently stored rotated with an
   orientation tag. Ignore it and maps arrive sideways. Apply
   `ImageOps.exif_transpose()` immediately after decode, before anything else
   touches the pixels.
2. **HDR gain maps.** Modern iPhone captures carry an HDR gain map. Decoded
   naively the result can be far brighter than the photo looked on the phone —
   which matters enormously here (§9). Take the SDR base image, and let the
   brightness stage do the rest.

### Normalisation

Convert to 8-bit sRGB RGB immediately. Strip alpha against black. Strip all
metadata from the render output — no EXIF, no GPS. A map photographed at home
should not carry the house's coordinates into a file that gets shared.

### Limits

| Limit | Value | Reason |
|---|---|---|
| Max upload size | 80 MB | A 48 MP HEIC is ~25 MB; this is generous with headroom. |
| Max source dimension | 16000 px | Beyond this, decode memory on a 4 GB Pi becomes a real risk. |
| Max total pixels | 80 MP | The number that actually predicts memory. 16000x16000 passes the dimension cap but is 256 MP. Also kept *below* Pillow's own decompression-bomb threshold (~179 MP), because that guard fires inside `Image.open` before the size can be read -- so an image between the two would be refused with "could not be read as an image" instead of a message saying it is too big. Found in testing. |
| Max stored originals | Soft cap, warn at 5 GB | SD card. See §14. |

---

## 7. The editor

The heart of the tool. Everything else exists to feed it.

### 7.1 Proxy rendering

The live preview operates on a proxy no larger than **960 × 540**, generated
once at ingest. Every slider movement re-renders the proxy, which is fast
enough to feel direct on a Pi 4. The full 3840 × 2160 render happens **once**,
on commit.

Consequence to accept: the preview cannot show fine detail or true grid
crispness. That is what §7.4 is for.

### 7.2 Controls

All six are always live, on every map, always.

| Control | Range | Default | Step |
|---|---|---|---|
| **Pan X** | ±1 full frame width | centred | 1 px fine / 1 square coarse |
| **Pan Y** | ±1 full frame height | centred | 1 px fine / 1 square coarse |
| **Scale** | 0.05× – 8× | detection's guess, else fit-to-frame | 0.1% fine |
| **Rotation** | −180° to +180° | 0° | 0.1° fine / 90° snap |
| **Brightness** | 0.15× – 1.5× | measured ceiling (§9) | 1% |
| **Contrast** | 0.5× – 1.5× | 1.0 | 1% |

**Pan must be sub-square precise.** Getting the pitch right is not enough —
grid *phase* matters just as much. If a map's rooms sit half a square off the
table's grid, every mini lands wrong. Coarse stepping by exactly one grid
square (107.85 px) is offered alongside fine pixel stepping, because "nudge it
one whole square" is a thing you want constantly and cannot do accurately by
dragging.

**Rotation and scale compose into a single resample.** Never chain them as
separate operations — each resample softens the image, and two applied in
sequence visibly degrade a map that will be looked at from two feet away.
Build one affine transform, apply it once, with `Image.BICUBIC` or better.

### 7.3 Snap to grid

A toggle. When on, pan snaps to whole multiples of the grid pitch and rotation
snaps to 90°. Off by default — snapping is for finishing, not for finding.

### 7.4 Preview on the table

A button that renders at full resolution and pushes the result to the real TV
via the existing `set_background` path, without publishing it to the library.

This is not a nicety. **You cannot judge "too bright for players" on a tablet
in a lit room**, and you cannot judge grid alignment without putting a real
mini on the real glass. The infrastructure already exists; the cost is writing
one file and calling one existing method.

Leaving preview mode restores whatever background was showing before.

---

## 8. Scale, fit, and the grid

### 8.1 The target

From `display-image-specifications.md` §4 — **107.85 px per 5 ft square**,
settled against real miniatures on the real table. Full screen is
**≈ 35 × 20 squares**.

Grid positions are computed as `round(i × 107.85)`, never by stepping a
rounded integer. Stepping 108 accumulates about a square and a half of drift
across the frame.

**This number is read from one shared constant, not copied.** If the table is
ever re-measured, one edit plus a re-render of every recipe (§11) makes every
custom map correct again.

### 8.2 Auto-detection

Two paths, chosen by what the user says the map is:

**Map has a printed grid** — detect its pitch:

1. Greyscale, then a one-pixel directional difference per axis. (A horizontal
   difference responds to *vertical* lines and ignores horizontal ones, so the
   two axes are measured independently instead of polluting each other.)
2. Project each to a 1-D signal **at full resolution**, then decimate.
3. Detrend, autocorrelate, and take the smallest lag that is within 90% of the
   best — a signal with period *p* correlates just as well at 2*p* and 3*p*.
4. Parabolic interpolation against the neighbouring lags for sub-pixel pitch.
5. Phase comes from the position of the first line, giving the initial pan.

**Two corrections that testing forced, both worth keeping:**

*Project at full resolution.* The first version resized the **image** to
1200 px before projecting. Grid lines are 2 px at 25% opacity; box-downscaling
attenuates them and shifts each by a different sub-pixel amount, so every
third line landed better than its neighbours. It reported **323 px for the
real 107.85 px grid** — a 3× harmonic, at "high" confidence, which is exactly
the failure §2 says must never happen. Summing a whole column at full
resolution preserves a thin line exactly. Decimating the *1-D signal*
afterwards is safe, because by then the lines are integrated into it.

*Axis agreement is required, not merely rewarded.* Plain artwork with no grid
was returning plausible pitches at "low" confidence, because texture always
repeats at *some* period and one axis can always be talked into a peak.
Artwork is very unlikely to repeat at the same period **both** ways; a square
grid does so by definition. Requiring agreement turned "usually right" into
"quiet when unsure".

Measured after both fixes: **107.949 px on the real `forest_*_grid.png`
(+0.09% against the true 107.85), high confidence, 0.5 s** — and `failed` on
all five ungridded backgrounds.

Scale factor is then `107.85 / detected_pitch`.

**Map has no grid** — nothing to detect. Scale defaults to fit-to-frame and
the table's own grid is drawn over the top.

**Declared size** — always available and always the most reliable: the user
types how many squares wide the map is. `scale = (squares × 107.85) / width`.
This is exact, takes five seconds, and is the recommended path whenever the
map's dimensions are known.

### 8.3 Confidence, and what it does

Detection reports **high / low / failed**. It changes exactly one thing: the
message shown above the editor.

- *High* — "Detected a 64 px grid; scaled to match the table."
- *Low* — "Grid detection was uncertain. Check the alignment before saving."
- *Failed* — "No grid detected. Set the scale manually, or enter the map's width in squares."

It never changes which controls are available. See §2.

### 8.4 When the map does not fit

A map wider than ~35 squares cannot display at true 5 ft scale. **The tool
asks; it does not choose:**

> This map is 40 squares wide. The table displays 35.
> · **Crop** — keep true 5 ft squares, lose 5 squares of width
> · **Scale down** — show the whole map, squares become 4.4 ft
> · **Adjust manually** — open the editor and decide by eye

Choosing "scale down" is legitimate and must not be discouraged — for
exploration and travel maps, seeing the whole thing beats mini-accurate scale.
But it must be a choice made knowingly, and the resulting square size is
recorded in the recipe and shown in the library.

### 8.5 Aspect mismatch — the vignette bleed

Source maps are rarely 16:9. Where the scaled map does not cover the frame,
fill with a **dark vignette bleed**:

1. Fill the frame with a heavily blurred, darkened copy of the map itself
   (large-radius Gaussian, luminance pulled well down).
2. Feather the map's edge into it over ~120 px.
3. Deepen towards the frame edges.

The result reads as the map fading into darkness rather than as a photo pasted
on black. It suits the table's aesthetic, it avoids a hard bright/dark seam in
peripheral vision, and it keeps emitted light low at exactly the edges nearest
the players' faces.

Pure black remains available as an option for anyone who wants it.

### 8.6 Safe area

The overscan safe box — **3456 × 1944 centred** — is drawn in the preview as a
guide. Map content should stay inside it; the vignette bleeds to the full
frame. This is advisory, not enforced: the spec's own guidance is that
backgrounds may bleed and only *maps* must be protected.

---

## 9. Brightness and colour

`display-image-specifications.md` §3 is unambiguous: the screen faces upward
into people's faces for hours, and brightness is *"the instruction most likely
to be skipped and most likely to ruin the result."*

A slider judged by eye on a bright iPad will not protect against this. So:

1. **Measure the house style once**, from the artwork already on this table.
   **Two numbers, and they are used for different things:**

   | | Measured | Used for |
   |---|---|---|
   | **mean** | 29.6 | what the **warning** compares against |
   | **ceiling** (brightest existing background) | 49.6 | what the auto brightness **default** aims at |

   Targeting the mean for the default was the obvious choice and it was
   **wrong** — caught by looking at a render. The existing backgrounds are
   atmospheric texture, meant to be barely there. A battle map has to be
   *read*: players need to see the walls and doors they are moving miniatures
   between. Pulled to the ambient average, a map is unreadable. The ceiling
   keeps the default inside the house style (it is as bright as the brightest
   thing already accepted here) while leaving the map legible.

2. **Measure every upload** and compare.
3. **Pre-set the brightness slider** to land the image near the ceiling — so
   the default is already sane and the slider is for taste, not rescue.
4. **Warn, with the actual number**, when the committed render is above
   target: *"This map is 40% brighter than your existing backgrounds. It will
   be noticeably brighter in the room."*
5. **Never block it.** It is a warning with a real number attached, not a
   limit. The GM decides.

Also reported: percentage of pixels above 90% luminance ("near-white fields"),
which the spec calls out as the specific thing that is blinding on an
upward-facing panel.

Contrast is a straight multiplier with no doctrine attached; it exists because
pulling brightness down flattens an image and contrast puts the depth back.

---

## 10. Output contract

### Files written per published map

```
<backgrounds>/custom/<slug>_3840x2160.png        plain artwork
<backgrounds>/custom/<slug>_3840x2160_grid.png   with the table grid drawn
```

Both **must** be written. The display falls back to plain artwork when a
variant is missing ([`feh_display.py:407`](warlock/devices/feh_display.py:407)) —
which is graceful, but it means a missing `_grid` file shows *the ungridded
map in grid mode* with no error anywhere. A quiet wrong-image failure is worse
than a loud one, so the writer verifies both files exist before declaring
success.

**No `_hex` variant is written.** Hex pitch has never been measured against
real minis on this table; generating one from an assumed number would be
inventing a measurement. Hex mode on a custom map falls back to the plain
artwork, which is quiet and correct. Revisit when hex is measured.

### Naming

- Slug from the user's title: lowercase, `[a-z0-9-]` only, max 48 chars.
- On collision: append `-2`, `-3`. Never silently overwrite.

**Correction, found by reading the code:** `_scan()` uses `os.listdir` and
**does not recurse** ([`feh_display.py:391`](warlock/devices/feh_display.py:391)).
So `backgrounds/custom/` is not discovered by being a subdirectory — it must
be registered as its **own entry in `config.background_paths`**. `install.sh`
creates it; the shipped example config lists it.

That also means base names are a **single flat namespace across every search
path**, so a directory cannot be used to avoid collisions. Collision checking
is therefore done against the live library — `available_backgrounds()` at
publish time — which is exact and covers both the built-in five and every
previously published custom map.

### Format

PNG, always. The spec is explicit that JPEG is never acceptable for anything
with a grid — JPEG artifacts cluster on exactly the thin high-contrast lines a
grid is made of. Expect 8–15 MB per file, 16–30 MB per published map.

### Grid rendering

Drawn programmatically over the artwork at `round(i × 107.85)`, 1–2 px wide,
20–30% opacity, matching the existing `*_grid.png` files. Never scaled up from
a smaller render.

---

## 11. The recipe — why non-destructive matters here

Each published map stores three things:

```
<data>/maps/originals/<slug>.<ext>     the upload, untouched
<data>/maps/recipes/<slug>.json        the transform
<backgrounds>/custom/<slug>_*.png      the renders
```

The recipe holds source filename, pan/scale/rotation, brightness/contrast,
grid pitch used, fit decision, vignette settings, and the tool version.

Three things this buys, all worth more than the disk it costs:

1. **Re-editing does not recompound.** Adjusting a map next month re-renders
   from the original, rather than resampling an already-resampled render.
2. **The grid constant stays soft.** 107.85 was measured once against real
   minis and could be re-measured. With recipes, a re-measurement is a
   constant change plus a batch re-render. Without them, it is redoing every
   map by hand — which in practice means never fixing it.
3. **It is a repair path.** A corrupted or accidentally deleted render is one
   command away from being back.

---

## 12. Panel integration

### Upload transport

`HTTP PUT` of the **raw file bytes**, with the filename in a query parameter.
Not multipart.

Multipart parsing in stdlib `http.server` means the `cgi` module (deprecated,
and removed in Python 3.13) or a hand-rolled parser. A raw PUT is a few lines,
has no parsing surface to get wrong, and every HTTP client can do it. The
panel already speaks JSON over `fetch`.

### Endpoints — a new third surface

The panel today keeps two API surfaces deliberately separate: `/api/action/*`
fires things, `/api/config/*` edits data. Map import is neither — it is a
long-running file operation. It gets its own prefix so it cannot be confused
with either:

| Method | Path | Does |
|---|---|---|
| `PUT` | `/api/maps/upload?name=` | Accept bytes, ingest, return a job id |
| `GET` | `/api/maps/<id>` | Ingest result: proxy, detection, confidence |
| `POST` | `/api/maps/<id>/adjust` | Set transform, return updated proxy |
| `POST` | `/api/maps/<id>/preview` | Full render, push to TV, do not publish |
| `POST` | `/api/maps/<id>/publish` | Full render, write library files, rescan |
| `GET` | `/api/maps` | List published custom maps |
| `DELETE` | `/api/maps/<slug>` | Remove renders, original and recipe |

### Threading

The server is `ThreadingHTTPServer`, so each request already has its own
thread. Renders must not touch controller state; the only controller
interaction is the rescan at the end of publish, and the temporary
`set_background` during preview.

This satisfies the project's isolation rule — a map render that fails, hangs,
or runs out of memory must not affect lights, audio or the running session.
Wrap the whole pipeline so it can only ever return an error, never raise into
the panel.

### UI

Its own section behind an "Add custom image" entry, built to
[`warlock-table-style-guide.html`](warlock-table-style-guide.html), following
the existing four-panel tab-bar structure. Two screens: a library grid of
published maps, and the editor.

---

## 13. Changes to existing code — the complete list

Deliberately exhaustive. If the build needs a change not on this list, that is
a signal to stop and re-read §2, not to make the change quietly.

| File | Change | Size |
|---|---|---|
| `warlock/devices/base.py` | Add `rescan()` to the `DisplayDevice` interface | 3 lines |
| `warlock/devices/feh_display.py` | Public `rescan()` wrapping the existing private `_scan()` under the lock | ~6 lines |
| `warlock/devices/fake.py` | No-op `rescan()` | 2 lines |
| `warlock/web/server.py` | Route the seven `/api/maps/*` paths into the new module | ~30 lines, all delegation |
| `warlock/config.py` | Two settings: custom backgrounds dir, luminance target | ~4 lines |
| `deploy/install.sh` | Create `maps/originals`, `maps/recipes`, `backgrounds/custom` | ~3 lines, matches existing pattern |
| `warlock/tablecheck.py` | Missing custom map warns instead of failing | ~35 lines |
| `data/config.example.json` | The two new paths | 3 lines |
| `warlock/web/static/index.html` | The Maps page markup, one Settings button | markup |
| `warlock/web/static/app.js` | Register "maps" as a page; two nav hooks | ~8 lines |
| `warlock/web/static/style.css` | Styles for the editor's controls | appended |
| `deploy/README.md` | Document the two apt packages | prose |
| `README.md` | One row in the orientation table | prose |

Plus two new files on the web side:

```
warlock/web/maps.py          the /api/maps/* endpoints
warlock/web/static/maps.js   the library and editor
```

Everything else is new, and lives in:

```
warlock/mapimport/
    __init__.py     the public entry points the panel calls
    ingest.py       decode, HEIC, EXIF, normalise, proxy
    detect.py       grid pitch and phase estimation
    transform.py    the single composed affine resample
    grid.py         the 107.85 constant and grid drawing
    tone.py         luminance measurement, brightness, contrast
    vignette.py     the dark bleed
    render.py       full-res render and library publish
    recipes.py      recipe read/write
warlock/web/static/  the maps section UI
```

`warlock/mapimport/` imports nothing from `controller.py`. It is given paths
and returns paths. That is what makes it a module rather than a feature.

---

## 14. Housekeeping

4K PNGs are 8–15 MB and this project deliberately keeps media out of git.
Custom maps accumulate on the Pi's SD card, which is also where the journal
cap and device state live.

- **Report total usage** in the maps section and in `tablecheck`.
- **Warn at 5 GB**, do not enforce.
- **Delete removes everything** — renders, original, recipe — and says how
  much it recovered.
- **Originals are the durable copy.** Anything backed up off the Pi should be
  `maps/originals` plus `maps/recipes`; the renders are reproducible and need
  not be backed up.

---

## 15. Failure modes to handle explicitly

| Failure | Behaviour |
|---|---|
| Unreadable / corrupt file | Reject at ingest, name the reason |
| HEIC without `heif-convert` | Clear message naming the apt package |
| Image beyond dimension cap | Reject before decode, not after OOM |
| Detection wrong but confident | Mitigated by design — manual controls are always live (§2) |
| Grid pitch right, phase wrong | Sub-square pan plus snap-to-grid (§7.2) |
| Render out of memory | Caught, reported, no partial files left in the library |
| Only one of the two variants written | Verified before publish declares success (§10) |
| Slug collision | Suffix, never overwrite |
| Rescan after publish fails | Files exist and are correct; report "restart to see it" |
| Disk full mid-render | Write to temp, atomic rename into the library |

---

## 16. Build order

Each phase is independently verifiable. Nothing proceeds on an unverified
assumption.

| # | Phase | Done when |
|---|---|---|
| 0 | **Verify dependencies on the real Pi** (§5) | **OUTSTANDING** — `python3-pil` and `heif-convert` confirmed working on the Pi itself |
| 1 | Ingest + normalise, CLI only | **PARTLY BLOCKED** — JPEG/PNG/WebP verified. Current-iPhone HEIC cannot decode on this OS (§6); the remaining test is whether uploading from an iPad through the panel converts to JPEG on the way |
| 2 | Transform + grid + render, CLI only | A known map renders to spec, and a mini sits correctly on the real table |
| 3 | Vignette and tone | Fit and brightness match the existing five |
| 4 | Detection | Pre-fills correctly on a gridded map; fails quietly on a photo |
| 5 | Recipes | A map re-opens and re-renders identically |
| 6 | Panel endpoints | Upload and publish work from the iPad |
| 7 | Editor UI | Sliders, preview-on-table, publish |
| 8 | Housekeeping | Listing, deletion, usage reporting |

Phases 1-8 are built and verified on a laptop. What has been checked so far:
grid geometry against the shipped `*_grid.png` files (pitch 107.857, 2 px
lines, 0.25 alpha — all matched), the affine transform, detection on real and
synthetic maps, the full HTTP path through the real panel, and the display
scanner picking up a published map without a restart.

**Phase 2's acceptance test is still open, and it is the one that matters.**
It is physical: render a map of known dimensions, put a real miniature on a
real square, and confirm the square is the size of the base. Every number in
this document descends from that test, and no amount of correct-looking code
substitutes for it.

---

## 17. Deferred, on purpose

- **Hex support** — needs a pitch measured against real minis first (§10).
- **Animated map backgrounds** — the display shows stills; video is a
  different subsystem.
- **Map orientation default** — assumed GM's seat, per the open question in
  `display-image-specifications.md` §8. The rotation control makes this a
  per-map decision, so the global default can stay unsettled.
- **Multi-page / tiled dungeon maps** — one image, one background, for now.
- **Auto-detecting map *content*** (walls, doors, lighting) — out of scope by
  a wide margin.

Also parked by decision, and unrelated to this work: tarot audio, the GPIO
shutdown button, and the table personality stretch goal.

---

## 18. Settled

**Custom maps are ordinary backgrounds, and go all the way.** They are
selectable as scene backgrounds in the scene editor, and a scene built on one
can be bound to an RFID card like any other. There are no accounts, so every
uploaded map is available to everyone running the table — that is intended,
not a limitation to work around.

This costs nothing to support, because the existing design already allows it:
scenes reference a background by bare name, and cards are dumb triggers that
point at scenes. A published custom map is a valid background name the moment
it is written, so it is scene-selectable and card-bindable with no further
work. Nothing in this module needs to know that.

**`tablecheck` warns on a missing custom map; it does not fail.** Today a
missing referenced background is `FAIL`
([`tablecheck.py:258`](warlock/tablecheck.py:258)). Custom maps are
user-uploaded and deliberately deletable, so a scene pointing at one that has
been removed is a thing to be told about, not a reason to red-flag the table
before a session.

Missing **built-in** backgrounds keep failing, which is unchanged behaviour —
those are shipped assets, and one going missing means something is actually
broken. The check distinguishes the two by asking the maps module which slugs
it published.
