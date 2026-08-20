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
- **Resolved — see §4.3–4.5 for the full interaction spec.** In short: cards are dumb triggers (UID + label); every card is a tap (no presence detection); a card points at a Scene, an Interruption, or a Random Table, editable between them in the management UI; cards are stateless. The mana/tarot distinction is configuration, not code — mana cards happen to map to Scenes and tarot cards to Interruptions, but either could be either.

### 3.3 Audio & Soundscapes
- Rich background soundscapes tied to the embedded TV visuals.
- Soundscapes echoed/coordinated with the lighting.
- Expanding overall audio capability and complexity.
- **Audio routing:** Pi 4 can output HDMI + analog jack simultaneously if we want sound in multiple places.

**Where audio files live (important):**
- **Audio is deliberately *not* in the git repo.** `.wav/.ogg/.mp3/.flac` are gitignored. Large binaries can't be diffed or compressed and every version is kept forever — the V1 audio alone was **1.08 GB**, which would have made every clone and every Pi pull drag.
- **Master copies:** `C:\Users\jonre\Documents\warlocktable-audio\` on the laptop (`Ov/` and `MagicCards/`, as moved out of `Warlock Table V1/MagicTarot/`).
- **Getting audio to the Pi:** `rsync` over the existing passwordless SSH — code goes via GitHub, media goes direct. Two different transport paths for two different kinds of asset.
- Note the legacy V1 code expects these files at `/home/pi/Documents/MagicTarot/Ov/...`; v2 should read the audio path from config rather than hardcoding it.

- **Backup:** masters are backed up on a personal external hard drive — **last verified current 2026-08-18** (all 36 `Ov/` files, including the 7 MP3s that had existed only on the Pi's SD card). Re-check whenever the sound library grows: git no longer provides an incidental second copy, so the backup is the only redundancy.

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
- **v1 scope decision (revised):** buttons/shortcuts that *fire actions*, **plus a subsystem status strip** — Lights / Sound / NFC / Network, green-or-red. Status readback was originally deferred to "later," but it's what turns *"it's broken and I don't know why"* into *"oh, the Pixelblaze lost power."* Cheap to build, and it's the difference between trusting the table and not. Full live state readback (current pattern, current track, volume levels) is still a later enhancement — this is just health, not detail. See §5.
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

*(Core shape is now decided — see §4.1/§4.2. Details still open at the end of the section.)*

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

### 4.1 The layers

The controller isn't one blob — it's a stack, where each layer knows as little as possible about the others (**separation of concerns**). Top to bottom:

| Layer | What it is | Why it's separate |
|---|---|---|
| **Control surfaces** | iPad panel, player phones. **Clients** talking HTTP to the controller (**server**) via a **REST API**. | Any device on the LAN can drive the table without knowing how anything works. |
| **Inputs / event sources** | NFC reader, panel, voice, dice. Each has one job: notice something and **emit an event** (`{"type":"card_scanned","uid":"04:39:67"}`). | An input never touches the lights. Adding voice later is just a new event source — the rest of the system doesn't change. |
| **Controller** | One long-running **service** (**daemon**) with an **event loop**, routing events to actions. | Single place where "what happens when" is decided. |
| **Config** | Event → action mapping in YAML/JSON. **Declarative** — describes *what*, not *how*. | New cards are data edits, not code edits. This is the fix for the V0/V1 `elif` chains. |
| **Actions** | The table's vocabulary: `set_light_scene`, `play_soundscape`, `speak_line`, `switch_background`. Held in an **action registry** (name → function). | Defined once, reused by every input. A card and a panel button fire the *same* action. |
| **Drivers / adapters** | Thin wrappers over each device — `lights.set_scene("combat")` internally calling `pb.setActivePattern("RedCard")`. | Presents a **stable interface** over a changeable implementation. Swap a device, and only this layer changes. |

**Why this ordering matters:** the V1 `TarotWizard.py` fused all six layers into one file — the NFC loop directly knew Pixelblaze pattern names *and* absolute audio paths. That's **tight coupling**, and it's precisely why adding a card meant copy-pasting Python.

### 4.2 Build order (fakes first)

The important consequence: **most of this can be built and tested on the laptop with no working hardware**, using **fakes** (a.k.a. stubs/mocks) — stand-in implementations satisfying the same interface. A fake `set_light_scene("combat")` just prints `LIGHTS → combat`.

0. Prove the Git-bridge loop (laptop → GitHub → Pi → runs).
1. **Write the action vocabulary down.** ~5–8 actions. A conversation, not code — these names become the project's shared language.
2. Controller skeleton, everything faked. Runs on the laptop.
3. Config file + event dispatch. Feed it a fake card scan, watch fake lights change. **At this point the entire logic of the table works, on a laptop, with no hardware.**
4. Swap *one* fake for real (lights first, once Phase 1 is done). Nothing else changes — that's the payoff. *If swapping in real hardware requires editing the controller, the layering is wrong.*
5. Swap in real NFC.
6. Add the web panel — nearly free, since the actions already exist.
7. Everything after is one of two moves: **a new input emitting events**, or **a new action in the vocabulary.**

**Risk to watch:** this is more structure than the project strictly needs on day one, and there's a real failure mode where the layers get built beautifully and nothing ever runs. Mitigation is step 3 — get to "fake table fully working" fast, then make it real. Don't build all six layers before anything works.

**Resolved architectural questions:**
- **Language/stack:** Python (NFC + GPIO + Pixelblaze client all fit).
- **One app vs. services:** **one process**, supervised by systemd, with fault isolation *inside* it (see §5.2). Microservices would add process management, IPC, and debugging pain to solve a problem that per-subsystem error handling already solves. One wrinkle to mitigate: if the controller wedges, the panel and its diagnostics go with it — hence the TV status screen (§5.1).
- **How actions are represented:** action registry in code, event→action mapping in config data.

### 4.3 Interaction Model

**A card is a trigger and nothing else.** A tag is a UID plus a human **label** describing the physical object ("The Devil", "blue postcard"). The system does not care what the object is — tarot card, playing card, postcard, stopwatch. Only the tag matters, and the behaviour lives entirely in what the tag is *mapped to*.

**Every card is a tap.** Physical presence detection was considered and **deliberately rejected** — leaving a card on the reader to hold a state gets confusing, and it conflicts with last-input-wins precedence. So: scan → fire → done. No removal events, no "card still sitting on the reader at boot", and the NFC layer stays dumb (read, debounce, emit). One reader, one card at a time.

**A card points at one of three target types:**

| Target | Behaviour | Currently used by |
|---|---|---|
| **Scene** | A state. Persists until something replaces it. | The five mana/environment cards |
| **Interruption** | Plays *over* the current scene, then reverts to it. | The tarot cards |
| **Random table** | Picks one of the above at random, rolled fresh each tap. | Wheel of Fortune, and anything else wanted |

Any card can point at any type, and it is **editable between them** in the management UI. Nothing about "tarot vs mana" is baked into the software — that is just how they happen to be configured today.

**Precedence: last input wins, flat.** A panel press or a new card supersedes whatever is running, including mid-interruption. No ranking between input sources.

**Stateless.** Same card, same behaviour, every time — random tables roll fresh but remember nothing. *(Variants that would need memory — "never repeat the last result", deck-style "each outcome once until exhausted" — are deliberately out for now, but are the obvious future refinement.)*

**Idle state:** breathing table lights, no background audio. This is the resting state, and what comes up on power-on (§5.1's visible-liveness signal).

**Transitions:**
- **Lights: hard cut.** Pixelblaze's fade/transition options appear to live in its sequencer/playlist mode rather than in direct `setActivePattern` API calls — *worth verifying on the device.* Building on the assumption of hard cuts; asking the Pixelblaze creator whether the API could support a fade, and treating it as a bonus if it arrives.
- **Audio: 1–2 second crossfade** between soundscapes.
- **Ducking:** the soundscape ducks under interruptions and voice lines where possible.
- All durations **tunable in the management interface**, not hardcoded.

**No timeline engine.** "Sequences" are content, not structure: a Pixelblaze pattern is already an animation, and an audio file is already a timeline. An interruption is simply *play this audio, set these lights, revert when it finishes*. A real step-scheduler would only be needed for **beat-coordinated** moments (lights flashing exactly on the thunder at 0:04) — deliberately out of scope, as it is a large jump in both build and authoring complexity for a modest gain.

### 4.4 Data Model

```
Card
  uid           NFC bytes
  label         human name of the physical object
  target        → Scene | Interruption | RandomTable

Scene           (a state — persists until replaced)
  name
  lights        Pixelblaze pattern
  soundscape    looping audio bed
  background    TV visual
  transition    crossfade / duck timings

Interruption    (plays over the current scene, then reverts)
  name
  audio         one-shot
  lights        optional override
  background    optional override

RandomTable
  name
  entries[]     list of targets; one picked at random per tap

Zone            6 total — one at each end, two along each side
  id, colour, LED range (from the pixel map)

Player
  name          entered on the web page
  zone          claimed by picking the colour they are sitting at
```

**Format: JSON.** The management UI writes this file, so it must round-trip cleanly by machine — which rules out hand-commented YAML, since a program rewriting it destroys every comment and reshuffles ordering. SQLite only if the relationships get tangled enough to earn it.

**Location: outside the git repo** (e.g. `/var/lib/warlocktable/`). Code is versioned in git and the Pi consumes it; card data is *owned* by the Pi and edited through the panel. Keeping data in the repo would put the Pi out of sync with GitHub on every card edit and break `pull.ff only` (§5.3). **Consequence:** card data has no incidental backup the way repo contents do, so export/backup is a required feature rather than a nicety.

### 4.5 Management System

The panel is not just a remote control — **it is the authoring tool.** This is a first-class requirement, not a later addition, because "actions as data" only pays off if something can edit that data.

Required capabilities:
- **View** every registered tag, its label, and what it maps to
- **Register** unknown tags — scanning an unrecognised card surfaces it as *unassigned*, ready to name and map. This replaces V1's `print('not a registered card!')` into a terminal nobody is reading
- **Edit** a card's target, including switching between scene / interruption / random table
- **Upload audio** through the panel and use it immediately in scenes and interruptions
- **Create and edit** scenes, interruptions, and random tables
- **Tune** transition and ducking durations
- **Fix seat claims** — reassign a player who picked the wrong colour, or resolve two people claiming the same one
- **Export / back up** the whole configuration

**Referential integrity: block with a list.** Deleting a sound that three cards use is refused, naming those three. The failure this exists to prevent is discovering a broken reference mid-session.

**The action registry must be self-describing.** For the UI to render editing forms it has to ask the controller what actions exist, what parameters they take, and which values are valid — with **live** lists where possible (patterns fetched from the Pixelblaze, sounds from the audio library). This makes it impossible to assign a pattern that does not exist, eliminating a whole class of "why isn't this card working".

**Two API surfaces, kept separate:**
- **Action API** — "do this now." Fires scenes, plays sounds. Instant, stateless.
- **Management API** — "change what things do." CRUD, validated, persisted.

**Access.** The operator panel is unrestricted. Player pages are a **separate, restricted surface** — name entry, seat claim, dice, break requests, receiving whispers — not the operator panel with buttons hidden, since hiding a control in a web page does not actually prevent anything. Players cannot fire scenes. Possibly later: letting players trigger sound effects and dice rolls.

**Seat claiming.** Players enter a name on the web page and pick **the colour of the lights they are sitting at**, which maps name → zone. This uses the table itself as the seat-identification mechanism and is self-calibrating. It implies a **seat-claim display mode** where the six zones show distinct colours — also useful for debugging zone layout.

**Resolved from §4.2:** the config schema is defined above; the web panel and controller share one process (§4) but expose the two API surfaces separately.

### 4.6 Fake-Hardware Skeleton (built)

The §4.2 milestone — "the entire logic of the table works, on a laptop, with no hardware" — is done. Lives in `warlock/`:

```
warlock/
  config.py       Config, Scene, Interruption, RandomTable, Card, Zone, Player
                  + load_config() with eager referential-integrity checking
  registry.py     the self-describing action registry (§4.5)
  controller.py   the Controller — every action from the vocabulary below,
                  precedence handling, timed interruption reverts
  eventlog.py     append-only JSON-Lines event log (§ open question 8)
  devices/        base.py = the abstract interfaces; fake.py = print-only
                  stand-ins. A real driver later implements the same
                  interface — nothing above the device layer changes.
  cli.py          the fake-NFC-tap prompt
run_table.py      entry point — `python run_table.py`
data/
  config.example.json   worked example, built from the real card inventory
                         (§4.4 — the Pi's live config lives outside the repo;
                         this file is a starting point, not production data)
```

No dependencies beyond the Python standard library.

**The action vocabulary (§4.2 step 1), as implemented:**

Targets — what a card or panel button points at:
```
apply_scene(scene)              enter a persisting state
play_interruption(interruption) layer over current, revert when done
roll_table(table)               pick at random, dispatch to the result
```
Primitives — what Scenes/Interruptions are built from, and what the panel drives directly:
```
set_lights(pattern)   set_soundscape(track)   set_background(image)
play_effect(sound)    speak_line(line)        set_brightness(level)
```
System:
```
go_idle()   handoff_display(target)   whisper(player, text)
```
The seat-claim colour display needed no new action — it's just a Scene, which is the data model doing its job (variety absorbed as config, not new code).

**Verified working**, tested over SSH against the Pi's Python 3.9 (the laptop currently has no Python installed at all — see the note below):
- A tapped card fires the right target; an unregistered card is reported, not silently ignored (V1's old failure mode)
- An interruption auto-reverts to the prior scene once its audio finishes
- A new action pre-empts a still-pending revert with no stray leftover state (the "last input wins" rule, proven, not just claimed)
- Random-table rolls vary tap to tap and stay stateless
- A dangling config reference is rejected at load with a specific error, not discovered mid-session
- `actions` command shows the registry describing itself, including live choice-lists pulled from the fake devices

**Known gap:** the laptop has no working Python interpreter — only the Microsoft Store alias placeholder, which errors on invocation. Worth fixing (a real install, e.g. via `winget install Python.Python.3.12` or python.org) before real device drivers are written here, since at that point testing everything via the Pi over SSH stops being convenient.

**Not yet built:** the real device drivers (Pixelblaze/audio/NFC), the web panel and its two API surfaces, systemd deployment. These are §4.2 steps 4 onward, gated on Phase 1 hardware being trustworthy.

---

## 5. Reliability & Startup Behavior

*Scope note: this is a hobby build, not a commercial appliance, and a certain amount of fiddliness is fine and expected. The specific thing worth engineering properly is **boot-up** — power the table on, pick up the iPad, and have it work without opening a terminal. Everything in this section serves that one goal; anything beyond it is explicitly out of scope (§5.5).*

### 5.1 Target startup sequence

1. **One switch** (smart plug or switched strip inside the table) powers Pi, Pixelblaze, LED supply, TV, and amp together.
2. Pi boots; systemd starts the controller with `Restart=always`. It comes up healthy **even though nothing else is ready yet**.
3. Pixelblaze associates with Wi-Fi; the controller's background retry loop finds it.
4. **LEDs come up to a default ambient scene on their own** — visible confirmation the table is alive, without having to go ask it.
5. TV shows a default background — or, if something is unhealthy, **a status screen naming what's wrong**. The TV is already there and already driven by the Pi, so this is a nearly free diagnostic surface, and it means you often don't need the iPad to know something's broken.
6. iPad → home-screen icon → panel loads, status strip all green.

Ready in about a minute, with no interaction required.

### 5.2 Core principles

- **The controller must start with zero hardware present.** Not "fail gracefully" — actually boot, serve the panel, and retry each device in the background until it appears. **Power-on order must never matter.**
- **Fault isolation.** Lights down ≠ sound down ≠ panel down. Every device call is wrapped so a failure marks *that* subsystem unhealthy and everything else carries on.
- **Discover, don't hardcode.** Devices announce themselves; the controller finds them.
- **The table reports its own status** — status strip on the panel (§3.7), status screen on the TV.
- **Never refuse to start.** Bad config → load last-known-good and surface the error on the panel.
- **No cloud call on the critical path.** Govee/dddice are cloud-dependent; lights, sound, and NFC must not care whether the internet is up.

### 5.3 Known failure modes to design against

| Failure | Why it happens | Mitigation |
|---|---|---|
| **Pixelblaze address drift** | DHCP lease expires or router reboots; hardcoded IP goes stale. *This already happened:* V0 hardcodes `10.1.10.165`, V1 `10.10.0.171`. | Use `PixelblazeEnumerator` discovery — **already present in the old code but ignored in favour of a hardcoded string.** Plus DHCP reservations for Pi + Pixelblaze, and mDNS (`warlocktable.local`) so the iPad never needs an IP either. |
| **Fixes made on the Pi getting lost** | Editing directly on the Pi puts the working version outside git. *This already happened:* V1's IP had a broken trailing slash (`"10.10.0.171/"` → malformed `ws://10.10.0.171/:81`). It was fixed by hand on the Pi and the fix sat there un-harvested; the repo carried the broken copy until it was spotted in Aug 2026. | Treat the Pi as consume-only (`pull.ff only` is set globally there). If a fix *must* be made at the table, port it back to the laptop the same session — otherwise the only working copy lives on an SD card. |
| **Boot race** | Pi boots faster than Wi-Fi associates or the Pixelblaze powers up. Old code does `pb = Pixelblaze(ip)` at module level with no error handling — one raise and the table is dark forever. | Controller starts regardless; background retry per device; `Restart=always`. |
| **Audio device roulette** | If the TV is off at boot, HDMI audio may not enumerate and the default output silently changes. | Pin the audio device explicitly in config. Never rely on "default." |
| **HDMI handshake** | Boot with the TV off → bad resolution or no output when it wakes. | Force hotplug in `/boot/config.txt` (verify the right setting for Bullseye). |
| **SD card corruption** | The #1 killer of long-running Pi projects; usually caused by yanking power. | Physical GPIO shutdown button → `shutdown -h now`; keep a known-good SD image on the shelf so recovery is ~20 min. Booting from USB SSD instead is a genuine upgrade the Pi 4 supports. |
| **Config typo bricks the table** | YAML edit the afternoon before a session. | Validate at startup; fall back to last-known-good; show the error on the panel. |
| **Game-day deploy** | The Git bridge makes it trivially easy to `git pull` an hour before people arrive and break everything. | Run a **tagged known-good version** on the Pi, not raw `main`, so rollback is one command. Test on the laptop first — the fakes (§4.2) make this possible. |
| **Unknown card scanned** | Old code printed `not a registered card!` to a terminal nobody is reading. | Surface it on the panel; ideally offer to register it right there. |

### 5.4 "Table Check" — pre-session self-test

One button on the panel that runs through:
- ping / discover the Pixelblaze, flash a test pattern
- play a one-second test tone on each audio output
- read the PN532 firmware version
- validate the config file

...and reports pass/fail per line. Run it ten minutes before people arrive. **This is the highest-value reliability feature in the whole build** — it's the difference between finding a problem with time to fix it and finding it with an audience.

### 5.5 Explicitly out of scope

Real techniques, but they're for appliances you can't physically reach — this one is furniture in the house:
- Read-only root filesystem / overlayfs
- Pi running its own Wi-Fi access point so the table doesn't inherit the house router's reliability
- Restoring exact scene state after a crash-restart

Revisit only if a specific problem actually shows up.

---

## 6. Roadmap

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

- [x] Decide overall software architecture — see §4 (layers, one process, config-driven actions)
- [x] **Write the action vocabulary down** (§4.2 step 1) — see §4.6
- [x] Controller skeleton with all-fake devices, running on the laptop — `warlock/`, run with `python run_table.py` (see §4.6). Built 2026-08-18. Python 3.12 since installed on the laptop, so development no longer round-trips through the Pi.
- [x] Config file + event dispatch — **fake table fully working end to end**, incl. verified: timed auto-revert from an interruption, a new scene correctly pre-empting a pending revert (precedence rule), referential-integrity rejection of a dangling reference, and stateless random-table rolls
- [ ] Run as a systemd service on the Pi (`Restart=always`, starts with zero hardware present)
- [x] Swap in real Pixelblaze via discovery, not a hardcoded IP — done; `--real-lights` drives the table, discovery recovers from a wrong/absent address hint
- [ ] Get the PN532 NFC reader reading reliably
- [ ] Basic audio output working (HDMI/analog as needed) — pin the device explicitly
- [ ] Basic screen visuals on the embedded TV
- [x] A way for one input (e.g., an NFC card) to trigger one output (e.g., a light scene) — the first end-to-end interaction **on real hardware**. Done 2026-08-20: a simulated card tap drives the physical table (`card forest` → GreenCard, `card thedevil` → sparkfire then timed revert). Input is still the CLI rather than the PN532, but the whole chain below it is real.

**Reliability work (per §5) — fold in alongside the above, not after:**
- [ ] Subsystem status strip on the panel + status screen on the TV
- [ ] Config validation with last-known-good fallback
- [ ] DHCP reservations + mDNS name so the iPad icon never breaks
- [ ] "Table Check" self-test button (§5.4)
- [ ] Physical GPIO shutdown button + a known-good SD image on the shelf
- [ ] Tag known-good releases; run tags on the Pi, not raw `main`

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

## 7. Open Questions To Work Through Together

- ~~Project / table name & branding~~ → **DECIDED: the project is called "Warlock Table."** (Visual branding still TBD, but the name is locked.)

- ~~Pi 4 OS + version~~ → **ANSWERED: Raspberry Pi OS Bullseye (Debian 11), aarch64/64-bit.**
- ~~What software stack for the immersive layer?~~ → **DECIDED: Python.** (See §4.)
- ~~One central app, or independent services on a message bus?~~ → **DECIDED: one process**, systemd-supervised, fault-isolated internally. (See §4.)
- ~~What's the "unit" of an experience?~~ → **ANSWERED: the Scene**, with Interruptions layering over it and Random Tables selecting between them. Card-driven and panel-driven both resolve to the same targets. (See §4.3.)
- How much should be authored/hand-designed vs. generative?
- Physical constraints: LED counts, speaker placement, mic placement, table layout.

---

## 8. Notes / Scratchpad

*(Running notes as we refine — add freely.)*
