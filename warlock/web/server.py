"""The operator web panel (plan doc 3.7, 4.5).

Served from the controller process, so the panel and a card tap fire the
*same* controller methods — no duplicated logic, which is the whole point of
the central-controller design (plan doc 4).

Built on stdlib http.server deliberately. Flask is installed on the Pi today
and would be less code, but the mini-racer episode showed what a dependency
costs on ARM: this keeps the Pi's install surface at exactly one package
(pixelblaze-client). Eight endpoints and some static files do not need a
framework.

TWO API SURFACES, kept separate (plan doc 4.5):

  /api/action/*    "do this now" - fires actions. Instant, stateless.
  /api/config/*    "change what things do" - reads (and later writes) the
                   card/scene data.

They are separated so a card-edit endpoint can never fire lights and a
stray action call can never rewrite config. Today the config surface is
read-only: step 1 of the 4.5 staging ("view"), which is nearly free and
immediately useful for debugging.

NOT authenticated. It is a LAN appliance panel, and any auth worth having
would need HTTPS. Player-facing pages will be a genuinely separate,
restricted surface rather than this one with buttons hidden - hiding a
control in a web page prevents nothing.
"""

from __future__ import annotations

import json
import mimetypes
import os
from urllib.parse import unquote as _unquote
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class _Handler(BaseHTTPRequestHandler):
    # Injected by make_server()
    controller = None
    runtime = None
    server_version = "WarlockTable"
    sys_version = ""

    # ------------------------------------------------------------- plumbing

    def log_message(self, fmt, *args):
        # BaseHTTPRequestHandler logs every request to stderr, which in a
        # systemd service means the journal fills with noise. Drop it; the
        # event log already records anything that changed the table.
        pass

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel: str) -> None:
        # Resolve and confirm the result is still inside STATIC_DIR, so a
        # crafted path cannot climb out and serve arbitrary files.
        path = os.path.abspath(os.path.join(STATIC_DIR, rel.lstrip("/")))
        if not path.startswith(STATIC_DIR) or not os.path.isfile(path):
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(path)
        if path.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        # The service worker must never be cached, or a stale one pins an
        # old app shell forever and the panel stops updating.
        if path.endswith("sw.js"):
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ------------------------------------------------------------------ GET

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/":
            self._send_static("index.html")
        elif path == "/api/status":
            self._send_json(self._status())
        elif path == "/api/vocabulary":
            self._send_json(self._vocabulary())
        elif path == "/api/actions":
            from ..registry import describe_actions
            self._send_json({"actions": describe_actions(self.controller)})
        elif path == "/api/config/cards":
            self._send_json({"cards": self.runtime.store.list_cards()})
        elif path == "/api/config/targets":
            self._send_json(self.runtime.store.valid_targets())
        elif path == "/api/config/unassigned":
            self._send_json({"unassigned": self.runtime.unassigned.list()})
        elif path.startswith("/api/"):
            self._send_json({"error": "unknown endpoint"}, 404)
        else:
            self._send_static(path)

    # ----------------------------------------------------------------- POST

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/config/cards/"):
            uid = _unquote(path[len("/api/config/cards/"):])
            from ..config import ConfigError
            try:
                self.runtime.store.delete_card(uid)
            except ConfigError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json({"ok": True, "cards": self.runtime.store.list_cards()})
            return
        self._send_json({"error": "unknown endpoint"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        # --- Management surface: changes what things DO (plan doc 4.5) ---
        if path == "/api/config/cards":
            body = self._read_json()
            from ..config import ConfigError
            try:
                result = self.runtime.store.set_card(
                    uid=body.get("uid", ""),
                    label=body.get("label", ""),
                    kind=body.get("target_kind", ""),
                    name=body.get("target_name", ""),
                )
            except ConfigError as exc:
                # A rejected edit is a content problem, not a server fault:
                # say what was wrong so the operator can fix it.
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            # Registering a tag clears it from the unassigned list.
            self.runtime.unassigned.forget(result["uid"])
            self._send_json({"ok": True, "card": result,
                              "cards": self.runtime.store.list_cards()})
            return

        # --- Action surface: does something NOW ---
        if path != "/api/action":
            self._send_json({"error": "unknown endpoint"}, 404)
            return

        body = self._read_json()
        name = body.get("action")
        params = body.get("params") or {}
        if not name:
            self._send_json({"error": "missing 'action'"}, 400)
            return

        fn = getattr(self.controller, name, None)
        # Only expose methods the registry knows about. Without this check,
        # any controller attribute could be invoked by name from the LAN.
        from ..registry import _REGISTRY
        if name not in _REGISTRY or not callable(fn):
            self._send_json({"error": "no such action: %s" % name}, 400)
            return

        try:
            fn(**params)
        except TypeError as exc:
            self._send_json({"error": "bad parameters: %s" % exc}, 400)
            return
        except Exception as exc:   # noqa: BLE001
            # A failing action must not take the panel down with it. The
            # controller already isolates device faults; this catches the
            # rest so the operator sees an error rather than a dead panel.
            self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
            return

        self._send_json({"ok": True, "status": self._status()})

    # ------------------------------------------------------------- payloads

    def _status(self) -> dict:
        st = self.controller.status()
        out = {"subsystems": st["subsystems"], "scene": st["scene"]}

        lights = getattr(self.runtime.lights, "status", None)
        if callable(lights):
            out["lights"] = lights()
        audio = getattr(self.controller.audio, "status", None)
        if callable(audio):
            out["audio"] = audio()
        disp = getattr(self.controller.display, "status", None)
        if callable(disp):
            out["display_device"] = disp()
        nfc = getattr(self.controller, "_nfc_status", None)
        if callable(nfc):
            out["nfc"] = nfc()
        out["version"] = _read_version()
        return out

    def _vocabulary(self) -> dict:
        cfg = self.controller.config
        return {
            "scenes": sorted(cfg.scenes),
            "interruptions": sorted(cfg.interruptions),
            "random_tables": sorted(cfg.random_tables),
            "idle_scene": cfg.idle_scene_name,
        }

def _read_version() -> Optional[str]:
    """What build is deployed, for the panel footer (plan doc 5.5)."""
    for path in ("/opt/warlocktable/VERSION",
                 os.path.join(os.path.dirname(STATIC_DIR), "..", "..", "VERSION")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.readline().strip()
        except OSError:
            continue
    return None


class WebPanel:
    def __init__(self, controller, runtime, log, port: int = 8080,
                 host: str = "0.0.0.0"):
        self.controller = controller
        self.runtime = runtime
        self.log = log
        self.port = port
        self.host = host
        self._server = None
        self._thread = None

    def start(self) -> bool:
        """Serve on a background thread. Never raises (plan doc 5.2) — the
        panel failing must not stop the table responding to cards."""
        handler = type("_BoundHandler", (_Handler,), {
            "controller": self.controller,
            "runtime": self.runtime,
        })
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError as exc:
            self.log.record("web.unavailable", port=self.port, error=str(exc))
            return False

        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="web-panel", daemon=True)
        self._thread.start()
        self.log.record("web.listening", port=self.port)
        return True

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
