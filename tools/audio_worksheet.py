#!/usr/bin/env python3
"""Build the tarot audio sourcing worksheet.

    python tools/audio_worksheet.py                        # on the Pi
    python tools/audio_worksheet.py --config ./config.json # from a laptop

Durations come from the live config. There is no API endpoint that serves
it whole -- /api/config/* exposes cards and targets, not durations -- so
this reads the file. On the Pi that is the default path; from a laptop,
copy it first:

    scp raspberrypi.local:/var/lib/warlocktable/config.json .

Writes `tarot-audio.html` and `tarot-audio.csv` next to the repo. The HTML
pastes into Google Docs as a real table; the CSV opens in Sheets.

WHY GENERATE IT RATHER THAN WRITE IT ONCE

The durations are the whole point of the sheet, and they are LIVE data --
they were all 60s until the Auras were retimed, and a hand-typed sheet
would have gone stale the same afternoon. Everything factual here is read
from the running table; only the creative briefs are literal text, and
those come from the design doc.

The length column matters more than it looks. play_effect() is called with
max_duration = the card's duration_s, so a clip longer than that is CUT
rather than faded -- the number in the sheet is a ceiling, not a target to
aim past.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_CONFIG = "/var/lib/warlocktable/config.json"

# Where the table looks for audio. From the live config's audio_paths --
# NOT /var/lib/warlocktable/audio, which is empty and looks like the
# obvious answer.
AUDIO_DIRS = "~/Documents/MagicTarot/Ov  or  ~/Documents/MagicTarot/MagicCards"

# Creative briefs, from warlock-table-interruption-cards.md. The Auras have
# a specified audio layer; the Persons and Boons do not, and saying so is
# more useful than inventing one and letting it look official.
BRIEF = {
    # --- Auras: audio specified in the design doc ---
    "the_sun":            ("Aura", "Warm golden glow, slow brighten and hold", "Triumphant swell"),
    "the_moon":           ("Aura", "Cool blue dim wash, slow pulse", "Distant eerie howl"),
    "the_star":           ("Aura", "Soft white/blue twinkle sparkles", "Gentle ambient chime"),
    "temperance":         ("Aura", "Blue-green slow wave, calm", "Soft water/harp tone"),
    "strength":           ("Aura", "Warm orange glow, slow heartbeat pulse", "Low resonant hum"),
    "justice":            ("Aura", "White/silver even pulse, metronomic", "Scale-tick chime"),
    "judgement":          ("Aura", "Bright white, rising crescendo", "Rising horn/trumpet"),
    "the_devil":          ("Aura", "Dim ember-red flicker", "Flame crackle + impish laughter"),
    "the_tower":          ("Aura", "Violent white strobe, sharp", "Cracking/thunder crash"),
    "death":              ("Aura", "Deep black-purple wash, slow fade down", "Low ominous tone"),
    "the_world":          ("Aura", "Full-spectrum slow colour cycle", "Orchestral swell"),
    "the_chariot":        ("Aura", "Fast light streaks racing the perimeter", "Galloping drums"),
    # --- Boons: doc says one shared placeholder chime, no suit-specific sound ---
    "ace_of_swords":      ("Boon", "Comet lap then ring flash — white/silver", "NOT SPECIFIED — doc says one shared chime for all four Aces"),
    "ace_of_cups":        ("Boon", "Comet lap then ring flash — blue", "NOT SPECIFIED — doc says one shared chime for all four Aces"),
    "ace_of_wands":       ("Boon", "Comet lap then ring flash — orange/red", "NOT SPECIFIED — doc says one shared chime for all four Aces"),
    "ace_of_pentacles":   ("Boon", "Comet lap then ring flash — gold", "NOT SPECIFIED — doc says one shared chime for all four Aces"),
    # --- Persons: the doc gives colour and motion only, no audio at all ---
    "the_magician":       ("Person", "Crimson red — sharp double-flash, a summoning snap", "NOT SPECIFIED"),
    "the_emperor":        ("Person", "Deep red-orange — slow fill rising, then holds", "NOT SPECIFIED"),
    "the_fool":           ("Person", "Bright yellow-white — erratic playful sparkle", "NOT SPECIFIED"),
    "the_empress":        ("Person", "Green — slow breathing glow, organic", "NOT SPECIFIED"),
    "the_high_priestess": ("Person", "Deep blue-silver — slow shimmering ripple", "NOT SPECIFIED"),
    "the_lovers":         ("Person", "Warm pink-gold — two lights meet and flash", "NOT SPECIFIED"),
    "the_hermit":         ("Person", "Pale amber — a lantern carried round the table", "NOT SPECIFIED"),
    "the_hanged_man":     ("Person", "Cool blue-violet — the ripple, reversed", "NOT SPECIFIED"),
    "the_hierophant":     ("Person", "Deep purple-red — three ceremonial pulses, bell-like", "NOT SPECIFIED"),
}

ORDER = ["Boon", "Person", "Aura"]
HEAD = ["Card", "Type", "Max length", "What the lights do", "Audio brief",
        "File to create", "Source / URL", "Licence", "Notes", "Done"]


def pretty(name: str) -> str:
    words = name.split("_")
    small = {"of", "the"}
    return " ".join(w if i and w in small else w.capitalize()
                    for i, w in enumerate(words))


def rows(cfg):
    out = []
    for name, entry in cfg["interruptions"].items():
        kind, lights, audio = BRIEF.get(name, ("?", "", ""))
        secs = entry.get("duration_s")
        out.append({
            "sort": (ORDER.index(kind) if kind in ORDER else 9, name),
            "Card": pretty(name),
            "Type": kind,
            "Max length": ("%.1fs" % secs) if secs else "?",
            "What the lights do": lights,
            "Audio brief": audio,
            "File to create": "%s.ogg" % name,
            "Source / URL": "", "Licence": "", "Notes": "", "Done": "",
        })
    out.sort(key=lambda r: r.pop("sort"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=LIVE_CONFIG,
                    help="config.json to read durations from "
                         "(default: %s)" % LIVE_CONFIG)
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print("no config at %s" % args.config)
        print("on a laptop, copy it first:")
        print("  scp raspberrypi.local:%s ." % LIVE_CONFIG)
        print("then: python tools/audio_worksheet.py --config ./config.json")
        return 2
    cfg = json.load(io.open(args.config, encoding="utf-8"))

    data = rows(cfg)

    csv_path = os.path.join(REPO, "tarot-audio.csv")
    with io.open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEAD)
        w.writeheader()
        w.writerows(data)

    html_path = os.path.join(REPO, "tarot-audio.html")
    with io.open(html_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("<h2>Warlock Table — tarot audio</h2>\n")
        fh.write("<p>%d cards. Clips are cut at the max length, not faded, "
                 "so treat it as a ceiling. Drop finished files in "
                 "<code>%s</code> on the Pi, named exactly as the "
                 "<b>File to create</b> column, then set the card's "
                 "<code>audio</code> field to the name without the "
                 "extension.</p>\n" % (len(data), AUDIO_DIRS))
        fh.write('<table border="1" cellpadding="6" cellspacing="0">\n<tr>')
        for h in HEAD:
            fh.write("<th align=\"left\">%s</th>" % h)
        fh.write("</tr>\n")
        for r in data:
            fh.write("<tr>")
            for h in HEAD:
                fh.write("<td>%s</td>" % (r[h] or "&nbsp;"))
            fh.write("</tr>\n")
        fh.write("</table>\n")

    print("wrote %s" % csv_path)
    print("wrote %s" % html_path)
    print("%d cards: %s" % (len(data), ", ".join(
        "%d %s" % (sum(1 for r in data if r["Type"] == k), k) for k in ORDER)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
