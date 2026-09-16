# Pixels Dice — Research Report & Integration Specification

*Written 2026-09-15 on the `pixels-dice` branch, from the handover
`warlock-table-gpio-and-pixels-handover.md` (Task 2). Research done
from source: the published `@systemic-games/pixels-core-connect` 1.3.0 and
`react-native-pixels-connect` 1.3.1 npm packages, the GameWithPixels
`.github/doc/CommunicationsProtocol.md`, the `nat20` 0.1.0 source, and
PyPI/Debian metadata. Nothing below is inferred from a packet capture.*

**Status: research complete, decisions taken (§7), scanning verified on
hardware (§8). Steps 2 and 3 built 2026-09-16: the input module, the
config section, controller dispatch, roll log, status strip, Table
Check, `/api/dice`, `--dice` flag and the service unit change. **Deployed
as v0.5.0 on 2026-09-16 and verified on the table: a natural 20 fired
*The Sun*. Step 4 built 2026-09-16: the panel's Dice Management page — heard
dice, register with a seat, the ordered trigger table. Verified on the
laptop; awaiting the Pi.**

---

## 1. What the ecosystem ships today

| | Finding |
|---|---|
| Official SDKs | JavaScript/TypeScript (`pixels-web-connect`, `pixels-core-connect`), React Native, Unity, Swift, C++ for Windows. **Still no official Python SDK.** |
| Official `PythonConnect` repo | Carries an *"Out of date"* banner; built on `bluepy`, and says the advertisement format and messages have changed since. Points at `nat20`. |
| Firmware source (`DiceFirmware`) and JS source (`pixels-js`) | **No longer public** — both return 404 as of 2026-09-15. The npm packages built from `pixels-js` are still published and contain the compiled protocol, which is what this document is based on. The `.github` protocol doc is still public but describes the *legacy* UUIDs. |
| Latest JS SDK release | 1.3.x, **2024-11-22**. Nothing newer in ten months; the protocol described here is what current dice run. |

### `nat20` — evaluated and rejected

| Check | Result |
|---|---|
| Version / date | 0.1.0, **2023-09-22**. Last repo push 2024-01-08. 9 stars, 10 open issues. |
| Python | **`>=3.11`**. The Pi runs **3.9.2** (`deploy/README.md`). Uses `typing.Self` and `match` — not a metadata quirk, it genuinely will not import. |
| `bleak` pin | `>=0.20.2,<0.21` — a 2023 release. |
| Protocol | **Legacy.** Scans for service `6e400001-…`; current firmware advertises `a6b90001-…` (§2), so its scanner filter never sees a current die. Its roll-state enum stops at 4 and would raise on state 5 (`onFace`). Its `IAmADie` is the old fixed-length struct; current firmware sends a chunked one. |

**Verdict:** three independent blockers. Do not use it. It was a good
reference for one thing — its advertisement decoder matches the current
layout (§2.1), confirming that part of the protocol has not moved.

### Decision: write our own, and keep it small

The part of the protocol this table needs is tiny: parse a 13-byte
advertisement. The whole of §2 fits in about 150 lines of Python on top
of `bleak`, with no protocol library between us and the dice — which is
also the only way to be sure it tracks *Jon's* firmware, not a 2023
snapshot of it.

---

## 2. The protocol, as currently shipped

### 2.1 Advertisement — everything we need, with no connection

A Pixel broadcasts its state in every BLE advertisement. Confirmed
byte-for-byte against `getScannedPixel.ts` in `react-native-pixels-connect`
1.3.1:

```
Manufacturer data (company id 0xFFFF), 5 bytes:
    [0] LED count
    [1] design & colour     high nibble = die type, low nibble = colourway
    [2] roll state          see 2.3
    [3] face index          0-based, see 2.4
    [4] battery             bit 7 = charging, bits 0-6 = percent

Service data (under 0x180A), 8 bytes, little-endian:
    u32 pixel id            factory-unique
    u32 firmware build      UNIX timestamp
```

Plus the die's name (up to 13 chars, user-set in the app) and RSSI from
the standard advert fields.

**This is the whole integration.** Roll state and face-up arrive in the
broadcast; the Pi only has to *listen*. See §3 for why this beats
connecting.

Older firmware (pre-service-data) packed 7 bytes into manufacturer data
with no service data. The SDK still parses it; ours will detect and
refuse it with a message, because the answer is "update the die in the
Pixels app", not "support 2022 firmware".

### 2.2 Services and characteristics — only needed to *command* a die

| | Current firmware | Legacy |
|---|---|---|
| Service | `a6b90001-7a5a-43f2-a962-350c8edc9b5b` | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| Notify | `a6b90002-…` | `6e400001-…` (same as service) |
| Write | `a6b90003-…` | `6e400002-…` |

Messages are `[id byte][payload]`, little-endian. The ones that matter:

| Id | Message | Direction | Payload |
|---|---|---|---|
| 1 | WhoAreYou | → die | none |
| 2 | IAmADie | ← die | *chunked* in current firmware (version info, die info, name, settings, status); legacy was one fixed struct |
| 3 | RollState | ← die | `state u8, face_index u8` — sent on every state or face change |
| 23 | RequestRollState | → die | none; replied with RollState |
| 29 | Blink | → die | `count u8, duration_ms u16, colour u32 ARGB, face_mask u32, fade u8, loop u8` |
| 34 | BatteryLevel | ← die | `percent u8, state u8` |

Connection is **not in scope for the first build**. It is here so that
"make the die flash when the table reacts" is a known, bounded addition
later (Blink, id 29), not a research project.

### 2.3 Roll states — and the trap

Current firmware (`PixelRollState.ts`, 1.3.0):

| Value | State | Meaning |
|---|---|---|
| 0 | `unknown` | |
| 1 | **`rolled`** | **A roll just finished and the die is flat. This is the event.** |
| 2 | `handling` | picked up / in hand |
| 3 | `rolling` | in motion |
| 4 | `crooked` | came to rest, not flat |
| 5 | `onFace` | resting flat, but *not* as the result of a roll (set down, or at wake) |

The legacy enum was `0 unknown, 1 onFace, 2 handling, 3 rolling, 4
crooked`. So on current firmware **value 1 means a completed roll**, and
`onFace` moved to 5. A library written against the old table
(`nat20`, `PythonConnect`, the `.github` doc's readers) sees the right
number and the wrong word. **We fire on `rolled` (1) only.** Putting a
die down on the table (`onFace`, 5) is not a roll and must not trigger
anything — otherwise every fidget fires a scene.

### 2.4 Face index → face value

From `DiceUtils.faceFromIndex`:

| Die type (high nibble of byte 1) | Value |
|---|---|
| 1 d4, 2 d6, 3 d8, 6 d12, 7 d20, 8 d6 pipped, 9 d6 fudge | `index + 1` |
| 4 d10 | `index` (0–9) |
| 5 d00 | `index × 10` (00–90) |
| 0 unknown | `index` |

One firmware build (2023-11-17) had bad normals on d4/d6 and the SDK
special-cases it. We do not: the firmware timestamp is in the advert, so
the probe (§5) will *report* it, and if a die is on that build the fix is
the Pixels app's updater.

---

## 3. Approach: listen, don't connect

**Decision (proposed): the Pi runs one continuous BLE scan and derives
roll events from advertisements. It never connects to a die.**

| | Scanning | Connecting |
|---|---|---|
| Pairing / bonding | none | none, but BlueZ connection quirks on Pi 4 are well known |
| Number of dice | **unlimited** — a scan sees everything | BlueZ practical ceiling ~7 concurrent; the SDKs warn about it |
| Die goes to sleep | nothing to do — it advertises again when moved | disconnect → reconnect loop, per die |
| Phone app open at the same time | **fine** — scanning takes no connection | a die holds **one** connection; the phone and the Pi fight |
| Latency | advert interval — expect 100–500 ms; **to be measured** (§5) | tens of ms |
| Command the die (blink) | no | yes |
| Missed events | possible if adverts are dropped; mitigated below | reliable |

Scanning wins on every axis that matters for a table with several
players each holding their own dice, and loses only on "make the die
blink," which is a future nicety. If it turns out to matter for the GM's
own die, connecting to *one* die is a bounded addition on top of the
scanner, not a rewrite.

**Deduplication.** Adverts repeat, so the same `(pixel_id, rolled, face)`
arrives many times. A roll event is emitted on the **transition into
`rolled`** — the previous advert from that die was any other state. A
consequence: if the same face is rolled twice in a row *and* every
intermediate `handling`/`rolling` advert is dropped, the second roll is
missed. Adverts are frequent and rolling takes a second or more, so this
should be rare; §5 measures it. If it is not rare, the fallback is a
short "quiet period" heuristic or connecting to that die — decided on
data, not now.

**Raw HCI, not bleak — found at the table 2026-09-16.** The first probe
used `bleak`, which goes through bluetoothd's discovery API. On Bullseye
(BlueZ 5.55) that API delivered **one update per device per minute**
from a die being rolled continuously — 10 adverts in 406 s on a 57–64 s
clock, with none of the `handling`/`rolling` states in between — and the
`DuplicateData` filter changed nothing. `hcitool lescan --duplicates`,
which bypasses bluetoothd and drives the chip over a raw HCI socket,
streamed the same die many times a second. So the scanner does what
`hcitool` does, from Python's standard library: open the raw socket, set
scan parameters with duplicate filtering off, read LE Advertising Report
events. **No dependency at all.** The cost is `CAP_NET_RAW`: the probe
runs under `sudo`, and the service unit gets
`AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN`.

Observed at the same time: a die uses **two Bluetooth addresses** — a
slow tick at rest (name `Pixel…`) and a fast burst while handled (name
`PXL…`). Same pixel id in both; everything is keyed on the id.

---

## 4. Platform concerns — checked and to-be-checked

| Concern | Status |
|---|---|
| BlueZ on Bullseye | 5.55. Fine for active scan; **no passive scan** (needs 5.56). |
| `bleak` on Pi 4 / 3.9 | **Dropped.** Installs fine (1.1.1 from piwheels) but BlueZ 5.55's discovery API throttles adverts to one a minute — see §3. Raw HCI from the stdlib instead. |
| Onboard Bluetooth vs. anything running | Nothing on the Pi uses Bluetooth today (audio is 3.5 mm / HDMI; Govee is LAN; Pixelblaze is Wi-Fi). **But** the Pi 4's Wi-Fi and BT share one radio (CYW43455) with time-sliced coexistence. A permanent BLE scan can shave Wi-Fi throughput. **[Jon]**: is the Pi on Ethernet or Wi-Fi? On Ethernet this is a non-issue. On Wi-Fi the probe should be run alongside a panel session to see whether the iPad notices. |
| Range through the table housing | BLE at 0 dBm through wood and a few feet of air is normally fine; a metal enclosure or the TV chassis between the Pi and the dice would not be. **Measure RSSI** with the probe from each seat — it is in the advert for free, and the probe prints it. |
| Multiple dice | Scanning has no limit. The probe will be run with every die Jon owns at once. |
| Reconnection after sleep | Not applicable to scanning. A sleeping die stops advertising; moving it wakes it and the first `rolling`/`rolled` advert is the event. The one thing to measure is **wake-to-first-advert delay** — if a die that has been asleep takes two seconds to announce its first roll, that is a latency the GM will notice. |
| Battery | Percent and charging flag in every advert. Surfaced on the panel's status strip per die, like the existing subsystem health — cheap and useful ("your d20 is at 8%"). |
| Firmware compatibility | The probe prints each die's firmware timestamp and which service UUID it advertises. If a die is on legacy firmware the probe says *update it in the Pixels app*. |

---

## 5. Build plan — standalone first

Same pattern as the map tool and `tools/tag_probe.py`: prove the input on
its own, under a new filename, before the controller learns about it.

**Step 1 — `tools/dice_probe.py`.** No controller, no config. Scans and
prints one line per advert change:

```
14:02:11.482  Jon's d20   id=1a2b3c4d  d20  rolled   face=20  batt=87%  rssi=-61  fw=2024-09-03
```

Also reports: service UUID seen (current vs legacy), face value via §2.4,
wake-to-first-advert delay, and a running count of `rolled` transitions
so a repeat-face miss (§3) shows up as a count that fails to increment.
**This is the hardware verification** — run at the table, from each
seat, with every die, with the Pixels app open on a phone at the same
time.

**Step 2 — `warlock/inputs/dice.py`** *(built 2026-09-16)*. The real
module, shaped exactly like `warlock/inputs/nfc.py`: a thread that owns
the raw HCI scanner, a pure `RollTracker` that turns reports into roll
events (tracks per address, fills in the id from the scan response, fires
on the transition into `rolled`, folds a die's two addresses, ignores
`onFace`), and a callback per roll — the same shape as a card tap
arriving. `FakeDiceScanner` for the laptop. `python -m
warlock.inputs.dice` runs it standalone. `tests/test_dice.py` (16 cases,
stdlib `unittest`, `python -m unittest discover -s tests`) exercises the
decoder and tracker against the bytes captured at the table — the first
unit tests in the repo. `tools/dice_probe.py` is now a thin diagnostic
over the same code, so what decodes in the probe decodes in the service.

**Step 3 — controller integration** *(built 2026-09-16)*.
`Controller.handle_roll(event)` next to `handle_card`: logs every roll to
the **roll log (§3.11)** — under the bound player's seat, else under
`table` with the die's own name — then looks it up in the trigger table
(§6) and, on a match, fires the target through the same dispatch as a
card. No match: logged, nothing else. `Config` gained `dice_known`,
`dice_triggers` and `match_roll()`, with the threshold shapes refused by
name at load. `--dice` on `run_service.py`/`run_table.py` (the fake is
always built, so `dice d20 20` works at the laptop prompt); `dice=`
on the service status line; a **Dice** row in Table Check; `dice` in
`/api/status` and a read-only `/api/dice`. `dice-state.json` beside the
config remembers address → id so a die is identified from its first
packet after the first session. `warlocktable.service` grants
`CAP_NET_RAW CAP_NET_ADMIN`; `install.sh` adds `--dice` to a fresh
defaults file (an existing one must be edited by hand).

**Step 4 — panel** *(built 2026-09-16)*. Settings → **Dice
Management**: a *Heard* list of dice the scanner sees (register one by
tapping it, like an unregistered card), *Known Dice* with name, type and
**seat** (a dropdown of the table's zone colours, so a die's rolls land
on that player's phone), and the ordered *Triggers* table with ▲▼ to
reorder, since first match wins. Faces are typed as `20` or `18, 19, 20`;
the server refuses anything else. Every dropdown is built from what the
table has (§4.5). `ConfigStore` gained `list_dice`, `set_known_die`,
`delete_known_die` (blocked while a trigger names the die),
`set_dice_triggers` (whole ordered list) and `set_dice_enabled`; the
routes are `POST /api/dice/{enabled,known,triggers}` and
`DELETE /api/dice/known/<key>`. A **dice** lamp joined the status strip.
`tests/test_dice_store.py` covers the writes and the refusals.

Each step verified on hardware before the next.

---

## 6. Proposed config shape — for review **[Jon]**

Follows the existing `Card → target` model in §4.4 of the plan doc. A
roll is an input that resolves to a target, exactly like a tap.

```json
"dice": {
  "enabled": true,

  "known": {
    "1a2b3c4d": { "name": "Jon's d20",   "type": "d20", "seat": null },
    "9f8e7d6c": { "name": "Sarah's d20", "type": "d20", "seat": "red" }
  },

  "triggers": [
    { "die": "any",      "type": "d20", "face": 20,
      "target": { "type": "interruption", "name": "critical" } },

    { "die": "any",      "type": "d20", "face": 1,
      "target": { "type": "interruption", "name": "fumble" } },

    { "die": "1a2b3c4d", "face": [6, 12],
      "target": { "type": "random_table", "name": "omens" } },

    { "die": "any",      "type": "d6fudge",
      "target": { "type": "scene", "name": "fate" } }
  ]
}
```

**`known`** — dice the table has seen and named. `seat` is optional and
binds the die to a zone colour so its rolls land in the roll log under
that player, like a phone roll. Unknown dice still work: their rolls
match `"die": "any"` triggers and log under the die's advertised name.
The panel registers an unknown die the way it registers an unknown card
— roll it, it appears as *unassigned*, name it.

**`triggers`** — evaluated top to bottom, **first match fires**, so a
specific die's rule can sit above a general one. Every field except
`target` is optional and narrows the match:

| Field | Matches |
|---|---|
| `die` | a pixel id, or `"any"` (default) |
| `type` | `d4 d6 d8 d10 d00 d12 d20 d6pipped d6fudge`, or omitted for any |
| `face` | one value, or a list of values, or omitted for any |

**Deliberately absent, per the handover's scope rule:** no `min`/`max`,
no `>=`, no modifiers, no "success". A threshold is a target number, and
a target number is a game rule. `face: [18, 19, 20]` is a list of faces
the table reacts to; `face >= 18` would be the system deciding what a
good roll is. The list form is the line, and it is drawn there on
purpose.

**Every roll is logged whether or not it matches a trigger.** The value
is carried, shown, and forgotten. Nothing is summed or compared.

---

## 7. Decisions — resolved 2026-09-15

1. **Scanning, not connecting.** Approved. Connecting stays a bounded
   later addition for making a die blink, if ever.
2. **The Pi is on Wi-Fi.** So Bluetooth/Wi-Fi radio coexistence is a
   real question, not a hypothetical: the probe (§5) is run alongside an
   open panel session on the iPad, and the panel's responsiveness with
   and without the scan running is part of the hardware verification.
   If the scan hurts the panel, the options are a USB BLE dongle (its
   own radio, no coexistence) or moving the Pi to Ethernet — decided on
   measurement.
3. **Config shape (§6) approved** as proposed: first match wins, `face`
   is a value or a list and nothing else, `seat` binds a die to a player.
4. **An unmatched roll is logged only.** No generic reaction. A roll that
   the table reacts to means something because most rolls do not.

## 8. Measured at the table — 2026-09-16

One d20 (`Pixel03ef405d`, firmware 2024-11-07), the Pi inside the table
housing, service running, `tools/dice_probe.py` over raw HCI:

| | |
|---|---|
| Adverts heard | **107 in 35 s** — a packet every ~200 ms while the die is awake (`0.194 s` median gap) |
| Rolls | 5 of 5 detected, each as a clean `rolling → rolled` sequence |
| Latency | `rolled` arrives 0.2–0.6 s after the last `rolling` packet; the die's own settle time dominates, not the radio |
| Repeat face | Rolls #3 and #4 both landed 15 and were counted separately — the intermediate states were heard. **The repeat-face miss (§3) did not occur** |
| RSSI | −31 to −63 dBm at one seat, through the housing. Comfortable |
| Pixel id | Rides only in the scan response; arrived once, unprompted, 22 s in. State tracking does not wait for it (§2.1 note below) |
| Two addresses | `…:74` (`Pixel…`) carried everything in this run. `…:75` (`PXL…`) was seen earlier in `hcitool` during a burst; the module folds addresses by id when it can |

**Found and fixed on the way** — both now in the probe and in §2/§3:

1. bleak via BlueZ 5.55 delivers one update per device per minute. Raw
   HCI from the stdlib delivers the stream. No dependency.
2. **The advert does not carry the pixel id or the Pixels service UUID.**
   It carries flags, the `180a` UUID, the 5-byte manufacturer data and
   the name. The id, firmware and Pixels UUID ride in the *scan
   response*, which the chip requests only occasionally. So the module
   tracks state per Bluetooth address, recognises a die by the `180a`
   listing or the `Pixel`/`PXL` name plus the 5-byte layout, and fills
   in the id when heard. §2.1's "confirmed against the SDK" was right
   about the bytes and silent about which packet they are in.

**Still to measure, none blocking the module:**

- Wake-from-sleep latency — the die never slept during the runs.
- RSSI from each seat, and with the TV between die and Pi.
- Wi-Fi coexistence: the iPad panel with the scan running.
- Several dice at once — Jon has one; test when there are more.

## Sources

- Protocol doc (legacy UUIDs, still-accurate advert and message layout):
  `github.com/GameWithPixels/.github/blob/main/doc/CommunicationsProtocol.md`
- Current UUIDs, message ids, roll states: `@systemic-games/pixels-core-connect@1.3.0`
  (`PixelsBluetoothIds`, `DieMessages`, `PixelRollState`)
- Current advertisement decoder: `@systemic-games/react-native-pixels-connect@1.3.1`
  (`src/getScannedPixel.ts`)
- Face mapping and die types: `@systemic-games/pixels-core-animation` (`DiceUtils`, `PixelDieType`)
- `nat20`: PyPI metadata and `github.com/AstraLuma/nat20` (`trunk`)
- `bleak`: PyPI release metadata; BlueZ: `packages.debian.org/bullseye/bluez`
