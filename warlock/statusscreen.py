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

FONT_DIR = "/usr/share/fonts/truetype/ibm-plex"
DISPLAY_FONT = os.path.join(FONT_DIR, "IBMPlexSans-Bold.ttf")     # Syne stand-in
BODY_FONT    = os.path.join(FONT_DIR, "IBMPlexSans-Regular.ttf")
MONO_FONT    = os.path.join(FONT_DIR, "IBMPlexMono-Regular.ttf")
FALLBACK     = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path, size):
    from PIL import ImageFont
    for candidate in (path, FALLBACK):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _sigil(draw, cx, cy, r, active=True):
    """The signature mark from the style guide §V.

    One geometric form reused with intention — the same ring that is the
    favicon and the 'currently speaking' frame. Brass rings for structure,
    purple cross for the live element.
    """
    accent = PURPLE if active else BONE_DIM
    w = max(2, r // 13)

    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=BRASS, width=w)
    r2 = int(r * 0.76)
    draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=BRASS, width=w)

    arm = int(r * 0.76)
    draw.line([cx, cy - arm, cx, cy + arm], fill=accent, width=w)
    draw.line([cx - arm, cy, cx + arm, cy], fill=accent, width=w)
    d = int(arm * 0.7)
    draw.line([cx - d, cy - d, cx + d, cy + d], fill=accent, width=w)
    draw.line([cx + d, cy - d, cx - d, cy + d], fill=accent, width=w)

    r3 = int(r * 0.37)
    draw.ellipse([cx - r3, cy - r3, cx + r3, cy + r3], outline=BRASS, width=w)

    dot = max(3, r // 20)
    for (px, py) in ((cx, cy - r), (cx, cy + r), (cx - r, cy), (cx + r, cy)):
        draw.ellipse([px - dot, py - dot, px + dot, py + dot], fill=BRASS)

    core = max(4, int(r * 0.12))
    draw.ellipse([cx - core, cy - core, cx + core, cy + core], fill=accent)


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


def render(path: str, report: Dict[str, Any], width: int = 3840,
           height: int = 2160, branding: Optional[str] = None) -> str:
    """Render the status screen to `path`. Returns the path."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), BLACK)
    draw = ImageDraw.Draw(img)

    s = width / 3840.0          # scale factor, so this works at any resolution

    def px(v):
        return int(v * s)

    # Faint radial warmth, echoing the guide's .bg-field. Kept very low:
    # this screen faces upward in a dim room for hours.
    for i in range(28):
        t = i / 28.0
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

    f_eyebrow = _font(MONO_FONT, px(30))
    f_title   = _font(DISPLAY_FONT, px(104))
    f_sub     = _font(BODY_FONT, px(36))
    f_row     = _font(DISPLAY_FONT, px(46))
    f_detail  = _font(BODY_FONT, px(30))
    f_mono    = _font(MONO_FONT, px(28))

    # ---- branding / sigil -------------------------------------------------
    top = px(150)
    placed_branding = False
    if branding and os.path.exists(branding):
        try:
            logo = Image.open(branding).convert("RGB")
            target_w = px(1100)
            ratio = target_w / logo.width
            logo = logo.resize((target_w, int(logo.height * ratio)),
                               Image.LANCZOS)
            img.paste(logo, ((width - target_w) // 2, top))
            top += logo.height + px(60)
            placed_branding = True
        except Exception:
            pass
    if not placed_branding:
        _sigil(draw, width // 2, top + px(140), px(140))
        top += px(340)

    draw = ImageDraw.Draw(img)

    # ---- headline ---------------------------------------------------------
    overall = report.get("overall", "warn")
    headline = {"pass": "The Circle Holds",
                "warn": "Attend",
                "fail": "The Circle Is Broken"}.get(overall, "Status")
    accent = {"pass": PURPLE, "warn": BRASS_BRIGHT, "fail": BAD}[overall]

    eyebrow = "WARLOCK TABLE · SYSTEM STATUS"
    ew = draw.textlength(eyebrow, font=f_eyebrow)
    draw.text(((width - ew) / 2, top), eyebrow, font=f_eyebrow, fill=BRASS)
    top += px(56)

    tw = draw.textlength(headline, font=f_title)
    draw.text(((width - tw) / 2, top), headline, font=f_title, fill=accent)
    top += px(150)

    # brass rule — structure
    draw.line([px(560), top, width - px(560), top], fill=LINE, width=max(1, px(3)))
    top += px(80)

    # ---- subsystem rows ---------------------------------------------------
    rows: List[Dict[str, Any]] = report.get("rows", [])
    left = px(700)
    mark_x = left + px(40)
    label_x = left + px(140)
    detail_x = left + px(760)

    for row in rows:
        state = row.get("state", "warn")
        _mark(draw, mark_x, top + px(26), px(34), state)
        draw.text((label_x, top), row.get("name", ""), font=f_row,
                  fill=BONE if state != "fail" else BAD)
        draw.text((detail_x, top + px(10)), row.get("detail", ""),
                  font=f_detail, fill=BONE_MID)
        top += px(96)

    # ---- footer -----------------------------------------------------------
    foot_y = height - px(190)
    draw.line([px(560), foot_y - px(50), width - px(560), foot_y - px(50)],
              fill=LINE, width=max(1, px(3)))

    left_text = report.get("panel_url", "")
    right_text = "%s · %s" % (report.get("version", "?"),
                                   time.strftime("%H:%M"))
    draw.text((px(700), foot_y), left_text, font=f_mono, fill=BRASS)
    rw = draw.textlength(right_text, font=f_mono)
    draw.text((width - px(700) - rw, foot_y), right_text, font=f_mono,
              fill=BONE_DIM)

    tmp = path + ".tmp"
    img.save(tmp, "PNG", optimize=False)
    os.replace(tmp, path)
    return path


def build_report(rt) -> Dict[str, Any]:
    """Turn live device status into the rows the screen draws."""
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
        add("Lights", i.get("healthy"),
            "%s · %s%%" % (i.get("pattern") or "—",
                                 i.get("effective_pct", "?"))
            if i.get("healthy") else (i.get("error") or "not connected"))
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

    scene = rt.controller.current_scene
    rows.append({"name": "Scene", "state": "ok" if scene else "warn",
                 "detail": scene.name if scene else "idle"})

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

    return {
        "overall": worst,
        "rows": rows,
        "version": version,
        "panel_url": "http://%s:8080" % host,
    }
