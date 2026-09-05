"""Composing the finished frame, and putting it in the library.

The pipeline, in the order it must happen:

    tone  ->  place  ->  bleed  ->  grid

Tone comes FIRST, on the source, for two reasons. The bleed is built from the
map itself, so toning afterwards would leave a bright halo around a darkened
map. And the source is usually smaller than 8 megapixels, so it is the
cheaper place to do it.

Grid comes LAST, after the bleed, so the table's grid runs across the whole
frame -- including the gutters. That is deliberate: miniatures can stand on
the bleed, and a grid that stops at the artwork's edge would strand them.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Dict, Optional, Tuple

from PIL import Image

from . import grid, tone, transform as tf_mod, vignette
from .errors import PublishError, RenderError
from .recipes import MapSpec


def compose(source: Image.Image,
            spec: MapSpec,
            frame: Tuple[int, int] = grid.FRAME,
            source_scale: float = 1.0,
            with_grid: bool = True,
            with_safe_area: bool = False) -> Image.Image:
    """Build one finished frame.

    `source_scale` is how much the passed-in image has ALREADY been reduced
    relative to the original the recipe's transform was measured against. The
    editor passes the small proxy plus its factor, so the same code path
    produces the preview and the final render -- which is the only way to be
    sure the preview is telling the truth.
    """
    fw, fh = frame

    # The frame may itself be a reduction of the full 3840x2160.
    frame_scale = fw / float(grid.FRAME_W)

    toned = tone.apply(source.convert("RGB"), spec.brightness, spec.contrast)

    # Pan and scale are recorded against the full-size source and the full
    # frame, so both need converting into whatever geometry we are drawing at.
    placed = tf_mod.Transform(
        pan_x=spec.transform.pan_x * frame_scale,
        pan_y=spec.transform.pan_y * frame_scale,
        scale=spec.transform.scale * frame_scale / (source_scale or 1.0),
        rotation=spec.transform.rotation,
    )

    layer = tf_mod.render(toned, placed, frame=frame)

    out = vignette.compose(
        layer, toned, frame=frame,
        feather_px=max(1, int(round(vignette.FEATHER_PX * frame_scale))),
        plain_black=spec.plain_black)

    if with_grid and spec.draw_grid:
        out = grid.draw(out,
                        pitch=spec.grid_pitch * frame_scale,
                        offset_x=spec.grid_offset_x * frame_scale,
                        offset_y=spec.grid_offset_y * frame_scale)

    if with_safe_area:
        out = grid.draw_safe_area(out)

    return out


def preview(proxy: Image.Image,
            spec: MapSpec,
            source_size: Tuple[int, int],
            width: int = 960,
            with_grid: bool = True,
            with_safe_area: bool = True) -> Image.Image:
    """A fast, honest preview, built by the same code as the real render."""
    height = int(round(width * grid.FRAME_H / float(grid.FRAME_W)))
    source_scale = proxy.size[0] / float(source_size[0] or 1)
    return compose(proxy, spec, frame=(width, height),
                   source_scale=source_scale,
                   with_grid=with_grid, with_safe_area=with_safe_area)


def render_full(source: Image.Image, spec: MapSpec) -> Tuple[Image.Image, Image.Image]:
    """The two published frames: plain artwork, and artwork with the grid."""
    try:
        plain = compose(source, spec, with_grid=False)
        gridded = grid.draw(plain,
                            pitch=spec.grid_pitch,
                            offset_x=spec.grid_offset_x,
                            offset_y=spec.grid_offset_y) if spec.draw_grid else plain.copy()
    except MemoryError:
        raise RenderError(
            "Ran out of memory rendering this map. Try a smaller source image.")
    except Exception as exc:           # noqa: BLE001
        raise RenderError("Could not render this map (%s)." % type(exc).__name__)

    for name, img in (("plain", plain), ("grid", gridded)):
        if img.size != grid.FRAME:
            raise RenderError("Internal error: %s render came out %dx%d, not "
                              "%dx%d." % ((name,) + img.size + grid.FRAME))
    return plain, gridded


# --- publishing ------------------------------------------------------------

def filenames(slug: str) -> Tuple[str, str]:
    """The two names FehDisplay's scanner will recognise.

    base_3840x2160.png       -> base "<slug>", plain artwork
    base_3840x2160_grid.png  -> base "<slug>", grid overlay
    """
    return ("%s_%dx%d.png" % (slug, grid.FRAME_W, grid.FRAME_H),
            "%s_%dx%d_grid.png" % (slug, grid.FRAME_W, grid.FRAME_H))


def _save_atomic(image: Image.Image, target: str) -> None:
    """Write to a temp file in the same directory, then rename into place.

    The library directory is being scanned by a live process. A half-written
    PNG appearing there mid-write would be picked up as a background and shown
    on the table, so the file must become visible only once it is complete.
    Rename within a filesystem is atomic; copying is not.
    """
    directory = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    os.close(fd)
    try:
        image.save(tmp, "PNG")
        os.replace(tmp, target)
    except Exception as exc:           # noqa: BLE001
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise PublishError("Could not write %s (%s)."
                           % (os.path.basename(target), exc))


def publish(source: Image.Image,
            spec: MapSpec,
            library_dir: str) -> Dict[str, str]:
    """Render and place both variants in the library. Returns their paths."""
    if not os.path.isdir(library_dir):
        try:
            os.makedirs(library_dir)
        except OSError as exc:
            raise PublishError("Could not create %s (%s)." % (library_dir, exc))

    plain, gridded = render_full(source, spec)
    plain_name, grid_name = filenames(spec.slug)
    plain_path = os.path.join(library_dir, plain_name)
    grid_path = os.path.join(library_dir, grid_name)

    written = []
    try:
        _save_atomic(plain, plain_path)
        written.append(plain_path)
        _save_atomic(gridded, grid_path)
        written.append(grid_path)
    except Exception:
        # Never leave one of a pair behind. A lone plain file would be a
        # perfectly valid background whose grid mode silently shows ungridded
        # art -- a wrong image with no error anywhere, which is the worst
        # outcome this module can produce.
        for path in written:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise

    # BOTH must exist before this is called a success, for the same reason.
    missing = [p for p in (plain_path, grid_path) if not os.path.isfile(p)]
    if missing:
        raise PublishError("Publish incomplete: %s missing."
                           % ", ".join(os.path.basename(p) for p in missing))

    return {"plain": plain_path, "grid": grid_path}


def unpublish(slug: str, library_dir: str) -> int:
    """Remove a map's renders. Returns bytes recovered."""
    freed = 0
    for name in filenames(slug):
        path = os.path.join(library_dir, name)
        if os.path.isfile(path):
            try:
                freed += os.path.getsize(path)
                os.unlink(path)
            except OSError:
                pass
    return freed
