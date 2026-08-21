"""QR codes for the table's join URL.

Thin wrapper over `segno`, kept separate so exactly one place knows whether
a QR encoder exists. segno is pure Python with no dependencies, which
matters here: the Pi has no ARM wheel problems with it, unlike most of the
imaging stack (see deploy/py_mini_racer.py for how that goes).

If it is not installed, qr_svg() raises and the join page falls back to
printing the URL. Worse, but people can still type an address; a join page
that 500s because a decoration is missing would be much worse.
"""

from __future__ import annotations

import io


def available() -> bool:
    try:
        import segno  # noqa: F401
    except ImportError:
        return False
    return True


def qr_svg(data: str, scale: int = 8, border: int = 2) -> str:
    """-> an SVG fragment encoding `data`, ready to inline in a page.

    Error level M: tolerates about 15% damage, which is the right trade for
    something printed and stuck to a table where it will be leaned on and
    spilled near. H would survive more but makes the code denser, and a
    phone camera in dim light would rather have big modules.

    The modules carry a class so the page can recolour them in CSS. segno
    validates colour arguments and rejects `currentColor`, so overriding the
    stroke in the stylesheet is the way to make one render work on any
    background.
    """
    import segno

    code = segno.make(data, error="m")
    buf = io.BytesIO()          # segno writes bytes even for SVG
    code.save(buf, kind="svg", scale=scale, border=border,
              svgclass="qr", lineclass="qr-mod",
              # No width/height and no XML declaration: this gets inlined
              # into a page, where a fixed size and a second prolog would
              # both be wrong.
              omitsize=True, xmldecl=False)
    return buf.getvalue().decode("utf-8")
