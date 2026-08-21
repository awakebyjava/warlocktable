# Warlock Table — Display Image Specification

*Everything needed to generate static backgrounds, battle maps, and animated content for the table's embedded TV. Self-contained — no other document required.*

*Measured from the actual panel, 2026-08-20.*

---

## 1. What this is for

A television is embedded face-up in a tabletop RPG gaming table. It displays background artwork tied to the game's current mood — a forest, a swamp, a burning hellscape — and sometimes battle maps that physical miniatures stand on.

Two things about this make it different from designing for an ordinary TV, and both change what "good" looks like:

1. **Players sit 2–3 feet away and look down at it.** Detail that would be invisible on a wall-mounted TV is clearly visible here.
2. **It is a light source in a dim room.** The screen faces upward into everyone's faces for hours at a stretch.

The table also has **764 addressable LEDs around its perimeter**, lit in the current scene's colour at the same time the image is showing.

---

## 2. THE SPEC — generate everything at 3840 × 2160

**Output must be exactly 3840 × 2160 pixels. No borders, no padding, no letterboxing.**

| Setting | Value |
|---|---|
| **Resolution** | **3840 × 2160** (exactly) |
| Aspect ratio | 16:9 (1.7778 : 1) |
| Colour space | sRGB |
| Bit depth | 8-bit |
| Static format | PNG (or JPEG quality 90+ for purely photographic work) |
| Video format | MP4, H.264 High profile, yuv420p |
| Video frame rate | 24–30 fps |

### Do NOT use 4096 × 2160

The TV advertises `4096×2160` as supported, and it is tempting because it is bigger. **It is the wrong shape.**

- The physical panel measures **1209 mm × 680 mm** = **1.7779 : 1** = 16:9
- `3840 × 2160` = 1.7778 : 1 → **matches exactly**
- `4096 × 2160` = 1.8963 : 1 → DCI 4K, 17:9 → **does not match**

Feeding the panel 4096-wide content means every image is letterboxed or horizontally stretched. Circles become ovals. Battle map grids stop being square, which makes miniatures sit wrong.

### Why 4K rather than 1440p or 1080p

On a 55" living-room TV, 4K is marginal. At table distance the maths changes completely:

| Resolution | Pixels per inch on this panel |
|---|---|
| 3840 × 2160 | **80.7 px/inch** |
| 2560 × 1440 | 53.8 px/inch |
| 1920 × 1080 | 40.3 px/inch |

At roughly 30 inches, the eye resolves detail far finer than 40 px/inch — **1080p pixels are individually visible** at this distance. 4K is a real, noticeable improvement here in a way it is not on a wall.

**The one exception:** this panel is limited to **30 Hz at any 4K mode** (60 Hz exists only at 2560×1440 and below). For slow ambient motion — drifting fog, flickering firelight, rippling water — 24–30 fps looks excellent, because slow movement does not need a high frame rate. Only if a specific animation has *fast* motion should it be rendered at **2560 × 1440 @ 60 fps** instead. Everything else: 3840 × 2160.

---

## 3. The most important guidance: make it DARK

**This is the instruction most likely to be skipped and most likely to ruin the result.**

Image generators default to bright, punchy, saturated, high-contrast output. That is exactly wrong for this table. The screen points **upward** in a **dim room** during a session that runs for hours.

A bright image is a lamp shining into everyone's faces. It destroys night vision, washes out the LED lighting, and is genuinely unpleasant to sit around.

**Ask for, explicitly:**
- **Dark, low-key, moody.** Firelit, moonlit, dusk, overcast, deep shade.
- **Large areas kept in the lower third of the brightness range.**
- **Desaturated / muted colour.** The 764 perimeter LEDs supply the room's colour; the screen supplies *texture and depth*. A vivid screen fights the lighting instead of completing it.
- Bright highlights only as **small accents** — a campfire, a shaft of light, glinting water. Never as fields.

**Avoid entirely:**
- Large white or near-white areas. On a 55" upward-facing panel this is blinding.
- Strong colour casts that *oppose* the scene's LED colour (a warm orange image under green forest lighting reads as a mistake, not a choice).
- Hard flat gradients — they band visibly on TV panels.
- Fine, high-contrast repeating detail — it shimmers and moirés.
- Baked-in text, unless it is meant to be read.

A useful mental test: *would you be happy with this image on a lamp pointed at your face for four hours?*

---

## 4. Battle maps — the grid

**Settled against real miniatures on the real table (2026-08-21).** The
working grid pitch is **107.85 px per square**, which is what the shipped
`*_grid.png` files use.

| Thing | Pixels |
|---|---|
| One grid square (5 ft / one medium base) | **107.85 px** |
| Large creature (2×2) | 215.7 px |
| Full screen | **≈ 35 × 20 squares** (about 175 × 100 ft) |

### Why this is not the number the panel size implies

Earlier drafts of this document derived a pitch of **80.68 px** from the
panel dimensions `xrandr` reports (1209 mm wide → 47.6″ → 80.68 px/inch).
Maps generated at that scale did not match physical minis.

The reason is that **`xrandr` reports the panel, not the table.** The TV is
recessed into the tabletop, so the visible area is smaller than the panel
itself — a pitch of 107.85 px corresponds to roughly **35.6 inches of
visible width**, not 47.6. The display density figure is therefore a
property of *this installation*, not of the TV.

**The lesson, for anything else physical:** a measurement taken from
software describes the hardware, not the build it is mounted in. Check it
against the object before designing to it.

### Practical rules

1. **Compute grid positions as `round(i × 107.85)`**, not by stepping a
   rounded integer — stepping 108 accumulates about a square and a half of
   drift across the full width.
2. **Draw the grid programmatically**, over AI-generated artwork. Image
   models are unreliable at evenly spaced grids, and a drifting grid is
   worse than no grid when miniatures sit on it.
3. Keep grid lines **thin and low-contrast** (1–2 px, 20–30% opacity). At
   table distance a heavy grid dominates the art beneath it.

*(If minis are not in play, none of this matters and the grid is
decorative.)*

## 5. Safe area — keep important content inside 3456 × 1944

Televisions frequently **overscan**, cropping a few percent off every edge. This panel has not been tested for it yet, so assume it happens.

- **Safe box: 3456 × 1944, centred.** That is 192 px in from left and right, 108 px from top and bottom (5% margin).
- Keep anything that must not be cut inside it: map edges, focal subjects, any text.
- **Let backgrounds bleed to the full 3840 × 2160.** Losing a little atmospheric edge is invisible; losing part of a map is not.

---

## 6. File formats in detail

**Static images**
- **PNG** — use for illustration, flat colour, anything with crisp lines, and *always* for anything with a grid. Lossless, so no compression mush on edges. Expect 5–15 MB at this size.
- **JPEG, quality 90 or higher** — acceptable for purely photographic or painterly images, and much smaller. **Never for grids** — JPEG artifacts cluster on exactly the thin high-contrast lines a grid is made of.

**Animated content**
- **MP4 / H.264 High profile / yuv420p.** This is what the Raspberry Pi decodes in hardware. H.265 is *not* reliably hardware-accelerated on a Pi 4 for playback.
- **Never animated GIF** — no hardware decode, poor colour, enormous files.
- **Loop seamlessly.** First and last frame should match. A visible jump every 20 seconds is very distracting in peripheral vision.
- Bitrate 15–25 Mbps at 4K30. Higher mostly wastes storage and read bandwidth.

---

## 7. How to actually generate these with an AI model

Most image models cannot output 3840 × 2160 directly — they typically cap around 1024–2048 px on the long edge. The workflow that works:

1. **Generate at the model's maximum in a 16:9 aspect.** Whatever 16:9 option it offers (1920×1080, 1344×768, 1792×1024). **Getting the aspect right at generation time matters far more than the pixel count** — you can add pixels later, you cannot fix a wrong shape.
2. **Upscale to exactly 3840 × 2160**, ideally with a model-based upscaler.
3. **Verify the final file is exactly 3840 × 2160.** Not 3840×2159, not 3838×2160. Exact.
4. **For battle maps:** generate the artwork only, then overlay the grid programmatically at 80.68 px pitch (see §4).

### A prompt template to adapt

> A dark, low-key, desaturated [SUBJECT] scene, viewed from directly overhead.
> Moody and atmospheric, lit only by [firelight / moonlight / bioluminescence].
> Muted, restrained colour palette. Deep shadows. No bright or white areas.
> Rich surface texture and fine detail. No text, no characters, no UI elements.
> Wide 16:9 landscape composition, evenly balanced with no single dominant
> focal point. Painterly, cinematic.

Notes on why that is shaped the way it is:
- **"viewed from directly overhead"** — for battle maps and most table backgrounds, a top-down view reads correctly on a horizontal screen. A landscape shot with a horizon looks odd lying flat.
- **"no single dominant focal point"** — people sit on all sides. A composition with an obvious subject in one place looks wrong to everyone not sitting at that side.
- **"no text, no characters"** — text has an orientation and will be upside down for half the table. Characters imply a viewing direction.
- Repeat the **dark / desaturated** instruction more than once. Models drift bright.

---

## 8. Composition — sit-around-a-table considerations

Because people sit on **all four sides**:

- **Prefer orientation-neutral compositions.** Textures, top-down terrain, abstract atmospherics, symmetrical layouts — these read correctly from any seat.
- **Avoid anything with an obvious "up"** unless the content genuinely needs it: horizons, skies, standing figures, text.
- **Avoid a strong single focal point**, which privileges one seat over the others. Even, ambient compositions work better.

**One open decision, not yet made:** whether battle maps and any text-bearing content should be oriented to the GM's seat, or kept orientation-neutral. This does not block generating atmospheric backgrounds, but it should be settled before commissioning a lot of map artwork.

---

## 9. Quick reference card

```
RESOLUTION       3840 x 2160  exactly
                 (NOT 4096 x 2160 - that is 17:9 and will distort)
ASPECT           16:9
COLOUR           sRGB, 8-bit

GRID SQUARE      107.85 px = one medium base = 5 ft
                 (settled against real minis - NOT the 80.68 the panel
                  size implies; xrandr reports the panel, not the visible
                  area, and the TV is recessed into the table)
FULL SCREEN      ~35 x 20 grid squares (~175 x 100 ft)
GRID MATH        position = round(i * 107.85)  -- do NOT step by 108

SAFE AREA        3456 x 1944 centred (5% margin all round)
                 backgrounds may bleed to full frame

STATIC FORMAT    PNG   (JPEG q90+ only for photographic, never for grids)
VIDEO FORMAT     MP4 / H.264 High / yuv420p
VIDEO FPS        24-30 at 4K  (panel is 30 Hz max at 4K)
                 60 fps only if rendered at 2560 x 1440 instead
VIDEO BITRATE    15-25 Mbps

STYLE            DARK. Low-key. Desaturated. Muted.
                 No white or near-white fields.
                 Top-down, orientation-neutral, no dominant focal point.
                 No text. No baked-in characters.
                 The screen supplies texture; the LEDs supply colour.
```

---

## 10. Panel reference data

For anyone recalculating any of the above:

| | |
|---|---|
| Display | TCL HDTV, embedded face-up in the table |
| Physical size | 1209 mm × 680 mm (47.598" × 26.772") |
| Diagonal | ≈ 1387 mm ≈ 54.6" |
| Physical aspect | 1.7779 : 1 (16:9) |
| Connection | Raspberry Pi 4, HDMI1 (second port) |
| Max 4K modes | 4096×2160 @ 30 Hz, 3840×2160 @ 30 Hz |
| Highest 60 Hz mode | 2560 × 1440 @ 60 Hz |
| Viewing distance | ~2–3 feet, looking down |
| Ambient light | Dim to dark during play |
| Also in the room | 764 addressable RGBW LEDs around the table perimeter, lit in the scene's colour |
