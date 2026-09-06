"""What can go wrong importing a sound, said in words an operator can act on.

Same rule as mapimport.errors: every message names the thing that was wrong
and, where there is one, the thing to do about it. "Import failed" tells the
person holding the iPad nothing.
"""

from __future__ import annotations


class AudioImportError(Exception):
    """Anything the operator should be told about, phrased for them."""


class UnreadableAudio(AudioImportError):
    """The file could not be decoded at all."""


class TooLong(AudioImportError):
    """Longer than the table is willing to hold in memory."""


class NoAudioStream(AudioImportError):
    """A real file, but there is no sound in it."""


class ToolMissing(AudioImportError):
    """ffmpeg is not installed.

    Its own class because the fix is a one-line apt install and has nothing
    to do with the file the operator just chose -- telling them their sound
    is broken would send them looking in entirely the wrong place.
    """
