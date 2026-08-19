"""Warlock Table v2 — controller package.

Layer map (see plan doc section 4.1). Each layer only talks to the one below it:

    inputs      →  controller  →  actions  →  devices  →  hardware
    (CLI, NFC,     (routing,      (the         (drivers /
     panel)         state)         verbs)       fakes)

Nothing above the device layer knows what a Pixelblaze is. That is the whole
point: swapping a fake device for a real one should not require touching the
controller.
"""

__version__ = "0.1.0-skeleton"
