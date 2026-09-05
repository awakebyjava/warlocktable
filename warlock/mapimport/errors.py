"""Failure types for map import.

Every one of these carries a message written to be shown to a person holding
an iPad, not to a developer reading a traceback. "This image is 22000 px wide;
the limit is 16000" is actionable. "ValueError" is not.

Section 12 of the spec: the pipeline must only ever *return* an error, never
raise into the panel. A map render that fails must not affect lights, audio,
or a running session.
"""

from __future__ import annotations


class MapImportError(Exception):
    """Base for every failure this package reports.

    Anything raised out of this package should be one of these, so the panel
    layer can catch exactly this and be confident it has a message worth
    showing.
    """


class UnsupportedImageError(MapImportError):
    """The file is not an image we can read, or is corrupt."""


class ImageTooLargeError(MapImportError):
    """Beyond the dimension cap.

    Raised *before* decoding, deliberately. A 25000 x 25000 PNG will exhaust
    a 4 GB Pi's memory during decode, and an OOM kill is a much worse failure
    than a refusal -- it can take the service down with it.
    """


class RenderError(MapImportError):
    """The full-resolution render could not be completed."""


class PublishError(MapImportError):
    """The renders exist but could not be placed in the library."""
