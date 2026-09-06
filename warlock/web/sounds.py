"""Panel endpoints for uploading sound.

    /api/sounds            GET     what is uploaded, and whether import works
    /api/sounds/upload     PUT     the raw bytes of a file
    /api/sounds/<kind>/<name>  DELETE

The same third API surface the map import uses: not "do this now" and not
"change what things do", but long-running file work that writes to disk.
Its own prefix for the same reason.

Guarded throughout. Import needs ffmpeg, which is apt-installed on the table
but absent on a laptop; the correct behaviour without it is to say so and
leave the rest of the panel working, exactly as map import does when Pillow
is missing.
"""

from __future__ import annotations

import os
import tempfile
from urllib.parse import parse_qs, unquote

PREFIX = "/api/sounds"

# Generous, because a lossless bed can legitimately be large -- mountain.wav
# is 80 MB. The real guard on memory is the duration cap in the importer,
# which is checked from the header before anything is decoded.
MAX_BODY = 120 * 1024 * 1024


class SoundsPanel(object):
    def __init__(self, runtime, controller, log):
        self.runtime = runtime
        self.controller = controller
        self.log = log

    # --- wiring -----------------------------------------------------------

    def _config(self):
        return self.runtime.store.config if hasattr(self.runtime, "store") \
            else self.runtime.config

    def _library(self):
        from ..audioimport import AudioLibrary
        from ..runtime import _with_uploads
        cfg = self._config()
        root = getattr(cfg, "sound_upload_path", None)
        if not root:
            raise RuntimeError(
                "Uploading sound is not configured. Set sound_upload_path in "
                "the table's config to a directory the table owns.")
        # The SAME derivation the running device used, so "does this name
        # already exist" is answered against the paths actually in play
        # rather than a second, subtly different list.
        tracks, cues = _with_uploads(cfg)
        return AudioLibrary(upload_root=root, track_paths=tracks,
                            cue_paths=cues)

    def route(self, handler, method: str, path: str) -> bool:
        """Handle a /api/sounds/* request. Returns False if it is not ours.

        Same contract as MapsPanel.route: nothing raises out of here. A
        failed import must not disturb lights, audio or a running session.
        """
        if not path.startswith(PREFIX):
            return False
        rest = path[len(PREFIX):].strip("/")
        query = parse_qs(handler.path.split("?", 1)[1])             if "?" in handler.path else {}

        if method == "GET" and not rest:
            handler._send_json(self.report())
            return True

        if method == "PUT" and rest == "upload":
            self._upload(handler, query)
            return True

        if method == "DELETE" and rest:
            parts = [unquote(p) for p in rest.split("/")]
            if len(parts) == 2:
                self._delete(handler, parts[0], parts[1])
                return True

        handler._send_json({"error": "unknown endpoint"}, 404)
        return True

    # --- operations -------------------------------------------------------

    def report(self) -> dict:
        from .. import audioimport
        why = audioimport.available()
        out = {
            "can_import": why is None,
            "error": why,
            "kinds": [{"kind": k,
                       "label": v["label"],
                       "loops": v["loop"]}
                      for k, v in audioimport.KINDS.items()],
            "uploads": {"track": [], "cue": []},
        }
        try:
            out["uploads"] = self._library().listing()
        except Exception as exc:      # noqa: BLE001
            out["error"] = out["error"] or str(exc)
        return out

    def _upload(self, handler, query) -> None:
        from .. import audioimport
        from ..audioimport import AudioImportError

        kind = (query.get("kind") or ["effect"])[0]
        raw_name = (query.get("name") or [""])[0]
        wanted = (query.get("as") or [""])[0]
        replace = (query.get("replace") or ["0"])[0] in ("1", "true", "yes")

        try:
            length = int(handler.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            handler._send_json({"error": "No file was received."}, 400)
            return
        if length > MAX_BODY:
            handler._send_json(
                {"error": "That file is %.0f MB. The limit is %d MB."
                          % (length / 1048576.0, MAX_BODY // 1048576)}, 413)
            return

        name = audioimport.clean_name(wanted or raw_name)

        try:
            lib = self._library()
            lib.ensure_dirs()
        except Exception as exc:      # noqa: BLE001
            handler._send_json({"error": str(exc)}, 500)
            return

        fd, tmp = tempfile.mkstemp(dir=lib.work_dir, suffix="-upload")
        try:
            # Chunked, for the same reason the map upload is: a 120 MB body
            # read in one call is 120 MB resident on a machine that is also
            # running a session.
            remaining = length
            with os.fdopen(fd, "wb") as fh:
                while remaining > 0:
                    chunk = handler.rfile.read(min(1024 * 256, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)

            info = audioimport.import_audio(tmp, kind, name, lib,
                                            replace=replace)
        except AudioImportError as exc:
            # Everything in this class is phrased for the operator, so it
            # goes straight through rather than becoming "import failed".
            handler._send_json({"error": str(exc)}, 400)
            return
        except Exception as exc:      # noqa: BLE001
            self.log.record("sounds.upload_failed",
                            error="%s: %s" % (type(exc).__name__, exc))
            handler._send_json({"error": "That sound could not be imported: "
                                         "%s" % exc}, 500)
            return
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        # The file exists; now make the running table aware of it. Failing
        # here is worth reporting but must not lose the upload, which is
        # safely on disk either way.
        try:
            info["library"] = self.controller.audio.rescan()
        except Exception as exc:      # noqa: BLE001
            info["library"] = {}
            info["notes"].append(
                "uploaded, but the table could not refresh its sound list "
                "(%s) -- it will appear after a restart" % exc)

        # `sound_kind`, not `kind`: EventLog.record's own first parameter
        # is called kind, so a field of that name is a TypeError at runtime
        # -- and only on the success path, which is how it survived to the
        # table. The upload had already been written when it blew up.
        self.log.record("sounds.uploaded", name=info["name"],
                        sound_kind=kind, seconds=info["after"]["seconds"])
        handler._send_json(info)

    def _delete(self, handler, kind: str, name: str) -> None:
        from ..audioimport import AudioImportError
        try:
            lib = self._library()
            gone = lib.delete(kind, name)
        except AudioImportError as exc:
            handler._send_json({"error": str(exc)}, 400)
            return
        except Exception as exc:      # noqa: BLE001
            handler._send_json({"error": str(exc)}, 500)
            return

        if not gone:
            handler._send_json({"error": "There is no uploaded sound called "
                                         "%r." % name}, 404)
            return
        try:
            self.controller.audio.rescan()
        except Exception:             # noqa: BLE001
            pass
        self.log.record("sounds.deleted", name=name, sound_kind=kind)
        handler._send_json(self.report())
