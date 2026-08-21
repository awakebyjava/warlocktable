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

**Panel facts (measured, not assumed):** TCL, **1209 mm × 680 mm**, exactly 16:9, ≈ 54.6" diagonal. Now on the Pi's **HDMI0** (`HDMI-1` in xrandr, the primary port) and pinned to **3840×2160** via `/boot/cmdline.txt`. Full generation spec in `display-image-specifications.md`.

**Two traps, both hit for real:**
- The TV advertises **4096×2160**, which is DCI 4K at 17:9 and does *not* match the panel. EDID negotiation picked it and the desktop came up stretched. Never generate at that width.
- `vc4-kms-v3d` **ignores** the legacy `hdmi_group`/`hdmi_mode` settings. The kernel `video=` parameter is the working lever.

**Where display artwork lives — same split as audio (§3.3):**
- `map-sources/` in the repo: the small raw generator output (~1 MB each). Tracked, because they are the versioned originals.
- **Finished 3840×2160 renders are NOT in git.** At 5–15 MB each and growing with every map, they are the audio problem one order of magnitude down. They live at `/var/lib/warlocktable/backgrounds/` on the Pi and arrive by **rsync**, resolved via `settings.background_paths` in config.

**First batch delivered (2026-08-20).** Ten files: five terrains × gridless and gridded, all **exactly 3840×2160** at a true 16:9. They live in `backgrounds/` (gitignored, ~78 MB) and go to the Pi by rsync.

**OPEN — grid pitch needs checking against real miniatures.** A rough measurement of the gridded images suggests a pitch near **81 px** where the spec calls for **80.68 px** (1 inch / 5 ft / one medium base). If that is real it accumulates to roughly **0.2 inches of drift across the full 47-square width** — about a fifth of a mini base, so probably fine in play. But the measurement carries about ±1 px of its own noise, so it cannot distinguish 81.00 from 80.68 with confidence. **Settle it by putting actual minis on the actual table**, not by measuring the file. If it does drift, regenerate with `round(i * 80.68)` rather than a fixed 81 px step.

**Superseded note on the raw sources:** generated at 1376×768, aspect 1.7917 vs the panel's 1.7778. Close, but they need a **×2.81 upscale and a 30 px width crop** — crop rather than stretch, or circles become ovals. A plain resize will look soft at 80 px/inch; this wants a model-based upscaler.

- **To expand:** what drives the display (a fullscreen viewer? a custom app?), whether content is oriented to the GM's seat or orientation-neutral, and how visuals stay in sync with lights and audio.

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
| **Drivers / adapters** | Thin wrappers over each device — `lights.set_scene("combat")` internally calling `pb.setActivePattern("Mountain")`. | Presents a **stable interface** over a changeable implementation. Swap a device, and only this layer changes. |

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

### 4.6 The controller as built

The §4.2 milestone — "the entire logic of the table works with no hardware" — is done, and since then the first two fakes have been replaced with real hardware. Lives in `warlock/`:

```
warlock/
  config.py       Config, Scene, Interruption, RandomTable, Card, Zone, Player
                  + load_config() with eager referential-integrity checking
                  + normalise_uid()/format_uid() so a UID matches regardless
                    of case or separators
  registry.py     the self-describing action registry (§4.5)
  controller.py   the Controller — every action in the vocabulary below,
                  precedence handling, timed interruption reverts, and
                  per-subsystem fault isolation via _try() (§5.2)
  eventlog.py     append-only JSON-Lines event log (§ open question 8)
  devices/        things the controller CALLS
                    base.py               abstract interfaces + DeviceError,
                                          UnknownAssetError
                    fake.py               print-only stand-ins
                    pixelblaze_lights.py  REAL — discovery, read-back
                                          verification, health reporting
  inputs/         things that CALL the controller
                    nfc.py                REAL — PN532 over SPI, tap
                                          semantics, background retry
  vendor/         third-party code, kept close to upstream (see its README)
                    pn532/                Waveshare/Adafruit PN532 lib (MIT)
  cli.py          the interactive prompt
run_table.py      entry point
patterns/         Pixelblaze patterns kept in-repo so the device is not the
                  only copy (breathing.js = the idle scene)
deploy/           Pi install notes + the py_mini_racer stub (see its README)
data/
  config.example.json   worked example built from the real card inventory
                        (§4.4 — the Pi's live config belongs outside the
                        repo; this is a starting point, not production data)
```

**Dependencies:** `pixelblaze-client` (see `requirements.txt`). The Pi needs a
special install route — `mini-racer` has no ARM wheel — documented in
`deploy/README.md`. Everything else is standard library.

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

**How to run:**
```
python run_table.py                          all fakes, any machine
python run_table.py --real-lights            drives the real Pixelblaze
python run_table.py --real-lights --nfc      + real card taps (Pi only)
```

**What is real vs. fake, as of 2026-08-20:**

| Subsystem | State |
|---|---|
| Lights | **Real** — Pixelblaze found by discovery, pattern writes verified by read-back |
| NFC input | **Real** — PN532 over SPI, physical taps drive the table |
| Audio | Fake — logs what it would play |
| Display / TV | Fake — logs what it would show |

**Verified on hardware:**
- A physical card tap fires the right target; an unregistered card is reported with its UID, not silently ignored (V1's failure mode)
- An interruption auto-reverts to the prior scene once its audio finishes
- A new action pre-empts a still-pending revert (the "last input wins" rule, proven rather than claimed) — from both a typed command and a real tap
- Tap-not-presence semantics: a card left on the reader fires once, and re-fires only after being lifted and replaced
- Random-table rolls vary tap to tap and stay stateless
- A dangling config reference is rejected at load, not discovered mid-session
- The controller starts with the Pixelblaze powered off, marks lights unhealthy, and keeps running — confirmed against genuinely absent hardware
- The Pi survives a reboot and the controller reconnects on its own

**Two bugs that only surfaced once real devices were attached**, both worth remembering because fakes cannot catch them:
1. The controller had *no* error handling — fakes never fail, so a single missing pattern name crashed the whole table.
2. `go_idle()` hardcoded a pattern name instead of reading the idle scene from config — the exact anti-pattern the design exists to prevent, surviving because the fake accepted any string.

*Fakes validate your logic. They do not validate your assumptions about the world.*

**Not yet built:** the audio and display drivers, the web panel and its two API surfaces, the management UI, headless mode, and the `install.sh`/systemd deployment (§5.5).

---

### 4.7 Zones and per-zone lighting *(built 2026-08-21)*

**This was the prerequisite for player phones.** Seat claiming (§4.5) asks a
player to "pick the colour of the lights you are sitting at", which the table
could not do while the controller could only set *whole patterns* — there was
no way to say "make this quarter green."

Two pieces were needed, and both now exist: a **zone map** (which LEDs belong
to which seat) in [`warlock/zones.py`](warlock/zones.py), and a **per-zone
lighting capability** spanning [`patterns/zones.js`](patterns/zones.js), the
`LightDevice` contract, the controller and the panel.

| Piece | Where |
|---|---|
| Zone map, palette, self-check | `warlock/zones.py` |
| On-device rendering | `patterns/zones.js` |
| Optional device capability | `warlock/devices/base.py` (`supports_zones`, `show_zones`, `set_zone_colour`) |
| Real + fake implementations | `pixelblaze_lights.py`, `fake.py` |
| Actions | `show_seat_colours`, `set_player_count`, `set_zone` |
| Persistence | `settings.player_count`, `ConfigStore.set_player_count` |
| Panel | Seats section; `GET /api/zones` |
| Pre-session check | Table Check — "Zone model", "Seats", "Zone lighting" |

**One manual step remains:** `patterns/zones.js` has to be uploaded to the
Pixelblaze by hand. Until it is, `supports_zones()` reports false, the panel
says so in plain words, and the seat actions no-op rather than failing.

#### The zone map: GM + N players

An earlier draft fixed six seats at the edges. That is wrong. **The number of
seats changes with who turned up** — the table takes a GM plus anywhere from
one to seven players — so the zone map is *computed from a player count*, not
configured. Implemented in [`warlock/zones.py`](warlock/zones.py).

Two fixed facts drive it:

1. **The GM's section never moves.** It is the stretch of the bottom edge in
   front of the television — from the middle of the TV out to its edges,
   **38 inches** (**93 LEDs** at this strip's 96/m), centred on the TV.
   That is the GM's seat at any player count.
2. **Everyone else divides what is left equally.** The remaining perimeter —
   the rest of the bottom edge, both short ends, the whole top edge, and all
   four corner rings — splits into N contiguous arcs.

Everything is computed in **path space**, walking the perimeter in physical
loop order, *not* in LED index order:

```
TL ring 60-119 -> Top 502-704 -> TR ring 0-59 -> Right 705-763
  -> BR ring 180-239 -> Bottom 240-442 -> BL ring 120-179 -> Left 443-501
```

Dividing raw indices instead would produce zones that are contiguous in
memory and scattered around the table. A consequence: a zone is one unbroken
arc physically but may be **two or three separate index ranges** in the
strip, and anything consuming the map must handle that.

**Corner rings are included in player zones**, unlike the six-seat draft that
held them back. With a variable player count seats no longer line up with the
physical edges — a boundary lands wherever the arithmetic puts it — so
excluding the corners would leave 240 dark pixels scattered mid-seat and make
the four- and six-player layouts look broken rather than deliberate.

The remainder is spread one pixel at a time across the first few zones rather
than dumped on the last, so no seat is visibly longer than its neighbours.
**Verified for every player count: zones never differ by more than one LED,
all 764 pixels are covered, none overlap, and each is a single unbroken arc.**

#### Scale: 96 LEDs per metre

Density confirmed 2026-08-21. Every conversion from a physical measurement to
a pixel count goes through `leds_for_inches()`, so this constant lives in one
place.

| | Pixels | Inches |
|---|---|---|
| Long edge segment | 203 | 83.3 |
| Short edge segment | 59 | 24.2 |
| Corner ring | 60 | 24.6 |
| **Whole perimeter** | **764** | **313.3** |
| **GM section (38 in)** | **93** | **38.1** |

The GM's 93-pixel arc sits inside the 203-pixel bottom edge with 45 inches to
spare, so it never spills onto a corner ring at any player count.

This also corroborates the recessed-TV finding from the HDMI work: if 38
inches is the *visible* width of the television, a 16:9 panel is 21.4 inches
tall, which fits inside the 24.2-inch short edge. The nominal panel figures
are larger and describe the whole unit, not the part you can see.

**An earlier draft of this section claimed 96/m was impossible.** It was
wrong twice over: it measured the table's short side as the 59-pixel edge
segment alone, ignoring that the two corner rings add physical length either
side of it, and it compared that against the TV's *panel* dimensions rather
than its visible area. Recorded here because the same two mistakes are easy
to repeat when reasoning about this table from pixel counts.

#### Seat sizes at each player count

| Players | Seats (LEDs) | Inches each |
|---|---|---|
| 1 | 671 | 275.2 |
| 2 | 336 / 335 | 137.8 |
| 3 | 224 / 224 / 223 | 91.9 |
| 4 | 168 / 168 / 168 / 167 | 68.9 |
| 5 | 135 / 134 × 4 | 55.4 |
| 6 | 112 × 5 / 111 | 45.9 |
| 7 | 96 × 6 / 95 | 39.4 |

**Seven players is the count the table was really built for.** At seven, each
seat is 39.4 inches — almost exactly the GM's 38 — so the division lands on
something physically honest, one seat per person's worth of table.

**Below about six players, equal division stops describing where people
actually sit.** A person occupies roughly 24–30 inches of table edge; at four
players a "seat" is 69 inches, and at one it is 275 — nearly the whole table.
The lights would be correct by the arithmetic and wrong about the room.

Equal division is what is specified and built, because it is what was asked
for and because it guarantees the zones tile the table with no dark gaps
between seats. But the alternative is worth naming: **fixed ~38-inch seats
placed where people actually sit**, with the leftover perimeter staying on
the ambient scene colour — the same treatment the six-seat draft gave the
corner rings. That needs someone to decide where the chairs go, which is a
question about the physical table and not about the code.

Do not resolve this from the numbers. Light the zones, sit people down, and
look.

**Player 1 is clockwise from the GM** (confirmed physically 2026-08-21).
That falls out of the loop order above: walking `Top → Right → Bottom →
Left` is clockwise seen from above, seats are numbered forward from the end
of the GM's arc, and forward along the bottom edge runs right to left. So
player 1 continues past the GM into the BL ring and up the left side.


#### Per-zone lighting

The controller sets patterns by name; it cannot address regions. Adding a
"light zone 3 green" action needs a new device method and a Pixelblaze
pattern that can be told what to draw.

**The mechanism:** a pattern holding exported arrays for per-zone colour,
written from the controller with `setActiveVariables()`. Because the map now
depends on player count, the controller pushes **three scalars** — where the
GM's arc starts, how long it is, and how many players — and the pattern
derives the rest. Pushing a 764-entry map on every change would be far
heavier.

```javascript
// zones.js - per-zone colour, driven from the controller
export var zoneH = array(8)   // hue  0..1   [0] = GM, [1..7] = players
export var zoneS = array(8)
export var zoneV = array(8)
export var gmStart, gmLen, playerCount   // written by the controller

// The physical loop, from the LED reference. Verified; do not tidy.
segStart = [ 60, 502,   0, 705, 180, 240, 120, 443]
segLen   = [ 60, 203,  60,  59,  60, 203,  60,  59]

path   = array(pixelCount)
zoneOf = array(pixelCount)

buildPath() {
  p = 0
  for (s = 0; s < 8; s++)
    for (k = 0; k < segLen[s]; k++) path[p++] = segStart[s] + k
}

buildZones() {
  for (i = 0; i < pixelCount; i++) zoneOf[i] = -1
  for (k = 0; k < gmLen; k++) zoneOf[path[(gmStart + k) % pixelCount]] = 0
  remaining = pixelCount - gmLen
  base  = floor(remaining / playerCount)
  extra = remaining % playerCount
  cursor = gmStart + gmLen
  for (z = 0; z < playerCount; z++) {
    len = base + (z < extra ? 1 : 0)
    for (k = 0; k < len; k++) zoneOf[path[(cursor + k) % pixelCount]] = z + 1
    cursor = cursor + len
  }
}

export function render(index) {
  z = zoneOf[index]
  hsv(zoneH[z], zoneS[z], zoneV[z])
}
```

**This duplicates the division arithmetic** — once in `warlock/zones.py`, once
in the pattern — and the two must agree exactly, including the remainder rule
(the first `extra` zones each get one pixel more). That is the price of not
shipping a 764-entry array over the wire on every change.

**This is enforced, not just documented.** `zones.verify()` reimplements the
pattern's arithmetic and compares it against this module's for every player
count, and Table Check runs it before every session. It is pure arithmetic:
no device, no network. If the two ever drift the symptom would otherwise be a
seat boundary in the wrong place, found by a confused player mid-session.

`buildZones()` re-runs when `playerCount`, `gmStart` or `gmLen` changes, not
per-frame — it is ~800 array writes, more than the render it feeds.

**Why exported variables rather than uploading a new pattern per change:**
writing a variable is a single websocket message; recompiling and uploading a
pattern takes seconds and wears flash. Per-seat initiative lighting will want
to move the highlight every turn.

**Controller side:** a `set_zone(zone, colour)` action, a `set_player_count(n)`
action, and a `show_seat_colours()` mode that lights every seat distinctly for
claiming. All belong on `LightDevice` as optional capability defaulting to
no-op — the same pattern as `set_overlay` on the display — so a Pixelblaze
without the zones pattern loaded degrades quietly instead of failing.

**In the interface:** player count is a session-level setting on the panel,
offered as 1-7 and defaulting to whatever was last used. Changing it
re-divides the table immediately and re-lights the seats, because the only
way to check it is right is to look at the table.

**Watch for:** the pattern must be *active* for variables to apply. Setting
zone colours while a scene pattern is running will silently do nothing, so
`show_seat_colours()` has to switch to the zones pattern first — and restore
the previous pattern afterwards, the way Table Check does.

#### What it unlocks

- **Seat claiming**, and therefore player phones (§3.7). `claim_seat()`
  already matches a player to a zone by colour; what it lacked was any way
  for the table to *show* those colours. It has one now.
- **Per-seat initiative lighting** (§3.9), which was always going to ride on
  a zone model. `set_zone()` is the per-turn call it needs — one seat, one
  websocket message, no layout resend.
- Per-seat effects generally: whispers, "you are being addressed", damage
  flashes.

#### Still open

- **Upload `patterns/zones.js` to the Pixelblaze.** Nothing lights until
  this is done. Table Check warns rather than fails, because a table with
  no zones pattern is a normal state, not a fault.
- **Confirm the division feels right below six players** — see the seat
  sizes above. Equal division is what is built; whether a solo player wants
  275 inches of table is a question for the room, not the code.
- **Seat claiming from a phone** still needs the player-facing surface
  (§3.7). The table side of it is done.

---

## 5. Reliability & Startup Behavior

> **Verified end to end on 2026-08-20.** A cold reboot brought the table up
> with no intervention: systemd started the controller, it connected to the
> Pixelblaze (by discovery), audio (38 tracks) and the PN532 (firmware 1.6),
> served the panel, and settled to the breathing idle scene — 0 restarts, no
> terminal. The startup sequence in 5.1 is behaviour, not aspiration.

*Scope note: this is a hobby build, not a commercial appliance, and a certain amount of fiddliness is fine and expected. The specific thing worth engineering properly is **boot-up** — power the table on, pick up the iPad, and have it work without opening a terminal. Everything in this section serves that one goal; anything beyond it is explicitly out of scope (§5.6).*

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
| **HDMI handshake / wrong mode** | Boot with the TV off, or let EDID choose, and the display comes up wrong. Both happened: a power cut with the TV off left X at 1024×768 on the *disconnected* port; later, EDID negotiation picked **4096×2160** — DCI 4K at 17:9, which does **not** match this 16:9 panel, so everything was stretched. | **Fixed 2026-08-20.** The TCL was moved to **HDMI0** (nearest USB-C), which xrandr calls `HDMI-1` and is already flagged primary — one cable swap instead of a login-time xrandr workaround. Mode is pinned in `/boot/cmdline.txt` with `video=HDMI-A-1:3840x2160@30`, because **`vc4-kms-v3d` ignores the legacy `hdmi_group`/`hdmi_mode` settings** in favour of EDID. The old `hdmi_force_hotplug:1=1` was removed — with the port now empty it was conjuring a phantom 1920×1080 display. Backups: `/boot/*.bak-cableswap`. |
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

### 5.5 Deployment layout — the repo is source, not runtime

**The Pi must not run the service out of a live git working tree.** A `git pull` would change code under a running process, a dirty tree or merge conflict would break startup, and "what version is running?" would have no answer beyond "whatever `main` was."

The repo is the **source**; the Pi runs an **installed copy**.

```
/opt/warlocktable/          code — replaced wholesale by install
    warlock/  run_table.py  patterns/
    venv/                   deps, incl. the ARM mini-racer workaround
    VERSION                 git describe output, recorded at install time

/var/lib/warlocktable/      state — install NEVER touches this
    config.json             live card/scene data (the panel edits this)
    device-state.json       last-known Pixelblaze address
    audio/                  rsync target for media
    backups/                config exports

/etc/systemd/system/warlocktable.service
```

**Rules:**
- **Install never overwrites `/var/lib/warlocktable/`.** Config is *seeded* on first install and thereafter belongs to the Pi. This is what makes §4.4 work — panel edits can't put the Pi out of sync with GitHub, because the panel edits data that git has never heard of.
- **Deploy is `git checkout <tag> && sudo deploy/install.sh`.** Rollback is the same command with an older tag, which is how §5.3's "run a tagged known-good version, not raw `main`" becomes real.
- **`VERSION` records what is actually installed**, so the panel's status can report it and "which build is on the table?" has an answer.
- The service runs as a user with GPIO/SPI access (the PN532 needs it).

**Prerequisite this exposes:** `run_table.py` is an interactive REPL reading stdin. A systemd service needs a **headless mode** that runs the controller and waits on events without a console. That doesn't exist yet, and the unit file can't be written meaningfully until it does.

**Ordering note:** do the install layout *before* the systemd unit — the unit encodes the paths, so writing it against the repo path means writing it twice.

**Decisions made 2026-08-20:**
- **Service user: `pi`** for now — it already has the GPIO/SPI group membership the PN532 needs, and this is a single-purpose home appliance, not a multi-tenant box. But the install script must take the user as a **parameter, not a hardcoded value**: the account may be renamed or its credentials changed later, and multiple users are a plausible eventual want.
- **The install script does NOT pull.** You run `git checkout <tag>` yourself; install deploys whatever is checked out. A script that pulls for you is convenient right up until it deploys something you hadn't reviewed.

**Not needed yet — deliberately deferred.** Running from the repo is fine while nothing writes config and nothing needs to survive a reboot. Two things end that:
1. **The panel becoming able to edit cards.** Config then becomes data the Pi owns, and cannot live in the repo (§4.4) — a `git pull` would fight the edits.
2. **The first real session at the table.** Hand-starting over SSH is fine for development, not with people waiting.

Note the FHS paths above are a *convention*, not a requirement. `/home/pi/warlocktable-app` + `/home/pi/warlocktable-data` would give the same benefits. What actually matters is the **separation** — code in one place, data in another, deployment replacing only the first. The standard paths just mean systemd, logrotate, and backup tooling agree with you without configuration.

### 5.6 Explicitly out of scope

Real techniques, but they're for appliances you can't physically reach — this one is furniture in the house:
- Read-only root filesystem / overlayfs
- Pi running its own Wi-Fi access point so the table doesn't inherit the house router's reliability
- Restoring exact scene state after a crash-restart

Revisit only if a specific problem actually shows up.

---

## 6. Roadmap

### Phase 1 — Hardware Foundation *(COMPLETE — 2026-08-20)*
Get the Pixelblaze lighting physically solid and verified before touching software.

- [x] Rebuild the **light signal distribution board**
  - [x] Correct the many channels coming off the Output Expander
  - [x] Fix the **ground wire connection** (suspected root cause of the fault)
  - [x] Redesign the distribution layout for reliability
- [x] Reflow suspect solder joints across the boards
- [x] Power-on test: confirm expander status LED behaves
- [x] **Verify the lighting system works as-is** end to end

**Exit criteria met.** 764 pixels across 8 expander channels, all verified
*physically on the table* rather than assumed — see
`warlock-table-led-reference.md`, which records the channel map, the corrected
`segStart` ordering, the pixel map, and the debugging lessons. The device
reports the same configuration the doc describes, renders at ~47 FPS, and a
working Pac-Man chase pattern runs across the full perimeter loop.

### Phase 2 — Software Foundation *(CURRENT)*
Stand up the core software on the Pi once hardware is trusted.

- [x] Decide overall software architecture — see §4 (layers, one process, config-driven actions)
- [x] **Write the action vocabulary down** (§4.2 step 1) — see §4.6
- [x] Controller skeleton with all-fake devices, running on the laptop — `warlock/`, run with `python run_table.py` (see §4.6). Built 2026-08-18. Python 3.12 since installed on the laptop, so development no longer round-trips through the Pi.
- [x] Config file + event dispatch — **fake table fully working end to end**, incl. verified: timed auto-revert from an interruption, a new scene correctly pre-empting a pending revert (precedence rule), referential-integrity rejection of a dangling reference, and stateless random-table rolls
- [x] Run the controller on the Pi at all — done 2026-08-20, drives the Pixelblaze over wifi. Required upgrading pixelblaze-client 0.9.6 -> 1.1.8 and stubbing mini-racer (no ARM wheel); see `deploy/README.md`
- [x] Headless mode — done 2026-08-20. `run_service.py` (`warlock/service.py`): no stdin, SIGTERM/SIGINT shut down cleanly so GPIO is released, nothing fatal. Shares device construction with the CLI via `warlock/runtime.py`. Verified on the Pi with all three subsystems real.
- [x] Config resilience (§5.2 "never refuse to start") — falls back requested → `.last-good` (written on every clean load) → minimal built-in that still defines an idle scene, so the lights come up even with nothing usable on disk. All three levels verified.
- [x] `deploy/install.sh` — done. Code to `/opt`, state in `/var/lib`, config seeded once and never overwritten. `deploy/update.sh` makes deploying one reviewed command.
- [x] Run as a systemd service — done. Starts on boot, `Restart=always`, clean SIGTERM shutdown, verified through a cold reboot.
- [x] Swap in real Pixelblaze via discovery, not a hardcoded IP — done; `--real-lights` drives the table, discovery recovers from a wrong/absent address hint
- [x] Get the PN532 NFC reader reading reliably — done 2026-08-20. Physical card taps drive the real table (`--nfc`). Tap-not-presence semantics verified: a card left on the reader fires once, and re-fires only after being lifted and replaced.
- [x] Audio — done. Two independent channel groups (looping bed + layered one-shots), true crossfade, ducking. 38 tracks. *Device pinning still uses the SDL default — not yet pinned explicitly (§5.3 risk remains).*
- [x] Screen visuals — done. feh fullscreen at 3840×2160, 5 backgrounds with gridded variants, ~50 ms swaps, grid toggle in the panel.
- [x] A way for one input (e.g., an NFC card) to trigger one output (e.g., a light scene) — the first end-to-end interaction **on real hardware**. Done 2026-08-20: a simulated card tap drives the physical table (`card forest` → GreenCard, `card thedevil` → sparkfire then timed revert). Input is still the CLI rather than the PN532, but the whole chain below it is real.

**Reliability work (per §5) — fold in alongside the above, not after:**
- [x] Status strip on the panel — done, and it reflects each device's own health, not just failed calls.
- [x] **Status screen on the TV — done.** Rendered to a PNG and shown through the *same* feh instance as the artwork, so only one thing ever draws on the screen. Shows per-subsystem marks, current scene, the panel URL and the deployed version. Appears automatically at startup, and on demand via the `show_status_screen` action. Styled to `warlock-table-style-guide.html` **exactly** — Syne, IBM Plex Sans and IBM Plex Mono are bundled in `warlock/web/static/fonts/` (SIL OFL) and served locally rather than from the Google CDN, so the table never needs the internet to render its own surfaces. The same font files feed both the TV and the iPad panel, so the two use identical type.
- [x] Config validation with last-known-good fallback — done, three levels (requested → `.last-good` → minimal built-in that still lights the table).
- [x] mDNS — `raspberrypi.local` works (avahi).
- [ ] **DHCP reservations** for the Pi and Pixelblaze — not done. Discovery covers the Pixelblaze; the Pi's address moving would still break a bookmarked IP.
- [x] **"Table Check" self-test — done.** Panel button, sub-second. Its centrepiece is a cross-device referential integrity check: every light pattern, audio track and background that config references is confirmed to exist on the real device. Verified by deliberately pointing a scene at a deleted pattern and a missing track — both caught by name, while every device still reported healthy. A second button additionally flashes lights and plays a clip (software cannot confirm photons or sound), restoring the previous scene afterwards.
- [ ] Physical GPIO shutdown button + a known-good SD image on the shelf
- [x] Tagged releases — `v0.1.0` cut and deployed; `VERSION` and the panel both report the build.

### Phase 3+ — Feature Build-Out
- [x] Operator web panel — done. iPad PWA, status strip, scene/interruption/table buttons built from the controller's vocabulary, brightness, grid toggle, card editing. *Apple TV hand-off is stubbed — it logs intent, HDMI-CEC not implemented.*
- [ ] Build the table's Pixelblaze pixel map (one-time)
- [ ] Pattern authoring loop + "upload pattern" via the web panel
- [x] Card management — reassign/create/delete from the panel, plus registering an unknown tag by tapping it (§4.5 steps 1–2).
- [ ] **§4.5 steps 3–4:** upload audio through the panel, and author scenes/interruptions from scratch.
- [ ] Phone-tag NFC support
- [ ] Govee room/accent lighting via API, synced into scenes (+ under-table strips)
- [ ] **Zone map + per-zone lighting** — specced in §4.7, not built. **Blocks player phones**, because seat claiming needs the table able to light six zones distinctly. Also unlocks per-seat initiative lighting.
- [ ] Player phone second-screens (dice rolls, break requests, private whispers) — depends on §4.7
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
