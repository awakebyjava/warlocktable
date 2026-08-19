"""Device layer — one thin wrapper per piece of hardware.

Everything above this layer speaks in intent ("set the lights to sparkfire"),
never in device dialect ("pb.setActivePattern('sparkfire')"). That indirection
is what lets a fake stand in for real hardware with nothing else changing.
"""

from .base import AudioDevice, DeviceError, DisplayDevice, LightDevice  # noqa: F401
