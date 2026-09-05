"""The public face of map import: upload, edit, publish, delete.

This is what the panel calls. Everything below it is pure image work; this
layer owns the directories, the slugs, and the editing session.

IT TOUCHES NOTHING BELONGING TO THE TABLE. It is given paths and a callback
to invoke when the library changes, and that callback is the only thing that
reaches the controller. Section 13 of the spec lists the complete set of
changes to existing code, and it is short precisely because of this boundary.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image

from . import detect, grid, ingest, recipes, render, tone
from . import transform as tf_mod
from .errors import MapImportError, PublishError
from .recipes import MapSpec
from .transform import Transform

SLUG_MAX = 48
_SLUG_BAD = re.compile(r"[^a-z0-9]+")

# Warn above this. Not enforced -- see spec section 14.
USAGE_WARN_BYTES = 5 * 1024 * 1024 * 1024

# An editing session older than this is abandoned; its scratch is reclaimed.
SESSION_TTL_S = 24 * 60 * 60


def slugify(title: str, fallback: str = "map") -> str:
    slug = _SLUG_BAD.sub("-", (title or "").strip().lower()).strip("-")
    slug = slug[:SLUG_MAX].strip("-")
    return slug or fallback


class Session(object):
    """One map being edited. Lives in its own scratch directory."""

    __slots__ = ("id", "workdir", "source", "detection", "spec",
                 "created", "_image", "_proxy")

    def __init__(self, sid, workdir, source, detection, spec):
        self.id = sid
        self.workdir = workdir
        self.source = source
        self.detection = detection
        self.spec = spec
        self.created = time.time()
        self._image = None
        self._proxy = None

    def image(self) -> Image.Image:
        """The full-resolution normalised source, loaded on demand."""
        if self._image is None:
            self._image = Image.open(self.source.path)
            self._image.load()
        return self._image

    def proxy(self) -> Image.Image:
        if self._proxy is None:
            self._proxy = Image.open(self.source.proxy_path)
            self._proxy.load()
        return self._proxy

    def close(self):
        for attr in ("_image", "_proxy"):
            img = getattr(self, attr)
            if img is not None:
                try:
                    img.close()
                except Exception:      # noqa: BLE001
                    pass
                setattr(self, attr, None)


class MapLibrary(object):
    def __init__(self,
                 library_dir: str,
                 originals_dir: str,
                 recipes_dir: str,
                 work_dir: str,
                 background_paths: Optional[Sequence[str]] = None,
                 luminance_target: Optional[float] = None,
                 on_change: Optional[Callable[[], None]] = None,
                 log=None):
        self.library_dir = library_dir
        self.originals_dir = originals_dir
        self.recipes_dir = recipes_dir
        self.work_dir = work_dir
        self.background_paths = list(background_paths or [])
        self.on_change = on_change
        self.log = log
        self._sessions: Dict[str, Session] = {}
        self._target = luminance_target

    # --- setup ------------------------------------------------------------

    def ensure_dirs(self) -> None:
        for d in (self.library_dir, self.originals_dir,
                  self.recipes_dir, self.work_dir):
            if d and not os.path.isdir(d):
                os.makedirs(d)

    def _levels(self) -> Dict[str, float]:
        """House brightness, measured once and cached (it reads 4K PNGs)."""
        if self._target is None:
            paths = self.background_paths or [self.library_dir]
            measured = tone.house_levels(paths)
            self._target = measured or {
                "mean": tone.FALLBACK_TARGET,
                "ceiling": tone.FALLBACK_CEILING,
                "count": 0.0,
            }
        return self._target

    def luminance_target(self) -> float:
        """What the brightness WARNING is measured against: the house average."""
        return self._levels()["mean"]

    def brightness_ceiling(self) -> float:
        """What the auto brightness DEFAULT aims at: the brightest background
        already in use. See tone.house_levels for why these differ -- a map
        pulled to the ambient average is too dark to read."""
        return self._levels()["ceiling"]

    # --- upload -----------------------------------------------------------

    def upload(self, upload_path: str, original_name: str = "") -> Dict:
        """Ingest a file and open an editing session for it."""
        self.ensure_dirs()
        self._reap_sessions()

        sid = uuid.uuid4().hex[:12]
        workdir = os.path.join(self.work_dir, sid)
        os.makedirs(workdir)

        try:
            source = ingest.ingest(upload_path, workdir)
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

        if original_name:
            source.original_name = original_name

        image = Image.open(source.path)
        image.load()

        detection = detect.detect(image)

        # Starting point for the sliders. Detection only ever pre-fills them
        # (spec section 2) -- everything here is editable the moment the
        # session opens.
        if detection.found:
            scale = tf_mod.scale_for_pitch(detection.pitch)
        else:
            scale = tf_mod.fit_scale(source.size)

        spec = MapSpec(
            slug="",
            title=os.path.splitext(source.original_name or "map")[0],
            source_file=source.original_name,
            source_width=source.width,
            source_height=source.height,
            transform=Transform(scale=scale),
            brightness=tone.suggest_brightness(image, self.brightness_ceiling()),
            contrast=1.0,
            detected=detection.to_dict(),
        )
        self._align_grid(spec, source.size, detection)

        session = Session(sid, workdir, source, detection, spec)
        session._image = image
        self._sessions[sid] = session

        return self.describe(sid)

    def _align_grid(self, spec: MapSpec, src_size, detection) -> None:
        """Put the table's grid in phase with the map's own, if it has one."""
        if detection is not None and detection.found:
            origin = (detection.offset_x, detection.offset_y)
        else:
            origin = (0.0, 0.0)
        ox, oy = tf_mod.grid_phase(spec.transform, src_size, origin)
        spec.grid_offset_x = ox
        spec.grid_offset_y = oy

    # --- inspection -------------------------------------------------------

    def session(self, sid: str) -> Session:
        s = self._sessions.get(sid)
        if s is None:
            raise MapImportError(
                "That upload is no longer open. Upload the image again.")
        return s

    def fit_report(self, spec: MapSpec) -> Dict:
        """Whether the map fits, and what the choices are (spec section 8.4).

        Reports; does not decide. A map that will not fit at true scale is a
        judgement call between cropping and shrinking the squares, and only
        the person running the game can make it.
        """
        w = spec.source_width * spec.transform.scale / grid.PITCH
        h = spec.source_height * spec.transform.scale / grid.PITCH
        across = grid.squares_across()
        down = grid.squares_down()

        fits = (w <= across + 0.01) and (h <= down + 0.01)
        report = {
            "squares_wide": round(w, 2),
            "squares_high": round(h, 2),
            "table_wide": round(across, 1),
            "table_high": round(down, 1),
            "fits": fits,
            "feet_per_square": 5.0,
        }
        if fits:
            return report

        shrink = min(across / w, down / h) if w and h else 1.0
        report["scale_down_factor"] = round(shrink, 4)
        report["scale_down_feet"] = round(5.0 / shrink, 2)
        report["message"] = (
            "This map is %.0f squares wide and %.0f high. The table shows "
            "%.0f by %.0f. Crop it, or scale it down and accept squares of "
            "%.1f ft instead of 5."
            % (w, h, across, down, 5.0 / shrink))
        return report

    def describe(self, sid: str) -> Dict:
        s = self.session(sid)
        spec = s.spec
        return {
            "id": sid,
            "title": spec.title,
            "source": s.source.to_dict(),
            "detection": s.detection.to_dict(),
            "transform": spec.transform.to_dict(),
            "brightness": spec.brightness,
            "contrast": spec.contrast,
            "draw_grid": spec.draw_grid,
            "plain_black": spec.plain_black,
            "grid_offset": [spec.grid_offset_x, spec.grid_offset_y],
            "fit": self.fit_report(spec),
            "pitch": grid.PITCH,
            "luminance_target": round(self.luminance_target(), 1),
            "luminance_ceiling": round(self.brightness_ceiling(), 1),
        }

    # --- editing ----------------------------------------------------------

    def adjust(self, sid: str, **controls) -> Dict:
        """Update any subset of the controls. All of them are always live."""
        s = self.session(sid)
        spec = s.spec

        tf = spec.transform
        for name in ("pan_x", "pan_y", "scale", "rotation"):
            if controls.get(name) is not None:
                tf = tf.replace(**{name: float(controls[name])})
        spec.transform = tf

        for name in ("brightness", "contrast"):
            if controls.get(name) is not None:
                setattr(spec, name, float(controls[name]))

        for name in ("draw_grid", "plain_black"):
            if controls.get(name) is not None:
                setattr(spec, name, bool(controls[name]))

        if controls.get("title"):
            spec.title = str(controls["title"])[:120]

        # Convenience: set the scale by declaring how wide the map is. The
        # most reliable path in the tool, because it is exact arithmetic
        # rather than an estimate (spec section 8.2).
        if controls.get("squares_across"):
            spec.transform = spec.transform.replace(
                scale=tf_mod.scale_for_squares(spec.source_width,
                                               float(controls["squares_across"])))

        if controls.get("fit") == "scale_down":
            report = self.fit_report(spec)
            factor = report.get("scale_down_factor", 1.0)
            spec.transform = spec.transform.replace(
                scale=spec.transform.scale * factor)
            spec.fit_choice = "scale_down"
            spec.feet_per_square = report.get("scale_down_feet", 5.0)

        if controls.get("realign_grid"):
            self._align_grid(spec, (spec.source_width, spec.source_height),
                             s.detection)
        else:
            for name, attr in (("grid_offset_x", "grid_offset_x"),
                               ("grid_offset_y", "grid_offset_y")):
                if controls.get(name) is not None:
                    setattr(spec, attr, float(controls[name]))

        return self.describe(sid)

    def preview_image(self, sid: str, width: int = 960,
                      safe_area: bool = True) -> Image.Image:
        s = self.session(sid)
        return render.preview(s.proxy(), s.spec,
                              (s.spec.source_width, s.spec.source_height),
                              width=width, with_safe_area=safe_area)

    def full_render(self, sid: str) -> Image.Image:
        """The real thing, for pushing to the table before publishing."""
        s = self.session(sid)
        plain, gridded = render.render_full(s.image(), s.spec)
        return gridded if s.spec.draw_grid else plain

    def brightness_warning(self, sid: str) -> Optional[str]:
        s = self.session(sid)
        toned = tone.apply(s.proxy(), s.spec.brightness, s.spec.contrast)
        return tone.warning_for(toned, self.luminance_target())

    # --- publishing -------------------------------------------------------

    def unique_slug(self, title: str, taken: Optional[Sequence[str]] = None) -> str:
        """A slug nothing else is using.

        Checked against the LIVE library rather than against a directory
        listing: FehDisplay's scanner does not recurse, so every background
        from every search path shares one flat namespace and a subdirectory
        cannot be used to avoid collisions.
        """
        base = slugify(title)
        existing = set(taken or [])
        existing.update(recipes.known_slugs(self.recipes_dir))
        for d in list(self.background_paths) + [self.library_dir]:
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                stem = os.path.splitext(fn)[0].lower()
                for suffix in ("_grid", "_hex"):
                    if stem.endswith(suffix):
                        stem = stem[:-len(suffix)]
                stem = re.sub(r"[_-]\d{3,5}x\d{3,5}$", "", stem)
                existing.add(stem)

        if base not in existing:
            return base
        for n in range(2, 200):
            candidate = "%s-%d" % (base[:SLUG_MAX - 4], n)
            if candidate not in existing:
                return candidate
        raise PublishError("Could not find an unused name for %r." % title)

    def publish(self, sid: str, title: Optional[str] = None) -> Dict:
        s = self.session(sid)
        spec = s.spec
        if title:
            spec.title = str(title)[:120]

        spec.slug = self.unique_slug(spec.title)
        self.ensure_dirs()

        paths = render.publish(s.image(), spec, self.library_dir)

        # Keep the source AFTER the renders succeed, so a failed publish does
        # not leave an orphan taking up space.
        #
        # WHAT IS KEPT is the NORMALISED PNG, not the bytes as uploaded. The
        # spec calls this "the original", and this is the honest reading of
        # it, for three reasons:
        #
        #   * It is lossless, so nothing is given up. Normalisation only
        #     rotates, flattens and strips -- it never resamples.
        #   * Re-rendering it years later needs nothing but Pillow. Keeping
        #     the raw HEIC would make the repair path depend on libheif still
        #     being installed and still decoding that file.
        #   * EXIF and GPS are already gone. Every table user can see every
        #     uploaded map, and a map photographed at home should not carry
        #     the house's coordinates with it.
        kept = os.path.join(self.originals_dir, "%s.png" % spec.slug)
        try:
            shutil.copyfile(s.source.path, kept)
            spec.source_file = os.path.basename(kept)
        except OSError:
            # Losing the original costs the re-edit path, not the map. Worth
            # a note in the log, not worth failing a publish that worked.
            self._note("mapimport.original_not_kept", slug=spec.slug)

        recipes.save(self.recipes_dir, spec)
        self._changed()

        result = {"slug": spec.slug, "title": spec.title,
                  "files": [os.path.basename(p) for p in paths.values()]}
        self._note("mapimport.published", slug=spec.slug)
        self.discard(sid)
        return result

    def rerender(self, slug: str) -> Dict:
        """Rebuild a published map from its original and recipe.

        The payoff for keeping both (spec section 11): if PITCH is ever
        re-measured, every custom map can be made correct again by calling
        this for each slug, rather than by hand.
        """
        spec = recipes.load(self.recipes_dir, slug)
        if spec is None:
            raise MapImportError("No recipe stored for %r." % slug)
        original = os.path.join(self.originals_dir, spec.source_file or "")
        if not os.path.isfile(original):
            raise MapImportError(
                "The original image for %r is missing, so it cannot be "
                "re-rendered." % slug)

        with Image.open(original) as im:
            im.load()
            source = ingest.normalise(im)

        # Recipes record the pitch they were rendered at; a re-render adopts
        # today's constant, which is the entire point.
        spec.grid_pitch = grid.PITCH
        paths = render.publish(source, spec, self.library_dir)
        recipes.save(self.recipes_dir, spec)
        self._changed()
        return {"slug": slug, "files": [os.path.basename(p) for p in paths.values()]}

    # --- listing and removal ----------------------------------------------

    def listing(self) -> List[Dict]:
        out = []
        for spec in recipes.load_all(self.recipes_dir):
            plain_name, grid_name = render.filenames(spec.slug)
            plain_path = os.path.join(self.library_dir, plain_name)
            grid_path = os.path.join(self.library_dir, grid_name)
            size = 0
            for p in (plain_path, grid_path):
                if os.path.isfile(p):
                    size += os.path.getsize(p)
            out.append({
                "slug": spec.slug,
                "title": spec.title,
                "created": spec.created,
                "updated": spec.updated,
                "feet_per_square": spec.feet_per_square,
                "fit_choice": spec.fit_choice,
                "bytes": size,
                "present": os.path.isfile(plain_path) and os.path.isfile(grid_path),
                "has_original": os.path.isfile(
                    os.path.join(self.originals_dir, spec.source_file or "")),
            })
        return out

    def delete(self, slug: str) -> Dict:
        """Remove a map completely: renders, original, recipe."""
        freed = render.unpublish(slug, self.library_dir)

        spec = recipes.load(self.recipes_dir, slug)
        if spec and spec.source_file:
            original = os.path.join(self.originals_dir, spec.source_file)
            if os.path.isfile(original):
                try:
                    freed += os.path.getsize(original)
                    os.unlink(original)
                except OSError:
                    pass

        removed = recipes.delete(self.recipes_dir, slug)
        self._changed()
        self._note("mapimport.deleted", slug=slug)
        return {"slug": slug, "removed": removed, "freed_bytes": freed}

    def usage(self) -> Dict:
        def total(directory):
            if not os.path.isdir(directory):
                return 0
            n = 0
            for fn in os.listdir(directory):
                path = os.path.join(directory, fn)
                if os.path.isfile(path):
                    n += os.path.getsize(path)
            return n

        renders = total(self.library_dir)
        originals = total(self.originals_dir)
        used = renders + originals
        return {
            "renders_bytes": renders,
            "originals_bytes": originals,
            "total_bytes": used,
            "warn_bytes": USAGE_WARN_BYTES,
            "over_warn": used > USAGE_WARN_BYTES,
        }

    # --- session lifecycle ------------------------------------------------

    def discard(self, sid: str) -> None:
        s = self._sessions.pop(sid, None)
        if s is None:
            return
        s.close()
        shutil.rmtree(s.workdir, ignore_errors=True)

    def _reap_sessions(self) -> None:
        """Drop abandoned sessions. An upload that was never published would
        otherwise keep a full-resolution PNG on the SD card indefinitely."""
        now = time.time()
        for sid in [k for k, v in self._sessions.items()
                    if now - v.created > SESSION_TTL_S]:
            self.discard(sid)

        if os.path.isdir(self.work_dir):
            for fn in os.listdir(self.work_dir):
                path = os.path.join(self.work_dir, fn)
                if fn in self._sessions or not os.path.isdir(path):
                    continue
                try:
                    if now - os.path.getmtime(path) > SESSION_TTL_S:
                        shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass

    # --- plumbing ---------------------------------------------------------

    def _changed(self) -> None:
        """Tell the display the library moved under it.

        The ONLY call this package makes towards the running table.
        """
        if self.on_change is None:
            return
        try:
            self.on_change()
        except Exception as exc:       # noqa: BLE001
            # A rescan failure does not invalidate the files, which are
            # written and correct. Say so rather than failing the publish.
            self._note("mapimport.rescan_failed", error=str(exc))

    def _note(self, event: str, **fields) -> None:
        if self.log is None:
            return
        try:
            self.log.record(event, **fields)
        except Exception:              # noqa: BLE001
            pass
