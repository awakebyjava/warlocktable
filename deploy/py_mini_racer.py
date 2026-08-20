"""Stub for py_mini_racer on the Raspberry Pi.

Copy this to the Pi's user site-packages:

    python3 -c "import site; print(site.USER_SITE)"
    # -> /home/pi/.local/lib/python3.9/site-packages
    cp deploy/py_mini_racer.py <that path>/

WHY THIS EXISTS
---------------
pixelblaze-client imports MiniRacer at module scope:

    from py_mini_racer import MiniRacer          # pixelblaze/pixelblaze.py:92

...but only USES it inside compilePattern() and getMapCoordinates() — both
pattern-authoring operations we do on the laptop, never on the Pi.

The real py_mini_racer embeds V8. There is no ARM wheel, so pip falls back to
building V8 from source, which fails outright on a Pi 4.

The alternative was pinning pixelblaze-client 0.9.6, which is what the Pi had
before. That version lacks setActivePatternByName() and EnumerateAddresses(),
both of which warlock/devices/pixelblaze_lights.py depends on — so pinning it
would mean the controller can't set patterns or recover from an address
change. Stubbing the unused dependency is the smaller compromise.

This fails loudly rather than silently, so if pattern compilation ever IS
attempted on the Pi, the error says why instead of producing nonsense.
"""


class MiniRacer:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "py_mini_racer is a stub on this Pi - JS pattern compilation is "
            "not available here. Compile and upload patterns from the laptop "
            "instead (see patterns/ and warlock-table-led-reference.md)."
        )
