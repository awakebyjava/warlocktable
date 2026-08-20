# Warlock Table — LED Layout & Pattern Authoring Reference

*Ground truth for all Pixelblaze perimeter patterns. Everything here was verified physically on the table, not assumed. When writing a new pattern, start from the path-building block at the bottom and only change the render logic.*

---

## 1. The physical layout

The table perimeter is a rectangle with a **60-LED ring at each corner** and an addressable **strip running along each of the four edges**. All directions are given **relative to the GM's seat** (the star on the sketches — the seat facing the embedded TCL television).

```
         TOP edge (203)
   TL ring ============== TR ring
   (ch0)                   (ch3... see note)
     |                       |
LEFT |                       | RIGHT
(59) |         TCL           | (59)
     |        (screen)       |
   BL ring ============== BR ring
         BOTTOM edge (203)
```

- **4 corner rings:** 60 LEDs each
- **Top & Bottom edges:** 203 LEDs each
- **Left & Right edges:** 59 LEDs each
- **Total: 764 LEDs** (4×60 + 203 + 203 + 59 + 59)

---

## 2. Expander channel configuration

Configured on the Pixelblaze **Settings → LED Type → Pixelblaze Output Expander** panel. **Auto Start Index is ON**, so start indices are contiguous. Do not hand-edit start indices — leave Auto on.

| Channel | Physical segment | Count | Start Index | Color Order |
|---------|-----------------|-------|-------------|-------------|
| 0 | Ring | 60 | 0 | GRBW |
| 1 | Ring | 60 | 60 | GRBW |
| 2 | Ring | 60 | 120 | GRBW |
| 3 | Ring | 60 | 180 | GRBW |
| 4 | Edge (203+59 combined) | 262 | 240 | GRBW |
| 5 | Edge (203+59 combined) | 262 | 502 | GRBW |
| 6 | *(under-table — unused so far)* | 0 | 764 | — |
| 7 | *(under-table — unused so far)* | 0 | 764 | — |

**Strips are SK6812 RGBW**, color order **GRBW**. (Confirmed from the purchase receipt — not WS2812B, despite the "5V/GND/Din/Do" markings. WS2812B in the config Type dropdown is fine as the driver family; the RGBW color-order option is what matters.)

**Key fact:** the two combined channels (4 and 5) each carry **one long edge (203) + one short edge (59)** in series — 262 pixels each. The pixel index ranges are:
- Channel 4: indices 240–501
- Channel 5: indices 502–763

---

## 3. THE CRITICAL GOTCHA — edge ordering within combined channels

The two edges inside each combined channel are **NOT** in the naive order you'd assume from the channel's physical entry point. They were verified by lighting each segment a distinct color and reading the actual order off the table.

The corrected segment start indices, in **true physical loop order**, are:

```
segStart = [60, 502, 0, 705, 180, 240, 120, 443]
```

Do not "fix" this array to look more logical — it is correct as-is and matches the physical wiring. The two 203 edges are effectively swapped from the assumption, and the two 59 edges are swapped, because of how the sub-runs sit inside channels 4 and 5.

**No edges need direction-flipping.** All four edges run the correct way once positioned correctly. All four rings run **clockwise** relative to the GM position.

---

## 3b. POWER BUDGET — read before touching brightness

| | |
|---|---|
| Strips | 764 × SK6812 RGBW |
| Draw at full white | ~60 mA/LED (RGB) to ~80 mA (all four channels) → **~46–61 A** |
| Power supply | **40 A @ 5 V = 200 W** |
| **Brightness ceiling (set 2026-08-20)** | **50%**, persisted to flash |
| Draw at that ceiling | **~23–31 A = 57–76% of supply** |

**50% is the deliberate ceiling**, chosen to sit inside the usual 80% continuous-load derating rule with real headroom. Slider is at 1.0, so effective output is a true 50%.

A limit is still required: at 100% the worst case (~61 A) would exceed the 40 A supply. Do not raise the ceiling above 50% on the current supply without redoing this arithmetic.

**The limit is the safety mechanism — patterns are not.** It scales *all* output, so no pattern can exceed it by lighting everything at full white. Therefore:

- **Pattern brightness values are an aesthetic choice, not a safety one.** `breathing`'s `maxV = 0.34` is about how a resting table should look, not about protecting the supply.
- Draw still varies *within* the cap: the Pac-Man chase lights ~4 dots out of 700 and draws near nothing, while a full-field wash sits at the ceiling. That affects heat and headroom, not safety.
- **Never treat a dim pattern as a substitute for the limit.** If the limit is wrong, every pattern is unsafe.

**Voltage drop / power injection.** At tens of amps across 764 pixels, the far end of a long run will dim and colour-shift even with ample supply capacity — 5 V systems are unforgiving about this. If the ends of the 203-pixel edges look yellowish or dim compared to the near ends, that is voltage drop, not a pattern bug, and the fix is injecting power at additional points along the run rather than raising brightness.

**Future: a second supply.** The plan is to add another supply and split the load. When that happens, split by *channel group* (e.g. rings on one, edges on the other), tie all grounds together, and do **not** join the 5 V rails of the two supplies.

**To actually get a brighter table**, the fix is a bigger supply, not a higher limit. Full brightness on 764 RGBW pixels wants something in the 200 W+ / 40 A class, plus power injection at multiple points along the runs so the far end isn't starved.

---

## 4. Ring corner skip

Each ring has a quarter-arc that faces **into** the table (toward the screen) and looks awkward/hidden. Patterns skip **8 LEDs at each end** of every ring (16 dead LEDs per ring), which lands the dark gap cleanly on the inside corner. The gap is one continuous arc at the ring's seam (end-of-ring meets start-of-ring), because the ring's wiring starts at the inside corner.

- `skipStart = 8`
- `skipEnd = 8`

This leaves **44 lit LEDs per ring**, so the "active" perimeter path length is **764 − (4 × 16) = 700 pixels**.

---

## 5. The physical loop order (plain language)

Relative to the GM seat, the chase travels:

**TL ring → Top edge (203) → TR ring → Right edge (59) → BR ring → Bottom edge (203) → BL ring → Left edge (59) → back to TL ring**

The rings and edges interleave correctly in path-space, so a pattern that walks the path array in order traces one clean continuous loop with even visual speed (rings and straights move at the same apparent rate, since spacing is handled in path-space).

---

## 6. Pixel map (for the Mapper tab)

A 2D pixel map is installed on the **Mapper** tab so that `render2D(index, x, y)` patterns work. See the companion file `warlock-table-pixelmap.js`.

- Set the Mapper scaling to **Contain** (not Fill), so the rectangular aspect ratio is preserved. Fill would squash the short edges and distort circular/radial patterns.

---

## 7. Reusable path-building block

**Every perimeter pattern starts with this exact block.** It builds `pathPos[]` (maps each physical pixel index to its position along the loop, or −1 if skipped/unused) and `pathLen` (the number of lit pixels, = 700). Only the `render()` logic below it changes from pattern to pattern.

```javascript
// ===== Warlock Table perimeter path builder =====
// Produces: pathPos[pixelIndex] -> loop position (or -1), and pathLen.
// See warlock-table-led-reference.md for the layout this encodes.

skipStart = 8
skipEnd   = 8
RING = 60

// Segments in TRUE physical loop order (verified on-table):
// TL ring, Top, TR ring, Right, BR ring, Bottom, BL ring, Left
segStart  = [ 60, 502,  0, 705, 180, 240, 120, 443]
segLen    = [ 60, 203, 60,  59,  60, 203,  60,  59]
segIsRing = [  1,   0,  1,   0,   1,   0,   1,   0 ]

pathPos = array(pixelCount)
for (i = 0; i < pixelCount; i++) pathPos[i] = -1

pathLen = 0
for (s = 0; s < 8; s++) {
  for (local = 0; local < segLen[s]; local++) {
    skip = 0
    if (segIsRing[s]) skip = (local < skipStart) || (local >= RING - skipEnd)
    idx = segStart[s] + local
    if (!skip && idx < pixelCount) {
      pathPos[idx] = pathLen
      pathLen = pathLen + 1
    }
  }
}
```

### The signed-distance trick (use this for any moving dot)

When lighting a moving dot/comet, compute the wrapped **signed** distance from the dot's head to each pixel — do NOT use `min(d, pathLen - d)`, which drops the sign and lets pixels near a seam get grabbed by the wrong element:

```javascript
d = p - head
d = d - pathLen * floor(d / pathLen + 0.5)  // wrap to [-pathLen/2, +pathLen/2]
d = abs(d)
```

---

## 8. Reference pattern — Pac-Man ghost chase (working)

The confirmed-working 4-ghost chase. Four evenly-spaced dots in classic ghost colors, one clean loop, consistent color, even speed.

```javascript
// ===== Warlock Table - Pac-Man Ghost Chase =====
skipStart = 8
skipEnd   = 8
RING = 60

segStart  = [ 60, 502,  0, 705, 180, 240, 120, 443]
segLen    = [ 60, 203, 60,  59,  60, 203,  60,  59]
segIsRing = [  1,   0,  1,   0,   1,   0,   1,   0 ]

pathPos = array(pixelCount)
for (i = 0; i < pixelCount; i++) pathPos[i] = -1

pathLen = 0
for (s = 0; s < 8; s++) {
  for (local = 0; local < segLen[s]; local++) {
    skip = 0
    if (segIsRing[s]) skip = (local < skipStart) || (local >= RING - skipEnd)
    idx = segStart[s] + local
    if (!skip && idx < pixelCount) {
      pathPos[idx] = pathLen
      pathLen = pathLen + 1
    }
  }
}

numGhosts = 4
ghostHue = array(numGhosts)
ghostHue[0] = 0.00   // red    (Blinky)
ghostHue[1] = 0.85   // pink   (Pinky)
ghostHue[2] = 0.50   // cyan   (Inky)
ghostHue[3] = 0.08   // orange (Clyde)

dotWidth = 4
speed = 0.15   // smaller = slower

export function beforeRender(delta) {
  head = time(speed) * pathLen
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }

  h = 0
  v = 0
  for (g = 0; g < numGhosts; g++) {
    gpos = head + pathLen * g / numGhosts
    d = p - gpos
    d = d - pathLen * floor(d / pathLen + 0.5)
    d = abs(d)
    if (d < dotWidth) {
      h = ghostHue[g]
      v = 1 - d / dotWidth
    }
  }

  hsv(h, 1, v)
}
```

To add a "frightened" blue-ghost mode later, swap all `ghostHue` entries to a single blue when a toggle/NFC card fires — the rest of the pattern is untouched.

### Patterns kept in this repo

Authored patterns live in `patterns/` so they survive a device reset — the Pixelblaze is not the only copy:

| File | Purpose |
|---|---|
| `patterns/breathing.js` | The idle / resting state (plan doc 4.3). Slow warm swell, never fully dark, so a breathing table doubles as the "controller is up" signal from 5.1. |

Uploaded to the device programmatically via `pixelblaze-client`'s `savePattern()` — that is plan doc 3.8's "upload pattern via the panel" working, just driven from a script rather than a UI so far.

---

## 9. Hard-won debugging lessons (so we don't repeat them)

- **Don't guess wiring order from symptoms.** Every time the chase traced wrong, the fastest fix was a static diagnostic that lit each segment a distinct color so the true order could be read off the table directly. Reach for that first.
- **The segment-color test is the master diagnostic:** paint each of the 8 segments a different hue statically, walk the table, report the actual color order. That exposed both the edge-swap bug and confirmed ring correctness.
- **A dot "disappearing" on a ring** was actually just physical density (4 LEDs is a tiny smudge on a tight 44-LED ring) — widening `dotWidth` confirmed it was visible, not missing.
- **Color changing at a boundary** turned out NOT to be color-order (a solid-color flood test proved every LED renders hue identically) — it was the path/order being wrong, so a ghost's color appeared to "change" when really the path jumped.
- **Confirmed-working config is precious.** The `segStart` array and skip values are ground truth. Don't refactor them to look tidier.
- **Watch variables to verify assumptions:** `export var` + the Vars Watch panel confirmed `pathLen == 700` and that `head` swept smoothly — which localized the bug to segment order, not motion or counting.

---

## 10. Quick-reference constants

```
Total LEDs:          764
Active path length:  700  (after ring skips)
Rings:               ch 0-3, 60 each, clockwise, skip 8 each end
Edges:               ch 4-5, 262 each (203 long + 59 short in series)
segStart:            [60, 502, 0, 705, 180, 240, 120, 443]
segLen:              [60, 203, 60, 59, 60, 203, 60, 59]
segIsRing:           [1, 0, 1, 0, 1, 0, 1, 0]
Color order:         GRBW (SK6812 RGBW strips)
Mapper scaling:      Contain
```
