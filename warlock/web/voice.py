"""Panel endpoints for the Entity voice.

Small enough to sit under /api/action's neighbour rather than earning a whole
surface of its own, but kept in its own file for the same reason web/maps.py
is: none of this belongs in server.py's dispatch, and the guard for "no voice
configured" wants somewhere to live.

Two of these -- enabled and chattiness -- write config through the store, the
same way the master volume does. The rest are read-only or fire-and-forget.
"""

from __future__ import annotations

from typing import Optional

PREFIX = "/api/voice"


class VoicePanel(object):
    def __init__(self, runtime, controller, log):
        self.runtime = runtime
        self.controller = controller
        self.log = log

    # --- plumbing ---------------------------------------------------------

    @property
    def voice(self):
        return getattr(self.controller, "voice", None)

    def _settings(self):
        return self.runtime.store.config.entity_voice

    def route(self, handler, method: str, path: str) -> bool:
        if not path.startswith(PREFIX):
            return False
        rest = path[len(PREFIX):].strip("/")
        try:
            self._dispatch(handler, method, rest)
        except Exception as exc:      # noqa: BLE001
            self.log.record("voice.api_error",
                            error="%s: %s" % (type(exc).__name__, exc))
            handler._send_json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
        return True

    def _dispatch(self, handler, method, rest):
        if method == "GET" and rest == "":
            handler._send_json(self.status())
            return

        if method == "GET" and rest == "lines":
            voice = self.voice
            handler._send_json({"lines": voice.lines() if voice else []})
            return

        if method == "POST" and rest == "enabled":
            body = handler._read_json()
            handler._send_json(self.set_enabled(bool(body.get("enabled"))))
            return

        if method == "POST" and rest == "chattiness":
            body = handler._read_json()
            handler._send_json(self.set_chattiness(body.get("chattiness")))
            return

        if method == "POST" and rest == "mood":
            body = handler._read_json()
            mood = body.get("mood") or ""
            self.runtime.store.set_voice(mood=mood)
            if self.voice is not None:
                self.voice.set_mood(mood or None)
            handler._send_json(self.status())
            return

        if method == "POST" and rest == "say":
            body = handler._read_json()
            line_id = body.get("line") or ""
            voice = self.voice
            if voice is None:
                handler._send_json({"error": "The table's voice is not "
                                             "running."}, 503)
                return
            # The manual path: no probability, no cooldown, no gesture
            # suppression. If the panel asks for a line, it gets that line.
            ok = voice.say(line_id)
            handler._send_json({"ok": ok, "line": line_id} if ok else
                               {"error": "No line %r, or its audio is "
                                         "missing." % line_id}, 200 if ok else 400)
            return

        handler._send_json({"error": "unknown endpoint"}, 404)

    # --- operations -------------------------------------------------------

    def status(self) -> dict:
        settings = self._settings()
        voice = self.voice
        if voice is not None:
            out = voice.status()
        else:
            # Configured but not running, or not configured at all. Say which
            # rather than reporting a bare "off" the operator cannot act on.
            out = {
                "enabled": settings.enabled,
                "healthy": False,
                "error": ("Turned off." if not settings.enabled else
                          "The voice is enabled but did not start -- check "
                          "lines_json and audio_dir in the table's config."),
                "chattiness": settings.chattiness,
                "mood": settings.mood,
                "speaking": False,
                "lines": 0,
            }
        out["running"] = voice is not None
        return out

    def set_enabled(self, enabled: bool) -> dict:
        """Turn the Entity on or off, persistently.

        Off takes effect at once -- the decision path returns before anything
        else. A line already sounding is allowed to finish rather than being
        cut mid-word, which reads as a fault rather than a silence.

        Turning it ON when nothing is loaded starts it here, so the operator
        does not have to restart the service to get a voice.
        """
        self.runtime.store.set_voice(enabled=enabled)
        settings = self._settings()

        if enabled and self.voice is None:
            from ..entity import EntityVoice
            voice = EntityVoice(settings, self.controller.audio, self.log)
            if voice.start():
                self.controller.voice = voice
        elif not enabled and self.voice is not None:
            self.voice.stop_pending()

        self.log.record("voice.enabled", enabled=enabled)
        return self.status()

    def set_chattiness(self, value) -> dict:
        """0.0 silent, 0.5 the configured rates, 1.0 everything.

        Scales the cooldown as well as the probability. A version that moved
        only the probability would look broken at the top: every trigger at
        1.0 still yields one line per cooldown period, so the tester turns it
        to maximum, hears one line, then silence.
        """
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.5
        self.runtime.store.set_voice(chattiness=value)
        self.log.record("voice.chattiness", value=self._settings().chattiness)
        return self.status()
