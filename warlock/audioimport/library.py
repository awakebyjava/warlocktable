"""Where an uploaded sound lands, and what is already there.

Uploads go to the table's OWN data directory, never into the operator's
personal audio folders. `~/Documents/MagicTarot` holds recordings the table
does not own and did not make; writing into it would mean a panel button
could overwrite something irreplaceable. /var/lib/warlocktable survives a
deploy untouched, which is the same reason the live config lives there.

The upload directory is the FIRST entry in each search path, so an uploaded
sound of a given name wins over one shipped with the table -- replacing a
bed is a matter of uploading one with the same name, and the original is
still on disk to fall back to.
"""

from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional

from .errors import AudioImportError

# Same shape the rest of the config uses for names. A name becomes a filename
# and then a library key, so anything outside this set is refused rather than
# sanitised into something the operator did not ask for.
NAME_OK = re.compile(r"^[a-z0-9_-]{1,48}$")

AUDIO_EXTENSIONS = (".ogg", ".wav", ".mp3", ".flac")


def clean_name(raw: str, fallback: str = "upload") -> str:
    """Turn a filename the operator chose into a table name.

    Lossy on purpose, and then checked: "Forest Ambience v2.WAV" becomes
    "forest_ambience_v2". If nothing survives, the caller is told rather
    than silently given a file called "_".
    """
    stem = os.path.splitext(os.path.basename(raw or ""))[0]
    stem = stem.strip().lower()
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    stem = re.sub(r"_+", "_", stem)[:48]
    return stem or fallback


class AudioLibrary(object):
    """The two upload destinations, and what is in them."""

    def __init__(self, upload_root: str, track_paths: List[str],
                 cue_paths: List[str]):
        self.root = os.path.expanduser(upload_root)
        # Beds and one-shots are both "tracks" as far as the mixer is
        # concerned -- they differ in how they are PROCESSED, not in where
        # they live, because a scene's soundscape and a card's sting are
        # both resolved out of the same library.
        self.upload_dir = os.path.join(self.root, "tracks")
        self.cue_dir = os.path.join(self.root, "cues")
        # Beside them, not inside: a half-written temporary must never sit
        # somewhere the mixer's directory walk will try to load it.
        self.work_dir = os.path.join(self.root, "_work")
        self.track_paths = [os.path.expanduser(p) for p in track_paths]
        self.cue_paths = [os.path.expanduser(p) for p in cue_paths]

    def ensure_dirs(self) -> None:
        for d in (self.upload_dir, self.cue_dir, self.work_dir):
            try:
                os.makedirs(d, exist_ok=True)
            except OSError as exc:
                raise AudioImportError(
                    "Could not create %s: %s" % (d, exc))

    def dest_dir(self, kind: str) -> str:
        return self.cue_dir if kind == "cue" else self.upload_dir

    def path_for(self, kind: str, name: str) -> str:
        return os.path.join(self.dest_dir(kind), name + ".wav")

    def check_name(self, name: str) -> None:
        if not NAME_OK.match(name or ""):
            raise AudioImportError(
                "%r is not a usable name. Use lower-case letters, numbers, "
                "dashes and underscores." % (name,))

    def existing(self, kind: str, name: str) -> Optional[str]:
        """An uploaded file of this name, if there is one."""
        path = self.path_for(kind, name)
        return path if os.path.isfile(path) else None

    def shadows(self, kind: str, name: str) -> Optional[str]:
        """A file of this name the table already ships, which an upload of
        the same name would take precedence over.

        Worth saying out loud in the panel: naming an upload "forest" does
        not corrupt the original, but it does mean the table stops playing
        it, and that is a surprising thing to discover mid-session.
        """
        roots = self.cue_paths if kind == "cue" else self.track_paths
        mine = os.path.normcase(os.path.abspath(self.dest_dir(kind)))
        for base in roots:
            if not os.path.isdir(base):
                continue
            for root, _dirs, files in os.walk(base):
                # Skip our own upload directory however it was reached. An
                # equality test on `base` is not enough: a search path that
                # is a PARENT of the upload directory would walk into it and
                # report the upload as shadowing itself.
                here = os.path.normcase(os.path.abspath(root))
                if here == mine or here.startswith(mine + os.sep):
                    continue
                for fn in files:
                    stem, ext = os.path.splitext(fn)
                    if stem == name and ext.lower() in AUDIO_EXTENSIONS:
                        return os.path.join(root, fn)
        return None

    def listing(self) -> Dict[str, List[dict]]:
        """Everything uploaded, by kind, newest first."""
        out: Dict[str, List[dict]] = {"track": [], "cue": []}
        for key, directory in (("track", self.upload_dir),
                               ("cue", self.cue_dir)):
            if not os.path.isdir(directory):
                continue
            for fn in os.listdir(directory):
                stem, ext = os.path.splitext(fn)
                if ext.lower() not in AUDIO_EXTENSIONS:
                    continue
                path = os.path.join(directory, fn)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                out[key].append({
                    "name": stem,
                    "bytes": st.st_size,
                    "uploaded": int(st.st_mtime),
                    "uploaded_text": time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                })
            out[key].sort(key=lambda r: r["uploaded"], reverse=True)
        return out

    def delete(self, kind: str, name: str) -> bool:
        """Remove an upload. Only ever touches the upload directories."""
        self.check_name(name)
        path = self.existing("cue" if kind == "cue" else "track", name)
        if path is None:
            return False
        os.unlink(path)
        return True
