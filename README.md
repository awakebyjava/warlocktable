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
| Design the tarot card behaviours | [`warlock-table-interruption-cards.md`](warlock-table-interruption-cards.md) — all 26 built and enrolled |
| Generate artwork for the TV | [`display-image-specifications.md`](display-image-specifications.md) |
| Upload and scale a battle map | [`map-import-specification.md`](map-import-specification.md) |
| Make the table talk | [`entity-voice-specification.md`](entity-voice-specification.md) |
| Give the table its sound effects | [`soundeffects/table-sfx.json`](soundeffects/table-sfx.json) |
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
  sfx/             the stings. Fires on the EFFECT channel, so a scene's
                   ongoing soundscape keeps playing underneath its own
                   arrival sting. Toggleable per family and per sound.
  entity/          the table's voice: whether to speak, which line, and
                   playing it. Flavour only -- delete it and the table is
                   unchanged, which is the constraint that shapes it.
  mapimport/       uploaded images -> table-correct backgrounds. Knows
                   nothing about the controller; writes files and asks the
                   display to rescan, which is the whole integration.
  config.py        the data model, plus atomic validated saves
  configstore.py   mutation under a lock — what the panel edits through
  registry.py      the self-describing action registry
  tablecheck.py    the pre-session self-test
  statusscreen.py  renders the TV status screen
  zones.py         divides the table perimeter into GM + N player seats
  initiative.py    whose turn it is, and which round
  devices/         things the controller CALLS (real + fake, same interface)
  inputs/          things that CALL the controller (the NFC reader)
  web/             the operator panel, served from the controller process
deploy/            install.sh, update.sh, the systemd unit
tools/             laptop-side, for the Pixelblaze and the live config:
                     patterngen.py       generate all 30 patterns
                     prune_patterns.py   delete patterns, one at a time
                     upload_watched.py   upload one at a time, verifying each
                     upload_pattern.py   upload a single named pattern
                     archive_patterns.py copy sources off before deleting
                     migrate_tarot.py    build card entries from the spec
                     migrate_playing_cards.py  the same for the 54-card deck
                     enrol_cards.py      tap physical cards to register them
                     enrol_offline.py    the same, but owning the reader
                                         outright with the service stopped
                     scan_deck.py        walk the 54-card deck in order,
                                         tapping each one onto the table
                     tag_probe.py        identify an unknown tag and its chip
                     sync_seat_colours.py realign a live config's palette
                     icon_manifest.py    the icon set the interface needs
                     audio_worksheet.py  what still needs recording
                     normalise_wavs.py   strip the JUNK chunk ffmpeg leaves,
                                         which pygame 1.9.6 refuses to open
                     voice_check.py      run ON THE PI: does the Entity work,
                                         and how often will it actually speak
                     catalog_sfx.py      describe a sound library into one CSV,
                                         so a shortlist can be made without
                                         listening to thousands of files
                     render_sfx.py       generate the table's 54 stingers from
                                         soundeffects/table-sfx.json
                     render_cues.py      generate the 15 music cues from
                                         soundeffects/table-cues.json, then
                                         put them through the bed repair chain
                     fix_beds.py         repair the five scene soundscapes --
                                         format, level and loop seam -- writing
                                         copies, never touching the originals
soundeffects/      what the table's 54 stings and 15 music cues are MADE
                   FROM, not the finished audio. `table-sfx.json` and
                   `table-cues.json` are the databases -- one entry per sound,
                   with the prompt that renders it -- and are the tracked
                   artifacts. The sampled libraries and the rendered `cues/`
                   beside them are gitignored and laptop-only; `cues/_raw/`
                   holds every API response, so the whole set can be
                   re-levelled later with no API calls at all.
branding/          the wordmark, app icons, and the table's two sigils
patterns/          Pixelblaze patterns, kept in git so the device is not the
                   only copy. `generated/` is patterngen.py's output (30);
                   idle, zones and breathing are hand-written; `legacy/`
                   holds the originals the generated scenes replaced.
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
`v0.3.1` — seat zones (GM + 1–7 players, each its own colour), player
initiative on the lights, the join/QR page with seat claiming, and volume
plus audio-output switching.
`v0.4.0` *(unreleased)* — all patterns generated from one vocabulary; the
26 tarot cards specced, built, enrolled and firing on tap; aura-over-scene
layering abandoned in favour of shorter stings; a hand-written idle
pattern; the status screen selectable and carrying the join QR; the TV
viewer recovering on its own; session recording.

Since, also unreleased — **player phone tools**: signals (`?` / `!`),
dice with a shared roll log, and private whispers. **Govee accent
lighting** over the LAN API, its colour derived from each scene's own
palette. **The interface redesign**: four GM panels behind a bottom tab
bar, three breakpoints, a whisper overlay, and card management as its own
page. **The status screen rebuilt** on the brand — wordmark, the table's
two sigils, four corner QR codes, and `tablecheck` folded in at startup.
Seats can now be vacated from either side, initiative counts rounds and
turns, and rolls show the individual dice in parentheses. **Preset roll
bars** page between d20, World of Darkness and BRP, and **d100** is
allowed — which introduced a split worth knowing about: `controller.DICE`
is what may be *rolled*, while the six shapes on the pad are what is
*shown*, and they are deliberately different lists.

Since that, still unreleased — **map import**: any image, including HEIC
straight off a phone, scaled to the table's own 107.85px grid, with pan,
scale, rotation, brightness and contrast always available by hand and a
square or hex overlay in white or black for artwork drawn without one.
**The Entity has a voice** — 91 pre-rendered lines chosen probabilistically,
with an on/off switch and a how-often slider, and it never speaks over a
sting. **Fifty-four sound effects**, generated rather than bought, firing on
the effect channel so a scene's ongoing soundscape keeps playing underneath
its own arrival sting; switchable per family, per sound, and by profile.
**A scene editor**, so scenes stopped being an ssh job, and the map can now
be changed mid-scene or with no scene at all. **The Run panel's
interruptions are grouped** into collapsible blocks that remember what you
left open.

**The five scene soundscapes were repaired, not replaced.** They were at
44100, 48000 and 96000 Hz against a mixer that runs at 44100, so SDL was
converting four of the five on load — and that conversion, not the
recordings, is where a 7.6 dB spread between quietest and loudest came
from. Fixing the format fixed the level. Separately, `plains` had a
completely dead right channel, and `island` ended at 4.15× the level it
started at, which is the thump you heard every time round. Repaired copies
live beside the originals and win by search order, so the two can still be
A/B'd on the table; `tools/fix_beds.py --check` measures without writing.

And a **music layer**, which is the one that changed shape while it was
being built. It began as "music for each scene" and that was wrong: a scene
says WHERE the party is, and what you actually want to underscore is WHAT IS
HAPPENING. So a cue -- travel, ambush, arcane, dread, grief -- is chosen
independently and combined with any scene. Fifteen of them in five groups,
on their own reserved channel pair so a cue crossfades without touching the
bed. Two rules, both decided at the table: a cue NEVER arms itself, combat
included, because a GM who wants a silent round should not have to fight the
table for it; and a scene change FADES THE CUE, because a change of location
is a scene break. Cues deliberately do not live in `audio_paths` -- anything
there shows up in `available_tracks()`, and the effect picker and scene
editor would fill with music.

Rollback is `git checkout <tag> && sudo ./deploy/install.sh`; the deployed
build is recorded in `/opt/warlocktable/VERSION` and shown in the panel.
