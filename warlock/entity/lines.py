"""The line database: loading entity-lines.json and indexing it into pools.

Nothing here decides anything. It answers "what could be said for this
trigger", in preference order, and the picker chooses.

THE FIELDS THAT MATTER AT RUNTIME are `id`, `trigger`, `trigger_category` and
`mood`. `reaction`, `line` and `delivery` are authoring notes -- kept, because
they make a log line readable ("said: Ah. Now we're honest."), but never used
to choose anything.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

# The last-resort pool. Its trigger id, and also its category name.
GENERAL_TRIGGER = "any_voice_eligible"
GENERAL_CATEGORY = "general"


class Line(object):
    __slots__ = ("id", "trigger", "category", "mood", "mask_slip",
                 "text", "delivery", "path")

    def __init__(self, raw: Dict, audio_dir: str):
        self.id = raw.get("id", "")
        self.trigger = raw.get("trigger", "")
        self.category = raw.get("trigger_category", "")
        self.mood = raw.get("mood")
        self.mask_slip = bool(raw.get("mask_slip"))
        self.text = raw.get("line", "")
        self.delivery = raw.get("delivery", "")

        # DERIVED FROM THE ID, deliberately, NOT from the `audio_file` field.
        # That field says ".mp3" throughout while the renderer now emits
        # ".wav" -- following it would mean 91 missing files. The primer flags
        # this; the id is the filename stem by definition, so use it.
        self.path = os.path.join(audio_dir, "%s.wav" % self.id)

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def to_dict(self) -> Dict:
        return {"id": self.id, "trigger": self.trigger,
                "category": self.category, "mood": self.mood,
                "mask_slip": self.mask_slip, "text": self.text,
                "present": self.exists}

    def __repr__(self):
        return "Line(%s, %s)" % (self.id, self.mood)


class LineLibrary(object):
    """Every line, indexed by trigger and by category."""

    def __init__(self, lines: Optional[List[Line]] = None):
        self.lines: List[Line] = list(lines or [])
        self.by_id: Dict[str, Line] = {}
        self.by_trigger: Dict[str, List[Line]] = {}
        self.by_category: Dict[str, List[Line]] = {}
        self._reindex()

    def _reindex(self) -> None:
        self.by_id = {}
        self.by_trigger = {}
        self.by_category = {}
        for line in self.lines:
            self.by_id[line.id] = line
            self.by_trigger.setdefault(line.trigger, []).append(line)
            self.by_category.setdefault(line.category, []).append(line)

    # --- loading ----------------------------------------------------------

    @classmethod
    def load(cls, json_path: str, audio_dir: str) -> "LineLibrary":
        """Read the database. Raises only if the file itself is unusable."""
        with open(json_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        lines = [Line(entry, audio_dir)
                 for entry in raw.get("lines", [])
                 if entry.get("id")]
        return cls(lines)

    # --- what could be said -----------------------------------------------

    def pool_for(self, trigger: str) -> List[Line]:
        """Candidate lines for a trigger, in the primer's preference order.

        1. the exact trigger
        2. everything in its category
        3. the general pool

        Each step is tried only if the one before it came back empty, so a
        trigger with its own lines never dilutes them with the category.
        """
        exact = self.by_trigger.get(trigger)
        if exact:
            return exact

        # Category is derived from the trigger's own lines where possible;
        # for a trigger with no lines at all, fall through to general.
        category = self.category_of(trigger)
        if category:
            pool = self.by_category.get(category)
            if pool:
                return pool

        return self.by_category.get(GENERAL_CATEGORY, [])

    def category_of(self, trigger: str) -> Optional[str]:
        lines = self.by_trigger.get(trigger)
        if lines:
            return lines[0].category
        # A trigger nobody wrote lines for still has a guessable family --
        # "tarot_boon_any" -> "tarot_boon" -- so a new card can borrow its
        # siblings' lines without anything being rewritten.
        for category in sorted(self.by_category, key=len, reverse=True):
            if category != GENERAL_CATEGORY and trigger.startswith(category):
                return category
        return None

    def playable(self, lines: List[Line]) -> List[Line]:
        """Drop lines whose audio is missing. Not all 91 are always rendered."""
        return [ln for ln in lines if ln.exists]

    # --- reporting --------------------------------------------------------

    def missing(self) -> List[str]:
        return [ln.id for ln in self.lines if not ln.exists]

    def summary(self) -> Dict:
        return {
            "lines": len(self.lines),
            "missing": len(self.missing()),
            "triggers": len(self.by_trigger),
            "categories": sorted(self.by_category),
            "moods": sorted({ln.mood for ln in self.lines if ln.mood}),
        }
