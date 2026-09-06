"""Turning what the table just did into a trigger id the line database knows.

The line database was written against its own vocabulary (`mana_black`,
`panel_combat_on`, `tarot_person_hermit`) and the controller has another
(`apply_scene("swamp")`, `run_initiative`, `play_interruption("the_hermit")`).
This module is the whole of the bridge, kept in one file so the mapping can be
read and corrected in one place.

Derived by cross-checking the database against the controller, because
`warlock-table-trigger-list.md` -- the reference the JSON names -- is not in
the repo. See entity-voice-specification.md section 3.
"""

from __future__ import annotations

from typing import Dict, Optional

# THE MANA COLOURS ARE THE SCENE CARDS. Magic's five lands, and the table
# happens to have exactly those five scenes. Confirmed by the lines
# themselves: "something old just woke up under the wood" (swamp), "it goes
# quiet and deep" (island), "everything gets loud" (mountain), "something's
# growing" (forest), "order, pressed flat against me" (plains).
SCENE_TRIGGERS: Dict[str, str] = {
    "plains": "mana_white",
    "island": "mana_blue",
    "swamp": "mana_black",
    "mountain": "mana_red",
    "forest": "mana_green",
}

# The four aces. Their patterns are the Boon-* family.
BOONS = frozenset({
    "ace_of_cups", "ace_of_pentacles", "ace_of_swords", "ace_of_wands",
})

# The twelve auras -- the pool the Wheel of Fortune draws from, which is
# also exactly the Aura-* pattern family.
AURAS = frozenset({
    "the_sun", "the_moon", "the_star", "temperance", "strength", "justice",
    "judgement", "the_devil", "the_tower", "death", "the_world",
    "the_chariot",
})

# The nine Person cards. The database calls two of them "person" that the
# lighting calls auras (justice, death) -- that is the line author's grouping,
# not the table's, and it does not need reconciling: these ids have their own
# written lines, so they win before any category fallback is reached.
PERSON_TRIGGERS: Dict[str, str] = {
    "the_magician": "tarot_person_magician",
    "the_high_priestess": "tarot_person_high_priestess",
    "the_empress": "tarot_person_empress",
    "the_emperor": "tarot_person_emperor",
    "the_hierophant": "tarot_person_hierophant",
    "the_hermit": "tarot_person_hermit",
    "justice": "tarot_person_justice",
    "the_hanged_man": "tarot_person_hanged_man",
    "death": "tarot_person_death",
}

# WHEEL OF FORTUNE IS A RANDOM TABLE, not an interruption -- which is why it
# is the 26th card with no pattern of its own. migrate_tarot.py builds
# random_tables["wheel_outcomes"] holding the twelve auras and points the card
# at it, so a tap rolls and fires whichever aura came up. It has no look; it
# borrows one.
WHEEL_TABLE = "wheel_outcomes"


def for_scene(scene_name: str) -> str:
    """A scene was applied.

    The five lands get their own characterful line. Anything else -- idle, or
    a scene added later -- falls to the generic panel pool, which is what
    those three `panel_scene_set` lines are for.
    """
    return SCENE_TRIGGERS.get((scene_name or "").lower(), "panel_scene_set")


def for_interruption(name: str) -> str:
    """A card fired. Person cards are specific; boons and auras share pools."""
    key = (name or "").lower()
    if key in PERSON_TRIGGERS:
        return PERSON_TRIGGERS[key]
    if key in BOONS:
        return "tarot_boon_any"
    if key in AURAS:
        return "tarot_aura_any_activate"
    # An unrecognised card still gets to speak, from the general pool. A new
    # card should not be silent just because nobody has written for it yet.
    return "any_voice_eligible"


def for_table(table_name: str) -> str:
    """A random table was rolled."""
    if (table_name or "").lower() == WHEEL_TABLE:
        return "tarot_wheel_of_fortune"
    return "any_voice_eligible"


def for_expiry() -> str:
    """An interruption's revert timer fired and the table went back.

    Nobody made this gesture, which is exactly why it is worth having: an
    unprompted line as something ends is the most presence-like moment the
    Entity gets.
    """
    return "tarot_aura_any_expire"
