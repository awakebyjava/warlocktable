"""Uploaded sound -> something the table can play, safely.

A bolt-on module in the same shape as `mapimport`: it knows nothing about
the controller. It takes a file, converts and repairs it, writes it into the
table's own data directory and reports what it did. Asking the audio device
to rescan is the caller's job, and that is the whole integration.

WHY AN IMPORT STEP AT ALL, RATHER THAN JUST COPYING THE FILE

Every audio fault this table has had was a format fault, and none of them
announced themselves:

  * the five scene beds ran at 44100, 48000 and 96000 against a 44100 mixer,
    so SDL converted four of them on load -- and THAT, not the recordings,
    produced a 7.6 dB spread that sounded exactly like a level problem;
  * all 91 voice lines were silently refused by pygame 1.9.6 because ffmpeg
    had left a JUNK chunk ahead of `fmt `;
  * plains.wav had a completely dead right channel;
  * generated music arrives with a 76x step between its head and its tail,
    which is audible on every loop.

A copied-in file inherits all of those. Converting on the way in means the
table only ever holds audio it is known to be able to play, and the operator
finds out about a problem while they are uploading rather than mid-session.

    from warlock import audioimport
    info = audioimport.import_audio(tmp_path, "cue", name="ambush_two",
                                    library=lib)
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

from . import decode, repair
from .errors import (AudioImportError, NoAudioStream, ToolMissing, TooLong,
                     UnreadableAudio)
from .library import AudioLibrary, clean_name

__all__ = ["AudioLibrary", "AudioImportError", "UnreadableAudio", "TooLong",
           "NoAudioStream", "ToolMissing", "clean_name", "import_audio",
           "KINDS", "available"]

KINDS = repair.KINDS


def available() -> Optional[str]:
    """None if importing will work, or why it will not.

    Checked before the panel offers an upload button, so a table without
    ffmpeg says so up front instead of accepting a file and then failing.
    """
    try:
        decode._tool("ffmpeg")
        decode._tool("ffprobe")
    except ToolMissing as exc:
        return str(exc)
    return None


def import_audio(upload_path: str, kind: str, name: str,
                 library: AudioLibrary, replace: bool = False) -> dict:
    """Convert, repair and install one uploaded sound.

    Returns what happened -- before and after measurements included, so the
    panel can show that it did something rather than just claiming success.
    """
    if kind not in KINDS:
        raise AudioImportError("%r is not a kind of sound the table knows."
                               % (kind,))
    library.check_name(name)
    library.ensure_dirs()

    dest = library.path_for(kind, name)
    if os.path.isfile(dest) and not replace:
        raise AudioImportError(
            "There is already an uploaded sound called %r. Upload it again "
            "with replace turned on to overwrite it." % name)

    audio, source = decode.decode(upload_path)
    before = repair.measure(audio)
    audio, after, dead = repair.process(audio, kind)

    # Write beside the destination and rename into place, so a failure
    # halfway through cannot leave a half-written file where the mixer will
    # try to load it.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".wav")
    os.close(fd)
    try:
        size = repair.write_wav(audio, tmp)
        os.replace(tmp, dest)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise
    finally:
        del audio

    notes = []
    if source["rate"] and source["rate"] != decode.RATE:
        notes.append("resampled from %d Hz to %d, so the mixer does not have "
                     "to convert it while it plays"
                     % (source["rate"], decode.RATE))
    if source["channels"] == 1:
        notes.append("was mono, copied to both channels")
    if dead:
        notes.append("channel %s was silent and has been filled from the "
                     "live one" % ", ".join(str(d) for d in dead))
    if KINDS[kind]["loop"] and before["seam"] > 1.5:
        notes.append("the loop joined badly (%.1fx between its end and its "
                     "start); the tail has been folded back over the head"
                     % before["seam"])
    if KINDS[kind]["target_rms_db"] is not None:
        notes.append("levelled to %.0f dB, matching the table's other %ss"
                     % (KINDS[kind]["target_rms_db"], kind))

    shadowed = library.shadows(kind, name)

    return {
        "name": name,
        "kind": kind,
        "label": KINDS[kind]["label"],
        "path": dest,
        "bytes": size,
        "source": source,
        "before": before,
        "after": after,
        "notes": notes,
        # An upload wins over a file of the same name that ships with the
        # table. That is useful and also surprising, so it is said plainly.
        "shadows": shadowed,
    }
