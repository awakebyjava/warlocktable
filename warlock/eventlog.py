"""Event log (plan doc section 4.3 / open question 8).

Every meaningful thing the table does gets recorded here. Two reasons:

1. Answering "why did the table just do that?" without SSHing in and squinting.
2. It is the substrate for the session-recap feature (section 3.10) later on.

Kept deliberately simple: append-only, one JSON object per line ("JSON Lines").
That format is trivial to write, trivial to tail, and trivial to parse later.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, List, Optional, TextIO


class EventLog:
    def __init__(self, path: Optional[str] = None, echo: bool = False,
                 stream: Optional[TextIO] = None):
        """path   — file to append to, or None to keep events in memory only.
        echo   — also print a human-readable line (used by the fake CLI).
        stream — where echoed lines go; defaults to stdout.
        """
        self.path = path
        self.echo = echo
        self.stream = stream or sys.stdout
        self.events: List[Dict[str, Any]] = []

    def record(self, kind: str, **fields: Any) -> Dict[str, Any]:
        event = {"ts": time.time(), "kind": kind}
        event.update(fields)
        self.events.append(event)

        if self.path:
            # Failing to write a log line must never take the table down.
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event) + "\n")
            except OSError as exc:
                print("[eventlog] could not write: %s" % exc, file=sys.stderr)

        if self.echo:
            print(self._humanize(event), file=self.stream)

        return event

    @staticmethod
    def _humanize(event: Dict[str, Any]) -> str:
        parts = [
            "%s=%s" % (k, v)
            for k, v in event.items()
            if k not in ("ts", "kind")
        ]
        detail = ("  " + " ".join(parts)) if parts else ""
        return "· %-18s%s" % (event["kind"], detail)

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.events[-limit:]
