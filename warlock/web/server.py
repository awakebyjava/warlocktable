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


# Paths anyone on the LAN may reach with no session (plan doc 4.8, access
# table). Everything else under /api, and every operator page, needs a
# GM session. Guests must keep the ten-second join: name, seat, dice,
# whispers -- so the whole player surface is here. Prefix matches.
PUBLIC_PREFIXES = (
    "/api/join", "/api/qr.svg", "/api/auth/",
    "/api/player/", "/api/seats/claim", "/api/seats/release", "/api/zones",
)


class _Handler(BaseHTTPRequestHandler):
    # Injected by make_server()
    controller = None
    runtime = None
    auth = None                 # warlock.auth.Auth
    maps = None                 # web.maps.MapsPanel, or None if not wired
    voice = None                # web.voice.VoicePanel, or None if not wired
    sfx = None                  # web.sfx.SfxPanel, or None if not wired
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

        # An ETag so revalidation costs a 304 rather than the whole file.
        # mtime and size, not a hash of the body: this runs on a Pi serving
        # a tablet over wifi, and hashing every asset on every request buys
        # nothing a deploy-shaped change cannot already be seen in.
        st = os.stat(path)
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)

        is_font = "/fonts/" in path.replace("\\", "/")
        if not is_font and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if is_font:
            # Fonts are the one thing here that genuinely does not change;
            # when one does it arrives under a new filename.
            self.send_header("Cache-Control", "public, max-age=604800")
        else:
            # EVERYTHING ELSE MUST REVALIDATE. This previously sent no
            # cache headers at all for the HTML, CSS and JS, which does not
            # mean "do not cache" -- with no directive and no validator a
            # browser may reuse a response indefinitely on its own
            # judgement. It did: a deployed redesign kept rendering with
            # the previous stylesheet, panels stacked in one column with no
            # tab bar, and the only clue was that the files on the Pi were
            # demonstrably correct.
            #
            # `no-cache` is not `no-store`: the copy is still kept, and the
            # service worker still has a shell to serve when the table is
            # unreachable. It just has to ask first, and the ETag makes
            # asking cheap.
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------- who is this

    def _who(self):
        """(user, session, token) from the cookie; cached per request."""
        if not hasattr(self, "_who_cache"):
            if self.auth is None:
                self._who_cache = (None, None, None)
            else:
                self._who_cache = self.auth.resolve(self.headers.get("Cookie"))
        return self._who_cache

    def _is_gm(self) -> bool:
        """A signed-in session in GM mode. The admin is a GM whenever they
        are signed in as one, like anyone else -- being admin is about
        what you may EDIT, not whether you are running the table tonight."""
        user, sess, _ = self._who()
        return user is not None and sess is not None and sess.mode == "gm"

    def _is_admin(self) -> bool:
        user, _, _ = self._who()
        return user is not None and user.role == "admin"

    def _gate(self, path: str) -> bool:
        """Refuse an operator route without a GM session. True = refused.

        API calls get 401 JSON, never a redirect: a fetch that follows a
        redirect to an HTML login page is the classic "why is my JSON a
        <!DOCTYPE" bug. Operator PAGES get the login page instead, which
        is what a person holding an iPad wants to see.
        """
        if self.auth is None:
            return False
        if path.startswith("/api/"):
            if any(path.startswith(p) for p in PUBLIC_PREFIXES):
                return False
            if self._is_gm():
                return False
            self._send_json({"error": "sign in as GM to use the panel",
                             "login": "/"}, 401)
            return True
        return False

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ------------------------------------------------------------------ GET

    # ---- map import ------------------------------------------------------

    def _maps(self, method: str, path: str) -> bool:
        """Hand /api/maps/* to the map import panel. Returns True if handled.

        All the logic lives in web/maps.py; this is pure delegation, and the
        guard means a build without map import wired still answers the rest of
        the panel normally.
        """
        if self.maps is None or not path.startswith("/api/maps"):
            return False
        return self.maps.route(self, method, path)

    def _voice_api(self, method: str, path: str) -> bool:
        """Hand /api/voice/* to the voice panel. Pure delegation, same as
        _maps -- see web/voice.py."""
        if self.voice is None or not path.startswith("/api/voice"):
            return False
        return self.voice.route(self, method, path)

    def _sfx_api(self, method: str, path: str) -> bool:
        if self.sfx is None or not path.startswith("/api/sfx"):
            return False
        return self.sfx.route(self, method, path)

    def _sounds_api(self, method: str, path: str) -> bool:
        """Hand /api/sounds/* to the audio upload panel. See web/sounds.py."""
        if getattr(self, "sounds", None) is None                 or not path.startswith("/api/sounds"):
            return False
        return self.sounds.route(self, method, path)

    def do_PUT(self):
        # PUT exists solely for map upload: the body IS the file, which avoids
        # multipart parsing in a stdlib server. See web/maps.py.
        path = self.path.split("?", 1)[0]
        if self._gate(path):
            return
        if self._maps("PUT", path):
            return
        if self._sounds_api("PUT", path):
            return
        self._send_json({"error": "unknown endpoint"}, 404)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if self._auth_api("GET", path):
            return
        if self._gate(path):
            return
        if self._campaign_api("GET", path):
            return
        if self._maps("GET", path):
            return
        if self._voice_api("GET", path):
            return
        if self._sfx_api("GET", path):
            return
        if self._sounds_api("GET", path):
            return

        # Three front doors. The QR code on the table points at "/", which
        # asks who you are; the GM's iPad goes straight to "/gm" (the PWA's
        # start_url), and a player lands on "/player" after choosing.
        if path == "/":
            # The front door: set-up until there is an admin with a PIN,
            # then the profile picker. The old player-or-GM chooser lives
            # on as the guest's path through the picker.
            if self.auth is not None and self.auth.users.needs_setup():
                self._send_static("setup.html")
            else:
                self._send_static("login.html")
        elif path == "/gm":
            # The PWA's start_url. Signed in as GM: the panel. Otherwise the
            # login page, at this address, so the installed app opens on
            # the right screen after a session expires.
            if self.auth is not None and not self._is_gm():
                if self.auth.users.needs_setup():
                    self._send_static("setup.html")
                else:
                    self._send_static("login.html")
            else:
                self._send_static("index.html")
        elif path == "/player":
            self._send_static("player.html")
        elif path == "/api/join":
            self._send_json(self._join_info())
        elif path == "/api/qr.svg":
            self._send_qr()
        elif path == "/api/recording":
            self._send_json(self.controller.recording_report())
        elif path == "/api/audio":
            self._send_json(self.controller.audio_report())
        elif path == "/api/initiative":
            self._send_json(self.controller.initiative_report())
        elif path == "/api/signals":
            self._send_json(self.controller.signal_report())
        elif path == "/api/rolls":
            self._send_json(self.controller.roll_log())
        elif path.startswith("/api/player/rolls"):
            from urllib.parse import parse_qs
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            self._send_json(self.controller.roll_history(
                (query.get("colour") or [""])[0]))
        elif path == "/api/whispers":
            # Every thread. The GM panel's view -- players use
            # /api/player/whisper?colour=..., which returns only theirs.
            self._send_json(self.controller.whisper_threads())
        elif path.startswith("/api/player/whisper"):
            from urllib.parse import parse_qs
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            self._send_json(self.controller.whisper_thread(
                (query.get("colour") or [""])[0]))
        elif path == "/api/dice":
            self._send_json(self._dice())
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
            self._send_json({"cards": self.runtime.store.list_cards(),
                             "campaign": self._campaign()})
        elif path == "/api/config/scenes":
            self._send_json({
                "scenes": self.runtime.store.list_scenes(),
                "options": self.runtime.store.scene_options(self.controller),
                "idle_scene": self.controller.config.idle_scene_name,
            })
        elif path == "/api/config/interruptions":
            self._send_json({
                "interruptions": self.runtime.store.list_interruptions(),
                "options": self.runtime.store.interruption_options(
                    self.controller),
            })
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
        if self._auth_api("DELETE", path):
            return
        if self._gate(path):
            return
        if self._maps("DELETE", path):
            return
        if self._dice_api("DELETE", path):
            return
        if self._sounds_api("DELETE", path):
            return
        if path.startswith("/api/config/scenes/"):
            name = _unquote(path[len("/api/config/scenes/"):])
            from ..config import ConfigError
            try:
                self.runtime.store.delete_scene(name)
            except ConfigError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json({"ok": True,
                             "scenes": self.runtime.store.list_scenes()})
            return

        if path.startswith("/api/config/interruptions/"):
            name = _unquote(path[len("/api/config/interruptions/"):])
            from ..config import ConfigError
            try:
                self.runtime.store.delete_interruption(name)
            except ConfigError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json({
                "ok": True,
                "interruptions": self.runtime.store.list_interruptions()})
            return

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
            store.persist()
        except Exception as exc:   # noqa: BLE001
            self.runtime.log.record("seat.persist_failed", error=str(exc))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if self._auth_api("POST", path):
            return
        if self._gate(path):
            return
        if self._campaign_api("POST", path):
            return
        if self._dice_api("POST", path):
            return
        if self._maps("POST", path):
            return
        if self._voice_api("POST", path):
            return
        if self._sfx_api("POST", path):
            return

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
        # --- player phone: the `?` and `!` (plan doc 3.7) -----------------
        #
        # Under /api/player/, not /api/action/, deliberately. /api/action
        # is the GM's vocabulary and anything routed through it shows up as
        # a button on the operator panel. A player raising a hand is not a
        # thing the GM should be able to do on their behalf.
        # The GM's own roller. Separate from the player endpoint so the
        # two identities cannot be confused, and so a GM roll is obviously
        # a GM roll in the log rather than a seat colour nobody sits at.
        if path == "/api/roll":
            body = self._read_json()
            try:
                entry = self.controller.roll(
                    colour=self.controller.GM_KEY,
                    count=body.get("count", 0),
                    sides=body.get("sides", 0),
                    name="GM")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(entry)
            return

        if path == "/api/player/roll":
            body = self._read_json()
            try:
                entry = self.controller.roll(
                    colour=str(body.get("colour", "")),
                    count=body.get("count", 0),
                    sides=body.get("sides", 0),
                    name=str(body.get("name", "")))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(entry)
            return

        if path == "/api/player/whisper":
            body = self._read_json()
            try:
                thread = self.controller.whisper(
                    colour=str(body.get("colour", "")),
                    text=str(body.get("text", "")),
                    sender="player",
                    name=str(body.get("name", "")))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(thread)
            return

        if path == "/api/whispers/reply":
            body = self._read_json()
            try:
                thread = self.controller.whisper(
                    colour=str(body.get("colour", "")),
                    text=str(body.get("text", "")),
                    sender="gm")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(thread)
            return

        if path == "/api/player/signal":
            body = self._read_json()
            try:
                report = self.controller.raise_signal(
                    colour=str(body.get("colour", "")),
                    kind=str(body.get("kind", "")),
                    name=str(body.get("name", "")))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(report)
            return

        if path == "/api/signals/clear":
            body = self._read_json()
            try:
                report = self.controller.clear_signal(
                    str(body.get("colour", "")))
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(report)
            return

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

        if path == "/api/seats/release":
            # One endpoint, two callers. The GM sends a colour ("whoever is
            # in that chair, out"); a player sends their own name ("I am
            # leaving"). Neither has to look up what the other knows -- see
            # controller.release_seat.
            body = self._read_json()
            colour = str(body.get("colour", "")).strip()
            name = str(body.get("name", "")).strip()
            if not colour and not name:
                self._send_json({"error": "a seat colour or a name is needed"}, 400)
                return
            try:
                freed = self.controller.release_seat(colour=colour, player_name=name)
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            if freed:
                self._persist_players()
            # Not an error when the seat was already empty: two GMs tapping
            # the same "remove" is a race, not a fault, and the second one
            # should see the seat empty rather than a red line.
            self._send_json({"ok": True, "freed": freed,
                              "zones": self.controller.zone_report()})
            return

        # --- Initiative (plan doc 3.9): GM only. Player turns, in the order
        # the GM tapped them. Nothing is parsed or sorted here.
        if path == "/api/initiative/order":
            body = self._read_json()
            try:
                report = self.controller.set_initiative_order(
                    body.get("order") or [])
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json(report)
            return

        if path == "/api/initiative/run":
            self.controller.run_initiative()
            self._send_json(self.controller.initiative_report())
            return

        if path == "/api/initiative/advance":
            body = self._read_json()
            self.controller.advance_turn(int(body.get("step", 1)))
            self._send_json(self.controller.initiative_report())
            return

        if path == "/api/initiative/stop":
            self.controller.stop_initiative()
            self._send_json(self.controller.initiative_report())
            return

        if path == "/api/initiative/clear":
            self._send_json(self.controller.clear_initiative())
            return

        if path == "/api/config/scenes":
            body = self._read_json()
            from ..config import ConfigError
            try:
                result = self.runtime.store.set_scene(
                    name=body.get("name", ""),
                    lights=body.get("lights", ""),
                    soundscape=body.get("soundscape"),
                    background=body.get("background"),
                    crossfade_s=body.get("crossfade_s"),
                    duck=body.get("duck"),
                    # Validated against what the devices actually have, so a
                    # scene cannot be saved naming something that is not there.
                    options=self.runtime.store.scene_options(self.controller),
                )
            except ConfigError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json({"ok": True, "scene": result,
                             "scenes": self.runtime.store.list_scenes()})
            return

        if path == "/api/config/interruptions":
            body = self._read_json()
            from ..config import ConfigError
            try:
                result = self.runtime.store.set_interruption(
                    name=body.get("name", ""),
                    audio=body.get("audio"),
                    lights=body.get("lights"),
                    background=body.get("background"),
                    duck=body.get("duck"),
                    duration_s=body.get("duration_s"),
                    options=self.runtime.store.interruption_options(
                        self.controller),
                )
            except ConfigError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:   # noqa: BLE001
                self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
                return
            self._send_json({
                "ok": True, "interruption": result,
                "interruptions": self.runtime.store.list_interruptions()})
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

        # A panel press is a fresh gesture. Everything it cascades into gets
        # one voice decision between it -- see warlock/entity/picker.py.
        self.controller.begin_gesture()

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

        # Carry through anything else the controller reported -- signals
        # ride here so the player bar costs no extra poll. Copying the
        # two keys by hand is why signals silently never reached the
        # panel the first time.
        out = {k: v for k, v in st.items() if k != "subsystems"}
        out["subsystems"] = subs

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
        dice = getattr(self.controller, "_dice_status", None)
        if callable(dice):
            out["dice"] = dice()
        out["version"] = _read_version()
        return out

    # ---- accounts (plan doc 4.8) -------------------------------------------

    def _me(self) -> dict:
        user, sess, _ = self._who()
        if user is None:
            return {"signed_in": False, "setup": bool(self.auth and self.auth.users.needs_setup())}
        return {"signed_in": True, "id": user.id, "name": user.name,
                "role": user.role, "mode": sess.mode,
                "setup": False}

    def _auth_api(self, method: str, path: str) -> bool:
        """Login, logout, set-up, and the admin's user management."""
        if self.auth is None or not path.startswith("/api/auth/"):
            return False
        from ..auth import AuthError, ADMIN, GM, PLAYER, MODES
        from ..auth import clear_cookie_header, set_cookie_header
        from ..config import ConfigError
        users, sessions = self.auth.users, self.auth.sessions
        try:
            # ---- anyone
            if method == "GET" and path == "/api/auth/me":
                self._send_json(self._me())
                return True
            if method == "GET" and path == "/api/auth/users":
                # The picker: names only. Names at a table are not secret;
                # emails and everything else are the admin's.
                self._send_json({"users": users.listing(),
                                 "setup": users.needs_setup()})
                return True
            if method == "POST" and path == "/api/auth/setup":
                # Only while there is no usable admin. Creates the admin,
                # or gives a PIN-less admin (after --reset-admin-pin) one.
                if not users.needs_setup():
                    self._send_json({"error": "already set up"}, 400)
                    return True
                body = self._read_json()
                pin = str(body.get("pin", ""))
                admin = users.admin()
                if admin is None:
                    admin = users.create(body.get("name", ""), body.get("email", ""),
                                         ADMIN, pin)
                else:
                    users.set_pin(admin.id, pin)
                token = sessions.issue(admin.id, GM)
                self._open_for(admin)
                self._send_json_with_cookie(self._me_for(admin, GM), set_cookie_header(token))
                return True
            if method == "POST" and path == "/api/auth/login":
                body = self._read_json()
                user_id = str(body.get("user", ""))
                mode = str(body.get("mode", PLAYER))
                if mode not in MODES:
                    self._send_json({"error": "mode must be gm or player"}, 400)
                    return True
                user = users.get(user_id)
                if user is None:
                    self._send_json({"error": "no such account"}, 404)
                    return True
                if not user.has_pin:
                    # First login after a reset: this call SETS the PIN.
                    pin = str(body.get("new_pin", ""))
                    users.set_pin(user.id, pin)
                else:
                    try:
                        users.verify(user.id, str(body.get("pin", "")))
                    except AuthError as exc:
                        import time as _time
                        _time.sleep(1.0)          # the deliberate cost of a wrong PIN
                        self._send_json({"error": str(exc)}, 403)
                        return True
                token = sessions.issue(user.id, mode)
                self.runtime.log.record("auth.login", user=user.id, mode=mode)
                if mode == GM:
                    self._open_for(user)
                self._send_json_with_cookie(self._me_for(user, mode), set_cookie_header(token))
                return True
            if method == "POST" and path == "/api/auth/logout":
                _, _, token = self._who()
                sessions.revoke(token)
                self._send_json_with_cookie({"signed_in": False}, clear_cookie_header())
                return True
            if method == "POST" and path == "/api/auth/mode":
                # Switch chairs without signing in again.
                user, sess, token = self._who()
                if user is None:
                    self._send_json({"error": "not signed in"}, 401)
                    return True
                mode = str(self._read_json().get("mode", ""))
                sessions.set_mode(token, mode)
                if mode == GM:
                    self._open_for(user)
                self._send_json(self._me_for(user, mode))
                return True
            if method == "POST" and path == "/api/auth/pin":
                # Your own PIN.
                user, _, _ = self._who()
                if user is None:
                    self._send_json({"error": "not signed in"}, 401)
                    return True
                body = self._read_json()
                try:
                    users.verify(user.id, str(body.get("pin", "")))
                except AuthError as exc:
                    self._send_json({"error": str(exc)}, 403)
                    return True
                users.set_pin(user.id, str(body.get("new_pin", "")))
                self._send_json({"ok": True})
                return True
            # ---- admin only from here
            if not self._is_admin():
                self._send_json({"error": "admin only"}, 403 if self._who()[0] else 401)
                return True
            if method == "GET" and path == "/api/auth/admin/users":
                self._send_json({"users": [
                    {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
                     "has_pin": u.has_pin, "created": u.created}
                    for u in users.users.values()]})
                return True
            if method == "POST" and path == "/api/auth/admin/users":
                body = self._read_json()
                u = users.create(body.get("name", ""), body.get("email", ""),
                                 body.get("role") or "user", body.get("pin") or None)
                self._send_json({"ok": True, "id": u.id})
                return True
            if path.startswith("/api/auth/admin/users/"):
                rest = _unquote(path[len("/api/auth/admin/users/"):])
                user_id, _, action = rest.partition("/")
                if method == "POST" and action == "reset-pin":
                    users.clear_pin(user_id)
                    sessions.revoke_user(user_id)
                    self._send_json({"ok": True})
                    return True
                if method == "POST" and action == "":
                    body = self._read_json()
                    u = users.update(user_id, body.get("name"), body.get("email"),
                                     body.get("role"))
                    self._send_json({"ok": True, "id": u.id})
                    return True
                if method == "GET" and action == "footprint":
                    self._send_json(self._user_footprint(user_id))
                    return True
                if method == "GET" and action == "export":
                    self._send_user_export(user_id)
                    return True
                if method == "DELETE" and action == "":
                    user = users.get(user_id)
                    if user is None:
                        self._send_json({"error": "no such account"}, 404)
                        return True
                    # If their library is the one running, run the shared one
                    # instead before the folder goes.
                    if getattr(self.runtime, "open_profile_id", None) == user_id:
                        self.runtime.open_profile(None, "shared")
                    footprint = self._user_footprint(user_id)
                    users.delete(user_id)
                    sessions.revoke_user(user_id)
                    self._remove_user_library(user_id)
                    self._send_json({"ok": True, "removed": footprint})
                    return True
            return False
        except ConfigError as exc:
            self._send_json({"error": str(exc)}, 400)
            return True
        except KeyError:
            self._send_json({"error": "no such account"}, 404)
            return True

    def _user_dir(self, user_id: str) -> str:
        import os as _os
        return _os.path.join(_os.path.dirname(_os.path.abspath(self.runtime.store.path)),
                             "profiles", user_id)

    def _user_footprint(self, user_id: str) -> dict:
        """What deleting this user takes with it: the list 4.8 says to show.
        Their tags become unknown to the table entirely (decided
        2026-09-11); nothing is quietly handed to the deck."""
        import os as _os
        d = self._user_dir(user_id)
        out = {"scenes": 0, "interruptions": 0, "random_tables": 0, "cards": [],
               "maps": 0, "sounds": 0, "dir": d if _os.path.isdir(d) else None}
        lib = _os.path.join(d, "library.json")
        if _os.path.exists(lib):
            try:
                with open(lib, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                for k in ("scenes", "interruptions", "random_tables"):
                    out[k] = len(raw.get(k) or {})
                out["cards"] = [{"uid": uid, "label": c.get("label", "")}
                                for uid, c in (raw.get("cards") or {}).items()]
            except (OSError, ValueError):
                pass
        for kind in ("maps", "sounds"):
            p = _os.path.join(d, kind)
            if _os.path.isdir(p):
                out[kind] = sum(len(files) for _, _, files in _os.walk(p))
        return out

    def _remove_user_library(self, user_id: str) -> None:
        import os as _os
        import shutil as _shutil
        d = self._user_dir(user_id)
        if _os.path.isdir(d):
            _shutil.rmtree(d, ignore_errors=True)
            self.runtime.log.record("users.library_removed", user=user_id)

    def _send_user_export(self, user_id: str) -> None:
        """One user's whole folder as a zip -- the 4.4 backup requirement,
        per person. Built in memory; a library is small."""
        import io as _io
        import os as _os
        import zipfile
        user = self.auth.users.get(user_id)
        d = self._user_dir(user_id)
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if _os.path.isdir(d):
                for root, _, files in _os.walk(d):
                    for f in files:
                        full = _os.path.join(root, f)
                        zf.write(full, _os.path.relpath(full, d))
            zf.writestr("USER.json", json.dumps(
                {"id": user_id, "name": user.name if user else "",
                 "email": user.email if user else ""}, indent=2))
        body = buf.getvalue()
        safe = "".join(c if c.isalnum() else "-" for c in (user.name if user else user_id))
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition",
                         'attachment; filename="warlock-library-%s.zip"' % safe)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _me_for(self, user, mode: str) -> dict:
        return {"signed_in": True, "id": user.id, "name": user.name,
                "role": user.role, "mode": mode, "setup": False,
                "campaign": self._campaign()}

    # ---- whose library is running (plan doc 4.8, step 4) --------------------

    def _campaign(self) -> dict:
        rt = self.runtime
        store = getattr(rt, "store", None)
        locked = bool(store is not None and getattr(store, "profiles", None) is not None
                      and store.profiles.write_target == "private")
        return {"open": getattr(rt, "open_profile_id", None),
                "name": getattr(rt, "open_profile_name", None) or "shared",
                "source": getattr(rt, "config_source", ""),
                # While a private library is open, the deck is read-only
                # and new tags are the GM's own.
                "deck_locked": locked}

    def _open_for(self, user) -> None:
        """Take the table: the admin runs the shared library alone (they
        have no private one); anyone else runs theirs over it. Best effort
        on a single-file layout, where there is nothing to open."""
        from ..config import ConfigError
        try:
            if user.role == "admin":
                self.runtime.open_profile(None, user.name)
            else:
                self.runtime.open_profile(user.id, user.name)
        except ConfigError as exc:
            # Single-file layout, or a library that does not compose: the
            # login still succeeds -- the panel runs what was running --
            # and the reason is on the record.
            self.runtime.log.record("profile.open_failed", user=user.id, error=str(exc))

    def _campaign_api(self, method: str, path: str) -> bool:
        if not path.startswith("/api/campaign"):
            return False
        from ..config import ConfigError
        if method == "GET" and path == "/api/campaign":
            self._send_json(self._campaign())
            return True
        if method == "POST" and path == "/api/campaign/open":
            if not self._is_admin():
                self._send_json({"error": "admin only"}, 403)
                return True
            body = self._read_json()
            target = body.get("user") or None
            try:
                if target is None:
                    self.runtime.open_profile(None, "shared")
                else:
                    user = self.auth.users.get(str(target))
                    if user is None:
                        self._send_json({"error": "no such account"}, 404)
                        return True
                    if user.role == "admin":
                        self.runtime.open_profile(None, user.name)
                    else:
                        self.runtime.open_profile(user.id, user.name)
            except ConfigError as exc:
                self._send_json({"error": str(exc)}, 400)
                return True
            self._send_json(self._campaign())
            return True
        return False

    def _send_json_with_cookie(self, payload, cookie: str, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _dice(self) -> dict:
        """What the scanner hears, and what the config says to do about it."""
        out = self.runtime.store.list_dice()
        status = getattr(self.controller, "_dice_status", None)
        out["scanner"] = status() if callable(status) else None
        return out

    def _dice_api(self, method: str, path: str) -> bool:
        """The dice editor's writes. True if the path was ours."""
        if not path.startswith("/api/dice"):
            return False
        from ..config import ConfigError
        store = self.runtime.store
        try:
            if method == "POST" and path == "/api/dice/enabled":
                body = self._read_json()
                store.set_dice_enabled(bool(body.get("enabled")))
            elif method == "POST" and path == "/api/dice/known":
                body = self._read_json()
                store.set_known_die(body.get("die", ""), body.get("name", ""),
                                    body.get("type") or None, body.get("seat") or None)
            elif method == "DELETE" and path.startswith("/api/dice/known/"):
                store.delete_known_die(_unquote(path[len("/api/dice/known/"):]))
            elif method == "POST" and path == "/api/dice/triggers":
                body = self._read_json()
                store.set_dice_triggers(body.get("triggers") or [])
            else:
                return False
        except ConfigError as exc:
            self._send_json({"error": str(exc)}, 400)
            return True
        except Exception as exc:   # noqa: BLE001
            self._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
            return True
        self._send_json(self._dice())
        return True

    def _vocabulary(self) -> dict:
        cfg = self.controller.config
        return {
            "scenes": sorted(cfg.scenes),
            "interruptions": sorted(cfg.interruptions),
            "interruption_groups": _group_interruptions(cfg),
            "random_tables": sorted(cfg.random_tables),
            # "shared" / "private" per name, or absent for a single-file
            # config. The editors show "mine" against private entries.
            "owners": {kind: dict(cfg.library_owner.get(kind, {}))
                       for kind in ("scenes", "interruptions", "random_tables")},
            "idle_scene": cfg.idle_scene_name,
            "backgrounds": self.controller.background_choices(),
            "cue_groups": _group_cues(self.controller.audio.available_cues()),
            "cue_now": getattr(self.controller.audio, "cue", None),
        }

# The order the panel shows the groups in: the tarot first, because those are
# the ones reached for during play, then the playing cards, which are 54 of the
# 79 and would otherwise bury everything else.
_GROUP_ORDER = ("Boons", "Persons", "Auras", "Fortune",
                "Hearts", "Diamonds", "Clubs", "Spades", "Jokers", "Other")

# What the block is CALLED on screen, which is not the same as what it is
# keyed on. Keyed on the lights pattern, the three tarot blocks come out as
# "Boons", "Persons" and "Auras" -- the table's own vocabulary for what a card
# does, and meaningless to someone looking for The Tower. Prefixing them says
# which deck they came out of, which is the split the panel was asked for,
# without giving up the more useful sort underneath it.
_GROUP_LABELS = {
    "Boons":   "Tarot · Boons",
    "Persons": "Tarot · Figures",
    "Auras":   "Tarot · Forces",
    "Fortune": "Tarot · Fortune",
}

_SUITS = ("hearts", "diamonds", "clubs", "spades")


def _group_interruptions(config):
    """Sort the interruptions into named blocks for the Run panel.

    CLASSIFIED OFF THE LIGHTS PATTERN, which is the authoritative statement of
    what a card is and is already in the live config: Boon-Cups, Person-Fool,
    Aura-Tower, Card-Comet-Red.

    Not off warlock/entity/triggers, which was the obvious source and is
    wrong for this: that taxonomy comes from the voice line database, where
    the author grouped Justice and Death as "persons" while the card spec has
    them as auras and Fool and Lovers as persons. Both groupings are valid for
    their own purpose; the panel should show what the card DOES, and the
    pattern name is that.

    Playing cards take their suit from the name, since Card-Comet-Red covers
    both hearts and diamonds.
    """
    groups = {}
    for name in sorted(config.interruptions):
        entry = config.interruptions[name]
        lights = (getattr(entry, "lights", "") or "")
        low = name.lower()

        if lights.startswith("Boon-"):
            key = "Boons"
        elif lights.startswith("Person-"):
            key = "Persons"
        elif lights.startswith("Aura-"):
            key = "Auras"
        elif "joker" in low:
            key = "Jokers"
        elif "wheel" in low or "fortune" in low:
            key = "Fortune"
        else:
            key = next((suit.capitalize() for suit in _SUITS
                        if low.endswith("_of_" + suit)), "Other")
        groups.setdefault(key, []).append(name)

    return [{"name": _GROUP_LABELS.get(k, k), "items": groups[k]}
            for k in _GROUP_ORDER if groups.get(k)]


# Which block each music cue is shown in, and the order the blocks appear.
#
# The NAMES come from the device -- available_cues() reads a directory -- so
# dropping a new .ogg into the cue path makes it appear without touching this
# file. Only the grouping is here, and anything unrecognised falls into
# "Other" rather than vanishing, which is the failure that would otherwise be
# silent: a cue that exists on disk, plays fine from the API, and is simply
# not drawn.
_CUE_ORDER = ('Journey', 'Threat', 'Uncanny', 'Between', 'Aftermath')
_CUE_GROUPS = {
    'travel':       'Journey',
    'long_road':    'Journey',
    'arrival':      'Journey',
    'ambush':       'Threat',
    'combat':       'Threat',
    'stalking':     'Threat',
    'the_big_one':  'Threat',
    'arcane':       'Uncanny',
    'dread':        'Uncanny',
    'revelation':   'Uncanny',
    'rest':         'Between',
    'haven':        'Between',
    'intrigue':     'Between',
    'grief':        'Aftermath',
    'triumph':      'Aftermath',
}


def _group_cues(names):
    """Sort the available cues into named blocks for the Run panel."""
    groups = {}
    for name in names:
        groups.setdefault(_CUE_GROUPS.get(name, "Other"), []).append(name)
    ordered = [g for g in _CUE_ORDER if groups.get(g)]
    ordered += [g for g in sorted(groups) if g not in _CUE_ORDER]
    return [{"name": g, "items": sorted(groups[g])} for g in ordered]


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
        # One MapsPanel shared by every request thread: it holds the editing
        # sessions, so a slider move and the publish that follows have to
        # reach the same object.
        from .maps import MapsPanel
        from .voice import VoicePanel
        from .sfx import SfxPanel
        from .sounds import SoundsPanel
        handler = type("_BoundHandler", (_Handler,), {
            "controller": self.controller,
            "runtime": self.runtime,
            "auth": getattr(self.runtime, "auth", None),
            "maps": MapsPanel(self.runtime, self.controller, self.log),
            "voice": VoicePanel(self.runtime, self.controller, self.log),
            "sfx": SfxPanel(self.runtime, self.controller, self.log),
            "sounds": SoundsPanel(self.runtime, self.controller, self.log),
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
