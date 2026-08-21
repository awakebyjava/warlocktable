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
        elif path.endswith(".ttf"):
            # Not reliably in the system mimetypes db; Safari is fussy about
            # font content types and will silently refuse to use them.
            ctype = "font/ttf"
        elif path.endswith(".woff2"):
            ctype = "font/woff2"
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        # The service worker must never be cached, or a stale one pins an
        # old app shell forever and the panel stops updating.
        if path.endswith("sw.js"):
            self.send_header("Cache-Control", "no-cache")
        elif "/fonts/" in path.replace("\\", "/"):
            self.send_header("Cache-Control", "public, max-age=604800")
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

        # Three front doors. The QR code on the table points at "/", which
        # asks who you are; the GM's iPad goes straight to "/gm" (the PWA's
        # start_url), and a player lands on "/player" after choosing.
        if path == "/":
            self._send_static("join.html")
        elif path == "/gm":
            self._send_static("index.html")
        elif path == "/player":
            self._send_static("player.html")
        elif path == "/api/join":
            self._send_json(self._join_info())
        elif path == "/api/qr.svg":
            self._send_qr()
        elif path == "/api/initiative":
            self._send_json(self.controller.initiative_report())
        elif path == "/api/status":
            self._send_json(self._status())
        elif path == "/api/vocabulary":
            self._send_json(self._vocabulary())
        elif path == "/api/actions":
            from ..registry import describe_actions
            self._send_json({"actions": describe_actions(self.controller)})
        elif path == "/api/zones":
            # Read-only view of the seat layout. The zone ACTIONS go through
            # /api/action like everything else — this is just what the panel
            # needs to draw them.
            self._send_json(self.controller.zone_report())
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

    # ---- join, QR and seat persistence -----------------------------------

    def _table_url(self) -> str:
        """The address to put on the QR code.

        Built from the address the CLIENT used to reach us, not from a
        lookup of our own hostname. That is the one address known to work
        from a phone on this network -- .local names need mDNS, and picking
        an interface ourselves guesses wrong on a machine with several.
        """
        host = self.headers.get("Host")
        if host:
            return "http://%s/" % host
        return "http://%s:%d/" % (self.server.server_address[0],
                                  self.server.server_address[1])

    def _join_info(self) -> dict:
        return {
            "url": self._table_url(),
            "players": self.controller.config.player_count,
            "zones": self.controller.zone_report(),
        }

    def _send_qr(self) -> None:
        """QR for the table's URL, as SVG.

        SVG rather than PNG because it needs no image library and scales to
        whatever the page wants. If the encoder is not installed the page
        falls back to showing the URL as text, which is worse but still
        gets people onto the table -- the same degrade-quietly rule the
        device layer follows.
        """
        try:
            from ..qr import qr_svg
            svg = qr_svg(self._table_url())
        except Exception as exc:   # noqa: BLE001
            self._send_json({"error": "no QR encoder: %s" % exc}, 501)
            return
        body = svg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _persist_players(self) -> None:
        """Save seat claims, but never let a failed write break the claim.

        A player who has claimed a seat and can see their colour has
        succeeded as far as they are concerned. Losing that on a restart is
        an annoyance; refusing the claim because the disk was busy would be
        a failure they cannot do anything about.
        """
        store = getattr(self.runtime, "store", None)
        if store is None:
            return
        try:
            from ..config import save_config
            save_config(store.config, store.path, store.backup_dir)
        except Exception as exc:   # noqa: BLE001
            self.runtime.log.record("seat.persist_failed", error=str(exc))

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

        # Table Check (plan doc 5.4). POST because the physical mode
        # deliberately changes what the table is doing, briefly.
        if path == "/api/check":
            body = self._read_json()
            from ..tablecheck import run_check
            try:
                report = run_check(self.runtime, physical=bool(body.get("physical")))
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(report)
            return

        # --- Seats: what a player's phone posts (plan doc 4.5) ---
        if path == "/api/seats/claim":
            body = self._read_json()
            name = str(body.get("name", "")).strip()
            colour = str(body.get("colour", "")).strip()
            if not name:
                self._send_json({"error": "a name is needed"}, 400)
                return
            try:
                ok = self.controller.claim_seat(name, colour)
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            if not ok:
                # The commonest case by far is two people picking the same
                # colour, so say which seat rather than just refusing.
                self._send_json({"error": "that seat is already taken",
                                  "zones": self.controller.zone_report()}, 409)
                return
            self._persist_players()
            self._send_json({"ok": True, "name": name, "colour": colour,
                              "zones": self.controller.zone_report()})
            return

        # --- Initiative (plan doc 3.9): GM only ---
        if path == "/api/initiative":
            body = self._read_json()
            try:
                report = self.controller.start_initiative(
                    body.get("order") or [], sort=bool(body.get("sort", True)))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(report)
            return

        if path == "/api/initiative/advance":
            body = self._read_json()
            self.controller.advance_turn(int(body.get("step", 1)))
            self._send_json(self.controller.initiative_report())
            return

        if path == "/api/initiative/goto":
            body = self._read_json()
            self._send_json(self.controller.goto_turn(int(body.get("index", 0))))
            return

        if path == "/api/initiative/end":
            self.controller.end_initiative()
            self._send_json(self.controller.initiative_report())
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
        from ..registry import _REGISTRY, validate_params
        if name not in _REGISTRY or not callable(fn):
            self._send_json({"error": "no such action: %s" % name}, 400)
            return

        # Validate against the action's live choice-lists before dispatching.
        # Without this the controller's fault isolation swallows a bad value
        # and the caller is told "ok" while nothing happened.
        problem = validate_params(self.controller, name, params)
        if problem:
            self._send_json({"error": problem}, 400)
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
        subs = dict(st["subsystems"])

        # The controller only marks a subsystem unhealthy once a call has
        # FAILED. A device that never started (no images, no Pixelblaze,
        # no sound card) has failed nothing yet, so it would show green
        # while being unusable. Where a device reports its own health, let
        # that override - the strip exists to be trusted at a glance.
        for key, dev in (("lights", self.runtime.lights),
                          ("audio", self.controller.audio),
                          ("display", self.controller.display)):
            probe = getattr(dev, "status", None)
            if callable(probe):
                try:
                    info = probe()
                    if "healthy" in info:
                        subs[key] = subs[key] and bool(info["healthy"])
                except Exception:
                    pass

        out = {"subsystems": subs, "scene": st["scene"]}

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
