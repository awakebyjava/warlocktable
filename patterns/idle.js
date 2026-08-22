// Idle -- the table at rest. Warlock eyes in the dark.
//
// HAND-WRITTEN, not from tools/patterngen.py. The generator's vocabulary
// makes good ambient fields, but idle is the state the table sits in for
// most of its life -- longer than any scene -- so it earns some shape of
// its own. It is also the first thing anyone sees.
//
// The look: a deep blue-violet so dark it reads as almost-black, the
// colour of an unlit eye. Slow eyes open across the ring into a bright
// neon violet and fade back down. Every twenty seconds or so a surge
// sweeps the whole loop, as though something noticed you.
//
// Geometry is the standard closed-loop path map (see
// warlock-table-led-reference.md): the strip does NOT run in index order
// around the table, so everything spatial works in path space.

segStart = [ 60, 502,  0, 705, 180, 240, 120, 443]
segLen   = [ 60, 203, 60,  59,  60, 203,  60,  59]
pathPos = array(pixelCount)
for (i = 0; i < pixelCount; i++) pathPos[i] = -1
pathLen = 0
for (s = 0; s < 8; s++) {
  for (k = 0; k < segLen[s]; k++) {
    idx = segStart[s] + k
    if (idx < pixelCount) { pathPos[idx] = pathLen; pathLen = pathLen + 1 }
  }
}

// --- palette ---------------------------------------------------------
// Neon is not simply "bright purple": it is bright AND less saturated.
// Holding saturation at 1.0 through the peak gives a dense grape colour
// that reads as dark even at full value. Letting it fall to ~0.68 is
// what makes the peak look lit from inside rather than merely loud.
H_DEEP = 0.735      // blue-violet, unlit
H_NEON = 0.800      // hot violet, leaning magenta
S_DEEP = 1.00
S_NEON = 0.68
V_DEEP = 0.022      // barely alight -- the ring is never truly black
V_NEON = 1.00

// --- base shimmer -----------------------------------------------------
// WHOLE coprime frequencies. This is a closed loop: a non-integer
// frequency does not join up with itself and puts a visible seam at the
// ring split. Coprime (2 and 5) so the two waves do not re-align into an
// obvious repeat.
wf1 = 2
wf2 = 5
ws1 = 0.42          // time() is in units of 65.536s, so ~28s
ws2 = 0.55          // ~36s -- slow enough to feel like weather

// --- eyes -------------------------------------------------------------
EYES = 6
EYE_WIDE = 26       // ~27cm at 96 LEDs/m
EYE_MIN = 7
EYE_VAR = 9
eyePos  = array(EYES)
eyeAge  = array(EYES)
eyeLife = array(EYES)
eyeGain = array(EYES)
eyeAmp  = array(EYES)   // this frame's brightness -- see beforeRender
for (i = 0; i < EYES; i++) {
  eyePos[i]  = random(pathLen)
  eyeLife[i] = EYE_MIN + random(EYE_VAR)
  eyeAge[i]  = random(eyeLife[i])   // stagger, or all six blink together
  eyeGain[i] = 0.55 + random(0.45)
}

// --- surge ------------------------------------------------------------
SURGE_SPEED = 260   // path pixels/sec -- ~3s for a lap of the table
SURGE_WIDE  = 90
surgePos  = 0
surgeAmp  = 0
surgeWait = 6 + random(10)

t1 = 0
t2 = 0
breath = 0

export function beforeRender(delta) {
  dt = delta / 1000
  t1 = time(ws1)
  t2 = time(ws2)
  breath = 0.55 + 0.45 * wave(time(0.15))

  // Each eye's brightness is a PER-EYE value, so it is computed once here
  // rather than once per pixel. Doing it in render meant six triangle()
  // calls and six divisions for all 764 pixels -- 4,584 evaluations a
  // frame to produce six numbers, which held this pattern at about 10fps.
  for (i = 0; i < EYES; i++) {
    eyeAge[i] = eyeAge[i] + dt
    if (eyeAge[i] >= eyeLife[i]) {
      eyeAge[i] = 0
      eyeLife[i] = EYE_MIN + random(EYE_VAR)
      eyePos[i] = random(pathLen)
      eyeGain[i] = 0.55 + random(0.45)
    }
    e = triangle(eyeAge[i] / eyeLife[i])
    eyeAmp[i] = e * e * eyeGain[i]
  }

  if (surgeAmp > 0.002) {
    surgePos = surgePos + SURGE_SPEED * dt
    if (surgePos > pathLen) surgePos = surgePos - pathLen
    // Decay scaled by dt, not per-frame: a frame-rate-dependent fade
    // would run at a different speed whenever the pattern count or
    // pixel count changed the render budget.
    surgeAmp = surgeAmp - surgeAmp * 1.8 * dt
    if (surgeAmp < 0) surgeAmp = 0
  } else {
    surgeAmp = 0
    surgeWait = surgeWait - dt
    if (surgeWait <= 0) {
      surgeWait = 14 + random(22)
      surgePos = random(pathLen)
      surgeAmp = 1
    }
  }
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }
  u = p / pathLen

  // Base: cubed so the mid-tones are crushed and the ring stays dark.
  // Without this the whole table sits at a flat dim lilac and the eyes
  // have nothing to emerge from.
  base = wave(u * wf1 + t1) * 0.6 + wave(u * wf2 - t2) * 0.4
  base = base * base * base
  f = base * 0.30 * breath

  for (j = 0; j < EYES; j++) {
    if (eyeAmp[j] > 0) {
      d = p - eyePos[j]
      d = d - pathLen * floor(d / pathLen + 0.5)   // seam-correct wrap
      d = abs(d)
      if (d < EYE_WIDE) {
        fall = 1 - d / EYE_WIDE
        f = f + fall * fall * eyeAmp[j]
      }
    }
  }

  if (surgeAmp > 0.002) {
    d = p - surgePos
    d = d - pathLen * floor(d / pathLen + 0.5)
    d = abs(d)
    if (d < SURGE_WIDE) {
      fall = 1 - d / SURGE_WIDE
      f = f + fall * fall * surgeAmp * 0.9
    }
  }

  if (f > 1) f = 1

  hue = H_DEEP + (H_NEON - H_DEEP) * f
  sat = S_DEEP + (S_NEON - S_DEEP) * f
  // Value squared: pushes the floor down hard so "dull" really is dull,
  // while the peaks still reach full neon.
  val = V_DEEP + (V_NEON - V_DEEP) * f * f
  hsv(hue, sat, val)
}
