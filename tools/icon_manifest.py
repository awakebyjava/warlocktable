#!/usr/bin/env python3
"""The icon set the redesigned interface needs.

    python tools/icon_manifest.py

Writes `icon-manifest.html` and `icon-manifest.csv` next to the repo, for
handing to whoever is drawing the symbols.

WHY THIS IS A FILE AND NOT A CHAT MESSAGE

The icon spec drifted from the interface because the interface changed
after the spec was written -- four panels, bottom tabs, a placeholder tab
on the player page, Return to Idle moving into Run. Regenerating a list
from one place beats maintaining two lists that disagree.

WHAT MATTERS TO THE PERSON DRAWING THEM

Priority, not completeness. TAB icons are load-bearing: they sit in a
bottom bar at 24px and may lose their text label at phone width, so an
icon nobody recognises is a destination nobody finds. STATUS marks are
next -- they are read at a glance across a lit table. BUTTON icons are
mostly decoration beside a text label and can be dropped if the set is
getting long.

The "must read at" column is the real constraint. Anything that only
works at 64px is not usable in a tab bar.
"""

from __future__ import annotations

import csv
import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (group, name, where, what it must say, must read at, priority)
ICONS = [
    # ---- GM bottom tabs. Four destinations, always visible. -------------
    ("GM tab", "Settings", "GM bottom bar",
     "Sound, brightness, recording, the technical shelf", "24px", "ESSENTIAL"),
    ("GM tab", "Players", "GM bottom bar",
     "The people at the table: seats, initiative, the join code. The landing panel", "24px", "ESSENTIAL"),
    ("GM tab", "Run", "GM bottom bar",
     "Driving the table: scenes, cards, tables, dice, back to idle", "24px", "ESSENTIAL"),
    ("GM tab", "Check", "GM bottom bar",
     "Is the table healthy. Pre-session, not play", "24px", "ESSENTIAL"),

    # ---- Player bottom tabs. ---------------------------------------------
    ("Player tab", "Dice", "Player bottom bar",
     "The roller and the roll log", "24px", "ESSENTIAL"),
    ("Player tab", "Messages", "Player bottom bar",
     "The private conversation with the GM. NOT a group chat -- there is none", "24px", "ESSENTIAL"),
    ("Player tab", "Seat", "Player bottom bar",
     "Who you are and which lights are yours", "24px", "ESSENTIAL"),
    ("Player tab", "Table", "Player bottom bar",
     "PLACEHOLDER. Table interaction, not yet designed. Ships empty", "24px", "ESSENTIAL"),

    # ---- Always on screen, both surfaces. --------------------------------
    ("Signal", "Question", "Header, every tab",
     "A player has a question. Currently the literal glyph ?", "20px", "ESSENTIAL"),
    ("Signal", "Need", "Header, every tab",
     "A player needs something. Currently the literal glyph !", "20px", "ESSENTIAL"),

    # ---- Subsystem status. Read at a glance across a lit table. ----------
    ("Status", "Lights", "GM status strip, TV status screen",
     "The Pixelblaze and the table's own LEDs", "16px", "HIGH"),
    ("Status", "Sound", "GM status strip, TV status screen",
     "Audio out, soundscapes and stings", "16px", "HIGH"),
    ("Status", "Screen", "GM status strip, TV status screen",
     "The embedded television", "16px", "HIGH"),
    ("Status", "Cards", "GM status strip, TV status screen",
     "The NFC reader", "16px", "HIGH"),
    ("Status", "Room", "GM status strip, TV status screen",
     "Govee accent lighting. NEW -- not in the old spec", "16px", "HIGH"),
    ("Status", "OK / Warn / Fail", "Beside every status",
     "Three states. Must differ in SHAPE, not only colour", "16px", "HIGH"),

    # ---- Run panel. ------------------------------------------------------
    ("Run", "Scene", "Run panel", "Enter a persisting place", "24px", "MEDIUM"),
    ("Run", "Card", "Run panel",
     "The tarot interruptions -- a one-off event over the scene", "24px", "MEDIUM"),
    ("Run", "Random table", "Run panel",
     "Roll on a table. Wheel of Fortune draws a random aura", "24px", "MEDIUM"),
    ("Run", "Return to Idle", "Run panel",
     "Put the table back to rest. Moved here from the bottom bar", "24px", "MEDIUM"),
    ("Run", "Grid overlay", "Run panel", "Square grid on the screen", "24px", "MEDIUM"),
    ("Run", "Hex overlay", "Run panel", "Hex grid on the screen", "24px", "MEDIUM"),
    ("Run", "No overlay", "Run panel", "Plain artwork, no grid", "24px", "MEDIUM"),

    # ---- Players panel. --------------------------------------------------
    ("Players", "Join code", "Players panel",
     "Put the QR up on the television. First thing at a session", "24px", "HIGH"),
    ("Players", "Initiative", "Players panel", "Turn order", "24px", "MEDIUM"),
    ("Players", "Previous / Next turn", "Players panel",
     "Step the order. Currently the glyphs and", "24px", "MEDIUM"),
    ("Players", "Seat colours", "Players panel",
     "Light every seat so people can find theirs", "24px", "MEDIUM"),

    # ---- Settings panel. -------------------------------------------------
    ("Settings", "Volume", "Settings panel", "Master level", "24px", "MEDIUM"),
    ("Settings", "Output: speakers", "Settings panel", "Sound to the 3.5mm jack", "24px", "MEDIUM"),
    ("Settings", "Output: television", "Settings panel", "Sound over HDMI", "24px", "MEDIUM"),
    ("Settings", "Brightness", "Settings panel", "Table LED level", "24px", "MEDIUM"),
    ("Settings", "Record", "Settings panel", "Start recording the session", "24px", "MEDIUM"),
    ("Settings", "Stop recording", "Settings panel", "And close the file cleanly", "24px", "MEDIUM"),
    ("Settings", "Card management", "Settings panel",
     "Admin: which tag fires what. Behind Settings, never on a play panel", "24px", "LOW"),

    # ---- Check panel. ----------------------------------------------------
    ("Check", "Run check", "Check panel", "Sub-second health check", "24px", "MEDIUM"),
    ("Check", "Test lights and sound", "Check panel",
     "Actually flash and play -- software cannot confirm photons", "24px", "MEDIUM"),

    # ---- Dice, both surfaces. -------------------------------------------
    ("Dice", "d4 d6 d8 d10 d12 d20", "Dice panel, GM and player",
     "Six dice. NO d100 and no percentile pair -- deliberately", "32px", "HIGH"),
    ("Dice", "Clear", "Dice pad", "Wipe the whole display, not one digit", "24px", "MEDIUM"),
    ("Dice", "Log", "Dice pad", "That player's own roll history", "24px", "MEDIUM"),
]

HEAD = ["Group", "Icon", "Where it appears", "What it must communicate",
        "Must read at", "Priority"]


def main() -> int:
    csv_path = os.path.join(REPO, "icon-manifest.csv")
    with io.open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEAD)
        w.writerows(ICONS)

    html_path = os.path.join(REPO, "icon-manifest.html")
    counts = {}
    for row in ICONS:
        counts[row[5]] = counts.get(row[5], 0) + 1
    with io.open(html_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("<h2>Warlock Table &mdash; icons the interface needs</h2>\n")
        fh.write("<p><b>%d icons.</b> %s</p>\n" % (
            len(ICONS),
            " &middot; ".join("%s: %d" % (k, counts[k]) for k in
                              ("ESSENTIAL", "HIGH", "MEDIUM", "LOW") if k in counts)))
        fh.write("<p>Monochrome, single colour, on a dark ground. The "
                 "<b>must read at</b> column is the real constraint: the "
                 "tab icons sit in a bottom bar and may lose their text "
                 "label at phone width, so one that only works large is a "
                 "destination nobody finds. Drawn against a dark "
                 "background &mdash; the whole interface is dark, and a "
                 "symbol tuned on white often disappears.</p>\n")
        fh.write("<p><b>The three status states must differ in shape, not "
                 "only colour.</b> They are read across a lit table, "
                 "sometimes by someone who cannot separate red from "
                 "green.</p>\n")
        fh.write('<table border="1" cellpadding="6" cellspacing="0">\n<tr>')
        for h in HEAD:
            fh.write('<th align="left">%s</th>' % h)
        fh.write("</tr>\n")
        for row in ICONS:
            fh.write("<tr>")
            for cell in row:
                fh.write("<td>%s</td>" % cell)
            fh.write("</tr>\n")
        fh.write("</table>\n")

    print("wrote %s" % csv_path)
    print("wrote %s" % html_path)
    print("%d icons: %s" % (len(ICONS), ", ".join(
        "%d %s" % (counts[k], k) for k in ("ESSENTIAL", "HIGH", "MEDIUM", "LOW")
        if k in counts)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
