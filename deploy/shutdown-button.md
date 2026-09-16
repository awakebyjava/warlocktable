# Shutdown / Wake Button and the Jewel Lamp

*From the handover `warlock-table-gpio-and-pixels-handover.md` (Task 1).
Hardware verified 2026-09-16; scheduled for the next SD-card clone.*

## Wiring

Header orientation: board with the 40-pin header at the top right and the
USB ports at the bottom. Pin 1 is the corner nearest the SD-card slot; odd
pins are the inner row, even pins the outer row, numbering down the board.

| Wire | Physical pin | What it is |
|---|---|---|
| Button, lead 1 | **5** | GPIO3 — the wake-capable pin |
| Button, lead 2 | **6** | Ground |
| Jewel LED **+** (anode, longer leg) | **4** | 5 V |
| Jewel LED **−** (cathode) | **14** | Ground |

Pins 4, 5 and 6 are adjacent; pin 14 is the next ground down the outer row.
The button is a momentary, normally-open, anti-vandal switch. Polarity does
not matter for the button; it does for the LED.

**Use 5 V for the jewel.** Its built-in resistor is sized for 5 V; on 3.3 V
it works but dim. (3.3 V would be pin 1, with ground on pin 9.)

### Pins this table already uses — do not reassign

| GPIO | Pin | Used by |
|---|---|---|
| 4 | 7 | PN532 chip select |
| 20 | 38 | PN532 reset |
| 9, 10, 11 | 21, 19, 23 | SPI0 (PN532 data) |
| **3** | **5** | **shutdown/wake button** *(this document)* |
| 18 | 12 | **reserved** — software control of the jewel, if ever wanted. Not implemented; do not use for anything else |

## What the button does

- **Running → press → clean shutdown.** `dtoverlay=gpio-shutdown` in
  `/boot/config.txt` makes the firmware treat GPIO3-to-ground as a power
  key. The kernel raises `KEY_POWER`, `systemd-logind` runs the normal
  poweroff, and the table stops exactly as it does for `systemctl
  poweroff`: the service's `ExecStop` runs, the Entity speaks its farewell
  line, the PN532's pins are released. **No Python is involved** and there
  is no polling loop to write, which is why the handover said not to.
- **Halted → press → power on.** GPIO3 is wired to the Pi 4's power
  management; pulling it low starts the SoC. That is the whole reason for
  choosing GPIO3 rather than a free pin — no other pin does this.

Pressing it while the Pi is *off at the wall* does nothing, obviously.

## The jewel is deliberately NOT software controlled

It is wired straight to the 5 V rail. It is lit whenever the Pi has
power and dark the instant it does not — an honest power indicator with
no code between it and the truth. That also means **it stays lit while the
Pi is halted**, because a halted Pi is still powered (that is what lets the
button wake it). *Lit* means "plugged in"; *dark* means "unplugged".

Do not "improve" this by moving it to a GPIO. If a software-driven lamp is
ever wanted (a slow breathe while running, say), GPIO18 (pin 12) is
reserved for it, as a *second* lamp — the power jewel stays as it is.

## Decision point 1 — resolved: GPIO3 is free

GPIO2/3 are also I²C. Checked on the table 2026-09-16, from the hardware,
not the docs:

| | Finding |
|---|---|
| `/boot/config.txt` | `dtparam=spi=on`; `i2c_arm` commented out |
| Device tree | `i2c@7e804000` **disabled**, `spi@7e204000` **okay** |
| `/dev` | `spidev0.0`, `spidev0.1`; **no** `/dev/i2c-1` (only the HDMI DDC buses 20/21) |
| `raspi-gpio get` | GPIO2, GPIO3 idle inputs with pull-ups; GPIO4, GPIO20 outputs (the PN532) |
| Code | `warlock/inputs/nfc.py`: SPI, `cs=4`, `reset=20` |

The PN532 is on SPI. **Proceed with GPIO3; wake-from-halt is kept.** The
enable script refuses to run if `dtparam=i2c_arm=on` is ever set, and
Table Check warns, so this cannot silently regress.

*If it ever has to move:* GPIO17 (pin 11) with ground on pin 9, and
`dtoverlay=gpio-shutdown,gpio_pin=17`. The button then shuts down but
**cannot wake** the Pi — that trade is Jon's call, never a silent
fallback.

## Decision point 2 — pre-shutdown work: already handled

The handover asks whether the table should do anything before it goes
down, and insists it not live in a button handler. It does not: the
service's ordinary stop path (`Runtime.shutdown()`, via systemd's
`ExecStop` on the unit) already

- plays the Entity's `system_shutdown` line (bounded to 2.5 s so it fits
  inside systemd's stop timeout),
- stops the web panel, the NFC reader and the dice scanner,
- closes the display and releases GPIO.

Because the button goes through the same `poweroff`, all of that runs on
a button press exactly as on `sudo poweroff`, a `shutdown -h` from SSH, or
a UPS-triggered halt. **Nothing button-specific was added**, and nothing
should be. If a lighting fade or a longer goodbye is ever wanted, it goes
in `Runtime.shutdown()` — one place, every path.

Decided by omission: no lighting fade. The Pixelblaze keeps its last
pattern when the Pi halts; the table goes dark when the plug is pulled.

## Enabling it — once per SD card

```bash
sudo ./deploy/enable-shutdown-button.sh
sudo reboot
```

Idempotent, backs up `config.txt`, refuses if I²C is on. `--check` reports
without changing anything. `install.sh` deliberately does **not** call
it: the boot partition is a per-card decision and needs a reboot.

## Verifying

1. After the reboot, `./deploy/enable-shutdown-button.sh --check` says
   *enabled*, and Table Check's **Shutdown button** row is a pass.
2. `journalctl -f` in one window; press the button. Expect
   `systemd-logind: Power key pressed`, then the warlocktable stop
   sequence (farewell line, `stopped cleanly in N s`), then halt. The
   jewel stays lit.
3. Press again. The Pi boots; the service starts itself (plan doc 5.2);
   the status screen comes up.

## Recovery

The backup is `/boot/config.txt.bak-shutdown-button-<timestamp>`. Removing
the `dtoverlay=gpio-shutdown` line and rebooting undoes everything. With
the overlay on and no button wired, GPIO3's pull-up keeps it high and
nothing happens — a card cloned with this enabled is safe in a Pi with
no button.
