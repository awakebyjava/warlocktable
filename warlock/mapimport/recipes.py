"""The recipe: everything needed to rebuild a map from its original.

A published map is three things -- the untouched upload, this recipe, and the
renders. The renders are the only one the table reads, and the only one that
is disposable.

WHY THIS EXISTS (spec section 11), because it is not obvious and it is the
first thing a future reader will be tempted to delete:

  1. Re-editing does not recompound. Adjusting a map next month re-renders
     from the original rather than resampling an already-resampled render.

  2. THE GRID CONSTANT STAYS SOFT. 107.85 was measured once against real
     miniatures and could be re-measured. With recipes, a re-measurement is a
     one-line change plus a batch re-render. Without them it is redoing every
     map by hand, which in practice means never fixing it and living with a
     wrong table forever.

  3. It is a repair path. A deleted or corrupted render is one command from
     being back.

Written as JSON with an explicit version, and read defensively: a recipe on
disk will outlive several versions of this code.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from . import grid
from .transform import Transform

RECIPE_VERSION = 1


class MapSpec(object):
    """A complete description of one published map."""

    def __init__(self,
                 slug: str,
                 title: str = "",
                 source_file: str = "",
                 source_width: int = 0,
                 source_height: int = 0,
                 transform: Optional[Transform] = None,
                 brightness: float = 1.0,
                 contrast: float = 1.0,
                 grid_pitch: float = grid.PITCH,
                 grid_offset_x: float = 0.0,
                 grid_offset_y: float = 0.0,
                 draw_grid: bool = True,
                 fit_choice: str = "manual",
                 feet_per_square: float = 5.0,
                 plain_black: bool = False,
                 detected: Optional[Dict[str, Any]] = None,
                 created: Optional[float] = None,
                 updated: Optional[float] = None):
        self.slug = slug
        self.title = title or slug
        self.source_file = source_file
        self.source_width = int(source_width)
        self.source_height = int(source_height)
        self.transform = transform or Transform()
        self.brightness = float(brightness)
        self.contrast = float(contrast)
        # The pitch the grid is DRAWN at. Normally grid.PITCH; stored
        # explicitly so a recipe records what it was actually rendered with
        # rather than what the constant happens to say today.
        self.grid_pitch = float(grid_pitch)
        self.grid_offset_x = float(grid_offset_x)
        self.grid_offset_y = float(grid_offset_y)
        self.draw_grid = bool(draw_grid)
        # "true_scale" | "cropped" | "scaled_down" | "manual"
        self.fit_choice = fit_choice
        self.feet_per_square = float(feet_per_square)
        self.plain_black = bool(plain_black)
        self.detected = detected or {}
        self.created = created or time.time()
        self.updated = updated or self.created

    # --- serialisation ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": RECIPE_VERSION,
            "slug": self.slug,
            "title": self.title,
            "source_file": self.source_file,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "transform": self.transform.to_dict(),
            "brightness": self.brightness,
            "contrast": self.contrast,
            "grid_pitch": self.grid_pitch,
            "grid_offset_x": self.grid_offset_x,
            "grid_offset_y": self.grid_offset_y,
            "draw_grid": self.draw_grid,
            "fit_choice": self.fit_choice,
            "feet_per_square": self.feet_per_square,
            "plain_black": self.plain_black,
            "detected": self.detected,
            "created": self.created,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MapSpec":
        """Read defensively. A recipe written by an older version must still
        load, with anything it did not know about taking today's default."""
        return cls(
            slug=raw.get("slug", ""),
            title=raw.get("title", ""),
            source_file=raw.get("source_file", ""),
            source_width=raw.get("source_width", 0),
            source_height=raw.get("source_height", 0),
            transform=Transform.from_dict(raw.get("transform")),
            brightness=raw.get("brightness", 1.0),
            contrast=raw.get("contrast", 1.0),
            grid_pitch=raw.get("grid_pitch", grid.PITCH),
            grid_offset_x=raw.get("grid_offset_x", 0.0),
            grid_offset_y=raw.get("grid_offset_y", 0.0),
            draw_grid=raw.get("draw_grid", True),
            fit_choice=raw.get("fit_choice", "manual"),
            feet_per_square=raw.get("feet_per_square", 5.0),
            plain_black=raw.get("plain_black", False),
            detected=raw.get("detected"),
            created=raw.get("created"),
            updated=raw.get("updated"),
        )


# --- storage ---------------------------------------------------------------

def path_for(recipe_dir: str, slug: str) -> str:
    return os.path.join(recipe_dir, "%s.json" % slug)


def save(recipe_dir: str, spec: MapSpec) -> str:
    """Write a recipe atomically.

    Temp file then rename, because a half-written recipe is worse than none:
    it would load, produce a wrong render, and give no clue why.
    """
    if not os.path.isdir(recipe_dir):
        os.makedirs(recipe_dir)

    spec.updated = time.time()
    target = path_for(recipe_dir, spec.slug)

    fd, tmp = tempfile.mkstemp(dir=recipe_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(spec.to_dict(), fh, indent=2, sort_keys=True)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise
    return target


def load(recipe_dir: str, slug: str) -> Optional[MapSpec]:
    path = path_for(recipe_dir, slug)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as fh:
            return MapSpec.from_dict(json.load(fh))
    except (OSError, ValueError):
        # A corrupt recipe should not take out the listing that contains it.
        return None


def load_all(recipe_dir: str) -> List[MapSpec]:
    if not os.path.isdir(recipe_dir):
        return []
    out = []
    for fn in sorted(os.listdir(recipe_dir)):
        if not fn.endswith(".json"):
            continue
        spec = load(recipe_dir, fn[:-len(".json")])
        if spec is not None:
            out.append(spec)
    return out


def delete(recipe_dir: str, slug: str) -> bool:
    path = path_for(recipe_dir, slug)
    if os.path.isfile(path):
        os.unlink(path)
        return True
    return False


def known_slugs(recipe_dir: str) -> List[str]:
    """Which backgrounds came from this tool.

    Used by tablecheck to tell a missing CUSTOM map (a warning -- the user may
    simply have deleted it) from a missing built-in background (still a
    failure -- a shipped asset going missing means something is broken).
    """
    if not os.path.isdir(recipe_dir):
        return []
    return sorted(fn[:-len(".json")] for fn in os.listdir(recipe_dir)
                  if fn.endswith(".json"))
