# Warlock Table — Interruption Card System

This document explains the tarot "interruption" card system for the Warlock Table, in plain language, so it can be implemented in the central controller's action/scene config. It covers the full taxonomy, how each subtype should behave, and the specific design for every card. A companion file, `warlock-table-interruption-cards.json`, contains the same information as structured data — treat this markdown as the source of truth for *intent*, and the JSON as a starting-point draft for *implementation*.

---

## 1. The taxonomy

The table's NFC card system has two top-level categories:

- **Scene cards** — the 5 Magic: The Gathering mana cards (White/Blue/Black/Red/Green). These set the environment/mood of the table and are already implemented (see the `magic tarot` reference folder). **Not covered in this document.**
- **Interruption cards** — all 26 tarot cards (the 22 Major Arcana + the 4 Aces). These are one-off or timed events that interrupt/layer onto whatever the table is currently doing.

Interruption cards split into four subtypes:

| Subtype | Cards | Count |
|---|---|---|
| Random Table | Wheel of Fortune | 1 |
| Boon | Ace of Swords, Ace of Cups, Ace of Wands, Ace of Pentacles | 4 |
| Person | Magician, Emperor, Fool, Empress, High Priestess, Lovers, Hermit, Hanged Man, Hierophant | 9 |
| Aura | Sun, Moon, Star, Temperance, Strength, Justice, Judgement, Devil, Tower, Death, World, Chariot | 12 |

That's 1 + 4 + 9 + 12 = 26, the full set of tarot cards currently RFID-tagged.

---

## 2. Subtype behaviors

### 2.1 Boon

A Boon card marks the moment the party **receives or uses a boon**. The actual narrative meaning ("what kind of boon") is entirely up to the GM in the moment — the table doesn't try to encode suit-specific meaning. It's purely a "something notable just happened" cue.

- **Trigger type:** one-time announcement. Fires, plays out, then the table returns to whatever it was doing before.
- **Light behavior:** a single sparkle/comet races once around the full LED perimeter loop (reuse the existing path-builder / ghost-chase logic — same one continuous lap), then blooms into a full-ring flash in the suit's color, and fades out.
- **Suit colors** (the only thing that varies between the four Aces):
  - Ace of Swords → white/silver
  - Ace of Cups → blue
  - Ace of Wands → orange/red
  - Ace of Pentacles → gold
- **Audio:** the same placeholder chime for all four. No suit-specific sound yet — that's a future refinement, not required now.

### 2.2 Person

A Person card announces that a **specific character/NPC has entered the scene**. Each of the 9 cards has its own distinct light signature (color + motion) baked in, independent of which NPC it ends up representing in a given campaign — the visual identity belongs to the card, not the NPC.

- **Trigger type:** one-time announcement only. It is **not** a persistent "this character is present" state — no ongoing light treatment. Flash/cue plays, then the table returns to normal. (We deliberately chose this over a persistent-presence option to keep things simple.)
- **NPC binding:** each card has an `npc_binding` field that starts empty/null. This is what the GM fills in later through the card-management UI — e.g. "The Hierophant = Aunt Vex the innkeeper" — for a specific campaign. The light/audio definition for the card itself never changes based on this binding.
- **The 9 signatures:**

| Card | Color | Motion |
|---|---|---|
| The Magician | Crimson red | Sharp double-flash — a "summoning" snap |
| The Emperor | Deep red-orange | Slow solid fill rising bottom→top, then holds — authority, weight |
| The Fool | Bright yellow-white | Erratic, playful sparkle skittering around the loop |
| The Empress | Green | Slow breathing glow (fade in/out) — organic |
| The High Priestess | Deep blue-silver | Slow shimmering ripple wave |
| The Lovers | Warm pink-gold | Two dots travel from opposite sides of the loop, meet in the middle, flash |
| The Hermit | Pale amber | A single dim point at one spot slowly brightens and holds (a lantern being lit) — **not** a full-loop effect, deliberately localized |
| The Hanged Man | Cool blue-violet | Same wave motion as normal, but reversed direction |
| The Hierophant | Deep purple-red | Three steady ceremonial pulses, bell-like |

- **Audio:** a placeholder clip per card, one to be recorded/sourced for each later.

### 2.3 Aura

An Aura card **modifies the ongoing scene** — it's a temporary flourish layered on top of whatever the table is currently doing (lighting, and eventually screen/audio), rather than replacing it.

- **Trigger type:** timed flourish. Plays for a fixed duration, then automatically fades back to whatever the base scene was. It is **not** persistent — it doesn't need to be manually cleared.
- **Default duration:** 60 seconds for all 12 cards (a single shared default, no per-card override for now — keep it simple until we have reason to differentiate).
- **The 12 overlays:**

| Card | Light overlay | Audio layer |
|---|---|---|
| The Sun | Warm golden glow, slow brighten and hold | Triumphant swell |
| The Moon | Cool blue dim wash, slow pulse | Distant eerie howl |
| The Star | Soft white/blue twinkle sparkles scattered around the loop | Gentle ambient chime |
| Temperance | Blue-green slow wave, calm | Soft water/harp tone |
| Strength | Warm orange steady glow, slow heartbeat pulse | Low resonant hum |
| Justice | White/silver even pulse, metronomic | Scale-tick chime |
| Judgement | Bright white, rising crescendo | Rising horn/trumpet |
| The Devil | Dim ember-red flicker | Flame crackle + impish laughter |
| The Tower | Violent white strobe, sharp and short-lived (still within the 60s) | Cracking/thunder crash |
| Death | Deep black-purple dim wash, slow fade down | Low ominous tone |
| The World | Full-spectrum slow color cycle, triumphant | Orchestral swell |
| The Chariot | Fast light streaks racing around the perimeter | Galloping drums |

- **Audio:** placeholder clip per card, to be sourced later — the descriptions above are the creative direction for that sourcing.

### 2.4 Random Table

Currently there's only one Random Table card: **Wheel of Fortune**.

- **Old behavior (being replaced):** pulled a random *scene*.
- **New behavior:** pulls a **random Aura card** and fires that card's effect exactly as if it had been tapped directly — same light overlay, same audio, same 60-second duration and auto-fade.
- **Selection method:** pure uniform random across all 12 Aura cards. Repeats are allowed (no "avoid repeating the last one drawn" logic, no weighting toward certain cards). Keep it simple — this can be revisited later if it feels repetitive in play.

---

## 3. Data shape

The companion JSON file (`warlock-table-interruption-cards.json`) has one entry per card, structured like this:

**Boon example:**
```json
{
  "id": "ace_of_swords",
  "display_name": "Ace of Swords",
  "category": "interruption",
  "subtype": "boon",
  "suit": "swords",
  "effects": {
    "light": { "pattern": "boon_comet_flash", "suit_color": "#E8E8E8" },
    "audio": { "clip": "boon_chime_placeholder.wav" }
  }
}
```

**Person example:**
```json
{
  "id": "the_hierophant",
  "display_name": "The Hierophant",
  "category": "interruption",
  "subtype": "person",
  "npc_binding": null,
  "effects": {
    "light": { "pattern": "triple_pulse", "color": "#5C2A6E" },
    "audio": { "clip": "person_hierophant_placeholder.wav" }
  }
}
```

**Aura example:**
```json
{
  "id": "the_devil",
  "display_name": "The Devil",
  "category": "interruption",
  "subtype": "aura",
  "duration_seconds": 60,
  "effects": {
    "light": { "pattern": "ember_flicker", "color": "#B5451B" },
    "audio": { "clip": "aura_devil_flame_laughter_placeholder.wav" }
  }
}
```

**Random Table example:**
```json
{
  "id": "wheel_of_fortune",
  "display_name": "Wheel of Fortune",
  "category": "interruption",
  "subtype": "random_table",
  "table": {
    "target_subtype": "aura",
    "selection": "uniform_random",
    "allow_repeats": true,
    "pool": ["the_sun", "the_moon", "the_star", "temperance", "strength", "justice", "judgement", "the_devil", "the_tower", "death", "the_world", "the_chariot"]
  }
}
```

---

## 4. What's still open (for Claude Code / future passes)

- **Pattern implementations.** The `pattern` names above (`boon_comet_flash`, `triple_pulse`, `ember_flicker`, etc.) are references, not code. Each one still needs an actual Pixelblaze/light-layer implementation. The perimeter path-building block from `warlock-table-led-reference.md` (the `pathPos[]` / `pathLen` logic) should be the foundation for any pattern that travels around the loop.
- **Audio assets.** Every clip referenced is a placeholder filename. Real audio (chimes, character stings, ambient loops) needs to be sourced or recorded and dropped into whatever path the placeholders point to.
- **NPC binding UI.** The `npc_binding` field on Person cards needs an actual editor in the card-management interface — this doc only defines the field and its default (null/empty).
- **Layering mechanics.** Aura cards are described as "layering on top of" the current scene — the controller needs a real mechanism for combining a temporary overlay pattern with whatever base pattern is already running, and for cleanly restoring the base pattern when the 60s expires. This document specifies the *intent*; the layering implementation itself is an open design/engineering question.
- **Scene cards** (5 MTG mana cards) are out of scope here — see the `magic tarot` reference folder for their current implementation.
