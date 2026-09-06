"""Panel endpoints for the sound effects.

Shaped like web/voice.py: pure delegation from server.py, everything guarded,
and the two writes that matter go through configstore so they persist the same
way the master volume does.

    GET  /api/sfx            state: master, families, counts, profiles
    GET  /api/sfx/sounds     all 54, with what each is for and whether it is on
    POST /api/sfx/enabled    master on/off
    POST /api/sfx/family     one family on/off
    POST /api/sfx/mute       one sound on/off
    POST /api/sfx/profile    apply a named set
    POST /api/sfx/play       audition one, ignoring every toggle
"""

from __future__ import annotations

PREFIX = "/api/sfx"


class SfxPanel(object):
    def __init__(self, runtime, controller, log):
        self.runtime = runtime
        self.controller = controller
        self.log = log

    @property
    def sfx(self):
        return getattr(self.controller, "sfx", None)

    def _settings(self):
        return self.runtime.store.config.sound_effects

    def route(self, handler, method: str, path: str) -> bool:
        if not path.startswith(PREFIX):
            return False
        rest = path[len(PREFIX):].strip("/")
        try:
            self._dispatch(handler, method, rest)
        except Exception as exc:      # noqa: BLE001
            self.log.record("sfx.api_error",
                            error="%s: %s" % (type(exc).__name__, exc))
            handler._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
        return True

    def _dispatch(self, handler, method, rest):
        if method == "GET" and rest == "":
            handler._send_json(self.status())
            return

        if method == "GET" and rest == "sounds":
            sfx = self.sfx
            handler._send_json({"sounds": sfx.listing() if sfx else []})
            return

        if method == "POST" and rest == "enabled":
            body = handler._read_json()
            self.runtime.store.set_sfx(enabled=bool(body.get("enabled")))
            self._start_if_needed()
            handler._send_json(self.status())
            return

        if method == "POST" and rest == "family":
            body = handler._read_json()
            self.runtime.store.set_sfx(family=body.get("family"),
                                       on=bool(body.get("on")))
            handler._send_json(self.status())
            return

        if method == "POST" and rest == "mute":
            body = handler._read_json()
            sid = str(body.get("sound") or "")
            settings = self._settings()
            muted = set(settings.muted)
            # `on` is the sound's desired state, so muting is its inverse.
            if body.get("on"):
                muted.discard(sid)
            else:
                muted.add(sid)
            self.runtime.store.set_sfx(muted=sorted(muted))
            handler._send_json(self.status())
            return

        if method == "POST" and rest == "profile":
            body = handler._read_json()
            name = str(body.get("profile") or "")
            from ..sfx import PROFILES
            if name not in PROFILES:
                handler._send_json({"error": "no such profile: %s" % name}, 400)
                return
            self.runtime.store.set_sfx(profile=name)
            handler._send_json(self.status())
            return

        if method == "POST" and rest == "play":
            body = handler._read_json()
            sfx = self.sfx
            if sfx is None:
                handler._send_json({"error": "Sound effects are not running."}, 503)
                return
            sid = str(body.get("sound") or "")
            # force=True: the audition button must work on a muted sound,
            # otherwise you cannot hear the thing you are deciding about.
            ok = sfx.play(sid, force=True)
            handler._send_json({"ok": ok, "sound": sid} if ok
                               else {"error": "Could not play %r." % sid},
                               200 if ok else 400)
            return

        handler._send_json({"error": "unknown endpoint"}, 404)

    # --- helpers ----------------------------------------------------------

    def _start_if_needed(self):
        """Turning it on from the panel should not need a restart."""
        settings = self._settings()
        if settings.enabled and self.sfx is None:
            from ..sfx import SoundEffects
            sfx = SoundEffects(settings, self.controller.audio, self.log)
            if sfx.start():
                self.controller.sfx = sfx

    def status(self) -> dict:
        sfx = self.sfx
        if sfx is not None:
            out = sfx.status()
        else:
            settings = self._settings()
            from ..sfx import FAMILIES, PROFILES
            out = {
                "enabled": settings.enabled,
                "healthy": False,
                "error": ("Turned off." if not settings.enabled else
                          "Enabled but not started -- check spec and audio_dir "
                          "in the table's config."),
                "sounds": 0, "missing": 0, "last_played": None,
                "families": [{"name": f, "on": settings.family_on(f),
                              "count": 0, "muted": 0,
                              "ducks": settings.duck_for(f)} for f in FAMILIES],
                "profiles": sorted(PROFILES),
            }
        out["running"] = sfx is not None
        return out
