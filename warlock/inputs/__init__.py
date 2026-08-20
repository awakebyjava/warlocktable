"""Input sources — things that notice something happened and emit an event.

Deliberately separate from `devices/`. A device is something the controller
*calls* (set these lights). An input is something that *calls the controller*
(a card was tapped).

The rule from plan doc 4.1: an input never touches an output. The NFC reader
does not know the Pixelblaze exists — it reports "card 04:39:65 was tapped"
and the controller decides what that means. That is why adding voice or dice
later costs almost nothing: they are just more things emitting events into a
controller that already knows what to do with them.
"""
