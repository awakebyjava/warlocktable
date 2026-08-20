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

*(Updated 2026-08-20. The project plan doc is the detailed source of truth — this is the summary.)*

- **Phase 1 (hardware) is COMPLETE.** The light distribution board is rebuilt and all 764 pixels across 8 expander channels are verified physically. `warlock-table-led-reference.md` is the ground truth for the layout, the corrected `segStart` ordering, the pixel map, and the power budget. **Read it before writing any Pixelblaze pattern.**
- **Phase 2 (software foundation) is current**, and the core loop works end to end on real hardware: **a physical NFC card tap drives the real table.** Controller runs on the Pi, finds the Pixelblaze by discovery, and the laptop is not in the path.
- **Real:** lights (Pixelblaze) and card input (PN532). **Still fake:** audio and display.
- **Not built:** the web panel and management UI, headless mode, and the `install.sh`/systemd deployment. The controller currently runs from the git working tree and must be started by hand — fine for development, not for a real session (see plan doc §5.5).

**Environment notes that will save you time:**
- The laptop has Python 3.12 (installed 2026-08-20). Windows' Store alias can shadow it in an already-open terminal — open a fresh one.
- The Pi needs a special install route for `pixelblaze-client`: `mini-racer` has no ARM wheel. See `deploy/README.md`.
- Pixelblaze is at 10.10.0.171 ("Warlock's Table"), the Pi at 10.10.0.24. Prefer discovery over hardcoding either — the Pixelblaze IP has already drifted once.

**Suggested next steps:** the audio driver (the last fake with real design content in it — two channels, crossfade, ducking), then deployment so the table survives a power cycle.

## Working-style reminders

- Small increments; confirm each works before the next.
- When something breaks, ask for the **exact error text**.
- Commit to Git often (that's the undo button).
- Keep the project plan doc as the shared source of truth; update it as decisions are made.
