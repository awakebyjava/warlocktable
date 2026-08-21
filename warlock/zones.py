"""Seating zones around the table perimeter (plan doc 4.7).

The table seats a GM plus 1-7 players, and the zone layout changes with how
many people are actually playing. So zones are COMPUTED, not configured:
give it a player count and it divides the perimeter.

TWO FIXED FACTS

1. **The GM's section never moves.** It is the stretch of the bottom edge in
   front of the television, 38 inches long -- 93 LEDs at this strip's
   96/m -- centred on the TV. That is the GM's seat at any player count.

2. **Everyone else shares what is left.** The remaining perimeter -- the rest
   of the bottom edge, both ends, the whole top edge, and all four corner
   rings -- divides into equal arcs, one per player.

Corner rings are included in player zones here, unlike an earlier
fixed-six-seat sketch that held them back. With a variable player count the
seats no longer line up with the physical edges, so a zone boundary lands
wherever the arithmetic puts it; excluding the corners would leave 240 dark
pixels between seats and make four-player and six-player layouts look
broken rather than deliberate.

WORKING IN PATH SPACE

Everything is computed over the *physical loop*, not raw LED index. The
strip does not run in index order round the table -- see the segStart
ordering in `warlock-table-led-reference.md`, which was established by
lighting each segment a different colour and reading the table. Dividing raw
indices would produce zones that are contiguous in memory and scattered in
space.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Physical loop order, from warlock-table-led-reference.md. Verified on the
# table; do not "tidy" these numbers.
SEGMENTS: List[Tuple[str, int, int]] = [
    ("TL ring",      60, 60),
    ("Top edge",    502, 203),
    ("TR ring",       0, 60),
    ("Right edge",  705, 59),
    ("BR ring",     180, 60),
    ("Bottom edge", 240, 203),
    ("BL ring",     120, 60),
    ("Left edge",   443, 59),
]

PIXEL_COUNT = 764
GM_ZONE = 0                 # zone id reserved for the GM
MAX_PLAYERS = 7

# A corner ring is a physical circle of 60 LEDs. A seat boundary can land
# inside one, which is fine when it cuts the ring into two real arcs -- but
# a boundary a few pixels from the ring's edge leaves a SLIVER: three or four
# stray pixels in a neighbouring seat's colour, which reads as a wiring fault
# rather than a seat boundary. Observed on the table at six players, where
# the slivers were 3, 4, 10 and 11 pixels (2026-08-21).
#
# A quarter of a ring is the line between "an arc" and "stray pixels". Below
# it the boundary is pushed to the nearer edge and the ring stays whole.
RING_LEN = 60
MIN_RING_FRAGMENT = RING_LEN // 4

# Strip density, confirmed 2026-08-21. Everything that converts a physical
# measurement into a pixel count goes through this.
DENSITY_PER_M = 96.0
MM_PER_INCH = 25.4

# The GM's section is the visible width of the television, measured across
# the tabletop: 38 inches. The TV is recessed, so this is the visible area
# and not the panel's nominal size.
GM_INCHES = 38.0


def leds_for_inches(inches: float) -> int:
    """Physical length -> pixel count. Rounded to the nearest whole LED."""
    return int(round(inches * MM_PER_INCH / 1000.0 * DENSITY_PER_M))


GM_LEDS = leds_for_inches(GM_INCHES)        # 93


def build_path() -> List[int]:
    """Path position -> LED index, walking the perimeter in physical order."""
    path: List[int] = []
    for _name, start, count in SEGMENTS:
        path.extend(range(start, start + count))
    return path


def _segment_span(name: str) -> Tuple[int, int]:
    """Where a named segment sits in PATH coordinates."""
    pos = 0
    for seg_name, _start, count in SEGMENTS:
        if seg_name == name:
            return pos, count
        pos += count
    raise KeyError(name)


def gm_span(gm_leds: int = GM_LEDS) -> Tuple[int, int]:
    """The GM's arc in path coordinates: (start position, length).

    Centred on the bottom edge, because that is where the television is and
    the GM sits in front of it.
    """
    bottom_start, bottom_len = _segment_span("Bottom edge")
    gm_leds = max(1, min(int(gm_leds), bottom_len))
    offset = (bottom_len - gm_leds) // 2
    return bottom_start + offset, gm_leds


def _ring_spans() -> List[Tuple[int, int]]:
    """Corner rings as (start, end) in PATH coordinates, end exclusive."""
    out: List[Tuple[int, int]] = []
    pos = 0
    for name, _start, count in SEGMENTS:
        if "ring" in name:
            out.append((pos, pos + count))
        pos += count
    return out


def _snap_out_of_sliver(position: int) -> int:
    """Move a boundary off a ring's edge if it would leave stray pixels.

    Only slivers move. A boundary near the middle of a ring is left alone:
    splitting a ring into two substantial arcs looks deliberate, and forcing
    every ring to stay whole would cost far more in seat evenness than it
    buys -- at seven players it would drag one seat down to 55 pixels
    against another's 117.
    """
    for start, end in _ring_spans():
        if not start < position < end:
            continue
        if position - start < MIN_RING_FRAGMENT:
            return start
        if end - position < MIN_RING_FRAGMENT:
            return end
        break
    return position


def boundaries(players: int, gm_leds: int = GM_LEDS) -> List[int]:
    """Offsets past the end of the GM's arc where each player's seat ends.

    Returned in path space, measured from the first pixel after the GM, so
    the last entry is always the full remaining perimeter.
    """
    _gm_start, gm_len = gm_span(gm_leds)
    remaining = PIXEL_COUNT - gm_len
    base, extra = divmod(remaining, players)

    gm_end = (_gm_start + gm_len) % PIXEL_COUNT
    cuts: List[int] = []
    running = 0
    for index in range(players - 1):
        running += base + (1 if index < extra else 0)
        snapped = _snap_out_of_sliver((gm_end + running) % PIXEL_COUNT)
        cuts.append((snapped - gm_end) % PIXEL_COUNT)
    cuts.append(remaining)
    return cuts


def assign(players: int, gm_leds: int = GM_LEDS) -> List[int]:
    """-> zone id per LED index. 0 = GM, 1..players = seats, -1 = unassigned.

    Players are numbered around the loop starting immediately after the GM's
    section, so player 1 is on one side of the GM and player N on the other.
    Which side is which depends on strip direction and wants confirming on
    the table (see plan doc 4.7).
    """
    if not 1 <= players <= MAX_PLAYERS:
        raise ValueError("players must be 1..%d" % MAX_PLAYERS)

    path = build_path()
    total = len(path)
    gm_start, gm_len = gm_span(gm_leds)

    zone_of = [-1] * PIXEL_COUNT
    for k in range(gm_len):
        zone_of[path[(gm_start + k) % total]] = GM_ZONE

    # Seats are cut at the offsets boundaries() chose. The remainder is
    # spread one pixel at a time across the first few seats rather than
    # dumped on the last, and any cut that would strand a sliver of a corner
    # ring has already been nudged off it.
    gm_end = gm_start + gm_len
    previous = 0
    for index, cut in enumerate(boundaries(players, gm_leds)):
        for offset in range(previous, cut):
            zone_of[path[(gm_end + offset) % total]] = index + 1
        previous = cut

    return zone_of


def summarise(players: int, gm_leds: int = GM_LEDS) -> List[Dict[str, object]]:
    """Human-readable zone table: contiguous LED runs per zone."""
    zone_of = assign(players, gm_leds)
    path = build_path()

    # Walk the path so runs come out in physical order, not index order.
    runs: Dict[int, List[List[int]]] = {}
    prev_zone: Optional[int] = None
    prev_led: Optional[int] = None
    for led in path:
        z = zone_of[led]
        if z == -1:
            prev_zone = prev_led = None
            continue
        # A run breaks on a zone change AND on a jump in LED index -- a zone
        # that crosses a segment boundary is one arc physically but two
        # separate ranges in the strip, and reporting it as one range would
        # describe LEDs that are nowhere near it.
        contiguous = prev_led is not None and led == prev_led + 1
        if z != prev_zone or not contiguous or not runs.get(z):
            runs.setdefault(z, []).append([led, led])
        else:
            runs[z][-1][1] = led
        prev_zone, prev_led = z, led

    out = []
    for z in sorted(runs):
        spans = runs[z]
        count = sum(1 for led in range(PIXEL_COUNT) if zone_of[led] == z)
        out.append({
            "zone": z,
            "label": "GM" if z == GM_ZONE else "Player %d" % z,
            "leds": count,
            "runs": [(a, b) for a, b in spans],
        })
    return out


# ---------------------------------------------------------------- colours

# Seat colours, as hue/saturation on the Pixelblaze's 0..1 scale.
#
# Deliberately a rainbow rather than the project's brass/purple identity:
# these exist to be told apart by a player pointing at the table in a dim
# room, so maximum separation beats house style.
#
# ORANGE IS NOT A SEAT COLOUR. It stays in this table so an existing config
# or an explicit set_zone() call still resolves, but it is out of the seat
# rotation: on the real table orange and yellow were indistinguishable
# (confirmed 2026-08-21). The underlying fault was not that one pair looked
# alike, it was that red/orange/yellow crowded three of seven seats into 13%
# of the hue wheel while yellow->green sat empty. Dropping the MIDDLE term
# separates both its neighbours at once -- worst-case gap 0.06 -> 0.12.
# Dropping yellow instead barely helps (0.07), because red and orange then
# become the confusable pair.
COLOUR_HSV: Dict[str, Tuple[float, float]] = {   # name -> (hue, saturation)
    "red":     (0.00, 1.0),
    "orange":  (0.07, 1.0),
    "yellow":  (0.13, 1.0),
    "green":   (0.33, 1.0),
    "cyan":    (0.50, 1.0),
    "blue":    (0.62, 1.0),
    "purple":  (0.75, 1.0),   # 0.75, not the idle breathing 0.78: it sits
                              # midway between blue and magenta there
    "magenta": (0.88, 1.0),
    "pink":    (0.94, 0.6),
    "white":   (0.00, 0.0),
}

# The GM is white: unsaturated, so it cannot be confused with any seat
# colour however the player palette is later reshuffled.
GM_COLOUR = "white"

# Default seat colours in zone order, matching the ids in config.zones.
# Seven hues, spaced so the closest pair is 0.12 apart on the wheel.
SEAT_COLOURS: List[str] = [
    "red", "yellow", "green", "cyan", "blue", "purple", "magenta",
]

# Brightness for seat display. The device's persisted brightness limit is
# the power safety mechanism and is not touched from here; this is scene
# content sitting underneath it, kept moderate because seat claiming runs
# with the room lights up and does not need to be blinding.
SEAT_VALUE = 0.6

# Every seat colour is fully saturated on purpose. On RGBW, dropping
# saturation pulls in the white channel and washes the hue toward a pastel
# grey -- which is precisely how two neighbouring seats stop being telling
# apart. Same reasoning as the sat note in patterns/breathing.js.


def hsv_for(colour: str, value: float = SEAT_VALUE) -> Tuple[float, float, float]:
    """Colour name -> (hue, saturation, value). Unknown names go white."""
    hue, sat = COLOUR_HSV.get(colour.lower().strip(), COLOUR_HSV["white"])
    return hue, sat, max(0.0, min(1.0, float(value)))


def seat_colour(zone: int) -> str:
    """Default colour for a zone id. 0 is the GM; players wrap the palette."""
    if zone == GM_ZONE:
        return GM_COLOUR
    return SEAT_COLOURS[(zone - 1) % len(SEAT_COLOURS)]


def layout(players: int, gm_leds: int = GM_LEDS,
           colours: Optional[Dict[int, str]] = None) -> List[Dict[str, object]]:
    """The full zone description a UI or API would render.

    Each entry carries the zone's id, label, colour and LED runs. `colours`
    overrides the defaults per zone id, so a claimed seat keeps the colour
    the player picked.
    """
    colours = colours or {}
    rows = summarise(players, gm_leds)
    for row in rows:
        z = int(row["zone"])
        row["colour"] = colours.get(z, seat_colour(z))
        row["inches"] = round(int(row["leds"]) / DENSITY_PER_M * 39.3701, 1)
    return rows


# ------------------------------------------------- agreement with the pattern

# The Pixelblaze pattern derives the map on-device from three scalars rather
# than being sent a 764-entry array on every change. That is the right
# trade -- one websocket message instead of a large one, many times a
# session -- but it means the division exists TWICE, here and in
# patterns/zones.js.
#
# If the two ever drift, the symptom is a seat boundary in the wrong place
# on a real table, noticed by a confused player mid-session. So the pattern's
# arithmetic is reimplemented below and compared against this module's, and
# Table Check runs it before every session. It is pure arithmetic: no device,
# no network, microseconds.
#
# If you change the division rule in either file, change it in BOTH and let
# this fail if you got it wrong.

PATTERN_PATH = "patterns/zones.js"

# _as_pattern_computes() below is a TRANSLITERATION of the pattern, not the
# pattern itself -- so editing one and not the other makes verify() compare
# this module against a stale copy of itself and cheerfully pass. That very
# nearly shipped. The pattern carries this marker in a comment; verify()
# refuses to vouch for a file that does not, which turns a silent false pass
# into a loud failure.
PATTERN_ALGO = "sliver-snap-v2"


def _as_pattern_computes(players: int, gm_start: int, gm_len: int) -> List[int]:
    """buildZones() from patterns/zones.js, transliterated."""
    path = build_path()
    path_len = len(path)
    path_pos = [-1] * PIXEL_COUNT
    for position, led in enumerate(path):
        path_pos[led] = position

    remaining = path_len - gm_len
    base = remaining // players
    extra = remaining % players

    gm_end = (gm_start + gm_len) % path_len
    cuts = []
    running = 0
    for k in range(players - 1):
        running += base + (1 if k < extra else 0)
        cuts.append((_snap_out_of_sliver((gm_end + running) % path_len)
                     - gm_end) % path_len)
    cuts.append(remaining)

    zone_of = [-1] * PIXEL_COUNT
    for i in range(PIXEL_COUNT):
        pos = path_pos[i]
        if pos < 0:
            continue
        d = (pos - gm_start + path_len) % path_len
        if d < gm_len:
            zone_of[i] = GM_ZONE
            continue
        r = d - gm_len
        # Count how many cuts we are past. No `break`: the pattern language
        # is a subset of JavaScript and this loop is transliterated from it.
        zone = 1
        for k in range(players - 1):
            if r >= cuts[k]:
                zone = k + 2
        zone_of[i] = zone
    return zone_of


def _check_pattern_marker() -> List[str]:
    """Confirm the pattern on disk implements the algorithm we transliterated.

    Cheap, and the only thing standing between "verify() passes" and
    "verify() compared this file to a copy of itself".
    """
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    pattern = os.path.join(os.path.dirname(here), *PATTERN_PATH.split("/"))
    if not os.path.exists(pattern):
        return ["%s is missing" % PATTERN_PATH]
    try:
        with open(pattern, encoding="utf-8") as fh:
            source = fh.read()
    except OSError as exc:
        return ["%s could not be read: %s" % (PATTERN_PATH, exc)]
    if ("ALGO: " + PATTERN_ALGO) not in source:
        return ["%s does not declare 'ALGO: %s' -- it is a different "
                "algorithm from the one checked here" % (PATTERN_PATH,
                                                         PATTERN_ALGO)]
    return []


def verify(gm_leds: int = GM_LEDS) -> List[str]:
    """-> list of problems, empty when everything agrees.

    Checks the invariants the whole zone model rests on, plus agreement
    with the on-device pattern.
    """
    problems: List[str] = []
    path = build_path()

    problems.extend(_check_pattern_marker())

    if sorted(path) != list(range(PIXEL_COUNT)):
        problems.append("perimeter path does not cover all %d LEDs exactly once"
                        % PIXEL_COUNT)
        return problems      # nothing below is meaningful if this is wrong

    pos_of = {led: i for i, led in enumerate(path)}
    gm_start, gm_len = gm_span(gm_leds)

    for n in range(1, MAX_PLAYERS + 1):
        zone_of = assign(n, gm_leds)

        if -1 in zone_of:
            problems.append("%d players: %d LEDs belong to no zone"
                            % (n, zone_of.count(-1)))

        # Seats are even to within a pixel UNLESS a boundary was nudged off
        # a ring to avoid stranding a sliver. Each nudge moves a boundary by
        # less than MIN_RING_FRAGMENT, and a seat has a boundary at each end
        # which can move in opposite directions -- so twice that, plus the
        # one-pixel remainder, is the most a seat can legitimately differ.
        allowed = 2 * MIN_RING_FRAGMENT + 1
        sizes = [zone_of.count(z) for z in range(1, n + 1)]
        if sizes and max(sizes) - min(sizes) > allowed:
            problems.append("%d players: seats differ by %d LEDs (max %d)"
                            % (n, max(sizes) - min(sizes), allowed))

        # The whole point of the nudging: no stray fragments of a ring.
        for start, end in _ring_spans():
            owners = {zone_of[path[q % PIXEL_COUNT]]
                      for q in range(start, end)}
            if len(owners) < 2:
                continue
            runs = []
            run_owner, run_len = None, 0
            for q in range(start, end):
                owner = zone_of[path[q % PIXEL_COUNT]]
                if owner != run_owner:
                    if run_owner is not None:
                        runs.append(run_len)
                    run_owner, run_len = owner, 0
                run_len += 1
            runs.append(run_len)
            if min(runs) < MIN_RING_FRAGMENT:
                problems.append(
                    "%d players: a corner ring is split %s -- fragments "
                    "under %d pixels read as stray LEDs"
                    % (n, "/".join(str(r) for r in runs), MIN_RING_FRAGMENT))

        # Every zone must be ONE arc round the table. A zone in two pieces
        # would light two separate stretches for one player.
        for z in range(0, n + 1):
            ps = sorted(pos_of[i] for i, v in enumerate(zone_of) if v == z)
            breaks = sum(1 for a, b in zip(ps, ps[1:]) if b != a + 1)
            if breaks > 1:          # 1 is the wrap past position 0
                problems.append("%d players: zone %d is in %d pieces"
                                % (n, z, breaks + 1))

        if zone_of != _as_pattern_computes(n, gm_start, gm_len):
            problems.append("%d players: %s computes a different map"
                            % (n, PATTERN_PATH))

    return problems


if __name__ == "__main__":  # python -m warlock.zones [players] [gm_leds]
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        issues = verify()
        for line in issues:
            print("  FAIL " + line)
        print("%s: %d problems" % (PATTERN_PATH, len(issues))
              if issues else "zone model consistent, and agrees with %s"
              % PATTERN_PATH)
        raise SystemExit(1 if issues else 0)

    players = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    gm_leds = int(sys.argv[2]) if len(sys.argv) > 2 else GM_LEDS
    print("%d players, GM = %d LEDs (%.0f in)"
          % (players, gm_leds, gm_leds / DENSITY_PER_M * 39.3701))
    for row in layout(players, gm_leds):
        runs = " | ".join("%d-%d" % (a, b) for a, b in row["runs"])
        print("  %-9s %-8s %3d px %5.1f in  %s"
              % (row["label"], row["colour"], row["leds"], row["inches"], runs))
