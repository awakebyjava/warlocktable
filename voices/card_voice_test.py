"""Should the table ANNOUNCE a card, or should a DEALER call it?

Both use the same voice ("The Table") and the same pipeline as the 91 Entity
lines. The difference is the two things that shape delivery:

  ENTITY  [bored] tag + the full LEGION recipe -- formant shift, two detune
          layers, a fifth below, sub. This is exactly how the Entity speaks,
          so a card announcement becomes the table doing it.

  DEALER  a measured tag and NO Legion. Same voice underneath, but read
          straight -- a croupier calling the table, not the thing in it.

Six API calls. Raws are kept in audio/cards/_raw, so re-tuning either
treatment afterwards costs nothing.

    python card_voice_test.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import entity_render as er
from pedalboard.io import AudioFile

CARDS = ["Ace of spades.", "Queen of hearts.", "The joker."]
RAW = Path("audio/cards/_raw")
OUT = Path("audio/cards/_test")


def render(text, tag, stem):
    """One API call, saved as a lossless raw. Skipped if already there."""
    raw = RAW / (stem + ".wav")
    if raw.exists():
        print("    raw exists, not spending a credit:", raw.name)
        return raw
    er.GLOBAL_TAG = tag
    er.synthesize(text, raw)
    return raw


def straight(raw_path, out_path):
    """No Legion. Just level and a short fade, so it is comparable."""
    import numpy as np
    with AudioFile(str(raw_path)) as f:
        audio = f.read(f.frames)
        rate = f.samplerate
    peak = float(abs(audio).max())
    if peak > 0:
        audio = audio * (er.PEAK / peak)
    k = int(rate * er.FADE_MS / 1000.0)
    if k > 0 and audio.shape[-1] > 2 * k:
        ramp = np.linspace(0.0, 1.0, k, dtype="float32")
        audio[:, :k] *= ramp
        audio[:, -k:] *= ramp[::-1]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with AudioFile(str(out_path), "w", rate, audio.shape[0]) as f:
        f.write(audio)


def main():
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("ELEVENLABS_API_KEY is not set.")
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    for card in CARDS:
        stem = card.lower().rstrip(".").replace(" ", "_")
        print(card)

        r = render(card, "[bored]", stem + "__entity")
        er.process(r, OUT / (stem + "__A_entity.wav"))
        print("    A entity  (Legion)   ->", stem + "__A_entity.wav")

        r = render(card, "[calm]", stem + "__dealer")
        straight(r, OUT / (stem + "__B_dealer.wav"))
        print("    B dealer  (straight) ->", stem + "__B_dealer.wav")

    print("\nlisten in:", OUT.resolve())


if __name__ == "__main__":
    main()
