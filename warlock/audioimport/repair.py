"""Make an uploaded sound behave like the ones already on the table.

This is the chain tools/fix_beds.py applies to the scene soundscapes, moved
where the table can run it -- rewritten against numpy alone because the Pi
has no pedalboard. Same faults, same fixes, same reasoning:

  * LEVEL, measured on the MONO SUM. People sit close around this table, so
    what they hear is near enough mono, and two files at matching per-channel
    level can be far apart once summed.
  * A DEAD CHANNEL gets the live one copied across. plains.wav arrived with a
    silent right channel and only ever came out of one speaker.
  * THE LOOP SEAM, for anything that loops. Music composes a real ending and
    fades out, so a raw cue measured 76x between its head and its tail; the
    beds were 4.15x. An equal-power fold of the tail back over the head makes
    the file end where it begins.

WHAT IS DELIBERATELY DIFFERENT PER KIND

A one-shot must NOT be loop-closed -- folding a sting's tail over its attack
destroys the very thing it is. And it must not be RMS-levelled either: a
short percussive hit has a low RMS by nature, so levelling it to a bed's
target makes it deafening. One-shots are peak-normalised and their dynamics
left alone.
"""

from __future__ import annotations

import wave
from typing import List, Optional, Tuple

import numpy as np

RATE = 44100
CHANNELS = 2

# What each kind of upload is treated as. Beds and cues loop under a scene;
# an effect is a moment.
KINDS = {
    "bed": {
        "label": "Scene soundscape",
        "target_rms_db": -30.0,     # what the five repaired beds sit at
        "loop": True,
        "crossfade_s": 4.0,
    },
    "cue": {
        "label": "Music cue",
        "target_rms_db": -32.0,     # under the beds, because it plays beneath one
        "loop": True,
        "crossfade_s": 4.0,
    },
    "effect": {
        "label": "One-shot sound",
        "target_rms_db": None,      # peak-normalised instead -- see module docstring
        "loop": False,
        "crossfade_s": 0.0,
    },
}

PEAK_CEILING = 0.99
EFFECT_PEAK = 0.89      # headroom: several effects can layer on one channel
MIN_CORRELATION = 0.35
FADE_MS = 12            # guarantees no click at either end


def repair_dead_channel(audio: np.ndarray) -> Tuple[np.ndarray, List[int]]:
    if audio.shape[0] < 2:
        return audio, []
    live = [i for i in range(audio.shape[0]) if float(audio[i].std()) > 1e-9]
    if not live or len(live) == audio.shape[0]:
        return audio, []
    src = live[0]
    fixed = np.vstack([audio[src]] * audio.shape[0]).astype(np.float32)
    return fixed, [i for i in range(audio.shape[0]) if i not in live]


def narrow_if_out_of_phase(audio: np.ndarray) -> Tuple[np.ndarray, float]:
    """Anything too decorrelated to survive a mono sum gets narrowed."""
    if audio.shape[0] < 2:
        return audio, 1.0
    for _ in range(12):
        if audio[0].std() < 1e-9 or audio[1].std() < 1e-9:
            return audio, 1.0
        corr = float(np.corrcoef(audio[0], audio[1])[0, 1])
        if not np.isfinite(corr) or corr >= MIN_CORRELATION:
            return audio, (corr if np.isfinite(corr) else 1.0)
        mid = (audio[0] + audio[1]) / 2.0
        side = (audio[0] - audio[1]) / 2.0 * 0.7
        audio = np.vstack([mid + side, mid - side]).astype(np.float32)
    return audio, MIN_CORRELATION


def close_the_loop(audio: np.ndarray, seconds: float) -> np.ndarray:
    """Fold the tail back over the head, equal-power so the level holds.

    Sine/cosine rather than linear: a linear crossfade dips in the middle,
    which is audible as a soft spot every time round.
    """
    n = audio.shape[-1]
    k = int(RATE * seconds)
    if k <= 0 or n <= 2 * k:
        return audio
    head, tail = audio[:, :k].copy(), audio[:, -k:]
    t = np.linspace(0.0, 1.0, k, dtype=np.float32)
    out = audio[:, :n - k].copy()
    out[:, :k] = head * np.sin(t * np.pi / 2) + tail * np.cos(t * np.pi / 2)
    return out


def fade_edges(audio: np.ndarray) -> np.ndarray:
    k = int(RATE * FADE_MS / 1000.0)
    if k <= 0 or audio.shape[-1] <= 2 * k:
        return audio
    ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)
    audio = audio.copy()
    audio[:, :k] *= ramp
    audio[:, -k:] *= ramp[::-1]
    return audio


def level(audio: np.ndarray, target_db: Optional[float]) -> np.ndarray:
    """RMS on the mono sum for loops; peak for one-shots."""
    if target_db is None:
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1e-9:
            audio = audio * (EFFECT_PEAK / peak)
        return audio

    mono = audio[:2].mean(axis=0) if audio.shape[0] >= 2 else audio[0]
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    if rms > 1e-9:
        audio = audio * ((10.0 ** (target_db / 20.0)) / rms)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > PEAK_CEILING:
        audio = audio * (PEAK_CEILING / peak)
    return audio


def measure(audio: np.ndarray) -> dict:
    mono = audio[:2].mean(axis=0) if audio.shape[0] >= 2 else audio[0]
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    k = max(1, int(RATE * 0.05))
    head = float(np.sqrt(np.mean(mono[:k].astype(np.float64) ** 2)))
    tail = float(np.sqrt(np.mean(mono[-k:].astype(np.float64) ** 2)))
    return {
        "seconds": round(audio.shape[-1] / float(RATE), 2),
        "rms_db": round(20 * np.log10(rms), 1) if rms > 0 else -99.0,
        "peak": round(float(np.max(np.abs(audio))) if audio.size else 0.0, 3),
        "seam": round(max(head, tail) / max(1e-9, min(head, tail)), 2),
    }


def process(audio: np.ndarray, kind: str) -> Tuple[np.ndarray, dict, List[int]]:
    spec = KINDS[kind]
    audio, dead = repair_dead_channel(audio)
    if spec["loop"]:
        audio = close_the_loop(audio, spec["crossfade_s"])
    else:
        audio = fade_edges(audio)
    audio, _corr = narrow_if_out_of_phase(audio)
    audio = level(audio, spec["target_rms_db"])
    return audio, measure(audio), dead


def write_wav(audio: np.ndarray, path: str) -> int:
    """Write canonical RIFF/fmt/data with the standard library.

    NOT through ffmpeg, deliberately. Asked to write a WAV, ffmpeg emits a
    JUNK chunk before `fmt `, and the Pi's pygame 1.9.6 refuses every file
    shaped that way -- it silently rejected all 91 voice lines until
    tools/normalise_wavs.py was written. `wave` cannot produce that layout,
    so the output is correct by construction.
    """
    if audio.shape[0] == 1:
        audio = np.vstack([audio[0], audio[0]])
    audio = np.clip(audio[:CHANNELS], -1.0, 1.0)
    pcm = (audio.T.reshape(-1) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    import os
    return os.path.getsize(path)
