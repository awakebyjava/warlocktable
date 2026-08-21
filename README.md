# Warlock Table

An immersive tabletop-RPG table. Tap a physical NFC card and the table
responds — 764 addressable LEDs around its perimeter change colour, a
soundscape crossfades in, and artwork appears on a 4K television embedded
face-up in the tabletop.

It runs as a service on a Raspberry Pi 4, starts itself on boot, and is
driven from an iPad web panel or from the cards themselves.

```
   card tap ─┐
  panel tap ─┼──▶  Controller  ──▶  Pixelblaze (764 px)
   (future:  ┘     (one process)──▶  Audio (2 channels, crossfade + duck)
 voice/dice)                    ──▶  TV (4K artwork, grid/hex overlays)
```

---

## Start here

| If you want to… | Read |
|---|---|
| **Pick up where the project left off** | [`Warlock-Table-Claude-Code-Handoff.md`](Warlock-Table-Claude-Code-Handoff.md) |
| Understand *why* it is built this way | [`Warlock-Table-v2-Project-Plan.md`](Warlock-Table-v2-Project-Plan.md) — the source of truth |
| Write a Pixelblaze pattern | [`warlock-table-led-reference.md`](warlock-table-led-reference.md) — **read the power budget first** |
| Generate artwork for the TV | [`display-image-specifications.md`](display-image-specifications.md) |
| Deploy to, or debug, the Pi | [`deploy/README.md`](deploy/README.md) |
| Build any UI | [`warlock-table-style-guide.html`](warlock-table-style-guide.html) |

---

## Running it

```bash
python run_table.py                                    # all fakes, any machine
python run_table.py --real-lights --real-audio --nfc   # real hardware (Pi)
python run_service.py --real-lights --real-audio --nfc --real-display --web
```

`run_table.py` is an interactive prompt for development. `run_service.py` is
headless, and is what systemd runs. **Everything works with no hardware
attached** — the fakes print what the real devices would have been told to
do, which is how most of this was built.

Panel: `http://raspberrypi.local:8080`

---

## How it is organised

```
warlock/
  controller.py    every action; precedence; per-subsystem fault isolation
  config.py        the data model, plus atomic validated saves
  configstore.py   mutation under a lock — what the panel edits through
  registry.py      the self-describing action registry
  tablecheck.py    the pre-session self-test
  statusscreen.py  renders the TV status screen
  devices/         things the controller CALLS (real + fake, same interface)
  inputs/          things that CALL the controller (the NFC reader)
  web/             the operator panel, served from the controller process
deploy/            install.sh, update.sh, the systemd unit
patterns/          Pixelblaze patterns, kept in git so the device is not the
                   only copy
```

**Media is deliberately not in git.** Audio and finished 4K artwork live
outside the repo and reach the Pi by `rsync`; only small sources are tracked.
The V1 audio alone was 1.08 GB, which would have made every clone drag.

---

## Three ideas that shape everything

**Cards are dumb triggers.** A tag is a UID and a label. What it *does* lives
in what it points at — a Scene, an Interruption, or a Random Table —
interchangeable from the panel. The system does not care whether the object
is a tarot card, a postcard or a stopwatch.

**One controller owns every action.** A card tap and a panel button call the
same method, so there is no duplicated logic and no way for the two to drift
apart. Adding voice or dice later means adding an input, not a subsystem.

**Fail one part, not the table.** Every device call is isolated: a dead
Pixelblaze must not stop the soundscape. The panel and the TV both report
per-subsystem health, because a table that is broken *and silent about it* is
the failure mode that matters at a session.

---

## Versions

`v0.1.0` — first working table (card tap → real lights and sound).
`v0.2.0` — all four subsystems real; panel, status screen, Table Check,
card editing, visual identity.

Rollback is `git checkout <tag> && sudo ./deploy/install.sh`; the deployed
build is recorded in `/opt/warlocktable/VERSION` and shown in the panel.
