# Entity Voice Playback — Implementation Primer

*Hand this to Claude Code. It describes one subsystem of the Warlock Table controller: the thing that decides whether the Entity speaks, picks which line, and plays it.*

---

## What this is (and isn't)

The Warlock Table is a **control interface** — lighting, sound, screen, and NFC triggers that a human operator runs alongside whatever else is happening in the room. It is not a game, implements no rules, and has no bearing on anything outside itself.

The Entity is **flavor audio**. It's a library of pre-rendered voice lines that occasionally play on top of a table action. It has no state that matters to anything, makes no decisions, and affects nothing. If the voice subsystem were deleted entirely, every other part of the table would work identically.

Keep that scope. This module's entire job is: *a trigger fired — should a voice line play, which one, and is the audio device free?*

---

## The assets

Rendering is already done and lives outside this code.

```
audio/entity/          91 finished WAV files, one per line, named <line_id>.wav
audio/entity/_raw/     lossless raws — never touched at runtime
entity-lines.json      the line database
```

Files are 44.1kHz mono WAV, normalized to 0.86 peak, faded at both ends. Durations run roughly 1.5 to 4 seconds — note that processing adds a reverb tail, so a file is meaningfully longer than the spoken words.

`entity-lines.json` structure:

```json
{
  "_meta": { "elevenlabs": { "voice_id": "...", ... } },
  "lines": [
    {
      "id": "tarot_boon_04",
      "trigger": "tarot_boon_any",
      "trigger_category": "tarot_boon",
      "mood": "sarcastic",
      "mask_slip": false,
      "reaction": "...",        // writing notes, ignore at runtime
      "line": "...",            // the text, ignore at runtime
      "delivery": "...",        // voice direction, ignore at runtime
      "audio_file": "audio/entity/tarot_boon_04.mp3"
    }
  ],
  "_bohica_tier": { "lines": [] },   // empty, will be populated later
  "_open_items": [ ... ]
}
```

**Two things to handle:** `audio_file` says `.mp3` but the renderer now outputs `.wav`. Derive the path from `id` rather than trusting that field, or fix the JSON on load. And `reaction` / `line` / `delivery` are authoring metadata — useful for logging, irrelevant to playback.

---

## The core behavior

### 1. Triggers are already defined elsewhere

The controller owns all actions (lighting scenes, sound, screen, Apple TV handoff). Every input — NFC tap, panel button — resolves to an action. This module **subscribes** to those actions; it does not intercept or gate them.

Critical: **the voice must never block or delay the table action.** The lights fire immediately; the voice is decided and played independently. If the voice logic throws, the table action still happened.

### 2. Not every trigger speaks

This is the single most important design constraint, and it's currently unresolved — you're implementing the mechanism, and the numbers get tuned by ear later.

The Entity speaking on every trigger would make it a talking toy within an hour. Speaking rarely makes it feel like a presence. So:

- Each trigger has a **speak probability** (roughly 1 in 6 to 1 in 10 is the starting guess — make it configurable per trigger, not global).
- A **global cooldown** prevents two lines in quick succession regardless of probability. Several minutes is the starting guess.
- Some triggers are **never** voice-eligible (soundscape change, mood toggle, private phone messages).
- Some triggers should speak at **much higher rates** — system startup in particular, where a line establishes the character at session start and there's no repetition risk.

Put all of this in config, not code. Rate tuning will happen live, and it should not require a code change.

### 3. Line selection

Given a trigger that's decided to speak:

1. Find lines matching that trigger id.
2. Fall back to the `trigger_category` pool if the specific trigger has none.
3. Fall back to `any_voice_eligible` (the `general` category) as a last resort.
4. Never repeat the same line twice in a row, and ideally not within the last N plays. A simple recently-played deque per pool handles this.
5. Filter by current mood if a mood is set; if that leaves nothing, ignore mood rather than staying silent.

**Mood is unresolved.** Five states exist — resentful, sarcastic, transactional, cryptic, unsettling — but whether they're manually toggled from the panel or drift automatically hasn't been decided. Build it so mood is just a filter value that something else sets. Don't implement drift logic yet.

### 4. Audio playback

- **One line at a time.** If a line is playing, a new trigger either queues or is dropped. Dropping is probably right — a stale reaction is worse than silence.
- Mixing matters: the Entity should duck or play over soundscapes, not fight them. Decide with the audio routing work, not here.
- Track playback duration so cooldown starts when the line *ends*, not when it starts.
- Audio output is HDMI and/or the 3.5mm jack on the Pi 4; both can run simultaneously.

### 5. Manual trigger from the panel

The operator panel must be able to fire any line by id, bypassing probability and cooldown entirely. Essential for testing, and useful during a session. This should be a separate code path from the probabilistic one.

---

## Suggested shape

Config as data, consistent with the rest of the controller:

```yaml
entity_voice:
  enabled: true
  audio_dir: audio/entity
  lines_json: entity-lines.json
  global_cooldown_seconds: 180
  default_speak_probability: 0.12
  no_repeat_window: 8

  triggers:
    system_startup:      { probability: 1.0 }
    tarot_boon_any:      { probability: 0.15 }
    panel_appletv_handoff: { probability: 0.25 }
    panel_soundscape:    { probability: 0.0 }
```

Rough interface:

```
EntityVoice.on_trigger(trigger_id) -> Optional[line_id]
    Decides and plays. Returns what played, or None. Never raises.

EntityVoice.play_line(line_id) -> bool
    Manual/panel path. Bypasses probability and cooldown.

EntityVoice.is_speaking -> bool
EntityVoice.set_mood(mood) / .mood
```

---

## Things that will bite

**Startup latency.** Loading and decoding a WAV on first play adds a delay that reads as the table hesitating. Preload into memory — 91 short WAVs is small enough that holding them all is reasonable on a Pi 4. Measure before optimizing.

**Timing against the light effect.** A voice line landing at the same instant as a comet sweep competes with it. A short delay — a beat after the visual starts — will probably feel better. Make it configurable per trigger.

**Missing files.** If a line is in the JSON but the WAV isn't on disk, log it and pick another rather than failing. Not all 91 may be rendered at any given moment.

**Mid-conversation firing.** A line landing while someone is talking reads as a malfunction rather than a presence. There's a room mic in the plan — eventually the queue could hold a line until the room is quiet. Don't build that now, but don't design in a way that forecloses it.

---

## Not in scope

- The Bohica per-person tier. Structure exists in the JSON, no lines written, no detection mechanism chosen.
- Mood drift logic.
- Keyword spotting from the room mic.
- Any rendering or audio processing. That's `entity_render.py`, run offline on the laptop, results committed.

---

## Reference files

| File | Purpose |
|---|---|
| `entity-lines.json` | Line database, 91 entries |
| `entity_render.py` | Offline renderer + LEGION processing. Not used at runtime. |
| `entity_tts_test.py` | Single-line test with `--audition` |
| `warlock-table-entity-character-bible.md` | Character reference for writing new lines |
| `warlock-table-trigger-list.md` | Full trigger inventory and voice-eligibility flags |

To add lines later: append to `entity-lines.json`, run `entity_render.py` (it skips anything already rendered), commit the new WAVs.

To retune the voice: edit the LEGION block in `entity_render.py` and run `--reprocess`. Rebuilds all 91 from stored raws with no API calls.
