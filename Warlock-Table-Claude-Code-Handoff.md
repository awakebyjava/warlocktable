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

**The table works.** A physical NFC card tap drives real lights, real sound and real artwork on the embedded TV, from a service that starts itself on boot and survives a power cut. Deployed build: **v0.2.0**.

**All four subsystems are real** — nothing is a fake any more:

| | |
|---|---|
| Lights | Pixelblaze, 764 px, found by UDP discovery. Pattern writes verified by read-back. 50% ceiling (power budget — see below) |
| Audio | Two channel groups: looping bed + layered one-shots, true crossfade, ducking. Output pinned by name to the 3.5mm jack |
| Cards | PN532 over SPI. Tap semantics — fires once, re-fires only after lift-and-replace |
| Screen | feh fullscreen at 3840×2160. Backgrounds carry named overlays: none / square grid / hex |

**Also built:** the operator panel (iPad PWA on :8080 — status strip, controls, brightness, overlays, **card editing** including registering an unknown tag by tapping it), the **TV status screen**, **Table Check** (pre-session self-test), headless mode, `install.sh` + systemd, and the full visual identity on both surfaces.

**Not built yet:**
- **Zones are not mapped to LEDs, and there is no per-zone lighting.** This blocks seat claiming, and therefore player phones. **Fully specced in plan doc §4.7** — zone table, the exported-variables mechanism, and the traps. It is the next piece of work.
- Audio upload and scene authoring in the panel (§4.5 steps 3–4)
- Govee, voice/personality, Overseer, dice, session recap — all still Phase 3+

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

**SD card image:** `~/Documents/warlocktable-backups/` on the laptop, verified. See its README.

## Working-style reminders

- Small increments; confirm each works before the next.
- When something breaks, ask for the **exact error text**.
- Commit to Git often (that's the undo button).
- Keep the project plan doc as the shared source of truth; update it as decisions are made.
