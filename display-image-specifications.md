# Warlock Table — Display Image Specifications

*Specs for generating static backgrounds, battle maps, and animated content for the table's embedded TV. Measured from the actual panel on 2026-08-20, not assumed.*

---

## 1. The panel

| | |
|---|---|
| Display | TCL HDTV, embedded in the table |
| Physical size | **1209 mm × 680 mm** (47.6" × 26.8"), ≈ **54.6" diagonal** |
| Physical aspect | **1.778 : 1 → exactly 16:9** |
| Connection | Pi 4 HDMI1 (second port), currently running 1920×1080 @ 60 Hz |

---

## 2. Target resolution — **3840 × 2160**, not 4096 × 2160

**Generate everything at 3840 × 2160 (UHD 4K, 16:9).**

The panel advertises `4096×2160` as a supported mode, but **do not use it.** That is DCI 4K, which is 17:9 (1.896:1). The physical panel is 16:9. Feeding it 4096-wide content means every image is either letterboxed or horizontally stretched — circles become ovals, and on a battle map the grid stops being square.

| Mode | Aspect | Verdict |
|---|---|---|
| 4096 × 2160 | 1.896 (17:9) | ✗ Does not match the panel |
| **3840 × 2160** | **1.778 (16:9)** | ✓ **Use this** |
| 2560 × 1440 | 1.778 (16:9) | ✓ Correct aspect, good fallback for animation |
| 1920 × 1080 | 1.778 (16:9) | ✓ Correct aspect, current mode |

### Why 4K genuinely matters here

On a living-room TV, 4K on a 55" panel is marginal. **This is a table you sit 2–3 feet from**, which changes the maths completely:

- At 3840 wide → **80.7 pixels per inch**
- At 1920 wide → 40.3 pixels per inch

At roughly 30 inches viewing distance, the eye resolves detail finer than 40 px/inch easily — 1080p pixels are *visible* at table range. 4K is a real, noticeable upgrade for this use case in a way it isn't on a wall.

---

## 3. Pixel density — critical for battle maps

**80.7 pixels per inch** at 3840 × 2160. Pixels are square (verified: 80.68 px/in horizontally and vertically).

If physical miniatures will stand on the map, the grid **must** match their bases:

| Thing | Physical | Pixels at 3840×2160 |
|---|---|---|
| Standard grid square (5 ft / medium base) | 1 inch | **≈ 81 px** |
| Large creature (2×2) | 2 inches | ≈ 161 px |
| Full screen width | 47.6 inches | **≈ 47 squares** |
| Full screen height | 26.8 inches | **≈ 26 squares** |

**So: a full-screen battle map at 1-inch scale is roughly a 47 × 26 grid** — about 235 × 130 feet of game space.

Practical guidance:
- Draw grid lines on an **80.7 px pitch**. Rounding to 81 px accumulates about half a square of drift across the full width, so if precision matters, compute positions as `x = round(i * 80.68)` rather than stepping by a fixed 81.
- Keep grid lines **thin and low-contrast** (1–2 px, 20–30% opacity). At table distance a heavy grid dominates the art.
- If minis are *not* being used, ignore all of this and treat the grid as decorative.

---

## 4. Safe area

TVs frequently overscan, cropping a few percent of the edges — and this panel has not been tested for it yet.

- Keep anything that must not be cut (text, key subjects, map edges) inside a **5% margin**: a safe box of **3456 × 1944**, centred, i.e. 192 px in from each side and 108 px from top and bottom.
- Let backgrounds and textures **bleed to the full 3840 × 2160**. Losing a little atmospheric edge is invisible; losing part of a map is not.

---

## 5. Brightness, contrast, and colour — the table-specific part

This is the guidance most likely to be missed, and the most likely to make images fail in the room.

**Make them dark.** The table sits in a dim room during play. A bright image is a lamp shining up into everyone's faces — it kills night vision, washes out the LED lighting, and is genuinely unpleasant to sit around for hours.

- Target an **overall dark, low-key image**. Think firelit, moonlit, dusk.
- Keep large flat areas in the **lower third of the brightness range**. Bright highlights are fine as *accents*, not as fields.
- **Avoid large white or near-white areas entirely.** A white background at 55" pointing upward is blinding.
- Reserve high contrast for small focal points.

**Colour and the LEDs.** The table's 764 perimeter LEDs will be lit in the scene's colour at the same time. Images should *complement* that, not fight it:
- For a scene whose lighting is strongly coloured (the green forest card, the red mountain card), the image can lean the same way — the effect is cohesive.
- Avoid images with a strong *opposing* colour cast, which reads as a mistake rather than a choice.
- **Desaturated images work better than vivid ones**, because the LEDs supply the colour and the screen supplies the texture.

**Avoid:** hard flat gradients (they band badly on TV panels), fine high-contrast repeating detail (shimmers/moirés), and anything with baked-in text unless it's meant to be read.

---

## 6. File formats

**Static images**
- **PNG** for illustration, flat colour, or anything with crisp lines (including grids). Lossless — no compression mush on edges.
- **JPEG (quality 90+)** is acceptable for purely photographic/painterly images and is much smaller. Do not use it for anything with a grid.
- Exactly **3840 × 2160**, sRGB, 8-bit.
- Expect ~5–15 MB per PNG at this size.

**Animated content**
- **MP4, H.264 (High profile), yuv420p** — this is what the Pi decodes in hardware. H.265 is *not* reliably hardware-accelerated on the Pi 4 for playback in all players.
- **Do not use animated GIF.** No hardware decode, terrible colour, huge files.
- Loop seamlessly (first and last frame should match) — a visible jump every 20 seconds is very noticeable in peripheral vision.

---

## 7. Animation: pick your resolution deliberately

There is a real constraint here.

**This TV maxes out at 30 Hz for any 4K mode** (both 3840 and 4096 report 30.00 as their highest). 60 Hz is only available at 2560×1440 and below.

| Option | Pros | Cons |
|---|---|---|
| **3840×2160 @ 30 fps** | Maximum detail; ideal for slow ambient motion | 30 Hz; Pi 4 decode is near its limit |
| **2560×1440 @ 60 fps** | Smooth motion, still 16:9, comfortable for the Pi | Softer than native 4K |
| **1920×1080 @ 60 fps** | Easiest on the Pi, very smooth | Visibly soft at table distance |

**Recommendation:** for *ambient* motion — drifting fog, flickering firelight, slow water — **3840×2160 @ 24 or 30 fps** looks excellent, because slow movement doesn't need a high frame rate. For anything with fast motion, drop to **2560×1440 @ 60**.

Keep bitrate moderate (15–25 Mbps at 4K30). Higher mostly wastes SD-card space and read bandwidth.

---

## 8. Practical note for generating these with an AI model

Most image models cannot output 3840 × 2160 directly — they typically top out around 1024–2048 px on the long edge.

The workflow that works:
1. **Generate at the model's maximum in a 16:9 aspect** (e.g. 1920×1080, 1344×768, or whatever 16:9 option it offers). Getting the *aspect* right at generation time matters far more than the pixel count.
2. **Upscale to exactly 3840 × 2160** afterwards, with a model-based upscaler if available.
3. For **battle maps specifically**, consider generating the *artwork* with AI and then **drawing the grid programmatically on top** at the exact 80.68 px pitch. AI models are unreliable at producing accurate, evenly-spaced grids, and an inaccurate grid is worse than none when minis have to sit on it.

Ask for dark, low-key, desaturated compositions explicitly — models default to bright, punchy, high-contrast images, which is the opposite of what this table wants.

---

## 9. Pi-side items still to sort (not blocking image creation)

- **Switch the display to 3840 × 2160.** Currently at 1920×1080. Needs a mode change and probably `hdmi_group`/`hdmi_mode` updates in `/boot/config.txt`.
- **GPU memory is 76 MB**, which is low for 4K. Likely wants raising (`gpu_mem=128` or more) before 4K video playback is smooth.
- **Overscan check** — confirm whether the panel crops edges, which would validate or relax the 5% safe area above.
- **Choose the viewer.** Static images need a fullscreen viewer with no window decoration; video needs a hardware-accelerated player. `omxplayer` is deprecated on Bullseye, so this is likely `mpv` or VLC.
- **Orientation is undecided.** People sit around a table on all sides. A landscape image has a "right way up" — is it oriented to the GM's seat, or should content be orientation-neutral? This matters most for battle maps and anything containing text.

---

## 10. Quick reference

```
Resolution:      3840 x 2160   (NOT 4096 x 2160 - wrong aspect)
Aspect:          16:9
Pixel density:   80.7 px per inch
Grid square:     80.68 px  (1 inch / 5 ft)
Full-screen grid: ~47 x 26 squares
Safe area:       3456 x 1944 centred (5% margin)
Colour:          sRGB, 8-bit
Static format:   PNG (JPEG q90+ for photographic only)
Video format:    MP4 / H.264 High / yuv420p
Video framerate: 24-30 fps at 4K (panel is 30 Hz max at 4K)
                 60 fps only at 2560x1440 or below
Style:           dark, low-key, desaturated - it lights the room
```
