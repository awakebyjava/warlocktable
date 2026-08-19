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

## Where we are right now / suggested next steps

- Repo is set up and syncing via GitHub. Prior code is being sorted into version folders.
- **Hardware Phase 1 is in progress:** the user is rebuilding the light signal distribution board (bad solder joints; suspected ground-wire fault on the Pixelblaze Output Expander). Software should assume the lighting hardware may not be fully verified yet.
- **Good first software milestone:** prove the Git-bridge loop end to end with something tiny — e.g., a small Python script (written on the laptop, pushed, pulled on the Pi, run on the Pi) that connects to the Pixelblaze via `pixelblaze-client` and changes one color. Once that loop works, every feature after is a repeat of it.
- From there, begin standing up the controller skeleton per the plan doc (Phase 2: software foundation).

## Working-style reminders

- Small increments; confirm each works before the next.
- When something breaks, ask for the **exact error text**.
- Commit to Git often (that's the undo button).
- Keep the project plan doc as the shared source of truth; update it as decisions are made.
