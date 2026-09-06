# Warlock Table — Entity Voice Specification

*The table occasionally says something. Specced and built 2026-09-05.*

Builds on [`voices/entity-voice-primer.md`](voices/entity-voice-primer.md),
which describes the intent and the assets. **This document does not repeat
it** — it records what the primer left open, what checking the assets and the
controller changed, and the decisions that follow.

---

## 1. Scope, restated because it governs everything

The Entity is **flavour audio**. It holds no state anything else reads, makes
no decisions, and affects nothing. Delete this subsystem and every other part
of the table behaves identically.

Two consequences that are not negotiable:

- **It never blocks or delays a table action.** Lights fire immediately; the
  voice is decided afterwards, on its own.
- **It never touches table state.** In particular it must not call
  `_supersede()`, which cancels scheduled reverts (`controller.py:478`).

---

## 2. What checking the assets found

91 lines ↔ 91 WAVs, no orphans in either direction. 44.1 kHz mono 16-bit,
34.7 MB total, `_raw` complete so `--reprocess` works.

| Primer says | Actually |
|---|---|
| durations "roughly 1.5 to 4 seconds" | **1.80 – 7.85 s, median 4.19** |
| `audio_file` field gives the path | says `.mp3`, files are `.wav` — derive from `id` |
| `warlock-table-trigger-list.md` is the trigger reference | **not present**; the mapping below was derived from the controller instead |

The long tail matters twice: cooldown must start when a line *ends*, and a
7.9 s line is a long time to hold the effect channel over a scene change.

**The audio must not go in git.** `*.wav` and `*.mp3` are already ignored, so
this is already correct — the WAVs reach the Pi by rsync like the rest of the
audio, and only the JSON and the tools commit.

---

## 3. The trigger map

The primer's `_open_items` asks for exactly this cross-check: *"The nine
Person card names and twelve Aura card names used here are assumed.
Cross-check against the tarot spec and rename trigger ids if they differ."*

Done. **All 91 lines can fire.** Three of the mappings were not obvious:

| Trigger | Lines | Fires on |
|---|---|---|
| `mana_white` | 2 | `apply_scene("plains")` |
| `mana_blue` | 2 | `apply_scene("island")` |
| `mana_black` | 2 | `apply_scene("swamp")` |
| `mana_red` | 2 | `apply_scene("mountain")` |
| `mana_green` | 2 | `apply_scene("forest")` |
| `panel_combat_on` | 3 | `run_initiative` |
| `panel_combat_off` | 2 | `stop_initiative` |
| `tarot_wheel_of_fortune` | 4 | `roll_table("wheel_outcomes")` |
| `tarot_boon_any` | 16 | `play_interruption` on the four aces |
| `tarot_person_<card>` | 18 | `play_interruption` on that card |
| `tarot_aura_any_activate` | 6 | `play_interruption` on one of the twelve auras |
| `tarot_aura_any_expire` | 2 | an aura's revert timer firing |
| `panel_scene_set` | 3 | `apply_scene` on anything *not* one of the five lands |
| `panel_map_change` | 3 | `set_background` |
| `panel_appletv_handoff` | 3 | `handoff_display` |
| `system_startup` | 5 | service start |
| `system_shutdown` | 3 | clean shutdown |
| `system_idle` | 3 | `go_idle` |
| `dice_roll` | 2 | a roll landing |
| `any_voice_eligible` | 8 | last-resort pool, never fired directly |

**The mana colours are the scene cards.** Confirmed by the lines themselves —
"something old just woke up under the wood" (swamp), "it goes quiet and deep"
(island), "everything gets loud" (mountain), "something's growing" (forest),
"order, pressed flat against me" (plains). Standard Magic lands, and the table
happens to have exactly those five scenes.

`panel_scene_set` is therefore the *generic* scene pool and only fires when
the scene is not one of the five — idle, or anything added later. The specific
card gets the specific line.

**Wheel of Fortune is a random table, not an interruption.** That is why it is
the 26th card with no pattern: `migrate_tarot.py` builds
`random_tables["wheel_outcomes"]` holding the twelve auras and points the card
at it, so a tap calls `roll_table` and that fires an aura. It has no look of
its own; it borrows one.

---

## 4. One gesture, one decision

The Wheel exposes a problem the primer does not cover.

**A single tap can produce several actions.** Tapping the Wheel fires
`roll_table`, which fires `play_interruption` on an aura, which sets lights,
audio and a background. Treating each as a trigger would have the Entity
consider speaking three or four times for one gesture — and occasionally
speak, then speak again.

So the unit is the **gesture**, not the action:

- The first voice-eligible trigger in a gesture is the one considered.
- Everything else in that gesture is suppressed, whether or not the first one
  spoke.
- A gesture ends when nothing has arrived for a short settle time (~1 s), or
  the next input begins.

This is also why the Wheel gets its own line rather than the aura's: the roll
is what the person did; the aura is what the table did about it.

---

## 5. Deciding whether to speak

Per the primer, all of this is config, not code, because it gets tuned by ear.

```json
"entity_voice": {
  "enabled": true,
  "lines_json": "/var/lib/warlocktable/voices/entity-lines.json",
  "audio_dir":  "/var/lib/warlocktable/voices/audio/entity",
  "global_cooldown_s": 180,
  "default_probability": 0.12,
  "chattiness": 0.5,
  "no_repeat_window": 8,
  "gesture_settle_s": 1.0,
  "mood": null,
  "triggers": {
    "system_startup":        { "probability": 1.0, "delay_s": 1.5 },
    "system_shutdown":       { "probability": 1.0 },
    "tarot_wheel_of_fortune":{ "probability": 0.35, "delay_s": 0.8 },
    "panel_appletv_handoff": { "probability": 0.25 },
    "panel_soundscape":      { "probability": 0.0 }
  }
}
```

Order of checks, cheapest first:

1. `enabled`, and the trigger is not already suppressed by its gesture.
2. Not currently speaking. **A line in flight drops the new trigger** rather
   than queueing it — a stale reaction is worse than silence.
3. Global cooldown expired, measured from when the last line **finished**.
4. `random() < probability` for this trigger, else the default.

`system_startup` at 1.0 is deliberate: it establishes the character once, at a
moment with no repetition risk, and there is no cooldown to respect yet.

**Never voice-eligible**, per the primer: soundscape changes, mood toggles,
volume, brightness, private phone messages, whispers, signals. These are set
to probability 0 in shipped config *and* excluded in code — a config typo
should not make the table start narrating the volume slider.

---

## 6. Choosing the line

1. Lines whose `trigger` matches exactly.
2. Failing that, lines in the same `trigger_category`.
3. Failing that, the `general` category (`any_voice_eligible`).
4. Filter by `mood` if one is set. **If that empties the pool, drop the mood
   filter rather than staying silent** — the primer is explicit, and silence
   is a worse failure than a slightly off-mood line.
5. Exclude anything in the recently-played deque (`no_repeat_window`, per
   pool). If that empties the pool, clear the deque and take any.
6. Exclude lines whose WAV is missing, and log it once per file.

Mood is a filter value that something else sets. **No drift logic** — the
primer defers it and so does this.

`mask_slip` (7 lines) is carried through but not used for selection yet. It
marks lines where the character breaks; if it ever gets a rule, it will be
rarity, not a filter.

---

## 7. Playback

**Not through `speak_line`.** That action exists (`controller.py:692`) and
already routes through the effect channel with ducking, which answers the
primer's open question about mixing — but it is the wrong vehicle here:

- it calls `_supersede()`, which cancels scheduled reverts (§1);
- `play_effect` resolves a **track name** out of `audio_paths`, so putting 91
  voice lines there would add all of them to `available_tracks()` — the
  panel's effect picker and the scene editor would fill with the table
  muttering.

So the Entity keeps its own directory and its own resolution, and plays
through the audio device's effect channel directly, with `duck=True`. Same
ducking, same layering over the soundscape, no pollution of the library.

- **Preload all 91** at startup. 34.7 MB, and the primer's warning about
  first-play latency reading as hesitation is right.
- **Per-trigger `delay_s`**, so a line lands a beat after the visual rather
  than fighting a comet sweep for the same instant.
- Track the real duration so cooldown starts at the end.
- On any failure, log and carry on. Never raise into the controller.

---

## 7a. The two controls that live in Settings

Both of these are ordinary table settings, sitting in the Settings panel
beside Sound, persisted through `configstore` the same way the master volume
is — validated, committed under a lock, rolled back on failure.

### The off switch

A plain toggle. It matters more than it looks: a table that has started
talking during a serious scene needs one control, reachable immediately,
that does not require finding a config file. Off means the decision path
returns before anything else happens, and a line already playing is allowed
to finish rather than being cut mid-word.

### Chattiness — and why it must move two things

One slider, from silent to every-single-time, so rates can be run high for
testing and dropped to something liveable for play.

**THE TRAP: probability and cooldown are two gates in series.** A slider that
only scaled the probability would appear broken at the top end — set every
trigger to 1.0 and a 180-second global cooldown still allows at most one line
every three minutes. The tester turns the dial to maximum, hears a line, then
silence, and concludes the control does nothing.

So chattiness moves both, with a meaningful midpoint:

| Slider | Probability | Cooldown |
|---|---|---|
| 0 | 0 — silent | — |
| 50 | exactly the configured per-trigger rates | as configured |
| 100 | 1.0 — every eligible trigger | 0 |

Between 0 and 50 the configured probability is scaled down linearly. Between
50 and 100 it is interpolated towards 1.0 while the cooldown is interpolated
towards zero. Written out, for `p` the trigger's configured probability and
`c` the slider as 0.0–1.0:

```
c <= 0.5:   probability = p * (c / 0.5)
            cooldown    = configured
c >  0.5:   probability = p + (1 - p) * ((c - 0.5) / 0.5)
            cooldown    = configured * (1 - (c - 0.5) / 0.5)
```

Default is **50** — the rates in config are the intended ones, and the slider
exists to depart from them temporarily, not to replace them.

The two controls stay separate rather than folding "off" into chattiness 0.
They mean different things: chattiness 0 is a rate, and someone will slide it
back up by accident. Off is a decision.

Per-trigger rates are still edited in config. This slider scales all of them
together; it does not replace the ability to say that startup always speaks
and soundscape changes never do.

---

## 8. Manual firing

A separate code path, bypassing probability, cooldown and gesture suppression
entirely — the primer is right that this is essential for tuning and useful
mid-session.

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/voice` | State: enabled, mood, cooldown remaining, last line, counts per pool |
| `GET` | `/api/voice/lines` | The database, for a picker |
| `POST` | `/api/voice/say` | Play one line by id, now |
| `POST` | `/api/voice/mood` | Set or clear the mood filter |
| `POST` | `/api/voice/enabled` | On/off, persisted |
| `POST` | `/api/voice/chattiness` | 0–100, persisted |

An off switch matters more than it looks. A table that has started talking
during a serious scene needs one control, reachable immediately.

---

## 9. Where it sits

```
warlock/entity/
    __init__.py     EntityVoice: on_trigger, say, mood, enabled
    lines.py        load and index entity-lines.json; pools and fallbacks
    picker.py       probability, cooldown, gesture suppression, no-repeat
    player.py       preload, delay, play through the effect channel
warlock/web/voice.py    the /api/voice/* endpoints
```

Changes to existing code, deliberately enumerated:

| File | Change |
|---|---|
| `warlock/controller.py` | Call one hook after an action completes. Nothing else. |
| `warlock/config.py` | The `entity_voice` block |
| `warlock/configstore.py` | `set_voice()`, shaped exactly like `set_audio()` |
| `warlock/web/static/*` | A Voice section in Settings: toggle and slider |
| `warlock/web/server.py` | Route `/api/voice/*` |
| `deploy/install.sh` | Create `voices/`, and rsync note |

`warlock/entity/` imports nothing from `controller.py`; the controller calls
*it*, passing a trigger id and never reading anything back. Same boundary as
`mapimport`, for the same reason.

---

## 10. Deliberately not now

- **Bohica per-person tier.** Structure exists in the JSON, no lines written.
- **Mood drift.** Mood is a value something sets.
- **Room-mic awareness.** The primer asks not to foreclose it: playback goes
  through one chokepoint, so "hold until the room is quiet" becomes a wait in
  that one place rather than a redesign.
- **Per-card aura lines.** Shared pool for now, per the JSON's own note.

---

## 10a. What the build found

**No-repeat needed two rules, not one.** The primer asks for "never the same
line twice in a row, and ideally not within the last N". A deque gives the
second. But when the deque exhausts a small pool it has to be cleared, and
clearing it loses the first -- on the `dice` pool, which has exactly two
lines, the same line came back-to-back within ten plays. Clearing now keeps
the just-played line excluded. Verified across 40 seeds x 40 plays on that
two-line pool: no repeats.

**The CLI had no gesture boundary.** Card taps go through `handle_card` and
panel presses through `/api/action`, both of which open a gesture. The
interactive CLI called controller methods directly, so it was the one route
that reached an action with no boundary. `_dispatch_command` now opens one.

**A device returning something odd could throw past the guard.** The duration
coercion sat just outside the `try` in `player._speak`, so a device returning
a non-number raised into the caller rather than being logged. Found by a test
helper that accidentally returned a dict. Now inside the try, where every
other device failure already was.

---

## 11. Open, and worth deciding by ear

1. **Rates.** Every number in §5 is a starting guess. They are in config
   precisely so tuning is not a code change — and the chattiness slider
   (§7a) exists so a tuning session does not need one either.
2. **Does the aura an expiring interruption reverts from speak?**
   `tarot_aura_any_expire` has 2 lines and the revert is not a gesture anyone
   made. Starting position: eligible, low probability, since an unprompted
   line when something ends is the most "presence"-like moment available.
3. **Startup on every boot?** Probability 1.0 means the table speaks whenever
   the service restarts, including a crash-restart mid-session. Possible
   refinement: only if uptime was long enough to be a real session start.
