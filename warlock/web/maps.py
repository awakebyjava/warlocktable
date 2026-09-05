"""Panel endpoints for map import.

A THIRD API surface, alongside the two the panel already keeps apart:

    /api/action/*   "do this now"          -- fires actions, instant
    /api/config/*   "change what things do" -- edits card and scene data
    /api/maps/*     long-running file work  -- this

Map import is neither of the first two. It uploads tens of megabytes, spends
seconds in Pillow, and writes files. Giving it its own prefix keeps that from
being confused with either, in the same spirit as the existing split.

Everything here is guarded: Pillow may not be installed (a laptop, or a Pi
where `apt install python3-pil` has not been run yet), and the correct
behaviour then is for these endpoints to explain that clearly while the rest
of the panel carries on working. A table with no map import is a table; a
table whose panel will not load is not.
"""

from __future__ import annotations

import io
import os
import tempfile
from typing import Optional
from urllib.parse import parse_qs

PREFIX = "/api/maps"

# The slug used for "show me this on the actual table before I publish it".
# Parenthesised like STATUS_SCREEN so it is visibly not a real map, and so it
# cannot collide with a slug (slugify strips brackets).
PREVIEW_SLUG = "map-preview"

MAX_BODY = 80 * 1024 * 1024


class MapsPanel(object):
    """Holds the library and the preview state for one running panel."""

    def __init__(self, runtime, controller, log):
        self.runtime = runtime
        self.controller = controller
        self.log = log
        self._library = None
        self._restore_to: Optional[str] = None

    # --- wiring -----------------------------------------------------------

    def _config(self):
        return self.runtime.store.config if hasattr(self.runtime, "store") \
            else self.runtime.config

    def library(self):
        """Build the MapLibrary lazily, from config.

        Lazy because importing Pillow costs real time at startup and most
        sessions never open this section at all.
        """
        if self._library is not None:
            return self._library

        from ..mapimport.library import MapLibrary

        config = self._config()
        custom = getattr(config, "custom_background_path", None)
        data = getattr(config, "map_data_path", None)

        if not custom or not data:
            raise RuntimeError(
                "Map import is not configured. Set custom_background_path and "
                "map_data_path in the table's config.")

        self._library = MapLibrary(
            library_dir=custom,
            originals_dir=os.path.join(data, "originals"),
            recipes_dir=os.path.join(data, "recipes"),
            work_dir=os.path.join(data, "work"),
            background_paths=list(config.background_paths),
            on_change=self._rescan_display,
            log=self.log,
        )
        return self._library

    def _rescan_display(self) -> None:
        """The only call this feature makes towards the running table."""
        rescan = getattr(self.controller.display, "rescan", None)
        if callable(rescan):
            rescan()

    # --- routing ----------------------------------------------------------

    def route(self, handler, method: str, path: str) -> bool:
        """Handle a /api/maps/* request. Returns False if it is not ours.

        Every failure below becomes a JSON error with a status code. Nothing
        raises out of here into the server: a map render that fails must not
        affect lights, audio, or a running session.
        """
        if not path.startswith(PREFIX):
            return False

        rest = path[len(PREFIX):].strip("/")
        query = parse_qs(handler.path.split("?", 1)[1]
                         if "?" in handler.path else "")

        try:
            self._dispatch(handler, method, rest, query)
        except ImportError:
            handler._send_json(
                {"error": "Image support is not installed on the table. Run: "
                          "sudo apt install python3-pil libheif-examples"}, 503)
        except Exception as exc:       # noqa: BLE001
            status, message = self._describe_error(exc)
            handler._send_json({"error": message}, status)
        return True

    def _describe_error(self, exc):
        from ..mapimport.errors import MapImportError
        if isinstance(exc, MapImportError):
            # These carry messages written for a person holding an iPad.
            return 400, str(exc)
        if isinstance(exc, RuntimeError):
            return 503, str(exc)
        self.log.record("mapimport.error", error="%s: %s" % (type(exc).__name__, exc))
        return 500, "%s: %s" % (type(exc).__name__, exc)

    def _dispatch(self, handler, method, rest, query):
        lib = self.library()

        # --- collection ---
        if method == "GET" and rest == "":
            from ..mapimport import grid
            handler._send_json({"maps": lib.listing(),
                                "usage": lib.usage(),
                                "pitch": grid.PITCH})
            return

        if method == "PUT" and rest == "upload":
            self._upload(handler, lib, query)
            return

        if method == "POST" and rest == "preview/stop":
            handler._send_json({"ok": True, "restored": self._stop_preview()})
            return

        parts = rest.split("/")
        ident = parts[0] if parts else ""
        action = parts[1] if len(parts) > 1 else ""

        if method == "DELETE" and ident and not action:
            handler._send_json(lib.delete(ident))
            return

        if method == "GET" and ident and action == "source.png":
            # The normalised proxy, untransformed. The browser composes its
            # own instant preview from this while a slider is moving; the
            # authoritative server render follows a moment later. Cheap to
            # serve -- it is a ~960px PNG already sitting on disk.
            self._send_png(handler, lib.session(ident).proxy())
            return

        if method == "GET" and ident and action in ("", "preview.png"):
            if action == "preview.png":
                width = int((query.get("width") or ["960"])[0])
                width = max(240, min(1920, width))
                image = lib.preview_image(ident, width=width,
                                          safe_area=(query.get("safe", ["1"])[0] != "0"))
                self._send_png(handler, image)
            else:
                payload = lib.describe(ident)
                payload["warning"] = lib.brightness_warning(ident)
                handler._send_json(payload)
            return

        if method == "POST" and ident and action == "adjust":
            body = handler._read_json()
            payload = lib.adjust(ident, **body)
            payload["warning"] = lib.brightness_warning(ident)
            handler._send_json(payload)
            return

        if method == "POST" and ident and action == "preview":
            handler._send_json(self._preview_on_table(lib, ident))
            return

        if method == "POST" and ident and action == "publish":
            body = handler._read_json()
            result = lib.publish(ident, title=body.get("title"))
            self._stop_preview()
            handler._send_json(result)
            return

        if method == "POST" and ident and action == "rerender":
            handler._send_json(lib.rerender(ident))
            return

        handler._send_json({"error": "unknown endpoint"}, 404)

    # --- upload -----------------------------------------------------------

    def _upload(self, handler, lib, query):
        """Accept the raw bytes of a file.

        A raw PUT rather than multipart/form-data. Multipart in stdlib
        http.server means the `cgi` module -- deprecated, and gone in Python
        3.13 -- or a hand-rolled parser with a parsing surface to get wrong.
        The body IS the file, and the name rides in the query string.
        """
        name = (query.get("name") or ["upload"])[0]

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

        lib.ensure_dirs()
        fd, tmp = tempfile.mkstemp(dir=lib.work_dir, suffix="-upload")
        try:
            # Read in chunks: a 60 MB body read in one call is 60 MB resident
            # on a machine that also has to keep a session running.
            remaining = length
            with os.fdopen(fd, "wb") as fh:
                while remaining > 0:
                    chunk = handler.rfile.read(min(1024 * 256, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)

            info = lib.upload(tmp, original_name=os.path.basename(name))
            info["warning"] = lib.brightness_warning(info["id"])
            handler._send_json(info)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # --- preview on the real table ----------------------------------------

    def _preview_on_table(self, lib, sid):
        """Render at full size and put it on the TV, without publishing.

        The point of this (spec section 7.4): you cannot judge "too bright for
        players" on a tablet in a lit room, and you cannot judge grid
        alignment without standing a real miniature on the real glass.

        Implemented entirely through the display's existing library + name
        interface -- write the files, rescan, select. No new display concept.
        """
        from ..mapimport import render

        image = lib.full_render(sid)

        if self._restore_to is None:
            self._restore_to = getattr(self.controller.display, "background", None)

        # Every variant gets the same picture: whichever overlay mode the
        # table happens to be in, the preview must show what was rendered.
        for name in render.filenames(PREVIEW_SLUG):
            render._save_atomic(image, os.path.join(lib.library_dir, name))

        self._rescan_display()
        self.controller.set_background(PREVIEW_SLUG)
        return {"ok": True, "showing": PREVIEW_SLUG,
                "restore_to": self._restore_to}

    def _stop_preview(self):
        """Put back whatever was on screen, and remove the preview files."""
        from ..mapimport import render

        restored = None
        try:
            lib = self.library()
            render.unpublish(PREVIEW_SLUG, lib.library_dir)
            self._rescan_display()
        except Exception:              # noqa: BLE001
            pass

        if self._restore_to:
            restored = self._restore_to
            try:
                self.controller.set_background(restored)
            except Exception:          # noqa: BLE001
                pass
        self._restore_to = None
        return restored

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _send_png(handler, image) -> None:
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        body = buffer.getvalue()
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Content-Length", str(len(body)))
        # The preview changes on every slider move and must never be cached.
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)
