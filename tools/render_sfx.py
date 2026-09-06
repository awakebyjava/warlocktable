#!/usr/bin/env python3
"""Render the table's sound effects from soundeffects/table-sfx.json.

    set ELEVENLABS_API_KEY in your environment, then:

    tools/render_sfx.py --list                # what would be generated
    tools/render_sfx.py --only combat_turn    # one sound
    tools/render_sfx.py --family interface    # one family
    tools/render_sfx.py                       # everything not yet rendered
    tools/render_sfx.py --audition combat_turn --takes 3
    tools/render_sfx.py --reprocess           # rebuild finals from raws, no API

SIBLING OF voices/entity_render.py, and deliberately shaped like it: generate
once, keep the raw, and let --reprocess rebuild every final for free when the
recipe changes. Nothing here calls the API twice for the same sound unless you
ask it to.

WHAT IT DOES *NOT* DO
---------------------
It does not run LEGION. That recipe is a voice: formant shift, sub-harmonic,
detune, a fifth below. Applied to a wooden knock it would be nonsense.

What the stingers DO share with the voice is the room and the finish -- the
same reverb, the same darkness on the tail, the same 0.86 peak and the same
12ms fades. That is what makes a card sting and a spoken line sound like they
are happening in the same place, which is the entire reason for generating
these rather than buying a library.

FAMILY COHERENCE comes from the shared prompt skeleton in the JSON's
`_meta.aesthetic`, prepended and appended to every prompt here. Four aces
written as four freehand prompts drift apart; four aces sharing a skeleton and
one processing chain do not.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

try:
    import numpy as np
    from pedalboard import LowpassFilter, Pedalboard, Reverb
    from pedalboard.io import AudioFile
except ImportError:
    sys.exit("needs numpy and pedalboard:  python -m pip install numpy pedalboard")

try:
    import requests
except ImportError:
    requests = None

HERE = Path(__file__).resolve().parent.parent
SPEC = HERE / "soundeffects" / "table-sfx.json"

# --- the finish, shared with the voice --------------------------------------
# These four are copied deliberately from voices/entity_render.py. If that
# recipe is retuned, retune these to match and --reprocess both, or the voice
# and the stingers will drift into different rooms.
SPACE = 0.12                 # how much reverb is blended in
SPACE_DARK = 1800            # the tail is rolled off here, as the voice is
PEAK = 0.86                  # headroom; a normalised peak can overshoot on
                             # reconstruction
FADE_MS = 12                 # guarantees no click at either end
TAIL_SECONDS = 1.0           # padding so the reverb tail decays rather than
                             # being cut off mid-decay, which clicks


def load_spec():
    if not SPEC.exists():
        sys.exit("can't find %s" % SPEC)
    with open(SPEC, encoding="utf-8") as fh:
        return json.load(fh)


def build_prompt(meta, sound):
    """The family's skeleton wrapped around this sound's specific.

    THE SKELETON IS PER-FAMILY, not global. A single global one is what made
    the first pass uniformly inert: the rule that keeps a card sting huge and
    the rule that keeps a panel tap quick are not the same rule, and forcing
    both through one description flattened everything to the same texture.

    Falls back to _meta.aesthetic for a family that defines neither, so an
    incomplete edit degrades to the old behaviour rather than dropping the
    skeleton entirely and silently producing something uncharacterised.
    """
    aesthetic = meta.get("aesthetic", {})
    family = (meta.get("families", {}) or {}).get(sound.get("family"), {}) or {}

    prefix = family.get("prefix", aesthetic.get("prefix", ""))
    suffix = family.get("suffix", aesthetic.get("suffix", ""))

    # _meta.aesthetic.shared is documentation, NOT part of the prompt. It says
    # "mixed loud and confident", which is right for a card sting and directly
    # contradicts "clear and quick" on a panel tap. The family suffix already
    # carries everything each family needs.
    parts = [prefix, sound["prompt"], suffix]
    return " ".join(p.strip() for p in parts if p and p.strip())


# --- generation -------------------------------------------------------------

def generate(prompt, seconds, influence, api_key, out_path, fmt,
             loop=False, model_id=None):
    """One API call. Writes the raw exactly as returned, and keeps it.

    `loop` asks the model for a sound that loops smoothly. It is documented as
    available only on eleven_text_to_sound_v2, which is the default model, and
    it is what the scene beds use -- the model closing the loop itself is
    better than stitching one afterwards.
    """
    if requests is None:
        sys.exit("needs requests:  python -m pip install requests")

    body = {
        "text": prompt,
        # MEASURED against the API: must be between 0.5 and 30. Asking for 60
        # returns invalid_generation_settings naming that range.
        "duration_seconds": round(float(seconds), 2),
        "prompt_influence": float(influence),
    }
    if loop:
        body["loop"] = True
    if model_id:
        body["model_id"] = model_id
    r = requests.post(
        "https://api.elevenlabs.io/v1/sound-generation",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        params={"output_format": fmt},
        json=body,
        timeout=180,
    )
    if r.status_code != 200:
        detail = r.text[:300].replace("\n", " ")
        raise RuntimeError("API %s: %s" % (r.status_code, detail))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return len(r.content)


# --- processing -------------------------------------------------------------

def process(raw_path, out_path):
    """Raw -> the finished WAV the table plays.

    Deliberately light. The generated sound is already the sound; this only
    puts it in the same room as the voice and finishes it safely.
    """
    with AudioFile(str(raw_path)) as f:
        rate = f.samplerate
        audio = f.read(f.frames)

    if audio.shape[-1] == 0:
        raise ValueError("raw file is empty")

    # Pad so the reverb has somewhere to decay to.
    pad = int(rate * TAIL_SECONDS)
    out = np.concatenate(
        [audio, np.zeros((audio.shape[0], pad), dtype=audio.dtype)], axis=1)

    if SPACE > 0:
        wet = Pedalboard([
            Reverb(room_size=0.5, damping=0.7, wet_level=1.0,
                   dry_level=0.0, width=0.8),
            LowpassFilter(cutoff_frequency_hz=SPACE_DARK),
        ])(out.astype(np.float32), rate)
        out = out * (1 - SPACE) + wet * SPACE

    # Trim the padding back to where it actually went quiet, keeping the tail.
    mag = np.max(np.abs(out), axis=0)
    thresh = float(np.max(mag)) * 0.0015
    nz = np.nonzero(mag > thresh)[0]
    if len(nz):
        end = min(out.shape[-1], nz[-1] + int(rate * 0.08))
        out = out[:, :end]

    # FADE FIRST, THEN NORMALISE -- the opposite order to entity_render.py,
    # and deliberately so.
    #
    # The voice chain normalises then fades, which is fine for speech: its
    # loudest moment is somewhere in the middle of a word, nowhere near the
    # 12ms ramp at the start. A percussive sound is the other way round. A
    # struck knock peaks at sample zero, squarely inside the fade, so fading
    # afterwards drags the true peak down -- measured at 0.799 against a
    # target of 0.86 on the first test, which would have left every stinger
    # quietly under-levelled against the voice.
    f_len = max(1, int(rate * FADE_MS / 1000.0))
    if out.shape[-1] > 2 * f_len:
        ramp = np.linspace(0.0, 1.0, f_len, dtype=np.float32)
        out[:, :f_len] *= ramp
        out[:, -f_len:] *= ramp[::-1]

    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = out / peak * PEAK

    write_canonical_wav(out.astype(np.float32), rate, out_path)
    return out.shape[-1] / float(rate)


def write_canonical_wav(audio, rate, out_path, channels=1):
    """Write with Python's `wave`, NOT via a library that may add chunks.

    THIS IS NOT FUSSINESS. The Pi runs pygame 1.9.6 on SDL 1.2, whose WAV
    loader requires `fmt ` to be the first chunk. ffmpeg-based writers insert a
    52-byte JUNK chunk ahead of it for possible RF64 promotion, and SDL then
    refuses the file with a bare "Unable to open file". All 91 Entity voice
    lines were unplayable for exactly this reason, and nothing else noticed --
    the files were valid by every other measure.

    Writing the frames ourselves produces RIFF/fmt/data and nothing else.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if channels == 1:
        data = audio.mean(axis=0) if audio.shape[0] > 1 else audio[0]
    else:
        if audio.shape[0] == 1:
            audio = np.concatenate([audio, audio], axis=0)
        # Interleave L,R,L,R... which is what RIFF expects.
        data = audio[:channels].T.reshape(-1)

    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())


# --- scene beds -------------------------------------------------------------

def make_loopable(audio, rate, crossfade_s):
    """Turn a one-shot render into a bed that loops into itself with no step.

    Take the last `crossfade_s` of the file and mix it back over the first
    `crossfade_s`, fading one down as the other comes up, then drop that tail.
    What is left ends exactly where it begins, so playing it on repeat has no
    seam at all.

    THE ORIGINAL BEDS HAD NO SUCH TREATMENT, and it is measurable: island's
    last 50ms was four times the level of its first 50ms, plains twice. That
    step is what is audible every time round the loop.
    """
    n = audio.shape[-1]
    k = int(rate * crossfade_s)
    if k <= 0 or n <= 2 * k:
        return audio

    head = audio[:, :k].copy()
    tail = audio[:, -k:]
    # Equal-power, so the sum holds a constant level through the blend rather
    # than dipping in the middle as a linear fade would.
    t = np.linspace(0.0, 1.0, k, dtype=np.float32)
    up, down = np.sin(t * np.pi / 2), np.cos(t * np.pi / 2)

    blended = head * up + tail * down
    out = audio[:, :n - k].copy()
    out[:, :k] = blended
    return out


def process_bed(raw_path, out_path, target):
    """Raw -> a finished, loopable, level-matched bed at the mixer's format."""
    with AudioFile(str(raw_path)) as f:
        rate = f.samplerate
        audio = f.read(f.frames)

    want_rate = int(target.get("samplerate", 44100))
    if int(rate) != want_rate:
        # Resample HERE rather than letting SDL do it on load. SDL 1.2's
        # conversion is where the level differences between the original beds
        # came from; doing it once, offline, at a known quality, removes that
        # variable entirely.
        with AudioFile(str(raw_path)).resampled_to(want_rate) as f:
            audio = f.read(f.frames)
        rate = want_rate

    channels = int(target.get("channels", 2))
    if audio.shape[0] == 1 and channels == 2:
        audio = np.concatenate([audio, audio], axis=0)
    elif audio.shape[0] > channels:
        audio = audio[:channels]

    # The model is asked for `loop: true`, so the file should already close on
    # itself. make_loopable stays available as a fallback for material that
    # does not -- set crossfade_s in the bed target to switch it on -- but it
    # is OFF by default, because trimming three seconds off an already-looping
    # file would cost length for nothing.
    crossfade = float(target.get("crossfade_s", 0.0))
    if crossfade > 0:
        audio = make_loopable(audio, rate, crossfade)

    # --- mono compatibility, BEFORE levelling --------------------------
    #
    # Generated beds vary enormously in stereo width. Measured across the
    # first five: L/R correlation ran from 0.89 down to MINUS 0.23 -- swamp's
    # channels were partly out of phase.
    #
    # That matters at this table specifically. People sit around it, close, so
    # what most of them hear is near enough a mono sum, and out-of-phase
    # content cancels in a sum. Swamp measured 4dB quieter mono-summed than
    # island while both sat at exactly -30dB per channel: identical on paper,
    # audibly different in the room.
    #
    # Narrow the side component until the channels correlate safely, which
    # costs a little width and buys a bed that sounds the same wherever you
    # sit.
    if audio.shape[0] == 2:
        floor = float(target.get("min_correlation", 0.35))
        for _ in range(12):
            left, right = audio[0].astype(np.float64), audio[1].astype(np.float64)
            if left.std() < 1e-9 or right.std() < 1e-9:
                break
            corr = float(np.corrcoef(left, right)[0, 1])
            if corr >= floor:
                break
            mid = (left + right) / 2.0
            side = (left - right) / 2.0
            side *= 0.7                      # narrow, and re-measure
            audio = np.vstack([mid + side, mid - side]).astype(np.float32)

    # --- one level for all of them --------------------------------------
    #
    # Measured on the MONO SUM, not per channel. Per-channel normalisation is
    # what produced five beds at exactly -30dB that were still 3.9dB apart in
    # the room -- the reference has to be what a listener actually hears.
    if audio.shape[0] == 2:
        reference = audio.astype(np.float64).mean(axis=0)
    else:
        reference = audio.astype(np.float64).reshape(-1)
    rms = float(np.sqrt(np.mean(reference ** 2)))
    if rms > 1e-9:
        gain = (10.0 ** (float(target.get("rms_db", -30.0)) / 20.0)) / rms
        audio = audio * gain
    peak = float(np.max(np.abs(audio)))
    if peak > 0.99:                       # never clip for the sake of a target
        audio = audio * (0.99 / peak)

    write_canonical_wav(audio.astype(np.float32), rate, out_path,
                        channels=channels)
    return audio.shape[-1] / float(rate)


# --- main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show what would be done")
    ap.add_argument("--only", help="one sound id")
    ap.add_argument("--family", help="one family: boon person aura scene interface system combat player")
    ap.add_argument("--force", action="store_true", help="regenerate even if it exists")
    ap.add_argument("--reprocess", action="store_true",
                    help="rebuild finals from stored raws, no API calls")
    ap.add_argument("--beds", action="store_true",
                    help="render the five looping scene soundscapes instead")
    ap.add_argument("--audition", help="generate several takes of one id to choose from")
    ap.add_argument("--takes", type=int, default=3)
    args = ap.parse_args()

    spec = load_spec()
    meta = spec["_meta"]
    eleven = meta["elevenlabs"]
    sounds = spec["sounds"]

    out_dir = HERE / "soundeffects" / eleven.get("output_dir", "audio/sfx/")
    raw_dir = HERE / "soundeffects" / eleven.get("raw_dir", "audio/sfx/_raw/")
    fmt = eleven.get("output_format", "mp3_44100_128")
    default_influence = float(eleven.get("default_prompt_influence", 0.45))

    # --- the scene beds -------------------------------------------------
    if args.beds:
        beds = spec.get("beds", [])
        cfg = meta.get("beds", {})
        target = dict(cfg.get("target", {}))
        loop_cfg = cfg.get("loop", {})
        target.setdefault("crossfade_s", loop_cfg.get("crossfade_s", 0.0))
        bed_dir = HERE / "soundeffects" / "audio" / "beds"
        bed_raw = HERE / "soundeffects" / "audio" / "beds" / "_raw"

        if args.only:
            beds = [b for b in beds if b["id"] == args.only]
        if args.list:
            for b in beds:
                print("%-16s %-10s %4.0fs  %s %s"
                      % (b["id"], b.get("scene", ""), b["duration_seconds"],
                         cfg.get("prefix", ""), b["prompt"]))
            return 0

        if args.reprocess:
            n = 0
            for b in beds:
                raws = sorted(bed_raw.glob("%s.*" % b["id"]))
                if not raws:
                    continue
                secs = process_bed(raws[0], bed_dir / ("%s.wav" % b["id"]), target)
                n += 1
                print("  %-16s %.1fs" % (b["id"], secs))
            print("")
            print("reprocessed %d beds (no API calls)" % n)
            return 0

        api_key = os.environ.get(eleven.get("env_var", "ELEVENLABS_API_KEY"))
        if not api_key:
            sys.exit("%s is not set." % eleven.get("env_var", "ELEVENLABS_API_KEY"))

        todo = [b for b in beds
                if args.force or not (bed_dir / ("%s.wav" % b["id"])).exists()]
        print("%d beds, %d to generate (loop=%s)"
              % (len(beds), len(todo), loop_cfg.get("use_api_loop", True)))
        ok = 0
        for b in todo:
            prompt = " ".join(x for x in (cfg.get("prefix", ""), b["prompt"],
                                          cfg.get("suffix", "")) if x)
            raw = bed_raw / ("%s.mp3" % b["id"])
            try:
                generate(prompt, b["duration_seconds"],
                         b.get("prompt_influence", 0.3), api_key, raw, fmt,
                         loop=bool(loop_cfg.get("use_api_loop", True)),
                         model_id=loop_cfg.get("model_id"))
                secs = process_bed(raw, bed_dir / ("%s.wav" % b["id"]), target)
                ok += 1
                print("  %-16s %.1fs" % (b["id"], secs))
            except Exception as exc:            # noqa: BLE001
                print("  %-16s FAILED: %s" % (b["id"], exc), file=sys.stderr)
            time.sleep(1.0)
        print("")
        print("rendered %d beds -> %s" % (ok, bed_dir))
        return 0

    selected = sounds
    if args.family:
        selected = [s for s in selected if s["family"] == args.family]
    if args.only:
        selected = [s for s in selected if s["id"] == args.only]
    if args.audition:
        selected = [s for s in sounds if s["id"] == args.audition]
    if not selected:
        sys.exit("nothing matched")

    if args.list:
        print("%-26s %-10s %5s  %s" % ("id", "family", "secs", "prompt"))
        for s in selected:
            done = (out_dir / ("%s.wav" % s["id"])).exists()
            print("%-26s %-10s %5.1f  %s%s"
                  % (s["id"], s["family"], s["duration_seconds"],
                     "[done] " if done else "", build_prompt(meta, s)[:96]))
        print("\n%d sounds, %.0f seconds of audio"
              % (len(selected), sum(s["duration_seconds"] for s in selected)))
        return 0

    # --reprocess never touches the network. Retuning the finish costs nothing.
    if args.reprocess:
        n = 0
        for s in selected:
            raws = sorted(raw_dir.glob("%s.*" % s["id"]))
            if not raws:
                continue
            try:
                secs = process(raws[0], out_dir / ("%s.wav" % s["id"]))
                n += 1
                print("  %-26s %.2fs" % (s["id"], secs))
            except Exception as exc:            # noqa: BLE001
                print("  %-26s FAILED: %s" % (s["id"], exc), file=sys.stderr)
        print("\nreprocessed %d (no API calls)" % n)
        return 0

    api_key = os.environ.get(eleven.get("env_var", "ELEVENLABS_API_KEY"))
    if not api_key:
        sys.exit("%s is not set." % eleven.get("env_var", "ELEVENLABS_API_KEY"))

    if args.audition:
        s = selected[0]
        prompt = build_prompt(meta, s)
        print("auditioning %s, %d takes" % (s["id"], args.takes))
        print("  %s\n" % prompt)
        for i in range(1, args.takes + 1):
            raw = raw_dir / "_audition" / ("%s_take%d.mp3" % (s["id"], i))
            try:
                generate(prompt, s["duration_seconds"],
                         s.get("prompt_influence", default_influence),
                         api_key, raw, fmt)
                final = out_dir / "_audition" / ("%s_take%d.wav" % (s["id"], i))
                secs = process(raw, final)
                print("  take %d  %.2fs  %s" % (i, secs, final))
            except Exception as exc:            # noqa: BLE001
                print("  take %d  FAILED: %s" % (i, exc), file=sys.stderr)
            time.sleep(1.0)
        print("\nListen, then copy the one you want to %s/<id>.wav" % out_dir)
        return 0

    todo = [s for s in selected
            if args.force or not (out_dir / ("%s.wav" % s["id"])).exists()]
    print("%d selected, %d to generate" % (len(selected), len(todo)))
    if not todo:
        print("nothing to do (use --force to regenerate)")
        return 0

    ok = failed = 0
    for n, s in enumerate(todo, 1):
        prompt = build_prompt(meta, s)
        influence = s.get("prompt_influence", default_influence)
        raw = raw_dir / ("%s.mp3" % s["id"])
        try:
            generate(prompt, s["duration_seconds"], influence, api_key, raw, fmt)
            secs = process(raw, out_dir / ("%s.wav" % s["id"]))
            ok += 1
            print("  %3d/%d  %-26s %.2fs" % (n, len(todo), s["id"], secs))
        except Exception as exc:                # noqa: BLE001
            failed += 1
            print("  %3d/%d  %-26s FAILED: %s"
                  % (n, len(todo), s["id"], exc), file=sys.stderr)
        # Gentle on the API; these are not urgent.
        time.sleep(1.0)

    print("\nrendered %d, failed %d" % (ok, failed))
    print("finals : %s" % out_dir)
    print("raws   : %s   (--reprocess rebuilds finals free)" % raw_dir)
    if ok:
        print("\nThese are canonical RIFF/fmt/data, so the Pi's pygame 1.9.6")
        print("will load them. Verify before shipping:")
        print("  tools/catalog_sfx.py --root soundeffects/audio/sfx")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
