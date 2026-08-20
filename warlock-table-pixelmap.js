// ============================================================
// Warlock Table - Pixelblaze Pixel Map  (paste into Mapper tab)
// ============================================================
// Matches the verified physical layout. See
// warlock-table-led-reference.md for full details.
//
// Total: 764 pixels
//   ch0 (idx   0- 59): TR ring   (top-right corner)
//   ch1 (idx  60-119): TL ring   (top-left corner)
//   ch2 (idx 120-179): BL ring   (bottom-left corner)
//   ch3 (idx 180-239): BR ring   (bottom-right corner)
//   ch4 (idx 240-501): 262 = Bottom(203) + Left(59)   [see note]
//   ch5 (idx 502-763): 262 = Top(203) + Right(59)      [see note]
//
// NOTE on ch4/ch5 sub-run order: the edges inside each combined
// channel sit in the SWAPPED position vs. the naive assumption.
// This map places each edge run at its TRUE physical location,
// consistent with segStart = [60,502,0,705,180,240,120,443]
// used in the pattern code.
//
// Ring<->channel corner mapping (verified):
//   TR ring = ch0 (idx 0)     TL ring = ch1 (idx 60)
//   BL ring = ch2 (idx 120)   BR ring = ch3 (idx 180)
//
// Set Mapper scaling to "Contain" so the rectangle isn't squashed.
// ============================================================

function (pixelCount) {
  var LONG = 203;   // top & bottom edge LED counts
  var SHORT = 59;   // left & right edge LED counts
  var RING = 60;    // LEDs per corner ring
  var ringR = 8;    // ring radius in map units (cosmetic)

  // Rectangle corner coordinates (map units).
  // Width chosen ~ LONG, height ~ SHORT so proportions echo the table.
  var W = LONG;
  var H = 120;      // visual height; kept > SHORT so rings read cleanly

  var TL = [0, 0];
  var TR = [W, 0];
  var BR = [W, H];
  var BL = [0, H];

  var map = [];

  // ---- helpers ----
  function ringPts(center, count) {
    // clockwise ring, starting angle arbitrary
    var pts = [];
    var i;
    for (i = 0; i < count; i++) {
      var a = (i / count) * Math.PI * 2;
      pts.push([center[0] + ringR * Math.cos(a),
                center[1] + ringR * Math.sin(a)]);
    }
    return pts;
  }
  function linePts(from, to, count) {
    var pts = [];
    var i;
    for (i = 0; i < count; i++) {
      var t = count > 1 ? i / (count - 1) : 0;
      pts.push([from[0] + (to[0] - from[0]) * t,
                from[1] + (to[1] - from[1]) * t]);
    }
    return pts;
  }

  // ---- channels 0-3: corner rings (in channel index order) ----
  var ch0 = ringPts(TR, RING);  // idx   0- 59  TR
  var ch1 = ringPts(TL, RING);  // idx  60-119  TL
  var ch2 = ringPts(BL, RING);  // idx 120-179  BL
  var ch3 = ringPts(BR, RING);  // idx 180-239  BR

  // ---- channel 4: idx 240-501 = Bottom(203) then Left(59) ----
  // Bottom edge runs BL -> BR direction? Physical order places the
  // first 203 of ch4 on the BOTTOM edge, last 59 on the LEFT edge.
  var ch4a = linePts(BL, BR, LONG);   // bottom, 203
  var ch4b = linePts(BL, TL, SHORT);  // left, 59
  var ch4 = ch4a.concat(ch4b);

  // ---- channel 5: idx 502-763 = Top(203) then Right(59) ----
  var ch5a = linePts(TL, TR, LONG);   // top, 203
  var ch5b = linePts(TR, BR, SHORT);  // right, 59
  var ch5 = ch5a.concat(ch5b);

  // assemble in channel index order (0..5) to match pixel indices
  map = ch0.concat(ch1).concat(ch2).concat(ch3).concat(ch4).concat(ch5);

  return map;
}
