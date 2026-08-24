/* Preset dice rolls, grouped by system.
 *
 * WHY A SHARED FILE
 *
 * The GM panel and the player page are separate documents with separate
 * scripts, and the numeric pad is already duplicated between them. A
 * second copy of THIS would be worse: the pad is a fixed piece of
 * furniture, whereas these lists are the part somebody will actually want
 * to edit, and two lists that drift is how a player ends up with a preset
 * the GM does not have. One file, loaded by both.
 *
 * WHAT EARNS A BUTTON
 *
 * Only rolls common enough in that system that punching the combination in
 * is busywork. Not every legal roll -- a bar that lists everything is a
 * keypad with extra steps, and the keypad is right there. Damage dice for
 * a specific weapon do not belong here; the roll everyone at the table
 * makes twenty times a session does.
 *
 * SYSTEM-AGNOSTIC STILL HOLDS. There are no modifiers here and no
 * arithmetic: every entry is a count and a die, exactly what
 * controller.roll() accepts. A preset named "Fireball" would be this
 * table taking a position on what game you are playing; "8d6" is just a
 * roll that happens to come up a lot.
 */

const DICE_PRESETS = [
  {
    id: "d20",
    name: "d20",
    note: "D&D, Pathfinder",
    rolls: [
      { n: 1,  d: 20 },
      // Advantage and disadvantage are the same two dice; which one you
      // wanted is a decision at the table, not something the table needs
      // to know. It rolls the pair and shows both -- see the individual
      // dice in the roll label.
      { n: 2,  d: 20 },
      { n: 1,  d: 4  },
      { n: 1,  d: 6  },
      { n: 2,  d: 6  },
      { n: 1,  d: 8  },
      { n: 1,  d: 10 },
      { n: 1,  d: 12 },
      // Rolling up a characteristic.
      { n: 4,  d: 6  },
    ],
  },
  {
    id: "wod",
    name: "World of Darkness",
    note: "d10 pools",
    rolls: [
      { n: 2,  d: 10 },
      { n: 3,  d: 10 },
      { n: 4,  d: 10 },
      { n: 5,  d: 10 },
      { n: 6,  d: 10 },
      { n: 7,  d: 10 },
      { n: 8,  d: 10 },
      { n: 9,  d: 10 },
      { n: 10, d: 10 },
    ],
  },
  {
    id: "brp",
    name: "BRP",
    note: "Call of Cthulhu, RuneQuest",
    rolls: [
      // NO PERCENTILE HERE, AND THAT IS A GAP RATHER THAN A CHOICE.
      // BRP's whole resolution mechanic is roll-under on 1d100, and this
      // table's dice set deliberately stops at d20 -- the d100 and the
      // percentile pair were left out on purpose when the roller was
      // built. Everything below is a real BRP roll; the one everybody
      // makes most is missing until d100 is allowed.
      { n: 3,  d: 6  },   // characteristics
      { n: 2,  d: 6  },
      { n: 1,  d: 4  },
      { n: 1,  d: 6  },
      { n: 1,  d: 8  },
      { n: 1,  d: 10 },
      { n: 2,  d: 10 },
      { n: 1,  d: 20 },
    ],
  },
];

/* Build the preset bar into `host`.
 *
 * `onRoll(count, sides)` fires the roll; the caller owns that because the
 * GM and a player post to different endpoints as different people.
 *
 * `storeKey` remembers which panel you were last on, per device. A GM who
 * runs one system should not page past two others every session, and that
 * is a view preference rather than a fact about the table -- the same
 * argument as the player bar pin.
 */
function buildPresetBar(host, onRoll, storeKey) {
  if (!host) return;
  let at = 0;
  try {
    const saved = parseInt(localStorage.getItem(storeKey) || "0", 10);
    if (saved >= 0 && saved < DICE_PRESETS.length) at = saved;
  } catch (e) { /* private mode, or no storage - the default is fine */ }

  const prev = document.createElement("button");
  prev.className = "preset-arrow";
  prev.type = "button";
  prev.textContent = "‹";
  prev.setAttribute("aria-label", "Previous system");

  const next = document.createElement("button");
  next.className = "preset-arrow";
  next.type = "button";
  next.textContent = "›";
  next.setAttribute("aria-label", "Next system");

  const label = document.createElement("div");
  label.className = "preset-name";

  const rolls = document.createElement("div");
  rolls.className = "preset-rolls";

  const draw = () => {
    const set = DICE_PRESETS[at];
    label.textContent = set.name;
    label.title = set.note || "";
    rolls.innerHTML = "";
    set.rolls.forEach(r => {
      const b = document.createElement("button");
      b.className = "preset";
      b.type = "button";
      b.textContent = (r.n > 1 ? r.n : "") + "d" + r.d;
      b.addEventListener("click", () => onRoll(r.n, r.d));
      rolls.append(b);
    });
    try { localStorage.setItem(storeKey, String(at)); } catch (e) {}
  };

  // Wrapping rather than disabling at the ends: three panels is few enough
  // that going round is quicker than backtracking, and a dead arrow in a
  // dim room reads as broken rather than as "you are at the end".
  const step = (by) => {
    at = (at + by + DICE_PRESETS.length) % DICE_PRESETS.length;
    draw();
  };
  prev.addEventListener("click", () => step(-1));
  next.addEventListener("click", () => step(1));

  host.innerHTML = "";
  const head = document.createElement("div");
  head.className = "preset-head";
  head.append(prev, label, next);
  host.append(head, rolls);
  draw();
}
