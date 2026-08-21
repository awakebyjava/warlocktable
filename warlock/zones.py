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

    # Everything from the end of the GM's arc, round to its start.
    remaining = total - gm_len
    cursor = gm_start + gm_len

    # Distribute the remainder one pixel at a time across the first few
    # zones rather than letting the last zone absorb it -- with 7 players
    # that would otherwise make one seat visibly longer than the rest.
    base, extra = divmod(remaining, players)
    for p in range(players):
        length = base + (1 if p < extra else 0)
        for k in range(length):
            zone_of[path[(cursor + k) % total]] = p + 1
        cursor += length

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


if __name__ == "__main__":  # python -m warlock.zones [players] [gm_leds]
    import sys

    players = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    gm_leds = int(sys.argv[2]) if len(sys.argv) > 2 else GM_LEDS
    print("%d players, GM = %d LEDs" % (players, gm_leds))
    for row in summarise(players, gm_leds):
        runs = " | ".join("%d-%d" % (a, b) for a, b in row["runs"])
        print("  %-9s %3d px  %s" % (row["label"], row["leds"], runs))
