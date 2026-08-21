# Warlock Table v2 — Handoff to Claude Code

*Read this alongside the project plan doc (`Warlock-Table-v2-Project-Plan.md`). This file is the current-status briefing: where the project stands and how it's set up. The plan doc is the full vision, subsystems, architecture, and roadmap.*

---

## What this project is (one paragraph)

Warlock Table is an immersive TTRPG table built around a **Raspberry Pi 4** with an embedded TV, a **Pixelblaze** LED system (with Output Expander), a **PN532 NFC reader**, audio/soundscapes, and a planned reactive light + sound + voice environment. NFC cards drive in-world "magic" interactions; an operator web panel handles everything else. See the plan doc for the full picture. **This is v2 — a rebuild.**

## The person you're working with

- **Not a professional software developer**, and explicitly wants to *learn* how software is built while building this. Explain the "why," not just the "what." Work in **small, tested increments** — one feature at a time, verify it works before moving on. Avoid dumping large amounts of code or many steps at once.
- Prefers to understand the whole map before committing to a step.

## Dev environment & workflow (this is the important part)

**The Git bridge — how code moves:**
- Work happens on the **Windows laptop** (in VS Code, with you — Claude Code — running there).
- Laptop **pushes** to a **GitHub** repo.
- The **Raspberry Pi pulls** from GitHub and **runs** the code against the real hardware (Pixelblaze, NFC, TV).
- GitHub is the middleman. Claude Code runs on the **laptop**, NOT on the Pi.

**Status of setup (all done):**
- Git installed + configured on both machines (laptop: git 2.55; Pi: git 2.30.2).
- The GitHub repo is **cloned on both** the laptop and the Pi.
- SSH from laptop → Pi works reliably with **key-based auth** (passwordless).

**Deliberately abandoned — do not resurrect without being asked:**
- **VS Code Remote-SSH into the Pi.** It hangs at "Initializing VS Code Server" / "Downloading VS Code Server" and never finishes. Ruled out as causes: OS age (Bullseye/Debian 11 is fine), disk space (36% used), internet (works), architecture (aarch64/64-bit — supported). Root cause not pinned. **We chose the Git bridge instead so we don't depend on Remote-SSH at all.** Don't send the user back down this hole unless they specifically want to.

**Pi environment facts:**
- Raspberry Pi 4, Raspberry Pi OS **Bullseye (Debian 11)**, **aarch64** (64-bit).
- Audio: HDMI + 3.5mm analog jack (can run simultaneously).

## Existing code to work from

There are **two prior implementations** being organized into folders (e.g., `version-zero/` and `version-one/`) as reference:
- The **"magic tarot" folder holds the most up-to-date, working scripts** — including functioning connections between the Raspberry Pi, the Pixelblaze, and the NFC reader. **This is the best reference for how the hardware actually talks to the Pi.**
- These older versions are reference material to build the new v2 plan from — not the final structure.

## Key architecture decisions carried forward (from the plan doc)

- **Central Controller pattern:** one service on the Pi owns all "actions" (play soundscape, set light scene, switch background, hand off to Apple TV, table speaks a line, etc.). Every input — NFC cards, operator web panel, voice, Overseer/VTT, dice — feeds the same controller. Actions are defined once and reused everywhere.
- **Actions/scenes as data, not code** (config-driven), so new cards/behaviors are added by editing config, and a future card-management UI can edit that same data.
- **Language/stack: Python** (fits NFC + GPIO + Pixelblaze client). Web panel via FastAPI or Flask, served as a PWA for the iPad. The one non-Python island is the Overseer Studio plugin (HTML/JS, required by their SDK).

## Where we are right now

*(Updated 2026-08-21. `Warlock-Table-v2-Project-Plan.md` is the detailed source of truth — this is the summary. If they disagree, the plan doc wins.)*

**The table works.** A physical NFC card tap drives real lights, real sound and real artwork on the embedded TV, from a service that starts itself on boot and survives a power cut. Deployed build: **v0.3.1**.

**All four subsystems are real** — nothing is a fake any more:

| | |
|---|---|
| Lights | Pixelblaze, 764 px, found by UDP discovery. Pattern writes verified by read-back. 50% ceiling (power budget — see below) |
| Audio | Two channel groups: looping bed + layered one-shots, true crossfade, ducking. Master volume, and switchable between the 3.5mm jack and the television |
| Cards | PN532 over SPI. Tap semantics — fires once, re-fires only after lift-and-replace |
| Screen | feh fullscreen at 3840×2160. Backgrounds carry named overlays: none / square grid / hex |

**Also built:** the operator panel (iPad PWA on :8080 — status strip, controls, brightness, **volume and audio output**, overlays, **card editing** including registering an unknown tag by tapping it), the **TV status screen**, **Table Check** (14 checks), headless mode, `install.sh` + systemd, and the full visual identity on both surfaces.

**Built 2026-08-21, all verified on hardware:**
- **Seat zones** — the perimeter divides between the GM (fixed 38 in section) and 1–7 players, each seat its own colour, numbered clockwise from the GM. §4.7.
- **Player initiative** — the GM taps players into an order; the active seat flashes. Standalone, and needs **no integration with anything**. §3.9.
- **Join page + seat claiming** — QR to `/`, which asks player-or-GM. The player page does exactly one thing: pick a seat. §3.7.
- **Volume and output switching** — including the `hdmi:` vs `plughw:` trap. §3.3.

**Not built yet:**
- **The tarot interruption system** — 26 cards, fully specified in `warlock-table-interruption-cards.md`, none of it implemented. Needs per-card patterns, audio, an NPC-binding editor, and a real mechanism for layering an Aura over a running scene. Its companion JSON is referenced but not in the repo.
- **Everything on the player phone beyond claiming a seat** — dice, break requests, whispers. **How far the phone should go is deliberately unsettled: ask, do not assume.**
- **Input-to-effect latency** (§5.7) — the NFC read is the biggest single delay and sits upstream of everything. **Measure before changing anything.**
- Audio upload and scene authoring in the panel (§4.5 steps 3–4)
- Govee, voice/personality, dice, session recap — Phase 3+. Overseer is explicitly **not planned**.

**Read these before touching the matching area:**
- `warlock-table-led-reference.md` — **before any Pixelblaze pattern.** Layout, the verified `segStart` ordering (do not "tidy" it), and the **power budget: the brightness limit is a 40 A supply constraint, not a preference.**
- `display-image-specifications.md` — before generating artwork. Grid pitch is **107.85 px**, not what the panel dimensions imply.
- `deploy/README.md` — before touching the Pi. Two copies of the code, and the ARM install route.
- `warlock-table-style-guide.html` — before any UI work.

**Environment notes that save time:**
- Laptop has Python 3.12. Windows' Store alias shadows it in an already-open terminal — open a fresh one.
- The Pi needs a special `pixelblaze-client` install (`mini-racer` has no ARM wheel) plus a stub. `deploy/README.md`.
- Pixelblaze at 10.10.0.171, Pi at 10.10.0.24. **Prefer discovery over hardcoding** — the Pixelblaze IP has already drifted once.
- **Config is Pi-owned.** `/var/lib/warlocktable/config.json` does not come from git; editing `data/config.example.json` will not reach the table.
- The panel and the interactive CLI **cannot both own the NFC reader**. Stop the service first.

**SD card image:** `~/Documents/warlocktable-backups/` on the laptop, verified. See its README. **It is stale as of 2026-08-21** — since it was taken, `/boot/cmdline.txt` gained the forced-HDMI `e`, `segno` was installed into the venv, and the live config grew new keys. None of that comes from git, which is exactly what the image is for. Take a fresh one.

## Zones and seats (added 2026-08-21)

The table perimeter divides between the GM and 1–7 players. The GM's section
is fixed — 38 inches (93 LEDs at 96/m) centred on the bottom edge in front of
the television — and the rest splits into equal arcs, numbered **clockwise
from the GM**.

The map is computed, never configured: `warlock/zones.py` is the only place
the division lives on this side. Set the count from the panel's **Seats**
section, or:

```bash
python -m warlock.zones 5        # what 5 players looks like
python -m warlock.zones verify   # the maths, and agreement with the pattern
```

**The one thing that will catch you out:** the arithmetic exists twice. The
Pixelblaze pattern `patterns/zones.js` derives the map on-device from three
numbers rather than being sent all 764, because per-turn initiative lighting
will move a highlight every turn and shipping the whole array each time is
wasteful. `zones.verify()` compares the two and Table Check runs it before
every session — if you change the division rule, change it in **both** files
and let the check tell you if you got it wrong.

**Patterns go up through the API**, from the laptop:

```bash
python tools/upload_pattern.py zones      # --activate to switch to it
python tools/upload_pattern.py --list     # what is on the device
```

Compiling needs V8, which the client gets by downloading the compiler from
the Pixelblaze's own web UI and running it under `py_mini_racer`. That has
no ARM wheel, so it is stubbed on the Pi — **upload from the laptop, not the
Pi.** Saving does not activate, so it is safe mid-session.

`zones` is already on the device and confirmed working. If it ever goes
missing, `supports_zones()` reports false, the panel says so, and the seat
actions no-op instead of failing.

**The language is not JavaScript, whatever the `.js` extension suggests.**
User-defined functions need the `function` keyword. Compile against the
device before believing any pattern is correct — it is the only thing that
knows.


## Working-style reminders

- Small increments; confirm each works before the next.
- When something breaks, ask for the **exact error text**.
- Commit to Git often (that's the undo button).
- Keep the project plan doc as the shared source of truth; update it as decisions are made.
