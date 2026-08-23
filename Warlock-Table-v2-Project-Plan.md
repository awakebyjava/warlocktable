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
**Built 2026-08-22.** All 26 tarot cards now have config entries pointing at
their own generated Pixelblaze patterns: 4 Boon, 9 Person, 12 Aura, and
Wheel of Fortune as a random draw over the twelve Auras. Built by
`tools/migrate_tarot.py` from the design doc rather than by hand, so a typo
fails loudly instead of producing a card that does nothing.

**They are silent for now, deliberately.** `Interruption.audio` was made
optional to allow it. The design doc defers sourcing the clips, and the
alternative was 25 entries failing referential integrity until someone
records 25 sounds. With no audio the revert is driven by `duration_s` —
60s for an Aura's flourish, ~5s for a one-shot announcement — which is what
those wanted anyway rather than an arbitrary clip length.

**Enrolling the physical cards:** `tools/enrol_cards.py` drives the running
table over its web API, so the controller keeps the PN532 and the table
stays alive while you tap. A standalone reader program would have to stop
the service first, because the panel and a CLI cannot both own the reader.
It asks what each object IS rather than assuming — the label describes the
thing on the table, and the idle trigger is a postcard, not a card called
"Idle".

**Wheel of Fortune changed behaviour.** It used to pull a random *scene*; it
now draws a random Aura and fires that card's effect. That retired the three
`fortune_*` interruptions.

- **The tarot set has its own design doc:**
  [`warlock-table-interruption-cards.md`](warlock-table-interruption-cards.md)
  — the full taxonomy for all 26 cards (Boon / Person / Aura / Random
  Table), what each should do, and the data shape. **Specified, not built.**
  It is the source of truth for *intent*; the companion
  `warlock-table-interruption-cards.json` carries the same 26 cards as
  structured data — a starting-point draft for implementation, not a config
  the controller reads today. Verified consistent with the markdown: 4 boon,
  9 person, 12 aura, 1 random table; unique ids; all nine Person cards have
  a null `npc_binding` awaiting a GM; and the Wheel's pool is exactly the
  twelve Aura ids.
  Note it **redefines Wheel of Fortune**: currently it pulls a random scene,
  and it is specified to draw a random Aura card and fire that card's effect
  instead.
- **Resolved — see §4.3–4.5 for the full interaction spec.** In short: cards are dumb triggers (UID + label); every card is a tap (no presence detection); a card points at a Scene, an Interruption, or a Random Table, editable between them in the management UI; cards are stateless. The mana/tarot distinction is configuration, not code — mana cards happen to map to Scenes and tarot cards to Interruptions, but either could be either.

### 3.3 Audio & Soundscapes
- Rich background soundscapes tied to the embedded TV visuals.
- Soundscapes echoed/coordinated with the lighting.
- Expanding overall audio capability and complexity.
- **Audio routing:** Pi 4 can output HDMI + analog jack simultaneously if we want sound in multiple places.

**Volume and output switching *(built 2026-08-21)*.** The panel's Sound
section has a master volume slider and a switch between named outputs.

- **Volume is applied in software**, across the bed and effects, rather than
  by moving the system mixer. ALSA's level is shared with the whole machine,
  and a table that quietly reconfigures the OS surprises whoever touches it
  next. It persists, because the right level is a property of the room, and
  is written on slider release rather than during the drag.
- **Outputs are named in config** (`settings.audio_outputs`), so the panel
  offers "Television" and the ALSA string stays a config detail. Named **by
  card, never by number** — `hw:0,0` breaks the moment HDMI renumbers the
  cards, which is the failure §5.3 records.
- **Switching rebuilds the mixer**, because SDL only reads the output device
  at init. Setup, not something to do mid-scene — though the soundscape is
  restarted afterwards so it does not go silent.

**The TV needs the `hdmi:` PCM, NOT `plughw:`.** This is not obvious and cost
real time. `vc4-hdmi` accepts only `IEC958_SUBFRAME_LE`, and the ALSA plug
layer will not convert to it — `plughw:CARD=vc4hdmi0,DEV=0` fails with
"Sample format non available" from `aplay` and "Couldn't find any hardware
audio formats" from SDL. The `hdmi:` plugin does the IEC958 framing and
accepts ordinary S16 stereo at 44100, which is exactly what the mixer asks
for. Correct values:

| Output | ALSA device |
|---|---|
| Speakers (3.5mm) | `plughw:CARD=Headphones,DEV=0` |
| Television (HDMI0) | `hdmi:CARD=vc4hdmi0,DEV=0` |

**A refused switch is better than a silent one.** `_init_mixer` deliberately
falls back to the SDL default when a device will not open, so the table is
never silent at boot. Correct there, wrong for a deliberate switch — it
would send sound somewhere unexpected *and* persist a broken device. The
switch compares what actually opened against what was asked for and reverts
if they differ.


**Where audio files live (important):**
- **Audio is deliberately *not* in the git repo.** `.wav/.ogg/.mp3/.flac` are gitignored. Large binaries can't be diffed or compressed and every version is kept forever — the V1 audio alone was **1.08 GB**, which would have made every clone and every Pi pull drag.
- **Master copies:** `C:\Users\jonre\Documents\warlocktable-audio\` on the laptop (`Ov/` and `MagicCards/`, as moved out of `Warlock Table V1/MagicTarot/`).
- **Getting audio to the Pi:** `rsync` over the existing passwordless SSH — code goes via GitHub, media goes direct. Two different transport paths for two different kinds of asset.
- Note the legacy V1 code expects these files at `/home/pi/Documents/MagicTarot/Ov/...`; v2 should read the audio path from config rather than hardcoding it.

- **Backup:** masters are backed up on a personal external hard drive — **last verified current 2026-08-18** (all 36 `Ov/` files, including the 7 MP3s that had existed only on the Pi's SD card). Re-check whenever the sound library grows: git no longer provides an incidental second copy, so the backup is the only redundancy.

- **To expand:** where speakers physically live, how many independent audio zones, what the soundscape library looks like, how audio syncs with light scenes.

### 3.4 Voice / Live Audio Input
- Two related but distinct ideas:
  1. **Live-audio reactive effects** — lights/visuals respond to ambient room sound (Pixelblaze sound input, and/or Pi mic). **Backlogged 2026-08-21** — see §6.
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

**Panel facts (measured, not assumed):** TCL, **1209 mm × 680 mm**, exactly 16:9, ≈ 54.6" diagonal. Now on the Pi's **HDMI0** (`HDMI-1` in xrandr, the primary port) and pinned to **3840×2160** via `/boot/cmdline.txt`:
`video=HDMI-A-1:3840x2160@30e`. Full generation spec in
`display-image-specifications.md`.

**Three traps, all hit for real:**
- The TV advertises **4096×2160**, which is DCI 4K at 17:9 and does *not* match the panel. EDID negotiation picked it and the desktop came up stretched. Never generate at that width.
- `vc4-kms-v3d` **ignores** the legacy `hdmi_group`/`hdmi_mode` settings. The kernel `video=` parameter is the working lever.
- **The trailing `e` on the mode string is load-bearing.** It forces the
  connector enabled regardless of what detection says. Without it the
  table booted to a black screen (2026-08-21): X starts ~14s in, the TV
  was not yet asserting hotplug on a port receiving no signal, so X
  logged `Unable to find connected outputs - setting 1024x768 initial
  framebuffer` and disabled HDMI-1. When the TV woke a moment later
  nothing told X to reconsider, and it stayed dark until someone ran
  `xrandr` by hand.

  A TV that boots *fast* is not the same as a TV that asserts EDID
  early, and the two were confused while diagnosing this. `e` is the
  KMS-era replacement for `hdmi_force_hotplug=1`, which the trap above
  records as ignored. Backup of the previous line:
  `/boot/cmdline.txt.bak-20260821`.

**Where display artwork lives — same split as audio (§3.3):**
- `map-sources/` in the repo: the small raw generator output (~1 MB each). Tracked, because they are the versioned originals.
- **Finished 3840×2160 renders are NOT in git.** At 5–15 MB each and growing with every map, they are the audio problem one order of magnitude down. They live at `/var/lib/warlocktable/backgrounds/` on the Pi and arrive by **rsync**, resolved via `settings.background_paths` in config.

**First batch delivered (2026-08-20).** Ten files: five terrains × gridless and gridded, all **exactly 3840×2160** at a true 16:9. They live in `backgrounds/` (gitignored, ~78 MB) and go to the Pi by rsync.

**OPEN — grid pitch needs checking against real miniatures.** A rough measurement of the gridded images suggests a pitch near **81 px** where the spec calls for **80.68 px** (1 inch / 5 ft / one medium base). If that is real it accumulates to roughly **0.2 inches of drift across the full 47-square width** — about a fifth of a mini base, so probably fine in play. But the measurement carries about ±1 px of its own noise, so it cannot distinguish 81.00 from 80.68 with confidence. **Settle it by putting actual minis on the actual table**, not by measuring the file. If it does drift, regenerate with `round(i * 80.68)` rather than a fixed 81 px step.

**Superseded note on the raw sources:** generated at 1376×768, aspect 1.7917 vs the panel's 1.7778. Close, but they need a **×2.81 upscale and a 30 px width crop** — crop rather than stretch, or circles become ovals. A plain resize will look soft at 80 px/inch; this wants a model-based upscaler.

- **To expand:** what drives the display (a fullscreen viewer? a custom app?), whether content is oriented to the GM's seat or orientation-neutral, and how visuals stay in sync with lights and audio.

#### Display redesign *(specced 2026-08-23, not built)*

Today the screen shows one finished PNG. Overlays are not overlays: the
grid and hex variants are **separate pre-rendered files**
(`forest_3840x2160_grid.png`), chosen by filename. That works for artwork
shipped with the table and not at all for anything else.

Wanted:

1. **Grid and hex as real overlays**, drawn over whatever is on screen
   rather than baked into a second copy of every image.
2. **Any uploaded image usable as a battle map**, fitted to the display
   with sensible stretch/crop rules.
3. **A turn indicator** — whose turn it is, on the screen.
4. **An effects overlay** — running auras, and anything the GM wants to
   put up as an ongoing effect.

##### Measured first, because it decides the design

Compositing a 4K frame on the Pi, timed 2026-08-23:

| Step | Time |
|---|---|
| open + decode a 4K background | 786 ms |
| resize to 4K | 60 ms |
| draw a grid (59 lines) | 74 ms |
| alpha composite | 254 ms |
| **save PNG, compress_level=1** | **2,256 ms** |
| **save PNG, compress_level=6** | **12,637 ms** |
| **save JPEG, q88** | **380 ms** |

**Write JPEG, not PNG.** PNG encoding at this size is 6x slower at its
*fastest* setting and thirty times slower at the default — twelve seconds
to change what is on screen is not a feature, it is a fault. feh reads
JPEG perfectly well. The status screen can stay PNG: it is rendered rarely
and has flat colour that PNG handles better.

**Cache the base composite.** Background decode is 786ms and the
background changes far less often than a turn indicator does. Hold the
composited background+grid in memory, paste the HUD onto a copy, save.
That puts a turn change at roughly **400ms**, which is the floor without
abandoning the one-file-and-feh model.

##### The trap: a grid that lies

A grid overlay is only useful if its scale is *meaningful*. If a battle
map is stretched to fill a 16:9 screen and a grid is laid over it, the
grid no longer matches the map's own squares, and every distance measured
on it is wrong. That is worse than no grid, because it looks authoritative.

So: **grid size and offset must be adjustable**, and fitting must default
to preserving aspect ratio. Stretch should exist but be an explicit
choice, and probably should disable the grid when used.

##### Open questions

- **Fit mode per image or global?** A portrait map and a 16:9 render want
  different answers. Likely per-image, remembered.
- **Does the turn indicator earn its cost?** The table's own LEDs already
  flash the active seat, and every HUD change costs ~400ms and a full
  redraw. It may be that the lights are the better channel and the screen
  should carry only what they cannot.
- **What is an "effect", concretely?** An aura is a card the table already
  knows. A GM-authored effect is free text, which is a different feature
  with an editor attached.
- **Where do uploaded maps come from?** §4.5 step 3 (upload through the
  panel) is unbuilt, so today a map arrives by rsync like everything else.

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

**Player phones *(seat claiming built 2026-08-21; the rest still to come)*.**

Three front doors, all on the same server:

| Path | Who | What |
|---|---|---|
| `/` | anyone scanning the QR | asks player-or-GM, nothing else |
| `/gm` | the GM | the operator panel (the PWA's `start_url`) |
| `/player` | a player | choose a seat |

- **The QR points at `/`.** Its URL is built from the `Host` header the phone
  actually used, not from a hostname lookup: that is the one address known
  to work from a device on this network, and it sidesteps mDNS entirely.
  Encoded with `segno` — pure Python, no ARM wheel trouble — and optional at
  runtime, degrading to printing the URL, because a join page that 500s over
  a missing decoration is far worse than an address people can type.
#### GM panel redesign *(specced 2026-08-23, not built)*

**Target: an iPad mini, held landscape.** 1133 x 744. That is the device
and the orientation; everything below follows from it.

##### What is wrong, measured

| | |
|---|---|
| Page height today | **5,542 px** |
| **Screens of scrolling** | **7.4** |
| Sections stacked in one column | 13 |
| Cards section alone | 2,165 px — 39% of the page |

The panel is a single column with a 940px max-width. On its target device
it wastes half the width and scrolls seven screens. It grew a section at a
time and nobody ever laid it out.

##### Panels, side by side

Four panels the GM moves between horizontally, plus one overlay:

| | Panel | Holds |
|---|---|---|
| ← | **Settings** | sound, output, brightness, recording, mic |
| ● | **Players** *(landing)* | Show Join/Status, player list, initiative, seats |
| → | **Run** | scenes, cards, random tables, dice, screen overlays |
| →→ | **Check** | run check, test lights & sound |
| ▼ | **Whisper** | drops over whatever is showing, then goes away |

**Players is where the GM lands**, because the first thing that happens at
a table is people arriving: put the join code up, watch seats fill.

**Card management does NOT get a panel.** It is 2,165px of configuration
that nobody touches mid-game, and giving it a swipe position next to
"scenes" invites editing the table's wiring during play. It belongs behind
Settings.

**Whisper drops over, rather than being a fifth panel.** It is a
conversation you return from, not a place you go — and a half-typed reply
must survive being interrupted by a card tap.

##### Layout notes from the table

- **`Set Initiative Order` and `Run Initiative` should not be full width.**
  Nothing about them earns 1133px.
- **Seat count, Set Initiative Order and Show Seat Colours share one row** —
  seat count as a dropdown rather than a row of numbered buttons. The
  player list sits under them.
- The header is the only thing that survives a panel switch, so signals
  stay reachable from anywhere. That is already true and must remain so.

##### Status screen changes

- **Drop "The Circle Holds".** It says nothing. `WARLOCK TABLE` alone.
- **Make the QR bigger.** It is the most useful thing on the screen at the
  start of a session and currently it is a footnote.
- **Run the check at startup and show the result.** `tablecheck` is
  sub-second and already exists; the screen currently reports fewer
  subsystems than the table actually has — Govee is not on it at all.
- Footer, version and clock stay. The idle pattern stays.

##### Technical notes *(analysis, not spec)*

- **744px vertical is the real constraint, not width.** The header is 164px
  today; add a panel switcher and the content budget is around 500px. The
  header has to shrink, and status chips and the player bar probably have
  to share a row.
- **Use the width.** Inside a panel, two columns beat one — Players wants
  initiative beside seats, not above it.
- **Tabs at the BOTTOM, not swipe** *(decided 2026-08-23)*. Swipe conflicts
  with scrolling inside a panel and is invisible to anyone who has not
  been told; a GM mid-session should not have to discover anything. Bottom
  rather than top because on a held tablet the thumbs are already there.
  It is proven in this codebase: `.idle-bar` is already a bottom-fixed bar
  handling `env(safe-area-inset-bottom)`, and the page already sets
  `viewport-fit=cover`.
- **The bottom edge is already taken.** `.idle-bar` — the always-available
  Go Idle button — lives exactly where the tabs want to be. Either it
  becomes part of the tab bar, or it moves. It is arguably a fifth
  destination rather than a button, since "put the table back to rest" is
  a place the GM goes.
- **The vertical budget, with tabs.** At 744px, minus a 56px tab bar and
  ~21px of safe area:

  | Header | Content left |
  |---|---|
  | 164px (today) | 503px |
  | 120px | 547px |
  | 90px | **577px** |

  So the header must come down to roughly 90px for a panel to hold
  anything substantial. That is the single most constraining number in
  this redesign.
- **Panel state must survive switching.** A typed whisper, a selected
  initiative order, a half-entered dice count.
- **The GM panel must work on a phone too** *(confirmed 2026-08-23)*, not
  merely survive. Bottom tabs help here: the pattern is native to phones,
  and four panels at 400px wide is a normal phone app rather than a
  compromise. The panels stay; only what is inside them reflows.
- **The PLAYER page is the phone surface that matters** and its design is
  settled — one column, tabs, signals in the header. It needs the new
  branding and nothing else. Do not reopen it.
- **This is downstream of the branding work**, which is in progress. The
  structure above can be settled now; type, colour and texture cannot.

#### One design, three widths *(specced 2026-08-23)*

A full complement of layouts: GM and player, on phone, tablet and browser.

**TWO documents, THREE breakpoints, ONE component vocabulary.** Not six
designs. Six bespoke layouts is where this kind of thing dies: a change to
the dice pad has to be made in three places, they drift, and eventually
nobody knows which is authoritative. Same classes, same tab pattern, and
the differences live as media queries in the one stylesheet both pages
already share.

Starting position, checked 2026-08-23: **the stylesheet contains no layout
media queries at all** — the only `@media` is `prefers-reduced-motion`. So
the current pages are one fixed layout that happens to survive on a phone.
Nothing to undo; this is greenfield.

| Width | Device | Layout |
|---|---|---|
| ≤ 600px | phone | one column, bottom tabs |
| 601–1199px | tablet (iPad mini landscape is 1133) | bottom tabs, two columns inside a panel |
| ≥ 1200px | browser | **panels side by side, tabs gone** |

**The wide breakpoint is the interesting one.** Tabs exist to solve a
space problem. On a 1400px browser there is no space problem, and a tab
bar that hides two thirds of the interface behind a tap is a downgrade —
show Settings, Players and Run at once. That is what "varied by device"
should mean: the navigation model changes when the constraint that
justified it goes away, not that the same screen wears three skins.

**Tabs come to the player page too**, moved to the bottom to match the GM
panel. The player page already has them (Dice / Whisper / Seat), so this
is a move rather than a build, and it makes one tab pattern serve both
surfaces at every width.

##### Constraints that are not negotiable

**"Works on every phone" means fluid, with a floor.** Every width from
**320px** (iPhone SE, small Android) upward has to work. Below that
nothing sane does, and no phone in use is narrower. The layout is fluid
between breakpoints rather than three fixed designs, so an unlisted device
lands somewhere sensible rather than nowhere.

**Use `dvh`, never `vh`.** Mobile Safari and Android Chrome shrink and
grow the viewport as their toolbars hide and reveal, and `100vh` is the
*largest* it ever gets — so anything sized in `vh` is taller than the
screen while the toolbar is showing. With a bottom tab bar that means the
tabs sit below the fold, which is the exact failure this would produce on
the devices most likely to see it. **The stylesheet currently uses `vh` in
four places** and all of them need converting.

**Fonts must be self-hostable.** The table has no internet, so a webfont
CDN is not an option — Syne and IBM Plex are bundled as variable TTFs in
`warlock/web/static/fonts/` with their OFL licence. Any new typeface needs
files we can ship and a licence that permits it.

**The symbols being drawn for the branding land here.** A bottom tab bar
wants an icon and a label per destination, and at the phone width the
label may have to go. That makes the symbols load-bearing rather than
decorative: a tab whose icon is not legible at 24px is a tab nobody can
find.

#### Phone tools — specified 2026-08-23, none built

Three additions beyond seat claiming. The scope of the phone was
deliberately left open until now; this is the answer.

**1. Signals — `?` and `!`**

Two buttons in a corner of the player screen. `?` means this player has a
question; `!` means this player needs something. Both put a message on the
GM's screen saying which player it came from. That is the whole feature.

Explicitly **not** a "break request" — that framing was considered and
rejected as too narrow. These are lighter and more general, and the GM
reads the room to decide what either one means.

**Clearing: either the GM or the player, and a 60-second timeout on top.**
Three ways out, deliberately. A signal nobody clears should not sit on the
GM's screen all session, and a player who taps `!` and then sorts it out
themselves should be able to take it back without waiting for the GM to
notice.

**2. Dice**

Its own pane, in two panels:

- **The display and the number pad are one panel**, together. A
  calculator: the display sits along the top showing the number being
  entered, the keys below it, and with them a **clear** button and a
  **history** button that pulls up that player's own log of rolls.
- **The standard tabletop dice shapes**, clickable, as the second panel.

You type a number, tap a die, and it rolls that many of that die.

**The display holds the last result** until new input is entered, at which
point it clears and starts the next entry. **Clear wipes the whole
display**, not one digit — a backspace is a small target for something
pressed under a table without looking.

**The log reads `(dice)d(sides)=(result)`** — `3d6=12`. That format is the
spec, not a suggestion.

**The dice are d4, d6, d8, d10, d12, d20.** No d100 and no percentile
pair. **No modifiers** — a number and a die, nothing else. The point is to
stay **system-agnostic**: the moment there are modifiers and a d100 it
starts encoding somebody's rules, and this table does not know what game
you are playing.

- **No indicator on the television.** Considered and dropped. That was the
  single largest piece of work in all three tools, and it bought the least.
- **The player keeps a record** of their own rolls.
- **The GM keeps a record** of the rolls.
- **Rolls are logged alongside the audio recording.** See below — this is
  the part that makes them worth keeping.

**3. Whisper**

Its own pane: a conversation with the GM, both ways.

- **No public chat room.** There is no all-players channel and will not be.
- A player's conversation is **not visible to the other players**.

---

**4. Player status panel** *(replaces push notifications)*

A bar across the top of the GM panel showing the players, which **stays in
place as you move around the interface** rather than scrolling away. It is
where a `?` or `!` appears, so a signal is seen without anything having to
interrupt.

**Push notifications were considered and rejected.** Not on effort — on
dependency. The iOS Push API routes every message through Apple's own push
service, so the Pi would need outbound internet, and the PWA would need a
real HTTPS certificate, which a `.local` LAN name cannot be issued. A
table in the same room as the phone would be asking Cupertino to pass a
note across it, and would go quiet whenever the internet did. **The table
stays self-contained.** A panel that is always on screen needs none of it.

**5. What the session log records**

Rolls, whispers, **and the cards and scenes used** — a record of the game,
not just of the dice. All of it beside the recording, all of it carrying
an offset from the recording's start.

**The interface needs a redesign** to hold all this. Noted, not specced.

---

##### Notes on building these *(analysis, not spec — argue with it)*

**Order by cost, cheapest first: Signals → Dice ≈ Whisper.** Dropping the
television indicator took the largest single piece of work out of Dice and
moved it from clearly-biggest to roughly level with Whisper. Whisper is
the stated priority and is not the cheapest; Signals is, by a wide margin,
and it proves the phone→GM path the other two both need.

- **Signals** is one endpoint, an in-memory list with an expiry, two
  buttons and a strip on the GM panel.
- **Dice** is phone UI — pad, display, six dice — plus a roll engine that
  is nearly trivial, two history views, and the session-log hook.
- **Whisper** is the only two-way one, which is what makes it the heaviest
  despite looking simpler: the GM side needs per-player threads, unread
  state and somewhere to switch between them.

**Rolls ride with the recording.** Recordings are
`session-%Y%m%d-%H%M%S.wav` in `recording_dir`. A roll log belongs beside
its recording under the matching name, and each entry should carry **an
offset from the recording's start**, not just a wall clock — an offset is
what lets a later transcript line "Jon rolled 3d6 → 11" up against the
moment somebody groaned. That is the whole reason to keep them.

Rolls happen whether or not the mic is running, so the in-memory history
for the phone and the panel is always live; the file is written *as well*,
and only while recording. This also feeds the transcription/recap item on
the roadmap, which otherwise has only audio to work from.

**Whispers, cards and scenes go in the same file.** A transcript that
knows the Tower came out, the scene turned to Swamp, and somebody
whispered the GM thirty seconds later is a far better account of an
evening than audio alone. Note the consequence: **whisper history stops
being ephemeral** the moment it is written down, and private messages on
disk are a different proposition to a conversation that evaporates.
Recorded here so it is a decision rather than a side effect.

**Everything else stays in memory**, matching the initiative order: a
signal is meaningless sixty seconds later by definition, and whisper
history is a live conversation rather than a record. A service restart
mid-session drops both, which is a real consequence and an accepted one.

- **The player page does exactly one job: pick a seat.** Name, then tap the
  colour lit in front of you. The swatch is large and flat because it is
  held up against the actual lights. A taken seat stays visible and greyed
  rather than vanishing, so someone whose friend grabbed the wrong colour
  can see *that* rather than wondering why there are fewer seats than
  chairs. Two people tapping the same colour gets a 409 and a repainted
  list, which will happen every session.
- **Still to come:** dice, break requests, and private whispers. Each is a
  separate decision rather than one lump, and **how far the phone goes has
  not been settled** — do not assume it, ask.


- Mostly "more routes" on the server you're already running; low added cost.

### 3.8 Pixelblaze Patterns — Authoring & Upload *(built 2026-08-22)*

**Patterns are generated, not hand-written.** `tools/patterngen.py` emits all
30 from a small vocabulary of fields, envelopes, palettes and features (plus
two hand-written: `patterns/zones.js` and `patterns/idle.js`). The
five terrain scenes were transcribed into it and compared side by side
against the hand-written originals on the table before replacing them; the
originals are in `patterns/legacy/`.

Not for the size saving, though it is 60%. Two better reasons:

- **One source of truth for the shared parts.** The perimeter path builder
  was copy-pasted verbatim into six patterns. Correcting `segStart` would
  have been six edits and a chance to miss one.
- **The craft scales.** Hand-tuning seventy patterns was never going to
  happen. The techniques that stop a loop looking machine-made — staggered
  bloom phases, seam-correct wrapped distance, blending toward a colour
  instead of adding to it — cost 15–45 bytes each and are now defaults
  every generated pattern inherits.

**Two rules the generator enforces rather than leaving to memory:**

- **Wave frequencies must be whole numbers and coprime.** `wave()` has
  period 1, so `wave(u * 7.3)` lands 0.3 of a cycle from where it started
  as `u` wraps — a visible seam, measured at 0.31–0.51 on a 0..1 field
  across the original five, and reported from the table as "a weird seam at
  the split in the ring". The non-repeating quality comes from
  incommensurate *speeds*, not frequencies, so whole numbers cost nothing.
  Coprime as well: 9 and 3 would make the field repeat three times around
  the ring.
- **Seam-correct wrapped distance** for anything travelling the loop.

#### Getting patterns onto the device

| Tool | Does |
|---|---|
| `tools/patterngen.py` | emit the patterns into `patterns/generated/` |
| `tools/upload_watched.py` | upload one at a time, verifying each |
| `tools/upload_pattern.py` | upload a single named pattern |
| `tools/archive_patterns.py` | pull sources off the device before deleting |
| `tools/prune_patterns.py` | delete stock patterns, one at a time |

**Compilation happens against the live device** — the client downloads the
compiler out of the Pixelblaze's own web UI and runs it under V8. The
bytecode is therefore always built by the compiler belonging to the
firmware that will run it, and syntax is checked by the real thing. It also
means uploads cannot happen on the Pi, where `py_mini_racer` is stubbed for
want of an ARM wheel. **Laptop only.**

The language is **not JavaScript** despite the `.js` extension. A
user-defined function needs the `function` keyword; there is no `break`.
Only the device can tell you.

#### Hard-won operational rules

These cost a wedged device, a power cycle, and the entire LED configuration
on 2026-08-21. See §5.3.

- **Stop the controller before any bulk device work.** It reconnects every
  10 seconds and that loop exhausts the Pixelblaze's small pool of
  websocket slots. A prune run wedged mid-way with the controller up and
  recovered the moment it was stopped.
- **Never run device work unattended.** The failure that started it was a
  70-pattern upload backgrounded and left for 47 minutes.
- **Attach no preview image.** `savePattern` takes a JPEG thumbnail for the
  device's own list. Copying one from an existing pattern cost **8,655
  bytes stamped onto every upload** — six times the size of the pattern it
  decorated — and turned a 123 KB job into a 669 KB one against 490 KB
  free. Pass `b""`. Note that *replacing* a pattern keeps its old preview;
  only a freshly created one gets the empty one, so reclaiming means
  delete-then-create.
- **`storageUsed` refreshes lazily, mostly on reboot.** Deleting a pattern
  moves it by zero. It is not a live capacity guard, and estimating from
  source bytes is how the original job was mis-sized.
- **Expect transient failures roughly every 5–15 operations** —
  `IncompleteRead`, empty source read-backs, occasional write failures.
  Every one left the device healthy and the pattern either fully written or
  not at all. Retrying works; a pattern that fails *twice* is a real
  problem. Small batches with pauses are reliable where long runs are not.

**The 2D pixel map IS installed** — confirmed on the device 2026-08-23
(`getMapFunction()` returns the 3,442-character map from
`warlock-table-pixelmap.js`, with both coordinate arrays populated). Two
docs disagreed about this for a while; the device is the tiebreaker.

**Still not built:** pattern upload from the panel. `tools/upload_pattern.py` does it from the command line, and the
Pi cannot compile, so a panel button would have to proxy to a laptop.

### 3.9 Player Initiative Lighting *(built 2026-08-21)*

Whose turn it is, shown on the table itself. Player turns only — the seat
of whoever is up flashes, and everyone else's seat drops back.

**How it is driven: entirely by the GM, entirely on the table.** There is no
integration with anything, nothing is fetched from another program, and
nothing is sent out. The GM taps "Set Initiative Order", taps the players in
the order they want, and taps Done. "Run Initiative" starts from the top,
with arrows either side to step forward and back. The arrows wrap, so going
round again is simply the next round.

**Nothing is parsed, sorted or guessed.** The order is exactly the sequence
of taps. There are no initiative scores, no dice, and no monsters: a monster
has no seat, so the table has nothing to say about it and it belongs on the
GM's own sheet.

**The only notification is the table.** No phone alerts, no banners, no
sounds. A seat flashing is the entire signal.

There is also a **Flash** button per seat, separate from initiative: it
flashes one player's lights three times and then puts the scene back. The
"oi, you" button, for getting someone's attention without starting combat.

An order entry is just a seat number. The player's name is looked up from
their seat claim when something needs displaying, so re-claiming under a
different name leaves no stale entry behind.

Not persisted, deliberately — see the note at the top of
`warlock/initiative.py`. It changes every turn, the SD card is the one
component here with a wear limit, and it is a fact about the next twenty
minutes rather than about the table.

Built on the zone model in §4.7. Implementation: `warlock/initiative.py`,
`patterns/zones.js` (`activeZone`), and the Initiative section of the panel.

#### An earlier version of this section was wrong

It said per-seat initiative was "deliberately **not** a standalone feature
(too fiddly to run manually)" and that it "rides on the VTT integration".
Both were wrong. Tapping players in order takes a few seconds, stepping
through them is one button, and none of it needs another program. Recorded
because the claim had already been sitting in this document long enough to
look settled.

#### Virtual tabletop integration (Overseer Studio) — *not planned*

**Not needed and not a dependency of anything.** Kept only because the
research was done and may be worth something later. If it ever happens it
will be additive: a way to drive actions the table already has, not a thing
the table waits on.

- **The app:** **Overseer Studio** — not a VTT itself, but a modular,
  offline-first **GM workspace** ("a tool for your tools") that embeds other
  apps (D&D Beyond, Roll20, Spotify) as tiles on a canvas. Desktop app,
  one-time purchase, Early Access as of mid-2026. By the creator of Astral
  Tabletop and dddice.
- **It has a real plugin SDK:** extensions are HTML/JS built via an official
  CLI (`@overseer-studio/sdk`); the runtime exposes events, toasts,
  shortcuts and a keyed state store that persists across sessions. Named
  shortcuts can be declared in the manifest and listened for
  (`onShortcut('next-turn', ...)`).
- **Shape it would take:** an Overseer plugin bridging Overseer ↔ the
  controller. A named shortcut in a session notifies the controller, which
  drives lights/sound/voice; and the reverse, a card or panel button
  triggering something in Overseer.
- **Caveats, if it is ever revisited:** the SDK's events look oriented around
  Overseer's own tiles and shortcuts, not deep hooks into whatever VTT is
  embedded inside it — so "GM fires a named shortcut, table reacts" is
  plausible while "react to a specific in-VTT combat event" may not be
  exposed at all. And Early Access means the API will move.

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

### 3.13 Govee Room & Accent Lighting *(specced 2026-08-23, not built)*

The table lights the table. Govee lights the room it sits in — wall and
accent strips, and strips under the table itself — so a scene reaches past
the edge of the furniture.

#### The LAN API, not the cloud one

**This uses Govee's LOCAL LAN API. The cloud API is rejected**, for the
same reason push notifications were: it routes every command through
Govee's servers, so the table would need outbound internet to change the
colour of a light in the same room, and would go dark whenever the
internet did. It also costs a round trip to a data centre on a chain we
just spent a day cutting to under 600ms.

The LAN API is plain UDP on the local network:

| | |
|---|---|
| **Discovery** | multicast `239.255.255.250:4001`, devices reply to UDP `4002` |
| **Commands** | UDP to the device's own IP, port `4003` |
| **On/off** | `{"msg":{"cmd":"turn","data":{"value":0}}}` — 0 or 1 |
| **Brightness** | `{"msg":{"cmd":"brightness","data":{"value":20}}}` — 1..100 |
| **Colour** | `{"msg":{"cmd":"colorwc","data":{"color":{"r":0,"g":12,"b":8},"colorTemInKelvin":7200}}}` |
| **State** | `{"msg":{"cmd":"devStatus","data":{}}}` — reply on 4002 |

**Four constraints that shape the design, and none are ours to change:**

1. **LAN control must be switched on per device in the Govee Home app.**
   It is off by default. A device that has not been enabled is invisible
   to discovery and there is nothing the table can do about it.
2. **Not every model supports it.** Check the model before buying anything
   for this.
3. **Multicast discovery is unreliable on consumer routers**, particularly
   across WiFi. The config must accept **explicit device IPs** as well, or
   this will work at one house and not another.
4. **UDP is fire-and-forget.** No acknowledgement, no delivery guarantee.
   `devStatus` is the only way to know a command landed.

**What the LAN API cannot do: Govee's built-in scenes and effects.** Those
are cloud-only. Locally you get solid colour, colour temperature,
brightness and power. That is enough for what this is for — the room
should support the table, not compete with it — but it does mean no
Govee-side animation, ever, and the spec should not imply otherwise.

#### How it fits

A device in `warlock/devices/` behind the same interface discipline as the
others, constructed in `runtime.py`, faked for development. It joins the
existing concurrent dispatch as a fourth job, so the room changes with the
lights rather than after them — and §5.2 applies unchanged: **a Govee that
is unplugged, unreachable or never enabled must degrade to nothing at all
happening in the room, with the table entirely unaffected.**

Devices are addressed in **named groups** rather than individually — a
scene wants to say "room" and "under-table", not recite MAC addresses.

#### Scope, settled 2026-08-23

**Accent strips that mirror the general colour of the table lights.** Solid
colour and brightness. That is the whole feature.

**Scenes only — not cards.** An Aura runs 4–9 seconds and the room flaring
for the Tower was tempting, but a UDP command with no acknowledgement, to a
device whose own response time is unknown, is not something to hang a
four-second sting on. It would also be exhausting over an evening. Scenes
change rarely and hold, which is exactly what this suits.

**The colour is DERIVED, not configured.** A scene names a pattern, and it
was not obvious the table could know what that pattern looks like — but it
can, because `tools/patterngen.py` holds every scene's palette. Taking the
hue and saturation weighted toward the lit end of each range gives:

| Scene | Colour |
|---|---|
| Forest | `#7AFF14` |
| Island | `#5FFAFF` |
| Mountain | `#FF9152` |
| Plains | `#FFBB35` |
| Swamp | `#CD0CFF` |
| idle | `#BB35FF` *(from `patterns/idle.js`'s own constants)* |

So no new config field, no colours picked by hand, and **no way for the
room to drift out of step with the table** — both read the same source. If
a scene's palette is retuned, the room follows without anyone remembering
to update it. Emitting these from the generator alongside the patterns is
the obvious implementation.

#### Proven on the real network, 2026-08-23

Discovery and status both work from the Pi. Four devices answered:

| Device id | SKU | Notes |
|---|---|---|
| `5A:BE:C6:35:34:35:4A:64` | H6076 | |
| `75:54:E8:55:05:06:4C:95` | H802A | |
| `C4:E9:60:74:F4:29:CE:CF` | H619E | |
| `D9:97:D0:35:33:35:2F:57` | H6076 | |

`devStatus` returns `onOff`, `brightness` (1–100), `color` as RGB and
`colorTemInKelvin`, so the read path is confirmed as well as the write
format. Nothing has been written to any device yet.

**ADDRESS DEVICES BY THEIR ID, NEVER BY IP.** Those IPs came from DHCP on
a network where the Pi has moved three times and the Pixelblaze once, in a
single day. A config file full of addresses would be broken by the next
lease renewal. The device id is stable; discovery maps id → current IP at
startup, and re-running it is the fix when something stops responding.

That also means **discovery is not optional** — the explicit-IP fallback
in the constraints above is for routers that block multicast, not the
normal path.

#### Still open

- **How often to reconcile?** UDP has no acknowledgement, so a dropped
  packet leaves the room out of step until the next scene change. A
  periodic `devStatus` and re-send fixes it; the interval trades against
  network chatter.
- **What does the room do at shutdown?** Stay lit, fade down, or go out.

### 3.12 (Future) Virtual Desktop / Remote Access
- Possibly add a second computer running a virtual desktop.
- Accessible remotely from an iPad or similar.
- **To expand:** why (what workload needs it), which VD tech, how it fits the table physically. Flagged as a stretch/later goal.

---

#### A cue begins when the card is tapped *(fixed 2026-08-22)*

`time()` on the Pixelblaze is a free-running wall clock, not a timer you
start. Every one-shot envelope and one-shot field was built on it, so a
Boon's 4-second flash lived at a fixed offset inside an 18-second cycle
that had nothing to do with anybody touching a card. Tapping at a random
moment showed nothing about 78% of the time; the Magician, whose flash is
1.8s of 18, was invisible about 90% of the time. Reported from the table
as "no visible pattern on any of the boons".

One-shots now run off `cueEl`, which counts from zero when the pattern is
activated. Cyclic envelopes — breathe, strobe, metronome, flicker,
heartbeat — still free-run, because ambience has no beginning.

**`action` is in absolute seconds**, converted once at construction. It
used to be a fraction of the period, which only ever meant "this many
seconds of an 18-second period" and silently meant something else the
moment the period changed.

#### Auras have a shape, and a ceiling *(2026-08-22)*

An Aura is a **sting**, capped at 10s and usually shorter — the length is
per-card because the right one is a property of the pattern: three
heartbeats is 8s, five metronome ticks is 8s, a hard strobe is 4s and not
a second more. `duration_s` in config matches the pattern's own length, so
the revert lands as the visual ends.

Their envelopes are cyclic, so they had no ending — the revert timer just
chopped them off. `Pattern(window=(attack, release, total))` adds a
one-shot gate multiplied into brightness at render time, giving every card
an arrival and a departure without touching its character. Applied at
render rather than folded into `env`, because flicker feeds back on its
own previous value and gating in place compounds the fade.

#### What actually costs frames

Measured 2026-08-22, and **not** what anyone guessed:

| Shape | fps |
|---|---|
| uniform field, no loop | 42–44 |
| 3 blooms | ~15 |
| 6 eyes | ~10 |
| 9 blooms | ~11 |

The VM executes roughly **300,000 operations per second, flat**. Frame rate
is total ops divided into that budget, and every operation costs about the
same. Two consequences, both learned the hard way:

- **Cheaper operations barely help.** Removing *every* division and
  `floor()` from the inner loops — the wrap became two compares, widths
  became precomputed reciprocals — bought 3–20%, not the 2–3x predicted.
- **Fewer iterations is the only real lever.** Aura-Star tested all 764
  pixels against all 9 blooms, 6,876 iterations, to light about 72 pixels:
  over 98% of that work produced nothing. **Fixed 2026-08-23 by scattering
  rather than gathering** — each bloom walks its own span in
  `beforeRender` into a ring buffer, and `render` does one lookup:

  | Pattern | Before | After |
  |---|---|---|
  | Aura-Star (9 blooms, 4 wide) | 11.3 | **33.6** |
  | idle (6 eyes, 26 wide, + surge) | 10.5 | **23.8** |
  | Forest (3 blooms, 70 wide) | 15.1 | **22.8** |

  Narrow blooms win most, because clearing the buffer is a fixed 764
  writes and wide blooms had less waste to remove. `vmerr` 0 throughout;
  the extra buffer costs ~820 memory units against 9,444 free.

  **The op-budget model above predicted this and the two cheaper fixes it
  did not.** Worth trusting next time: count iterations, not operations.

Also fixed: a bloom's envelope was evaluated *per pixel* rather than per
bloom. Correct to hoist, but it saved almost nothing, which an A/B against
the previous Forest showed plainly.

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

**Uploaded and working on the table** (2026-08-21). Patterns go up through the
API with `tools/upload_pattern.py`; there is no manual step. If the pattern is
ever missing, `supports_zones()` reports false, the panel says so in plain
words, and the seat actions no-op rather than failing.

```bash
python tools/upload_pattern.py zones      # laptop only - compiling needs V8
```

**Two things only the device could tell us**, both found by uploading:

1. **The Pixelblaze language is not JavaScript.** A user-defined function
   needs the `function` keyword — `buildZones() {` is a syntax error, which
   no pattern already in `patterns/` would have revealed, because none of
   them defines one. The firmware's own compiler caught it.
2. **`setActiveVariables()` does write exported arrays.** This was the load-
   bearing assumption of the whole design and had no precedent on this table:
   every other pattern exports only a scalar. Confirmed by writing all three
   colour arrays and reading them back.

Compilation happens **against the live device** — the client pulls the
compiler out of the Pixelblaze's own web UI and runs it under V8. So the
bytecode is always built by the compiler belonging to the firmware that will
run it, and syntax is checked by the real thing rather than by assumption.
It also means uploading needs a reachable device, and cannot be done from
the Pi (`py_mini_racer` has no ARM wheel and is stubbed there).

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


#### Seat colours

Seven hues, defined in `warlock/zones.py`. Deliberately a rainbow rather than
the project's brass-and-purple identity: these exist to be told apart by a
player pointing at the table in a dim room, so separation beats house style.

**Orange is not a seat colour.** On the real table orange and yellow were
indistinguishable (observed 2026-08-21). The underlying fault was not that
one pair looked alike — it was that red, orange and yellow crowded three of
seven seats into 13% of the hue wheel while the span from yellow to green
sat empty. Dropping the *middle* term separates both its neighbours at once,
taking the worst-case gap from 0.06 to 0.12. Dropping yellow instead would
barely have helped (0.07), because red and orange then become the confusable
pair. Purple fills the gap between blue and magenta.

Orange stays in the lookup table so an existing config or an explicit
`set_zone()` still resolves; it is simply out of the seat rotation.

Every seat colour is fully saturated on purpose. On RGBW, dropping saturation
pulls in the white channel and washes the hue toward pastel grey — which is
exactly how two neighbouring seats stop being tellable apart.

**A live config overrides all of this, and that is a trap.** `install.sh`
seeds `config.json` once and then never touches it, so a config seeded before
a palette change keeps the old colours no matter how much new code is
deployed. That bit for real: the orange/yellow fix landed in code and would
have had no effect on the Pi whatsoever. Hence:

```bash
python3 tools/sync_seat_colours.py --dry-run   # on the Pi, AS THE SERVICE USER
python3 tools/sync_seat_colours.py
sudo systemctl restart warlocktable
```

**Not with `sudo`.** The config belongs to the service user and is writable
by it. Running the tool as root once left a root-owned `0600` config the
service could not read, and the table crash-looped until the ownership was
restored. The underlying fault was in `save_config`: `os.replace()` swaps the
temp file in wholesale, so the config inherited `mkstemp`'s mode and owner
rather than keeping its own. It now copies both across, which also fixes the
panel having quietly turned a `0644` config into `0600` on every edit.

Deliberately **not** run by `install.sh` — overwriting seat colours on every
deploy would discard a real customisation, and seeding-once exists precisely
so the operator's data stays theirs.

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

- ~~Upload `patterns/zones.js` to the Pixelblaze.~~ Done — uploaded through
  the API and confirmed lighting seven seats on the table. Table Check
  still warns rather than fails if it goes missing, because a table with
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
| **HDMI handshake / wrong mode** | Boot with the TV off, or let EDID choose, and the display comes up wrong. Both happened: a power cut with the TV off left X at 1024×768 on the *disconnected* port; later, EDID negotiation picked **4096×2160** — DCI 4K at 17:9, which does **not** match this 16:9 panel, so everything was stretched. | **Fixed 2026-08-20.** The TCL was moved to **HDMI0** (nearest USB-C), which xrandr calls `HDMI-1` and is already flagged primary — one cable swap instead of a login-time xrandr workaround. Mode is pinned in `/boot/cmdline.txt` with `video=HDMI-A-1:3840x2160@30`, because **`vc4-kms-v3d` ignores the legacy `hdmi_group`/`hdmi_mode` settings** in favour of EDID. The old `hdmi_force_hotplug:1=1` was removed — with the port now empty it was conjuring a phantom 1920×1080 display. Backups: `/boot/*.bak-cableswap`. **Recurred 2026-08-21** in a third form: the mode was pinned but the connector was not *forced*, so a cold boot with the TV slow to assert hotplug left HDMI-1 connected with **no mode set** — signal absent, every subsystem green. Fixed by appending `e` to the mode string (§3.6), and Table Check now has a **Video output** check that asks the X server whether a mode is actually set, because nothing else in the system could tell. |
| **SD card corruption** | The #1 killer of long-running Pi projects; usually caused by yanking power. | Physical GPIO shutdown button → `shutdown -h now`; keep a known-good SD image on the shelf so recovery is ~20 min. Booting from USB SSD instead is a genuine upgrade the Pi 4 supports. |
| **Config typo bricks the table** | YAML edit the afternoon before a session. | Validate at startup; fall back to last-known-good; show the error on the panel. |
| **Game-day deploy** | The Git bridge makes it trivially easy to `git pull` an hour before people arrive and break everything. | Run a **tagged known-good version** on the Pi, not raw `main`, so rollback is one command. Test on the laptop first — the fakes (§4.2) make this possible. |
| **Unknown card scanned** | Old code printed `not a registered card!` to a terminal nobody is reading. | Surface it on the panel; ideally offer to register it right there. |

**Pixelblaze flash exhaustion and websocket wedging (2026-08-21).** Worth
its own entry, because it took the table down for an evening and the cause
was not where it looked.

| | |
|---|---|
| **Symptom** | Upload hung mid-run; websocket then refused every connection while HTTP still served fine. Power cycle brought it back with **the entire LED configuration lost** — `ledType: noLeds`, `pixelCount: 0`, `colorOrder: BGR`, and the brightness limit reset from 50 to **100** |
| **Root cause** | `savePattern` was copying an **8,655-byte preview image** onto every uploaded pattern. 70 patterns needed 669 KB against 490 KB free — it could never have fit. The capacity estimate that said otherwise counted source bytes only |
| **Made worse by** | The upload was backgrounded and left unattended for 47 minutes; and the controller's 10-second reconnect loop was competing for the device's small pool of websocket slots throughout |
| **Fixed by** | Empty previews (`b""`), one-at-a-time uploads with verification, stopping the controller during device work, and archiving before deleting |

**The brightness limit resetting to 100 is the part that mattered most.**
That is the power ceiling for a 40 A supply feeding 764 SK6812 RGBW (§3b of
the LED reference). It was restored *before* the pixel count, so there was
never a moment where 764 pixels could run at full. `tools/upload_watched.py`
now checks the pixel count and the limit after **every** upload, because
they were lost silently once and nothing noticed.

**Two device behaviours worth knowing before touching it again:**

- **`storageUsed` refreshes lazily**, mostly on reboot. Deleting a pattern
  moves it by zero. It cannot be used as a live capacity guard.
- **Transient failures happen roughly every 5–15 operations** —
  `IncompleteRead`, empty source read-backs, occasional write failures —
  and the device is healthy immediately after each. Retrying works. Small
  batches with pauses are reliable where long runs are not.
- **`savePattern` APPENDS, it does not replace.** Saving over a name that
  already exists leaves TWO patterns with that name. The verifier resolves
  by name and can compare against the stale one, reporting "source read
  back does not match" on a perfectly good write — and the controller
  resolves by name too, so the table may keep playing the old copy with
  nothing reporting a fault. `upload_watched.py --only` now deletes every
  existing copy before writing.
- **`getStatistics()` enables preview-frame streaming, and the fps figure
  is a lagging average.** Read over a shared connection or too soon after
  a pattern switch, it reports the PREVIOUS pattern. That made per-pattern
  render cost look like device-wide degradation on 2026-08-22, and led to
  two pointless reboots and a wrong answer to the user about diffuser
  optics. **To measure honestly: fresh connection, set the pattern, drop
  the socket, wait 14s, reconnect, take ONE reading.**

**The viewer can die, and nothing used to bring it back (2026-08-22).**
`feh` was launched once at startup. When it exited, `status()` flipped
unhealthy and every `set_background()` after that raised — the TV went
black and stayed black until someone restarted the service. Mid-session
that is the entire visual half of the table, with nobody at a keyboard.

It happened for real: no OOM, no segfault, 3.2GB free, and nothing in any
log saying why. We cannot prevent an exit we cannot explain, so a watcher
thread now notices within ~2s and relaunches. Nothing needs restoring —
the picture is whatever is in `.current.png`, and feh exiting does not
touch that file. `RESPAWN_MAX_TRIES` guards a spawn loop that will never
work and **resets on every success**, so a viewer that dies nightly keeps
being rescued. `tablecheck` WARNs once it has needed rescuing: self-healing
nobody can see is how a flapping display stays hidden until the night it
does not come back.

Two traps fixed in the same path:

- feh's stderr went to a **pipe nobody drained** after the 0.6s startup
  check. Once it wrote ~64KB it would block forever on write — picture
  frozen, process still passing a `poll()` check. It goes to a file now.
- `set_background()` refused while unhealthy, which would have dropped a
  card tap for the ~2s a respawn takes.

**journald showed a stale picture (2026-08-22).** stdout to journald is a
pipe, so Python block-buffered it and log lines surfaced in ~4KB bursts,
minutes after the events they described — worst exactly during an
incident, when you end up debugging a table that has already moved on.
`Environment=PYTHONUNBUFFERED=1` in the unit.

### 5.4 "Table Check" — pre-session self-test *(built)*

One button on the panel. Run it ten minutes before people arrive. **This is
the highest-value reliability feature in the whole build** — it is the
difference between finding a problem with time to fix it and finding it with
an audience.

Fourteen checks, in three groups. Never raises: a broken check still reports.

**Does config point at things that exist?** The centrepiece, because every
device can be perfectly healthy while the table is still broken.

| Check | Answers |
|---|---|
| Build | which version is actually installed |
| Config | it parses, and what is in it |
| Light patterns | every pattern config names is on the Pixelblaze |
| Audio tracks | every track resolves to a real file |
| Backgrounds | every background image exists |
| Zone model | 1–7 players divide cleanly, and `patterns/zones.js` agrees |
| Seats | the player count is sane and nobody claimed a seat that is gone |
| Zone lighting | the `zones` pattern is on the device |

**Is each device alive?** Lights, Audio, NFC reader, Display, Disk space.

**Is anything actually coming out?** Video output — see below. And in
`physical` mode, a pattern is flashed and a sound played so a human can
confirm with their own eyes and ears, then whatever was showing is restored.

**Why "Video output" is the odd one out, and why it matters most.** Every
other check answers *"did the call succeed"*. That one answers *"did anything
come out"*, and they are not the same question. On 2026-08-21 the HDMI output
sat connected with **no mode set**: the Pi drove no signal, the TV was black,
and the service, the display device, feh and the status strip all reported
green — because each was working exactly as designed. Nothing was wrong
upstream. There was simply nothing downstream. A connected output is not a
working one; only an active mode is.

**Worth adding, not yet built:** a check that the zones pattern is
*configured*, not merely present. On 2026-08-21 initiative appeared to do
nothing: the controller was correct throughout — order set, running, right
zone, right pattern loaded — but the pattern had never been sent a player
count, so it rendered its unconfigured fallback. That fallback is the idle
purple rather than black, deliberately, so a table in that state looks
resting instead of dead — which is also precisely what hid it. Nothing
errored, nothing logged, the status strip stayed green. Reading back
`playerCount` from the device would have caught it in seconds.

That gap is the general form of the problem noted in §5.7: *device call
returned* is not *the thing changed*. Video output is the only check that
currently closes it, and the same reasoning would apply to sound if it were
ever worth asking ALSA whether samples are really leaving the card.

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
### 5.7 Responsiveness — where the lag actually is *(observed, not yet fixed)*

**Observed on the real table, 2026-08-21.** Tapping a card produces a visible
stagger: the lights change, then the audio, then the picture, in that order
and far enough apart to notice. The table works; it just does not feel
*immediate*, and immediacy is most of the effect.

Two separate problems, and the smaller one is the more visible.

#### The NFC read is the single biggest delay

It is also the worst place for a delay, because it sits **upstream of
everything else** — whatever the rest of the chain costs, this is added to
all of it. Nothing happens until the card is recognised.

The knob is `poll_timeout` (default **0.5 s**) in
[`warlock/inputs/nfc.py`](warlock/inputs/nfc.py), passed to
`read_passive_target()`. Things worth trying, cheapest first:

- **Shorten `poll_timeout`.** A tighter loop detects sooner at the cost of
  more SPI traffic. Cheap to try, and the effect is measurable in minutes.
- **SPI clock speed** in the vendored PN532 driver (`warlock/vendor/pn532`).
- **`InAutoPoll`** — the PN532 has a dedicated autopoll command that lets the
  chip watch for targets itself rather than being asked repeatedly. The
  vendored driver does not use it.
- **A different reader.** The PN532 is a 2011-era part and may simply be the
  floor here. Worth benchmarking alternatives — but only *after* measuring,
  because replacing hardware to fix a software poll interval would be an
  expensive way to learn nothing.

#### The display trails the lights and sound

Two causes, very unequal:

1. **The picture is asked for last.** `apply_scene` calls lights, then audio,
   then display, sequentially (§4.6). The display does not start until the
   other two return. Worth perhaps 50 ms.
2. **feh polls.** It runs with `--reload 1`, so it re-stats the file **once a
   second**. The swap itself is a ~50 ms copy; the rest is feh not having
   looked yet. **This dominates** — reordering the calls would barely help.

Candidate fixes, neither yet tested on the Pi:

- **Signal feh instead of waiting for its poll.** feh acts on `SIGUSR1`. The
  doubt: in single-image mode that is documented as "next image", and it is
  unclear whether it forces a re-read from disk or reuses a cached pixbuf.
  One test on the Pi settles it.
- **Fractional `--reload`.** Some builds accept `--reload 0.2`; older ones
  parse it as an integer, and `0` may busy-loop. Depends on the build.

**Do not abandon feh over this.** The polling is a property of the approach,
and the approach was chosen for a good reason: feh survives running headless
under systemd, where pygame did not (§4.6). Fix the poll, keep the process
model.

#### MEASURED 2026-08-22

Timed from the Pi, where the controller sits. The guesses above were
partly right and missed the largest software cost entirely.

| Step | Cost |
|---|---|
| NFC `poll_timeout` (upstream of everything) | 0–500 ms |
| Sending a pattern command to the Pixelblaze | **0.3–1.2 ms** |
| Pixelblaze actually switching pattern | **270–320 ms** |
| `getActivePattern()` read-back confirmation | 88 ms |
| **`set_pattern()` total, which the controller BLOCKS on** | **~480 ms** |
| `set_background()` file copy | 76–320 ms |
| feh noticing the file (`--reload 1`) | 0–1000 ms |
| `getPatternList()` | 0 ms — cached in the client |

**The biggest finding is not on the list above: the controller is
serial.** `apply_scene` calls lights, *then* audio, *then* display, and
each waits for the last. So audio does not start until ~480 ms after the
lights command, and the picture is asked for later still. That is not a
device problem and costs nothing to fix.

A card tap today, worst case: 500 ms to notice the card, +280 ms for the
lights, +480 ms before audio begins, +up to 1 s before feh looks at the
file. Roughly **two seconds to a complete picture**, arriving in three
distinct instalments — exactly the stagger that was reported.

**The 270–320 ms pattern switch is a floor.** Sending costs a millisecond;
the rest is the device loading bytecode and starting it. `saveToFlash` is
already False, so it is not a flash write.

Ranked by value:

1. **Dispatch the three subsystems concurrently.** Removes ~480 ms of pure
   serialisation. Note it *reorders* the stagger rather than removing it —
   audio would then lead the lights by ~250 ms — so aligning deliberately
   (delay the fast ones to meet the Pixelblaze) is the actual goal.
2. **`--reload 0.2`.** feh 3.6.3 on the Pi accepts a fractional value; it
   parses fine and only fails on the display. Cuts picture jitter from
   0–1000 ms to 0–200 ms. One word.
3. **Make the read-back confirmation occasional rather than per call.**
   88 ms, and it exists for observability rather than correctness.
4. **`poll_timeout`.** Halving to 0.25 s halves the upstream delay, at the
   cost of more SPI traffic. Cheap to try, easy to revert.

#### The original guesses, kept for the record

**Nothing here has been timed.** The ordering above is what a person
perceived, which is enough to know something is wrong and not enough to know
what to fix. Before changing anything, instrument the chain end to end:

| From | To |
|---|---|
| card enters the field | UID decoded |
| UID decoded | controller dispatches |
| dispatch | each device call returns |
| device call returns | pixels / audio / picture actually change |

That last row is the one that matters and the one no log currently captures:
every device call can return promptly while the table still looks slow, which
is exactly the situation here. The event log already timestamps most of the
middle rows, so this is mostly a matter of reading it rather than building
something new.


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
- [x] **Status screen on the TV — done.** Rendered to a PNG and shown through the *same* feh instance as the artwork, so only one thing ever draws on the screen. Shows per-subsystem marks, current scene, the panel URL and the deployed version. **It also carries the join QR, and is selectable (2026-08-22):** it appears in `available_backgrounds()` — listed first, because it is the one entry that is not artwork and burying it alphabetically hides what you reach for when something is wrong — with a **Show Join / Status Screen** button on the panel, lit while it is on screen. `set_background` previously took free text with no choice list at all, so there was nothing to pick from. The controller routes that name to `show_status_screen()`, since the screen must be RENDERED from live status the display device knows nothing about. **The QR encodes a LAN IP, not the `.local` name:** the web server can use the client's Host header because it is answering a request, but this renders at boot with nobody connected, and `.local` needs mDNS that many Android phones will not resolve — a join code that works for half the table reads as the table being broken. The footer prints that same address so the type-it-in fallback works for exactly the phones that could not scan. Drawn from segno's raw matrix rather than a PNG round-trip so modules land on whole pixels, with a quiet zone in whole modules; a missing segno returns False rather than raising, because this screen is what you look at WHEN things are broken. Appears automatically at startup, and on demand via the `show_status_screen` action. Styled to `warlock-table-style-guide.html` **exactly** — Syne, IBM Plex Sans and IBM Plex Mono are bundled in `warlock/web/static/fonts/` (SIL OFL) and served locally rather than from the Google CDN, so the table never needs the internet to render its own surfaces. The same font files feed both the TV and the iPad panel, so the two use identical type.
- [x] Config validation with last-known-good fallback — done, three levels (requested → `.last-good` → minimal built-in that still lights the table).
- [x] mDNS — `raspberrypi.local` works (avahi).
- [ ] **DHCP reservations** for the Pi and Pixelblaze — not done, and it
  bit on 2026-08-23: the Pixelblaze moved `.171` → `.169` mid-session.
  The controller was fine, because discovery does its job — but every
  laptop tool reads a cached address from `data/device-state.json` and
  they all failed with "no route to host" until it was corrected. The Pi
  has moved once too (`.24` → `.25`). Discovery covers the device;
  reservations would cover the tools and any bookmarked IP.
- [x] **"Table Check" self-test — done.** Panel button, sub-second. Its centrepiece is a cross-device referential integrity check: every light pattern, audio track and background that config references is confirmed to exist on the real device. Verified by deliberately pointing a scene at a deleted pattern and a missing track — both caught by name, while every device still reported healthy. A second button additionally flashes lights and plays a clip (software cannot confirm photons or sound), restoring the previous scene afterwards.
- [ ] Physical GPIO shutdown button + a known-good SD image on the shelf
- [x] Tagged releases — `v0.1.0` cut and deployed; `VERSION` and the panel both report the build.

### Phase 3+ — Feature Build-Out
- [x] Operator web panel — done. iPad PWA, status strip, scene/interruption/table buttons built from the controller's vocabulary, brightness, grid toggle, card editing. *Apple TV hand-off is stubbed — it logs intent, HDMI-CEC not implemented.*
- [x] **Generate all patterns from one vocabulary** — built 2026-08-22
  (§3.8). 70 patterns, 60% smaller, with the anti-machine-made techniques
  as enforced defaults rather than per-pattern decisions.
- [x] **Pixelblaze pixel map** — installed and verified on the device
  2026-08-23. `warlock-table-pixelmap.js` is the source; `render2D()`
  patterns will work. Nothing currently uses it, which is why it went
  unnoticed as done.
- [ ] Pattern authoring loop + "upload pattern" via the web panel — `tools/upload_pattern.py` does it from the command line already; the panel cannot, and the Pi cannot compile (no ARM wheel for V8).
- [x] Card management — reassign/create/delete from the panel, plus registering an unknown tag by tapping it (§4.5 steps 1–2).
- [ ] **§4.5 steps 3–4:** upload audio through the panel, and author scenes/interruptions from scratch.
- [x] **Cut input-to-effect latency** — measured and largely fixed
  2026-08-22 (§5.7). The chain was timed rather than guessed at, and the
  biggest cost turned out not to be a device at all: the controller
  dispatched lights, then audio, then display *serially*, so the sound
  waited ~480ms for the Pixelblaze to load bytecode. Now concurrent.
  Also: feh's poll 1s → 0.2s, the NFC poll 0.5s → 0.25s, and the
  set_pattern read-back from every call to once per 30s. A tap should
  resolve in under 600ms against roughly two seconds before.
  - [ ] **Confirm at the table.** Audio now slightly LEADS the lights
    rather than trailing; if that reads worse, the fix is a deliberate
    ~250ms delay on audio and display. Not added — fast was preferred
    over synchronised.
  - The Pixelblaze's 270–320ms pattern load is a floor. Sending the
    command costs one millisecond; the rest is the device.
- [x] **Volume and audio output switching** — built 2026-08-21 (§3.3).
  Master volume in software, and a switch between the 3.5mm jack and the
  television.
- [x] **The tarot interruption system** — built 2026-08-22 (§3.2). All 26
  cards have entries pointing at their own patterns, all 32 physical cards
  are enrolled, and the card→target→pattern chain was traced end to end
  with zero dangling references.
  - [x] ~~**Layering an Aura over a Scene.**~~ **ABANDONED 2026-08-22.**
    The Pixelblaze cannot composite two patterns at runtime, so this was
    built as 40 pre-rendered aura×scene combinations — 65% of everything
    the generator emitted. **Not one was ever used:** `play_interruption()`
    sets the interruption's pattern verbatim, so nothing ever asked for
    `Forest+Chariot`, and the selection code was never written. Covering
    the matrix honestly meant 72 patterns on a device whose flash had
    already been filled once, and filling it was what wedged the
    Pixelblaze and cost the LED configuration. **An Aura now replaces the
    scene for its duration and reverts** — which is what the four
    `replaces` auras always did. The loss is real and is not recoverable
    without the combos: the forest is gone for those 60 seconds rather
    than tinted.
  - [ ] **Audio for the 26 cards.** They are silent by design for now;
    `Interruption.audio` is optional so they work until clips exist. With
    no audio the revert is driven entirely by `duration_s`.
  - [~] **NPC binding editor** — **not planned** (decided 2026-08-23).
    `npc_binding` stays defined in the spec and null on every card. The
    nine Person cards work as announcements without it; binding each to a
    named NPC was speculative and nobody has wanted it.
- [ ] **GM panel redesign** (§3.7) — four side-by-side panels for an iPad
  mini in landscape, plus a whisper overlay. Measured: 7.4 screens of
  scrolling today on the device it is built for.
- [ ] **Display redesign** (§3.6) — real grid/hex overlays, battle maps
  with fit/crop rules, a turn indicator and an effects overlay. Measured:
  write JPEG rather than PNG or a redraw costs 2-12 seconds.
- [ ] **Playing cards** — a deck of MIFARE Ultralight tags. Effect
  undecided; likely suit and rank combining, with four suit patterns and
  rank as a parameter rather than 52 patterns. NOT the tarot suits.
- [ ] Phone-tag NFC support
- [ ] Govee room/accent lighting via API, synced into scenes (+ under-table strips)
- [x] **Zone map + per-zone lighting** — built 2026-08-21 (§4.7). The perimeter divides between the GM and 1–7 players, each seat lit its own colour; `patterns/zones.js` is on the device and confirmed working. **Unblocks player phones.**
- [~] Player phones — join QR and seat claiming built 2026-08-21. The
  phone page does exactly one thing: choose a seat. Dice, break requests
  and private whispers are still to come, and are separate decisions
  rather than one lump.
- [ ] Soundscape library + light-scene coordination
- [x] **Session recording** — built 2026-08-21 (§3.10). One button on the
  panel; the room mic to a WAV in `/var/lib/warlocktable/recordings/`.
  Transcription and recaps deliberately deferred: the one thing that cannot
  be done retrospectively is the recording itself.
- [ ] Table personality: write the character, record/render the voice-line library
- [ ] Panel-triggered voice lines
- [x] **Player initiative lighting** — built 2026-08-21 (§3.9). Order set
  by the GM tapping players; the active seat flashes. Standalone, and
  needs no integration with anything.
- [ ] *(not planned)* Overseer Studio plugin bridging VTT events ↔ the
  controller. Kept as a note in §3.9 only; nothing depends on it.
- [ ] Session recording → AI transcription → recap
- [ ] dddice integration (software dice on screen / player phones)
- [ ] Expanded audio zones
- [ ] (Later) Pixels physical dice support
- [ ] (Stretch) Virtual desktop / iPad remote access

### Backlog — deliberately not now

Parked 2026-08-21. Not abandoned, and not blocked by anything: judged more
work than is wanted at this stage. Listed so their absence reads as a
decision rather than an oversight.

- **Live-audio reactive effects** — lights and visuals responding to room
  sound, via the Pixelblaze's own sound input and/or the Pi mic.
- **Spoken-trigger events** — the table acting on what it hears.
- **Keyword spotting** for the table's voice (§3.5). The voice itself can
  still be driven from the panel; it is the *listening* half that is
  parked.

All three want always-on audio analysis, which is a different problem from
recording: recording writes a file and stops, whereas these need continuous
low-latency processing and a wake-word strategy. The microphone is already
attached and working, so none of this is gated on hardware.

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
