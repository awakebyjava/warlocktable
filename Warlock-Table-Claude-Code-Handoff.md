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

*(Updated 2026-08-24. `Warlock-Table-v2-Project-Plan.md` is the detailed source of truth — this is the summary. If they disagree, the plan doc wins.)*

**The table works.** A physical NFC card tap drives real lights, real sound and real artwork on the embedded TV, from a service that starts itself on boot and survives a power cut. Deployed build: **v0.3.1-83-gcaadada** (v0.4.0 is unreleased — see the README's Versions section for what has landed since the tag).

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

**Built 2026-08-22 (later session):**
- **Card effects start when the card is tapped.** One-shot envelopes ran on `time()`, a free-running wall clock, so a Boon's flash sat at a fixed offset in an 18s cycle unrelated to the tap — the four Aces and the Magician showed nothing most of the time. They now run off `cueEl`, zeroed at activation.
- **Auras are stings, capped at 10s** (Tower 4s, most 8–9s), each with a one-shot gate so it arrives, plays and leaves instead of being chopped off mid-cycle at 60s. `duration_s` matches each pattern's own length.
- **The Hermit carries the lantern** — was a static point on a corner ring half the table could not see.
- **The status screen is selectable and carries the join QR**, with a panel button.
- **Display auto-recovery** — feh dying no longer means a black TV until someone restarts the service.
- **Unbuffered logging** — journald now reflects the present, not four kilobytes ago.

**Built 2026-08-22 (earlier):**
- **All patterns generated** from `tools/patterngen.py` — 30 of them, on the device. The five terrain scenes were compared against the hand-written originals on the table before replacing them; originals kept in `patterns/legacy/`.
- **The tarot system** — 26 cards with config entries pointing at their own patterns, and all 32 physical cards enrolled. Wheel of Fortune draws a random Aura. Silent for now: `Interruption.audio` is optional so the cards work before the clips exist.
- **Stock patterns pruned** — 39 removed after archiving, then the 40 aura×scene combos on top. *(Superseded: abandoning aura layering took the device from ~70 patterns to 30, and free flash from 529KB to 830KB.)*
- **Aura-over-scene layering was ABANDONED**, not deferred. The combos existed but nothing ever selected one, and finishing the feature meant 72 patterns on flash that had already been filled once. An Aura now replaces the scene and reverts. Do not rebuild the combos without reading plan doc §3.2 first — the reasons are recorded there and the memory is better spent elsewhere.
- **`idle` is hand-written**, `patterns/idle.js` — not from the generator. It is the state the table sits in longest and it was running a stock pattern called `breathing`. Deep unlit-warlock-eye violet, eyes opening into neon, a surge every ~20s.

**Built 2026-08-23/24 (this run):**
- **Player phone tools** — signals (`?` / `!` with a 60s expiry), dice with a shared roll log, and private whispers. No public channel, by design. §3.7.
- **Govee accent lighting** over the **LAN** API, never the cloud. The colour is derived from each scene's own palette, so the room cannot drift out of step with the table. §3.13.
- **The interface redesign** — four GM panels behind a bottom tab bar, three breakpoints, a whisper overlay, card management as its own page. 7.4 screens of scrolling became none on the target iPad. §3.7.
- **The status screen rebuilt on brand** — wordmark hero, the table's two real sigils, **four corner QR codes** (people sit on all four sides), one compact subsystem row, `Prepared` / `Assistance Needed`, and `tablecheck` folded in at startup. §3.6.
- **Seats can be vacated** from either side, **initiative counts rounds and turns**, **rolls show the individual dice**, and there are **preset roll bars** for d20 / WoD / BRP.
- **Latency** measured and cut from ~2s to under 600ms. §5.7.
- **All 32 physical cards enrolled.**

**Not built yet:**
- **Audio for the 26 tarot cards.** The cards fire silently; `Interruption.audio` is optional so they work before the clips exist. `tools/audio_worksheet.py` lists what is missing.
- Audio upload and scene authoring in the panel (§4.5 steps 3–4)
- **Display redesign** (§3.6) — real grid/hex overlays and battle maps.
- Voice/personality, session recap — Phase 3+. Overseer is explicitly **not planned**.
- **NPC binding editor** — *dropped.* The user's call: "NPC binding isn't going to happen." Do not resurrect it.

**Before measuring frame rate, read §5.3.** `getStatistics()` turns on
preview streaming and its fps figure lags a pattern switch by seconds. Read
carelessly it reports the PREVIOUS pattern, which makes per-pattern render
cost look like the device degrading. That cost real time on 2026-08-22 and
produced two pointless reboots and one confidently wrong answer. Fresh
connection, set, drop the socket, wait 14s, reconnect, one reading.

**Before touching the Pixelblaze, read §3.8 and §5.3.** An unattended bulk
upload wedged it, cost a power cycle, and lost the entire LED configuration
including the brightness limit that keeps the table inside its 40 A supply.
The short version: stop the controller first, never run device work
unattended, pass an empty preview image, and expect a transient failure
every 5–15 operations that is safe to retry.

**Two traps found on 2026-08-24, both of which wasted a deploy cycle:**

- **Run `./deploy/update.sh` WITHOUT sudo.** It elevates itself. Git
  compares a repo's owner against `SUDO_UID`, so running the whole script
  as root makes the nested `sudo install.sh` see `SUDO_UID=0`, which no
  longer matches the pi-owned repo; git rejects it as dubious ownership
  and the deploy stamps `VERSION` as `not-a-git-checkout`. The table then
  cannot say which build it is running. It now refuses to start as root.
- **A deploy landing is not the same as a browser seeing it.** The server
  sent no cache headers at all for HTML/CSS/JS, which does not mean "do
  not cache" — with no directive and no validator a browser may reuse a
  response indefinitely, and it did. A redesigned panel rendered with the
  previous stylesheet, and the files on the Pi were demonstrably correct
  the whole time. Fixed with `no-cache` plus an ETag. **If the table looks
  wrong after a deploy, check what the browser is actually holding before
  debugging the code.**

**Read these before touching the matching area:**
- `warlock-table-led-reference.md` — **before any Pixelblaze pattern.** Layout, the verified `segStart` ordering (do not "tidy" it), and the **power budget: the brightness limit is a 40 A supply constraint, not a preference.**
- `display-image-specifications.md` — before generating artwork. Grid pitch is **107.85 px**, not what the panel dimensions imply.
- `deploy/README.md` — before touching the Pi. Two copies of the code, and the ARM install route.
- `warlock-table-style-guide.html` — before any UI work.

**Environment notes that save time:**
- Laptop has Python 3.12. Windows' Store alias shadows it in an already-open terminal — open a fresh one.
- The Pi needs a special `pixelblaze-client` install (`mini-racer` has no ARM wheel) plus a stub. `deploy/README.md`.
- **Addresses drift and DHCP reservations are still not done.** As of 2026-08-24 the Pi is at **10.10.0.23** and the Pixelblaze at **10.10.0.169**; both have moved twice. **Prefer discovery over hardcoding**, and reach the Pi as `raspberrypi.local` rather than by address.
- **Config is Pi-owned.** `/var/lib/warlocktable/config.json` does not come from git; editing `data/config.example.json` will not reach the table.
- The panel and the interactive CLI **cannot both own the NFC reader**. Stop the service first.

**SD card image:** `~/Documents/warlocktable-backups/` on the laptop, verified. See its README. **It is stale as of 2026-08-21, and more so now** — since it was taken, `/boot/cmdline.txt` gained the forced-HDMI `e`, `segno` was installed into the venv, and the live config grew new keys. None of that comes from git, which is exactly what the image is for. Take a fresh one.

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
