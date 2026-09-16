#!/usr/bin/env bash
#
# Enable the physical shutdown / wake button (deploy/shutdown-button.md).
#
#   sudo ./deploy/enable-shutdown-button.sh          # enable, then reboot
#   ./deploy/enable-shutdown-button.sh --check       # report only, no sudo
#
# Adds ONE line to /boot/config.txt:
#
#   dtoverlay=gpio-shutdown
#
# which tells the firmware that GPIO3 (physical pin 5) pulled to ground is
# a request to shut down cleanly. No Python, no polling loop, no service:
# the kernel raises a KEY_POWER event and systemd runs the normal
# shutdown, so the table stops exactly as it does for `systemctl poweroff`
# -- the service's ExecStop runs, the Entity says its farewell line, the
# PN532 pins are released. And because it is GPIO3, the same button wakes
# a HALTED Pi 4: that pin is wired to the power-management chip and a
# low pulse on it is the one thing that starts the SoC without pulling
# the plug. That is why GPIO3 and not any other pin.
#
# GPIO3 is also I2C SCL. This script REFUSES if the ARM I2C bus is enabled,
# because the two cannot share the pin; on this table the NFC reader is on
# SPI and I2C is off, verified on the hardware 2026-09-16.
#
# Idempotent: run it twice and the second run says "already enabled". It
# is NOT called by install.sh on purpose -- it edits the boot partition,
# which is a per-SD-card decision, and it needs a reboot to take effect.

set -euo pipefail

CONFIG=/boot/config.txt
LINE="dtoverlay=gpio-shutdown"
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

if [[ ! -f "$CONFIG" ]]; then
    echo "no $CONFIG -- is this the Pi? (Bookworm moved it to /boot/firmware/)" >&2
    exit 2
fi

enabled=0
grep -Eq "^\s*dtoverlay=gpio-shutdown(\s*$|,)" "$CONFIG" && enabled=1
i2c=0
grep -Eq "^\s*dtparam=i2c_arm=on" "$CONFIG" && i2c=1

echo "config:        $CONFIG"
echo "overlay:       $([[ $enabled -eq 1 ]] && echo enabled || echo NOT enabled)"
echo "i2c_arm:       $([[ $i2c -eq 1 ]] && echo ON -- conflicts with GPIO3 || echo off)"
if [[ -r /proc/device-tree/soc/i2c@7e804000/status ]]; then
    echo "i2c in DT:     $(tr -d '\0' < /proc/device-tree/soc/i2c@7e804000/status)"
fi
if command -v raspi-gpio >/dev/null 2>&1; then
    echo "GPIO3 now:     $(raspi-gpio get 3 2>/dev/null)"
fi
echo
echo "wiring:  button between pin 5 (GPIO3) and pin 6 (GND)"
echo "         jewel LED +  to pin 4 (5V), -  to pin 14 (GND) -- not software controlled"
echo

if [[ $CHECK_ONLY -eq 1 ]]; then
    exit $(( enabled == 1 ? 0 : 1 ))
fi

if [[ $i2c -eq 1 ]]; then
    echo "REFUSING: dtparam=i2c_arm=on shares GPIO3 with the button." >&2
    echo "Either turn I2C off (nothing on this table uses it) or move the" >&2
    echo "button to GPIO17 with 'dtoverlay=gpio-shutdown,gpio_pin=17' --" >&2
    echo "which LOSES wake-from-halt. See deploy/shutdown-button.md." >&2
    exit 3
fi

if [[ $enabled -eq 1 ]]; then
    echo "already enabled -- nothing to do."
    exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
    echo "needs root to edit $CONFIG: sudo $0" >&2
    exit 2
fi

backup="$CONFIG.bak-shutdown-button-$(date +%Y%m%d-%H%M%S)"
cp -p "$CONFIG" "$backup"
echo "backed up to $backup"

cat >> "$CONFIG" <<'EOF'

# Warlock Table: momentary button on GPIO3 (pin 5) to GND (pin 6) shuts
# down cleanly, and wakes a halted Pi. deploy/shutdown-button.md.
dtoverlay=gpio-shutdown
EOF

echo "added '$LINE'. Reboot for it to take effect:"
echo "  sudo reboot"
