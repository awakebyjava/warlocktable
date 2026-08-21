// ============================================================
// Warlock Table - "zones"  (per-seat colour, driven by the controller)
// ============================================================
// Plan doc 4.7. This is the pattern that makes seat claiming possible:
// it paints each seat's arc of the perimeter in its own colour, so a
// player can point at the table and say "I'm the green one".
//
// It is NOT a scene. It draws exactly what the controller tells it to
// and animates nothing, because its whole job is to be read literally.
//
// Built on the standard perimeter path block from
// warlock-table-led-reference.md section 7. Per that doc, the path
// builder below is copied verbatim and ONLY the render logic differs.
// Do not "tidy" segStart - it is verified physical ground truth.

// ===== Warlock Table perimeter path builder =====
// skip = 0: the ring corner skip is for CHASE patterns only (reference
// doc section 4). Seats must tile the table with no gaps, so every pixel
// is assigned. pathLen is therefore 764, not the chase-path 700.
skipStart = 0
skipEnd   = 0
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

// ===== Written by the controller =====
// Zone 0 is the GM; 1..7 are players, numbered CLOCKWISE from the GM
// (confirmed physically 2026-08-21). Arrays are 8 long so the maximum
// seating - GM plus seven - always fits without reallocation.
export var zoneH = array(8)
export var zoneS = array(8)
export var zoneV = array(8)

// Layout. gmStart/gmLen are in PATH coordinates, not LED index: the strip
// does not run in index order round the table, so a seat is one arc here
// but two or three separate index ranges on the physical strip.
export var gmStart = 497      // 38in section centred on the bottom edge
export var gmLen = 93         // 38in at 96 LEDs/m
export var playerCount = 0    // 0 until the controller says otherwise

// ===== Zone map =====
// Rebuilt only when the layout changes, not per frame. It is ~800 array
// writes; doing that every frame would cost more than the render itself.

zoneOf = array(pixelCount)
builtFor = -1                 // playerCount the current map was built for
builtStart = -1
builtLen = -1

buildZones() {
  remaining = pathLen - gmLen
  base = floor(remaining / playerCount)
  extra = remaining % playerCount
  // Where the run of longer zones ends, in positions past the GM's arc.
  // The first `extra` zones get one pixel more so the remainder is spread
  // instead of landing entirely on the last seat. This MUST match
  // warlock/zones.py exactly or seat boundaries drift between the two.
  bigSpan = extra * (base + 1)

  for (i = 0; i < pixelCount; i++) {
    p = pathPos[i]
    if (p < 0) {
      zoneOf[i] = -1
    } else {
      // Distance forward around the loop from the start of the GM's arc.
      d = (p - gmStart + pathLen) % pathLen
      if (d < gmLen) {
        zoneOf[i] = 0
      } else {
        r = d - gmLen
        if (r < bigSpan) {
          zoneOf[i] = 1 + floor(r / (base + 1))
        } else {
          zoneOf[i] = 1 + extra + floor((r - bigSpan) / base)
        }
      }
    }
  }

  builtFor = playerCount
  builtStart = gmStart
  builtLen = gmLen
}

export function beforeRender(delta) {
  // Watch for the controller changing the layout underneath us. Comparing
  // all three matters: changing only the player count while the GM's arc
  // stayed put is the common case, but a re-measured GM section must also
  // take effect without a pattern reload.
  if (playerCount >= 1 &&
      (playerCount != builtFor || gmStart != builtStart || gmLen != builtLen)) {
    buildZones()
  }
}

export function render(index) {
  if (playerCount < 1) {
    // Not configured yet. Show the idle purple rather than going dark - a
    // black table is indistinguishable from a dead one, which is the whole
    // argument in plan doc 5.1 for the table having a resting glow at all.
    hsv(0.78, 0.80, 0.06)
    return
  }

  z = zoneOf[index]
  if (z < 0 || z > playerCount) {
    rgb(0, 0, 0)
    return
  }
  hsv(zoneH[z], zoneS[z], zoneV[z])
}
