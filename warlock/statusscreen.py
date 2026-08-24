"""The TV status screen (plan doc 5.1) — rendered to the table's own screen.

WHY THIS EXISTS

A table that boots to a blank screen looks identical whether the controller
crashed, the Pixelblaze lost power, or HDMI negotiated badly. All three
happened during this build. The iPad panel answers the question, but only if
you have it, it is charged, and it is on the right network — which is a lot
of ifs at the moment you most need an answer.

The TV is already there and already driven by the Pi. This makes it say what
is wrong.

HOW IT FITS

Rendered to a PNG and shown through the same feh instance as the artwork, so
there is exactly one thing drawing on the screen. Making the status screen
"just another background" avoids two viewers fighting over the display.

STYLE

Follows warlock-table-style-guide.html: black field, brass for structure,
purple for what is currently alive, bone for sparse text, sharp 2px corners,
the circular sigil frame reused as the status mark.

One documented substitution: the guide specifies Syne for display type, which
is not packaged for Debian. IBM Plex Sans Bold stands in. Everything else
(Plex Sans, Plex Mono) is exact.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

# --- style guide tokens (warlock-table-style-guide.html §I) ---
BLACK       = (0x0b, 0x0a, 0x08)
BLACK_2     = (0x15, 0x13, 0x10)
BRASS       = (0xc9, 0xa1, 0x5a)
BRASS_BRIGHT= (0xe0, 0xbe, 0x80)
BRASS_DIM   = (0x6e, 0x5a, 0x35)
PURPLE      = (0x8a, 0x5c, 0xc9)
PURPLE_DEEP = (0x3c, 0x2a, 0x5c)
BONE        = (0xea, 0xe4, 0xd6)
BONE_MID    = (0xa8, 0x9f, 0x8c)
BONE_DIM    = (0x9c, 0x95, 0x87)
LINE        = (0x3a, 0x33, 0x27)
BAD         = (0xc9, 0x5a, 0x5a)   # not in the guide; a failure needs to read

# Bundled with the panel, so the TV and the iPad use identical type rather
# than the TV falling back to whatever apt happened to install.
BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "web", "static", "fonts")
DISPLAY_FONT = os.path.join(BUNDLED, "Syne.ttf")
BODY_FONT    = os.path.join(BUNDLED, "IBMPlexSans.ttf")
MONO_FONT    = os.path.join(BUNDLED, "IBMPlexMono-Regular.ttf")

# The table's own marks (plan doc 3.6). Two sigils are inlaid in the real
# tabletop, and the screen echoes them rather than inventing a third: the
# procedural "wheel" that used to sit here was a placeholder from before
# there was any artwork, and it never appeared on the physical table at all.
BRANDING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "branding")
HERO      = "warlock-hero-wordmark.png"
SIGIL_L   = "Goetia_seal_of_solomon.svg.webp"
SIGIL_R   = "3733_the-astaroth-sigil.png"

# apt-installed copies, if the bundled ones are somehow missing.
SYSTEM_DIR   = "/usr/share/fonts/truetype/ibm-plex"
FALLBACKS = {
    DISPLAY_FONT: os.path.join(SYSTEM_DIR, "IBMPlexSans-Bold.ttf"),
    BODY_FONT:    os.path.join(SYSTEM_DIR, "IBMPlexSans-Regular.ttf"),
    MONO_FONT:    os.path.join(SYSTEM_DIR, "IBMPlexMono-Regular.ttf"),
}
LAST_RESORT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path, size, weight=None):
    """Load a font, selecting a named instance for variable faces.

    Syne and IBM Plex Sans are shipped as VARIABLE fonts - one file holding
    a weight axis. Without set_variation_by_name() they render at their
    default (Regular), so a "bold" heading would come out the same weight as
    body text. PIL exposes the named instances, so ask for one by name.
    """
    from PIL import ImageFont
    for candidate in (path, FALLBACKS.get(path), LAST_RESORT):
        if not candidate:
            continue
        try:
            f = ImageFont.truetype(candidate, size)
        except OSError:
            continue
        if weight:
            try:
                f.set_variation_by_name(weight)
            except Exception:
                pass    # static font, or no such instance - keep the default
        return f
    return ImageFont.load_default()


def _asset(name):
    """Open a branding asset, or None. Never raises.

    A missing decoration must not be the reason the status screen fails to
    draw, because the status screen is what you look at WHEN things are
    failing.
    """
    from PIL import Image
    path = os.path.abspath(os.path.join(BRANDING_DIR, name))
    if not os.path.exists(path):
        return None
    try:
        return Image.open(path)
    except Exception:      # noqa: BLE001
        return None


def _ink(name, size, colour, opacity=1.0):
    """Load a black-line sigil and re-draw it in `colour` at `size`.

    THE SIGILS ARE BLACK INK AND THIS SCREEN IS A BLACK FIELD, so they are
    invisible pasted as-is. What matters is the SHAPE, which has to be
    recovered as a mask and repainted.

    The two files disagree about how they store that shape, and one formula
    covers both:

      Astaroth  black ink, transparent ground -> alpha alone is the shape
      Solomon   black ink, OPAQUE WHITE ground -> alpha says "all of it"

    So the mask is alpha AND darkness: opaque-and-dark is ink, opaque-and-
    pale is the white disc that should not be there, transparent is
    nothing. Multiplying the two handles either file without special-casing
    which is which -- and keeps working if one is later re-exported the
    other way round.
    """
    from PIL import Image, ImageChops
    src = _asset(name)
    if src is None:
        return None
    try:
        src = src.convert("RGBA").resize((size, size), Image.LANCZOS)
        alpha = src.getchannel("A")
        # 255 where the pixel is dark, 0 where it is pale.
        darkness = ImageChops.invert(src.convert("L"))
        mask = ImageChops.multiply(alpha, darkness)
        if opacity < 1.0:
            mask = mask.point(lambda v: int(v * opacity))
        layer = Image.new("RGBA", (size, size), colour + (0,))
        layer.putalpha(mask)
        return layer
    except Exception:      # noqa: BLE001
        return None


def _mark(draw, cx, cy, r, state):
    """Per-subsystem mark, style guide §III.

    Same circular frame for every mark - that shared frame IS the family.
    Brass ring = exists. Purple centre = active. Muted bone = unavailable.
    """
    w = max(2, r // 5)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                 outline=BRASS if state != "fail" else BRASS_DIM, width=w)
    inner = max(3, int(r * 0.32))
    if state == "ok":
        draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=PURPLE)
    elif state == "fail":
        # An X, so a failure is legible at a glance and without colour.
        d = int(r * 0.42)
        draw.line([cx - d, cy - d, cx + d, cy + d], fill=BAD, width=w)
        draw.line([cx + d, cy - d, cx - d, cy + d], fill=BAD, width=w)
    else:
        draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner],
                     outline=BONE_DIM, width=max(2, w // 2))


def _fit_text(draw, text: str, font, max_w: float) -> str:
    """Clip `text` to `max_w`, with an ellipsis if anything was cut.

    Subsystem detail strings used to be short by convention ("38 tracks").
    Once the cross-device integrity check can contribute a row too, a
    detail can legitimately be a sentence naming every missing asset -- and
    the QR now sits close enough that an unclipped one would run under it.
    """
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid] + ell, font=font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell


def _draw_qr(draw, data: str, x: int, y: int, side: int) -> bool:
    """Draw a QR for `data` as a `side`-wide square at (x, y).

    Returns False if segno is not installed rather than raising: a missing
    decoration must never be the reason the status screen fails to render,
    because the status screen is what you look at WHEN things are failing.
    The URL is printed in the footer regardless, so the information is
    never lost -- only the convenience.
    """
    try:
        import segno
    except ImportError:
        return False
    try:
        code = segno.make(data, error="m")
        rows = [list(r) for r in code.matrix]
    except Exception:      # noqa: BLE001 -- a bad URL must not kill the screen
        return False

    n = len(rows)
    if not n:
        return False

    # Integer module size, then centre the remainder. A non-integer module
    # leaves seams of background between cells that a camera reads as noise.
    quiet = 4
    mod = max(1, side // (n + quiet * 2))
    span = mod * n
    ox = x + (side - span) // 2
    oy = y + (side - span) // 2

    # White quiet zone, sized in whole modules. Without it, a code on a dark
    # background is effectively unscannable no matter how crisp it is.
    pad = mod * quiet
    draw.rectangle([ox - pad, oy - pad, ox + span + pad, oy + span + pad],
                   fill=(255, 255, 255))
    for r, row in enumerate(rows):
        cy = oy + r * mod
        for c, on in enumerate(row):
            if on:
                cx = ox + c * mod
                draw.rectangle([cx, cy, cx + mod - 1, cy + mod - 1],
                               fill=(0, 0, 0))
    return True


def render(path: str, report: Dict[str, Any], width: int = 3840,
           height: int = 2160, branding: Optional[str] = None) -> str:
    """Render the status screen to `path`. Returns the path.

    LAID OUT FOR A TABLE, NOT A MONITOR. People sit around all four sides
    of this screen, so the join code is drawn FOUR TIMES, once in each
    corner, and everyone has one within reach instead of the far side of
    the table leaning over a single large one. Four small codes beat one
    big one for the same reason four door handles beat one wide door.

    The centre is the hero wordmark, the verdict, and a single compact row
    of subsystem marks. The row used to be six stacked lines with a detail
    column each, which was most of the screen spent telling a healthy table
    it was healthy. Anything actually WRONG still gets a full line of its
    own, below -- so the screen is quiet when there is nothing to say and
    specific when there is.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), BLACK)
    draw = ImageDraw.Draw(img)

    s = width / 3840.0          # scale factor, so this works at any resolution

    def px(v):
        return int(v * s)

    # Faint radial warmth, echoing the guide's .bg-field. Kept very low:
    # this screen faces upward in a dim room for hours.
    for i in range(20):
        t = i / 20.0
        rad = int(px(1500) * (1 - t) + px(300))
        alpha = int(9 * (1 - t))
        if alpha <= 0:
            continue
        overlay = Image.new("RGB", (width, height), BLACK)
        od = ImageDraw.Draw(overlay)
        od.ellipse([width // 2 - rad, -px(400) - rad // 3,
                    width // 2 + rad, -px(400) + rad],
                   fill=(BRASS[0] // 9, BRASS[1] // 9, BRASS[2] // 11))
        img = Image.blend(img, overlay, alpha / 255.0 * 2.2)
    draw = ImageDraw.Draw(img)

    f_eyebrow = _font(MONO_FONT, px(28))
    f_title   = _font(DISPLAY_FONT, px(96), "ExtraBold")
    f_chip    = _font(BODY_FONT, px(30))
    f_problem = _font(BODY_FONT, px(32))
    f_problem_name = _font(DISPLAY_FONT, px(34), "Bold")
    f_qr      = _font(MONO_FONT, px(24))
    f_mono    = _font(MONO_FONT, px(26))

    overall = report.get("overall", "warn")

    # ---- the join code, in all four corners -------------------------------
    # The one thing on this screen everybody needs and nobody should have to
    # walk around the table for.
    join_url = report.get("join_url") or report.get("panel_url") or ""
    qr_side = px(300)
    qr_pad = px(96)
    corners = [
        (qr_pad, qr_pad),
        (width - qr_pad - qr_side, qr_pad),
        (qr_pad, height - qr_pad - qr_side),
        (width - qr_pad - qr_side, height - qr_pad - qr_side),
    ]
    if join_url:
        cap = "SCAN TO JOIN"
        cw = draw.textlength(cap, font=f_qr)
        for (qx, qy) in corners:
            if not _draw_qr(draw, join_url, qx, qy, qr_side):
                break
            # Caption outside the code, away from the nearest screen edge,
            # so it never crowds the quiet zone the scanner needs.
            top_half = qy < height // 2
            cy = (qy + qr_side + px(30)) if top_half else (qy - px(52))
            draw.text((qx + (qr_side - cw) / 2, cy), cap, font=f_qr, fill=BRASS)

    # The centre column has to clear the corner codes.
    inner_l = qr_pad + qr_side + px(90)
    inner_r = width - inner_l

    # ---- hero wordmark ----------------------------------------------------
    hero = None
    if branding and os.path.exists(branding):
        from PIL import Image as _I
        try:
            hero = _I.open(branding).convert("RGB")
        except Exception:      # noqa: BLE001
            hero = None
    if hero is None:
        hero_src = _asset(HERO)
        hero = hero_src.convert("RGB") if hero_src is not None else None

    if hero is not None:
        from PIL import ImageChops
        target_w = px(1180)
        ratio = target_w / hero.width
        hero = hero.resize((target_w, int(hero.height * ratio)), Image.LANCZOS)

    # MEASURE, THEN CENTRE. Anchoring to a fixed top left the bottom third
    # of the screen empty, which reads as unfinished rather than spacious --
    # and the amount of space involved changes with whether anything is
    # wrong, because problem rows only exist when there are problems.
    rows_pre: List[Dict[str, Any]] = report.get("rows", [])
    n_problems = min(PROBLEM_ROWS,
                     len([r for r in rows_pre
                          if r.get("name") not in COMPACT_ROWS
                          or r.get("state") != "ok"]))
    block_h = ((hero.height + px(60)) if hero is not None else px(340))
    block_h += px(52) + px(150) + px(70) + px(96)
    if n_problems:
        block_h += px(20) + px(64) * n_problems
    top = max(px(210), (height - block_h) // 2)

    if hero is not None:
        # Crush near-black to true black: the source carries compression
        # noise a shade lighter than the field, and ImageChops.lighter
        # faithfully keeps every one of those pixels, drawing a faint
        # rectangle around the artwork.
        hero = hero.point(lambda v: 0 if v < 26 else v)
        x0 = (width - hero.width) // 2
        box = (x0, top, x0 + hero.width, top + hero.height)
        img.paste(ImageChops.lighter(img.crop(box), hero), box)
        hero_mid = top + hero.height // 2
        top += hero.height + px(60)
    else:
        hero_mid = top + px(200)
        top += px(340)

    # ---- the table's two sigils, flanking the wordmark --------------------
    # The real tabletop has these two inlaid in it. They are watermarks
    # here, not furniture: dim brass, well outside the wordmark, and never
    # over anything that has to be read.
    sig_size = px(360)
    for name, sx in ((SIGIL_L, inner_l + px(40)),
                     (SIGIL_R, inner_r - px(40) - sig_size)):
        layer = _ink(name, sig_size, BRASS_DIM, opacity=0.55)
        if layer is not None:
            img.paste(layer, (int(sx), int(hero_mid - sig_size // 2)), layer)

    draw = ImageDraw.Draw(img)

    # ---- verdict ----------------------------------------------------------
    # Plain words about the table's readiness. The old headline announced
    # that "The Circle Holds", which is a mood rather than a status: it
    # told a GM glancing over nothing they could act on.
    headline = {"pass": "Prepared",
                "warn": "Assistance Needed",
                "fail": "Assistance Needed"}.get(overall, "Assistance Needed")
    accent = {"pass": PURPLE, "warn": BRASS_BRIGHT, "fail": BAD}[overall]

    eyebrow = "WARLOCK TABLE · SYSTEM STATUS"
    ew = draw.textlength(eyebrow, font=f_eyebrow)
    draw.text(((width - ew) / 2, top), eyebrow, font=f_eyebrow, fill=BRASS)
    top += px(52)

    tw = draw.textlength(headline, font=f_title)
    draw.text(((width - tw) / 2, top), headline, font=f_title, fill=accent)
    top += px(150)

    draw.line([inner_l, top, inner_r, top], fill=LINE, width=max(1, px(3)))
    top += px(70)

    # ---- subsystems, one compact row --------------------------------------
    rows: List[Dict[str, Any]] = report.get("rows", [])
    chips = [r for r in rows if r.get("name") in COMPACT_ROWS]
    problems = [r for r in rows
                if r.get("name") not in COMPACT_ROWS or r.get("state") != "ok"]

    if chips:
        mark_r = px(20)
        gap = px(34)
        widths = [mark_r * 2 + gap + draw.textlength(c.get("name", ""), font=f_chip)
                  for c in chips]
        spacing = px(70)
        total_w = sum(widths) + spacing * (len(chips) - 1)
        x = (width - total_w) / 2
        for c, w in zip(chips, widths):
            state = c.get("state", "warn")
            _mark(draw, int(x + mark_r), int(top + px(18)), mark_r, state)
            draw.text((x + mark_r * 2 + gap, top),
                      c.get("name", ""), font=f_chip,
                      fill=BONE if state == "ok" else
                           (BAD if state == "fail" else BRASS_BRIGHT))
            x += w + spacing
        top += px(96)

    # ---- and anything actually wrong, in full -----------------------------
    if problems:
        top += px(20)
        detail_x = inner_l + px(420)
        detail_max_w = inner_r - detail_x
        for r in problems[:PROBLEM_ROWS]:
            state = r.get("state", "warn")
            draw.text((inner_l, top), r.get("name", ""), font=f_problem_name,
                      fill=BAD if state == "fail" else BRASS_BRIGHT)
            detail = _fit_text(draw, r.get("detail", ""), f_problem, detail_max_w)
            draw.text((detail_x, top + px(6)), detail, font=f_problem,
                      fill=BONE_MID)
            top += px(64)
        extra = len(problems) - PROBLEM_ROWS
        if extra > 0:
            draw.text((inner_l, top), "+ %d more · see Settings → Table Check"
                      % extra, font=f_problem, fill=BONE_DIM)

    # ---- footer -----------------------------------------------------------
    # Between the bottom pair of codes, and small: useful to quote when
    # something is wrong, and of no interest at all the rest of the time.
    foot_y = height - px(150)
    left_text = report.get("join_url") or report.get("panel_url", "")
    right_text = "%s · %s" % (report.get("version", "?"),
                                    time.strftime("%H:%M"))
    draw.text((inner_l, foot_y), left_text, font=f_mono, fill=BRASS)
    rw = draw.textlength(right_text, font=f_mono)
    draw.text((inner_r - rw, foot_y), right_text, font=f_mono, fill=BONE_DIM)

    tmp = path + ".tmp"
    img.save(tmp, "PNG", optimize=False)
    os.replace(tmp, path)
    return path


# The six that get a compact chip in the centre row. Everything else on
# the report is, by definition, something that went wrong, and gets a full
# line to say what.
COMPACT_ROWS = ("Lights", "Audio", "Cards", "Screen", "Room", "Scene")
PROBLEM_ROWS = 5

# The categories tablecheck catches that no device probe below can:
# missing assets a scene REFERENCES rather than a device being unreachable.
# Config renaming a pattern and every device staying green is the exact
# failure this module's own docstring exists to prevent (see the top of
# tablecheck.py) -- so when one of these is not clean, the status screen
# needs to say so, not just report every device present and healthy.
_INTEGRITY_ROWS = {
    "Config", "Light patterns", "Audio tracks", "Backgrounds",
    "Zone model", "Seats", "Zone lighting", "Video output", "Disk space",
}
_INTEGRITY_ROW_CAP = 4


def build_report(rt, check: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Turn live device status into the rows the screen draws.

    `check` is a tablecheck.run_check() result, run separately because it
    is slower and does things (asset cross-referencing) a boot-time device
    probe does not. When supplied, its overall verdict is folded in and
    its non-passing integrity rows are appended -- capped, because a badly
    broken table could otherwise produce more rows than the screen has
    room for, and past a handful the fix is "open Settings", not "read a
    longer screen".
    """
    rows = []
    worst = "pass"

    def add(name, healthy, detail, absent=False):
        nonlocal worst
        if absent:
            state = "warn"
        else:
            state = "ok" if healthy else "fail"
        if state == "fail":
            worst = "fail"
        elif state == "warn" and worst == "pass":
            worst = "warn"
        rows.append({"name": name, "state": state, "detail": detail})

    probe = getattr(rt.lights, "status", None)
    if callable(probe):
        i = probe()
        if i.get("healthy"):
            pat = i.get("pattern")
            detail = ("%s · %s%%" % (pat, i.get("effective_pct", "?"))
                      if pat else "%s%% · awaiting scene"
                                  % i.get("effective_pct", "?"))
        else:
            detail = i.get("error") or "not connected"
        add("Lights", i.get("healthy"), detail)
    else:
        add("Lights", False, "simulated", absent=True)

    probe = getattr(rt.controller.audio, "status", None)
    if callable(probe):
        i = probe()
        add("Audio", i.get("healthy"),
            "%s tracks" % i.get("tracks") if i.get("healthy")
            else (i.get("error") or "unavailable"))
    else:
        add("Audio", False, "simulated", absent=True)

    probe = getattr(rt.controller, "_nfc_status", None)
    if callable(probe):
        i = probe()
        add("Cards", i.get("healthy"),
            "reader %s · %s taps" % (i.get("firmware"), i.get("taps", 0))
            if i.get("healthy") else (i.get("error") or "not detected"))
    else:
        add("Cards", False, "reader not enabled", absent=True)

    probe = getattr(rt.controller.display, "status", None)
    if callable(probe):
        i = probe()
        add("Screen", i.get("healthy"),
            "%s backgrounds" % i.get("images") if i.get("healthy")
            else (i.get("error") or "unavailable"))
    else:
        add("Screen", False, "simulated", absent=True)

    # Govee accent lighting (plan doc 3.13). Added 2026-08-24 -- the table
    # had been running this subsystem for a while before the status screen
    # said anything about it at all.
    probe = getattr(getattr(rt.controller, "govee", None), "status", None)
    if callable(probe):
        i = probe()
        if not i.get("configured"):
            add("Room", False, "no accent strips configured", absent=True)
        elif i.get("healthy"):
            detail = "%d strip%s" % (i.get("devices", 0),
                                     "" if i.get("devices") == 1 else "s")
            missing = i.get("missing") or []
            if missing:
                detail += " · %d configured but not found" % len(missing)
            add("Room", True, detail)
        else:
            add("Room", False, i.get("error") or "not connected")
    else:
        add("Room", False, "simulated", absent=True)

    scene = rt.controller.current_scene
    rows.append({"name": "Scene", "state": "ok" if scene else "warn",
                 "detail": scene.name if scene else "idle"})

    # Fold in whatever tablecheck found that a device probe structurally
    # cannot: every device above can be perfectly healthy while a scene
    # still points at a pattern, track or background that does not exist
    # (this module's own reason for being -- see its docstring). `check`
    # is None on any render that ran before the first startup check
    # finished, or if the check itself failed to run; the screen still
    # renders in that case, just without this extra information.
    if check:
        rank = {"pass": 0, "warn": 1, "fail": 2}
        if rank.get(check.get("overall", "pass"), 0) > rank.get(worst, 0):
            worst = check["overall"]

        integrity = [r for r in check.get("results", [])
                     if r["name"] in _INTEGRITY_ROWS and r["status"] != "pass"]
        for r in integrity[:_INTEGRITY_ROW_CAP]:
            rows.append({"name": r["name"], "state": r["status"],
                         "detail": r.get("detail", "")})
        extra = len(integrity) - _INTEGRITY_ROW_CAP
        if extra > 0:
            rows.append({"name": "+ %d more" % extra, "state": "warn",
                         "detail": "see Settings → Table Check"})

    version = "unknown"
    try:
        with open("/opt/warlocktable/VERSION", "r", encoding="utf-8") as fh:
            version = fh.readline().strip()
    except OSError:
        pass

    host = "raspberrypi.local"
    try:
        import socket
        host = socket.gethostname() + ".local"
    except Exception:
        pass

    # The QR gets a LAN IP, not the .local name. The web server can use the
    # client's own Host header because it is answering a request; this runs
    # at boot with nobody connected, so it has to choose. A .local name
    # needs mDNS, which iPhones resolve and a good number of Android phones
    # do not -- and a join code that works for half the table is worse than
    # useless, because the failure looks like the table being broken.
    #
    # The UDP connect picks whichever interface actually routes off-box
    # without sending anything, which beats guessing on a machine with both
    # wifi and ethernet.
    join_host = host
    try:
        import socket as _s
        probe_sock = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        try:
            probe_sock.connect(("10.255.255.255", 1))
            join_host = probe_sock.getsockname()[0]
        finally:
            probe_sock.close()
    except Exception:      # noqa: BLE001 -- fall back to the .local name
        pass

    return {
        "overall": worst,
        "rows": rows,
        "version": version,
        "panel_url": "http://%s:8080" % host,
        "join_url": "http://%s:8080/" % join_host,
    }
