#!/usr/bin/env python3
"""Render the 54 playing cards in the Entity's voice.

    python card_render.py --list        # what it would say, spend nothing
    python card_render.py --dry-run
    python card_render.py               # render everything missing
    python card_render.py --only ace_of_spades joker_big
    python card_render.py --reprocess   # rebuild from stored raws, no API
    python card_render.py --force

WHY THE ENTITY AND NOT A DEALER

Both were rendered and compared on the table. The same voice underneath
either way -- the difference is the [bored] audio tag and the LEGION chain
(formant shift, two detune layers, a fifth below, sub). A straight read
sounded like a croupier calling a table; the Entity sounds like the thing in
the table noticing what you drew. The second one won.

The cost is length: LEGION appends TAIL_SECONDS of silence so the delay taps
and reverb have room to decay instead of being cut off mid-decay, which
clicks. That makes each announcement about two seconds rather than one.

EVERYTHING ELSE IS entity_render's

Same voice id, same model, same settings, same LEGION constants, same
raw-keeping. This module is a name list and a spelling of each card; if the
Entity is ever retuned, --reprocess rebuilds these from disk along with the
91 lines and they stay in character automatically.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import entity_render as er   # noqa: E402

RAW_DIR = Path("audio/cards/_raw")
OUT_DIR = Path("audio/cards")

SUITS = ("hearts", "diamonds", "clubs", "spades")
RANKS = ("ace", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "jack", "queen", "king")

# The two jokers are the only cards whose name does not spell itself. Nothing
# in the config distinguishes them beyond big/small, so they are said the way
# a person would say them out loud.
JOKERS = {
    "joker_big": "The joker.",
    "joker_small": "The little joker.",
}

# The Entity's default delivery, the same tag the 91 lines are rendered with.
TAG = "[bored]"


def deck():
    """[(config name, spoken text)] for all 54, in deck order."""
    out = []
    for suit in SUITS:
        for rank in RANKS:
            out.append(("%s_of_%s" % (rank, suit),
                        "%s of %s." % (rank.capitalize(), suit)))
    out.extend(sorted(JOKERS.items()))
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="CARD")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--reprocess", action="store_true",
                    help="rebuild finals from stored raws, no API calls")
    args = ap.parse_args()

    cards = deck()
    if args.only:
        want = set(args.only)
        cards = [c for c in cards if c[0] in want]
        missing = want - {c[0] for c in cards}
        if missing:
            sys.exit("no such card: %s" % ", ".join(sorted(missing)))

    if args.list:
        for name, text in cards:
            final = OUT_DIR / (name + ".wav")
            print("%-20s %-22s %s"
                  % (name, text, "final" if final.exists() else "-"))
        print("\n%d cards" % len(cards))
        return 0

    if not args.reprocess and not args.dry_run:
        if not os.environ.get("ELEVENLABS_API_KEY"):
            sys.exit("ELEVENLABS_API_KEY is not set.")

    er.GLOBAL_TAG = TAG
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    done = skipped = 0
    failed = []
    for name, text in cards:
        raw = RAW_DIR / (name + ".wav")
        final = OUT_DIR / (name + ".wav")

        if final.exists() and not (args.force or args.reprocess):
            skipped += 1
            continue

        if not raw.exists() or (args.force and not args.reprocess):
            if args.reprocess:
                print("%-20s no raw to reprocess" % name)
                continue
            if args.dry_run:
                print("%-20s would say %r" % (name, text))
                continue
            try:
                er.synthesize(text, raw)
            except SystemExit:
                raise
            except Exception as exc:            # noqa: BLE001
                print("%-20s FAILED  %s" % (name, exc))
                failed.append(name)
                continue

        if args.dry_run:
            print("%-20s would process the existing raw" % name)
            continue

        secs = er.process(raw, final)
        done += 1
        print("%-20s %-22s %.2fs" % (name, text, secs))

    print()
    print("rendered %d, already present %d" % (done, skipped))
    if failed:
        print("%d failed: %s" % (len(failed), ", ".join(failed)))
        print("re-run just those:  python card_render.py --only %s"
              % " ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
