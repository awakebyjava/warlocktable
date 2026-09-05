"""Map import and scaling (map-import-specification.md).

Turns an arbitrary image -- a Patreon map, a Roll20 export, a photo of a
hand-drawn map taken on an iPhone -- into a background the table displays at
the correct scale, with a grid that matches the physical miniatures.

THE POINT OF THIS PACKAGE IS THAT THE TABLE DOES NOT KNOW ABOUT IT.

`FehDisplay` discovers backgrounds by scanning directories and parsing
filenames. So the entire contract with the running application is "write two
correctly-named PNGs into a scanned directory, then ask for a rescan". This
package is handed paths and returns paths; it imports nothing from
controller.py, and the controller imports nothing from here.

Keep it that way. If this package ever needs to reach into the controller,
something has been designed wrong.

WRITTEN FOR PYTHON 3.9 AND PILLOW 8.1 -- what Raspberry Pi OS Bullseye ships
via `apt install python3-pil`. A development laptop almost certainly has
Python 3.12 and Pillow 12, which is the *more permissive* environment and
will happily accept code the Pi then rejects. See the spec, section 5:

    Image.BICUBIC          not  Image.Resampling.BICUBIC   (9.1+)
    Image.LANCZOS          not  Image.ANTIALIAS            (gone in 10)
    typing.Dict/List       not  bare dict[str, int] at runtime
"""

from .errors import MapImportError, UnsupportedImageError, ImageTooLargeError

__all__ = [
    "MapImportError",
    "UnsupportedImageError",
    "ImageTooLargeError",
]
