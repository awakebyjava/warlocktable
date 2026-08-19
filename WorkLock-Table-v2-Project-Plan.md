# Warlock Table v2 — Project Plan

*A living document. Everything below is a first-pass distillation — sections are meant to be expanded, corrected, and reorganized as we go.*

---

## 1. Vision

WorkLock Table v2 is an interactive, immersive table build centered on a Raspberry Pi 4 with an embedded television, driven by a Pixelblaze LED system, NFC card interactions, and a reactive light + sound environment. The goal is a fun, immersive experience where lights, audio, screen visuals, and physical NFC cards all work together and respond to what's happening in the room.

The big themes:
- **Physical interaction** via NFC cards (and phones)
- **Immersive ambiance** — coordinated light scenes, soundscapes, and screen visuals
- **Reactivity** — the environment responds to live audio and possibly spoken triggers
- **Extensibility** — easy to add new cards, new scenes, and new behaviors over time

---

## 2. Hardware Inventory

*(Confirm / correct these — some are assumptions.)*

| Component | Role | Notes |
|---|---|---|
| Raspberry Pi 4 | Main brain | Runs the embedded TV display and core software |
| Embedded television | Primary visual surface in the table | Driven by the Pi |
| Pixelblaze | LED controller / pattern engine | Has a sound/audio input for live-audio effects |
| Pixelblaze Output Expander | Fans out many LED channels | Currently suspected faulty — see Phase 1 |
| Light signal distribution board | Custom board routing expander channels to LED runs | Being rebuilt |
| PN532 NFC reader | Reads NFC cards / phone tags | Want to support more cards + phones |
| Audio output | HDMI + 3.5mm analog jack (Pi 4 has both) | Can run simultaneously if desired |
| Microphone | Voice / room-audio capture | Planned — for triggers and/or effects |
| (Future) Second computer | Virtual desktop accessible from iPad, etc. | Undecided / stretch goal |

---

## 3. Subsystems

### 3.1 Lighting (Pixelblaze + Expander)
- Pixelblaze drives patterns; the Output Expander splits the signal across many channels.
- The custom **light signal distribution board** carries those channels out to the physical LED runs.
- Live-audio reactivity is possible via the Pixelblaze's built-in sound input.
- **To expand:** how many channels, LED types/counts per channel, physical layout of the runs in the table, which scenes we want.

**Room / ambient lighting (Govee) — extends scenes beyond the table:**
- Already own Govee lights. Use the **Govee API**, triggered from the controller, so a "scene" isn't just the table LEDs — the whole room reacts (dim to red for combat, etc.).
- Cheap to expand: add Govee strips for **under-table lighting** and **accent lighting around the room**.
- **To expand:** confirm Govee API access (they gate it behind an API key / developer program), which fixtures, how they map into scenes.

### 3.2 NFC / Cards
- **Reader:** PN532.
- **Goals:**
  - Get the reader working reliably.
  - Support NFC tags on a phone (not just physical cards).
  - Expand the number of cards in play.
  - Build an interface for registering new cards and defining what each card *does* (its interactions/effects).
- **Existing card inventory (already RFID-tagged):**
  - **5 environment cards** — the five Magic: The Gathering mana types (White/Blue/Black/Red/Green). Likely used to set the environment / mood of the table.
  - **A few tarot cards** — e.g., Wheel of Fortune, The Devil, Ace of Pentacles. **Tarot is the intended expansion path** — the card set that grows and carries the richer, more numerous interactions.
- **To expand:** what a "card interaction" should be able to trigger (a light scene? a sound? a screen change? a combination?), how cards are stored/managed, whether cards have state, and the specific behaviors for the mana/environment cards vs. the tarot cards.

### 3.3 Audio & Soundscapes
- Rich background soundscapes tied to the embedded TV visuals.
- Soundscapes echoed/coordinated with the lighting.
- Expanding overall audio capability and complexity.
- **Audio routing:** Pi 4 can output HDMI + analog jack simultaneously if we want sound in multiple places.
- **To expand:** where speakers physically live, how many independent audio zones, what the soundscape library looks like, how audio syncs with light scenes.

### 3.4 Voice / Live Audio Input
- Two related but distinct ideas:
  1. **Live-audio reactive effects** — lights/visuals respond to ambient room sound (Pixelblaze sound input, and/or Pi mic).
  2. **Spoken triggers** — the Pi listens on a microphone, recognizes speech, and fires events when someone says something.
- **To expand:** on-device vs. cloud speech recognition, wake-word vs. always-listening, privacy considerations, what phrases trigger what.

### 3.5 Table Personality / Voice
The table has a **character** — a personality expressed through a voice that can talk back and interact.

- **Voice responses.** The table "speaks" using audio clips. Triggered by:
  - **Keyword spotting** — the room mic on the Pi listens for keywords/phrases and fires matching responses, so the table seems to react to what people say in the room.
  - **The web panel** — you can also trigger any line manually (great for testing, or for playing "operator" during a session).
  - (Later) NFC cards or events could trigger lines too — it's just another action.
- **Pre-rendered voice library.** Rather than live text-to-speech, render a bunch of lines ahead of time to establish a consistent voice and personality. Build out a library of clips that flesh out the character.
- **Design notes:**
  - Pre-rendered gives better quality + a consistent "voice" than on-the-fly TTS; live TTS could be a later fallback for dynamic/unscripted lines.
  - Personality is worth writing down: who *is* the table? Tone, attitude, catchphrases, how it responds to different keywords.
- **To expand:** the personality itself, the keyword→response map, how many lines, how the mic keyword-spotting works (ties into 3.4), where the voice comes from (which TTS/voice for pre-rendering).

### 3.6 Display (Embedded TV)
- Television embedded in the table, driven by the Pi.
- Shows light/soundscape-linked background visuals.
- **To expand:** what the visuals are (generative? video files? a custom app?), resolution/orientation, how visuals stay in sync with lights and audio.

### 3.7 Control Surfaces (Two-Tier Control)
The table is controlled through two deliberately separate surfaces:

- **Guest-facing / physical — NFC cards.** Drive the immersive "magic" interactions. This is the primary, in-world way to interact with the table.
- **Operator-facing — web control panel.** A "backstage" web app served from the Pi, accessed over Wi-Fi from an iPad (or any device on the LAN). For everything *not* bound to a card: overrides, quick switches, and controls that would be awkward as physical cards.

**Web panel should include shortcuts for:**
- **Pixelblaze control** — a clean custom set of buttons (set pattern, brightness, trigger variables) instead of Pixelblaze's own UI. Uses the Pixelblaze **WebSocket API** (Python client: `pixelblaze-client`).
- **Audio player + mix** — start/stop soundscapes, adjust the mix, layer effects over the music. Candidate base: **MPD (Music Player Daemon)**, which is headless and LAN-controllable.
- **Digital background switching** — simple static-image switching as a v1; more later.
- **Hand-off to Apple TV** — one button that switches the TV's input to the connected Apple TV (which handles anything more complex than the Pi renders). Likely via **HDMI-CEC** (`libcec` / `cec-utils`), if the TV supports CEC.

**Implementation notes:**
- Serve as a **PWA** so it "Add to Home Screen"s on the iPad as a full-screen, app-like icon.
- Lightweight Python server (**FastAPI** or **Flask**) fits well if the rest of the stack is Python.
- **v1 scope decision:** buttons/shortcuts that *fire actions* (no live status readback yet — that's a later enhancement).
- **To expand:** exact button list, layout, whether any controls need live state later.

**Player phones as second screens (subtask):**
- The same Pi web server can serve **player-facing pages** to phones on the Wi-Fi — a lighter counterpart to the operator iPad panel.
- Uses: **rolling dice** (pairs naturally with dddice — see Dice subsystem), **requesting a break**, and other simple player actions.
- **Private messages:** the table can send a **private whispered message** to an individual player's phone — great for secrets, DM asides, and character-specific info.
- Mostly "more routes" on the server you're already running; low added cost.

### 3.8 Pixelblaze Patterns — Authoring & Upload
Two distinct pieces, deliberately separated:

- **Pixel map (one-time, DIY task).** The table needs a correct pixel map (x/y coordinates per LED) built once and pasted into Pixelblaze's Mapper. This is a manual setup step, not a tool to build — but it's a prerequisite for good 2D patterns, so it's worth doing early. *No custom tooling needed; just get it done once.*
- **Pattern authoring (collaborative, with Claude).** Pixelblaze patterns are written in a small JavaScript-like language and are simple enough that the workflow is: **describe the pattern in plain English → Claude writes the Pixelblaze code**. The "tool" here is really just that collaboration loop, plus a way to get the code onto the device without hand-copying.
- **Upload via API (buildable feature).** The `pixelblaze-client` Python library can write patterns to the device programmatically over WebSocket. So an **"upload new pattern" button in the web panel** is real and achievable: Claude writes the pattern → the panel pushes it to the Pixelblaze → it appears on the table.

**What makes Claude's patterns good:**
- A correct **pixel map** (so patterns animate across the true physical layout).
- Access to the **Pixelblaze language reference** when writing, for correct syntax.

**To expand:** how patterns get versioned/stored, whether the panel lists/manages existing patterns too, whether we want live preview.

### 3.9 Virtual Tabletop Integration (Overseer Studio)
Bridge the table's controller to a virtual tabletop app so on-screen game events drive real-world effects (and vice versa).

- **The app:** **Overseer Studio** — note this is *not* a VTT itself, but a modular, offline-first **GM workspace** ("a tool for your tools") that embeds other apps (D&D Beyond, Roll20, Spotify, etc.) as tiles on a canvas. Desktop app for Windows/macOS/Linux, one-time purchase, in Early Access as of mid-2026. Made by the creator of Astral Tabletop and dddice.
- **It has a real plugin SDK** — the key enabler:
  - Extensions are **HTML/JS**, built/published via an official CLI (`@overseer-studio/sdk`).
  - Runtime library exposes **events, toasts, shortcuts**, and a **keyed state store** that persists across sessions.
  - You can define **named shortcuts** in the manifest and listen for them (e.g., `onShortcut('next-turn', ...)`).
- **Integration shape:** build an **Overseer plugin that bridges Overseer ↔ the Pi controller.** A named shortcut or event in a session → plugin notifies the controller → controller drives lights/sound/voice. And the reverse: a card or panel button → triggers something in Overseer.
- **Honest caveats:**
  - The SDK's events look oriented around **Overseer's own tiles/shortcuts/state**, not deep hooks into whatever VTT is embedded inside it. So "GM fires a named shortcut → table reacts" is very likely; "react to a specific in-VTT combat event" may not be exposed.
  - **Early Access = moving target.** The API will change. The full dev docs + their Discord are where to confirm the current event vocabulary.
- **To expand:** confirm exact available events, decide the shortcut/event → effect mapping, how the plugin reaches the Pi (HTTP call to the controller over the LAN?).

**Per-seat initiative lighting (subtask — depends on Overseer):**
- Each player gets a zone of the LED layout; the **active player's zone lights up on their turn**.
- Only really practical if driven *by* Overseer — a "next turn" shortcut/event advances the highlight automatically, so there's nothing extra to manage by hand in-game.
- Deliberately **not** a standalone feature (too fiddly to run manually); it rides on the VTT integration.

### 3.10 Session Logging & Recap
Turn the room mic into a session record and auto-generate recaps.

- Since a good room mic is already part of the build, **record the session audio**, run it through **AI transcription**, and generate a **recap / summary** afterward.
- Could also log dice rolls and notable events alongside the transcript for a richer recap.
- More utility than immersion, but a genuinely nice payoff for having the mic there anyway.
- **To expand:** which transcription/AI service, on-device vs. cloud, how recaps are formatted/delivered (email? a page on the web panel?), retention/privacy.

### 3.11 Dice
Two complementary options; not mutually exclusive.

- **Pixels dice (physical, planned — later).** Real polyhedral Bluetooth dice full of LEDs that know which face they land on and can report it wirelessly. The player rolls a real glowing die → the table reacts (lights, sound, voice). Best fit for the physical/tactile feel of the table. There are official SDKs plus an ESP32 Bluetooth library, so the dice can feed the controller. **Chosen as an option, but scheduled for later — not near-term.**
- **dddice (software 3D dice).** Same creator as Overseer Studio; full API/SDK, renders 3D dice, syncs rolls, keeps a roll log, can display rolls on screen. Natural fit for **player phones as second screens** (roll from your phone, see it on the table's TV) and for remote players. The controller can react to roll results (nat 20 → gold + cheer, nat 1 → red).
- **To expand:** which comes first (dddice is the lighter/cheaper start; Pixels is the "wow"), how rolls map to effects.

### 3.12 (Future) Virtual Desktop / Remote Access
- Possibly add a second computer running a virtual desktop.
- Accessible remotely from an iPad or similar.
- **To expand:** why (what workload needs it), which VD tech, how it fits the table physically. Flagged as a stretch/later goal.

---

## 4. Architecture

*(Early thinking — this is the part we're actively working out.)*

**Central Controller pattern (recommended).** Build one "controller" service on the Pi that *owns all the actions* — play soundscape X, set light scene Y, switch background Z, hand off to Apple TV, etc. Every input then just calls into that same layer:

```
   NFC cards ──┐
   Web panel ──┼──▶  Controller (owns all actions)  ──▶  Pixelblaze
   Voice ──────┘                                     ──▶  Audio (MPD/mixer)
   (future)                                          ──▶  Background/TV
                                                     ──▶  Apple TV (CEC)
```

Why this matters:
- A **card** and a **panel button** can fire the *identical* action with no duplicated logic.
- Adding **voice** later is just a third input feeding the same controller.
- Actions are defined once, in one place, and become the vocabulary for the whole table.

**Open architectural questions:**
- Language/stack for the controller (Python is the likely fit given NFC + GPIO + Pixelblaze client).
- One monolithic app vs. small cooperating services (and if the latter, how they talk — HTTP, a message bus, etc.).
- How actions are represented (a registry/config? code? data the card-management UI can edit?).
- How the web panel talks to the controller (shared process vs. API calls).

---

## 5. Roadmap

### Phase 1 — Hardware Foundation *(CURRENT)*
Get the Pixelblaze lighting physically solid and verified before touching software.

- [ ] Rebuild the **light signal distribution board**
  - [ ] Correct the many channels coming off the Output Expander
  - [ ] Fix the **ground wire connection** (suspected root cause of the current fault)
  - [ ] Redesign the distribution layout for reliability
- [ ] Reflow suspect solder joints across the boards
- [ ] Power-on test: confirm expander status LED behaves (powered + receiving data + drawing)
- [ ] **Verify the lighting system works as-is** end to end

**Exit criteria:** Pixelblaze reliably drives all intended LED channels through the rebuilt board, with a clean ground and solid joints.

### Phase 2 — Software Foundation
Stand up the core software on the Pi once hardware is trusted.

- [ ] Decide overall software architecture (what runs on the Pi, how subsystems talk to each other)
- [ ] Get the PN532 NFC reader reading reliably
- [ ] Basic audio output working (HDMI/analog as needed)
- [ ] Basic screen visuals on the embedded TV
- [ ] A way for one input (e.g., an NFC card) to trigger one output (e.g., a light scene) — the first end-to-end interaction

### Phase 3+ — Feature Build-Out
- [ ] Operator web control panel (Pixelblaze/audio/background shortcuts, Apple TV hand-off)
- [ ] Build the table's Pixelblaze pixel map (one-time)
- [ ] Pattern authoring loop + "upload pattern" via the web panel
- [ ] Card management interface (add cards, define interactions)
- [ ] Phone-tag NFC support
- [ ] Govee room/accent lighting via API, synced into scenes (+ under-table strips)
- [ ] Player phone second-screens (dice rolls, break requests, private whispers)
- [ ] Soundscape library + light-scene coordination
- [ ] Live-audio reactive effects
- [ ] Spoken-trigger events
- [ ] Table personality: write the character, record/render the voice-line library
- [ ] Keyword-spotting → voice responses (plus panel-triggered lines)
- [ ] Overseer Studio plugin bridging VTT events ↔ the controller
  - [ ] Per-seat initiative lighting (rides on the Overseer integration)
- [ ] Session recording → AI transcription → recap
- [ ] dddice integration (software dice on screen / player phones)
- [ ] Expanded audio zones
- [ ] (Later) Pixels physical dice support
- [ ] (Stretch) Virtual desktop / iPad remote access

**Separate / not table-run:** fog machine (mentioned, but handled independently — not driven by the table).

---

## 6. Open Questions To Work Through Together

- ~~Project / table name & branding~~ → **DECIDED: the project is called "Warlock Table."** (Visual branding still TBD, but the name is locked.)

- Pi 4 OS + version (desktop vs. Lite, Bookworm vs. Bullseye)? Affects audio, NFC, and app choices.
- What software stack do you want the immersive layer written in (Python? something else)?
- How should subsystems be coordinated — one central app, or independent services talking over a message bus?
- What's the "unit" of an experience — is it card-driven, scene-driven, time-driven, or a mix?
- How much should be authored/hand-designed vs. generative?
- Physical constraints: LED counts, speaker placement, mic placement, table layout.

---

## 7. Notes / Scratchpad

*(Running notes as we refine — add freely.)*
