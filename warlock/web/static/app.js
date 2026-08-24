/* Warlock Table operator panel.
 *
 * Deliberately plain JS, no framework and no build step. The panel is served
 * off the Pi and edited over SSH; a toolchain would be one more thing to
 * install on ARM and one more thing to break.
 */

const $  = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls)  n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

let currentScene = null;
let failures = 0;

/* ---------- transport ---------- */

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ cache: "no-store" }, opts));
  if (!res.ok) {
    let msg = res.status + " " + res.statusText;
    try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

function showError(msg) {
  const bar = $("#footer");
  $("#err").textContent = msg || "";
  // The bar is hidden when there is nothing to say, so an empty strip does
  // not sit under every panel claiming space it is not using.
  bar.hidden = !msg;
  if (msg) setTimeout(() => {
    if ($("#err").textContent === msg) {
      $("#err").textContent = "";
      bar.hidden = true;
    }
  }, 6000);
}

/* ---------- firing actions ---------- */

async function fire(action, params, btn) {
  if (btn) btn.classList.add("busy");
  try {
    const out = await api("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, params: params || {} })
    });
    // The POST returns fresh status, so the strip updates immediately
    // rather than waiting for the next poll.
    if (out.status) render(out.status);
    showError("");
  } catch (e) {
    showError(e.message);
  } finally {
    if (btn) btn.classList.remove("busy");
  }
}

/* ---------- rendering ---------- */

// The subsystem row, in SETTINGS rather than the header. `state` is one of
// ok / bad / absent; the lamp carries the colour and the row carries the
// label. A failure BLINKS as well as going red, because roughly one man in
// twelve cannot separate red from green and a second channel costs nothing.
const LAMP_HUE = { ok: 132, bad: 4, absent: 44 };

function chip(name, state) {
  const row = $(`.sys[data-sys="${name}"]`);
  if (!row) return;
  row.className = "sys " + state;
  const lamp = row.querySelector(".lamp");
  if (!lamp) return;
  lamp.style.setProperty("--hue", LAMP_HUE[state] || 44);
  // Absent is a lamp that never came on, which is a different statement
  // from one that went out -- and it is the honest one for a subsystem the
  // table was started without.
  lamp.style.setProperty("--lit", state === "absent" ? 0 : 1);
  lamp.classList.toggle("blink", state === "bad");
}

function render(s) {
  document.body.classList.remove("offline");
  failures = 0;

  const sub = s.subsystems || {};
  chip("lights",  sub.lights  ? "ok" : "bad");
  chip("audio",   sub.audio   ? "ok" : "bad");
  chip("display", sub.display ? "ok" : "bad");
  // Govee accent lighting (plan doc 3.13). Absent rather than broken when
  // the strips were never configured -- the table runs fine without them.
  if (sub.govee === undefined) chip("room", "absent");
  else chip("room", sub.govee ? "ok" : "bad");

  // NFC is a separate input, not a controller subsystem - and it is absent
  // rather than broken when the service runs without --nfc.
  if (s.nfc) chip("nfc", s.nfc.healthy ? "ok" : "bad");
  else       chip("nfc", "absent");

  currentScene = s.scene;
  const sceneLine = $("#scene-now");
  sceneLine.innerHTML = "";
  sceneLine.append("scene: ");
  sceneLine.append(el("b", null, s.scene || "—"));
  if (s.nfc && typeof s.nfc.taps === "number") {
    sceneLine.append(`   ·   ${s.nfc.taps} tap${s.nfc.taps === 1 ? "" : "s"}`);
  }
  if (s.lights && s.lights.effective_pct != null) {
    sceneLine.append(`   ·   ${s.lights.effective_pct}% brightness`);
  }

  // Highlight whichever scene button is live.
  document.querySelectorAll("#scenes button").forEach(b => {
    b.classList.toggle("active", b.dataset.name === currentScene);
  });

  renderPlayerBar(s.signals || []);
  refreshWhispers();
  refreshRolls();

  // Table screen: reflect the device's own state rather than what we last
  // asked for, so the controls cannot drift out of sync with reality.
  const dd = s.display_device;
  if (dd) {
    $("#display-section").style.display = "";
    renderOverlayButtons(dd);
    // Lit while it is the thing on screen, so the GM can see at a glance
    // whether the join code is up without looking over their shoulder.
    $("#show-status").classList.toggle("active", dd.background === STATUS_SCREEN);
    $("#display-note").textContent = dd.healthy
      ? `${dd.images} background${dd.images === 1 ? "" : "s"}` +
        (dd.background ? ` · showing ${dd.background}` : "")
      : (dd.error || "display unavailable");
  } else {
    // No real display attached - hide the section rather than show
    // controls that silently do nothing.
    $("#display-section").style.display = "none";
  }

  if (s.version) $("#version").textContent = s.version;
}

function markOffline() {
  document.body.classList.add("offline");
  $("#scene-now").innerHTML = "";
  $("#scene-now").append("cannot reach the table");
}

/* ---------- build the UI from the controller's own vocabulary ---------- */

function addButtons(container, names, action, paramName, kindLabel) {
  container.innerHTML = "";
  if (!names.length) {
    container.append(el("p", "note", "none defined"));
    return;
  }
  names.forEach(name => {
    const b = el("button");
    b.dataset.name = name;
    b.append(document.createTextNode(name));
    if (kindLabel) b.append(el("span", "kind", kindLabel));
    b.addEventListener("click", () => {
      const p = {}; p[paramName] = name;
      fire(action, p, b);
    });
    container.append(b);
  });
}

async function buildUI() {
  const v = await api("/api/vocabulary");
  // Idle is on its own always-visible button; listing it twice invites
  // tapping the wrong one mid-session.
  addButtons($("#scenes"),
             v.scenes.filter(n => n !== v.idle_scene),
             "apply_scene", "scene_name", null);
  addButtons($("#interruptions"), v.interruptions,
             "play_interruption", "interruption_name", null);
  addButtons($("#tables"), v.random_tables,
             "roll_table", "table_name", "roll");
  if (!v.random_tables.length) $("#tables-section").style.display = "none";

  await refreshCards();
  await refreshSeats();
  await refreshInitiative();
  await refreshAudio();
  await refreshRecording();
  // The only thing here that changes on its own, so it gets its own tick.
  setInterval(refreshRecording, 5000);
}

/* ---------- cards: view + edit (plan doc 4.5 step 2) ---------- */

let validTargets = {};

function cardRow(card, opts) {
  const row = el("div", "card-row" + (opts && opts.unassigned ? " unassigned" : ""));
  const left = el("div");
  left.append(el("div", null, card.label || "(unnamed)"));
  left.append(el("div", "uid", card.uid));
  row.append(left);
  const right = el("div");
  right.append(el("div", "target",
    opts && opts.unassigned ? "tap to register"
                            : `${card.target_kind}: ${card.target_name}`));
  row.append(right);
  row.append(el("span", "chev", "›"));
  row.addEventListener("click", () => openEditor(card, opts && opts.unassigned));
  return row;
}

async function refreshCards() {
  validTargets = await api("/api/config/targets");

  const c = await api("/api/config/cards");
  const box = $("#cards");
  box.innerHTML = "";
  $("#card-count").textContent = `(${c.cards.length})`;
  c.cards.forEach(card => box.append(cardRow(card)));

  const u = await api("/api/config/unassigned");
  const ubox = $("#unassigned");
  ubox.innerHTML = "";
  $("#unassigned-section").style.display = u.unassigned.length ? "" : "none";
  u.unassigned.forEach(item => {
    ubox.append(cardRow(
      { uid: item.uid, label: `unknown tag · ${Math.round(item.seconds_ago)}s ago` },
      { unassigned: true }));
  });
}

/* ---------- the editor ---------- */

let editing = null;

function fillNames(kind, selected) {
  const sel = $("#ed-name");
  sel.innerHTML = "";
  (validTargets[kind] || []).forEach(n => {
    const o = el("option", null, n);
    o.value = n;
    if (n === selected) o.selected = true;
    sel.append(o);
  });
  if (!(validTargets[kind] || []).length) {
    sel.append(el("option", null, "(none defined)"));
  }
}

function openEditor(card, isNew) {
  editing = { uid: card.uid, isNew: !!isNew };
  $("#ed-title").textContent = isNew ? "Register Card" : "Edit Card";
  $("#ed-label").value = isNew ? "" : (card.label || "");
  $("#ed-uid").value = card.uid;
  const kind = card.target_kind || "scene";
  $("#ed-kind").value = kind;
  fillNames(kind, card.target_name);
  $("#ed-err").textContent = "";
  $("#ed-delete").style.display = isNew ? "none" : "";
  $("#editor").hidden = false;
  if (isNew) setTimeout(() => $("#ed-label").focus(), 50);
}

function closeEditor() {
  $("#editor").hidden = true;
  editing = null;
}

$("#ed-kind").addEventListener("change", () => fillNames($("#ed-kind").value));
$("#ed-cancel").addEventListener("click", closeEditor);
$("#editor").addEventListener("click", (e) => {
  if (e.target.id === "editor") closeEditor();   // tap the backdrop to dismiss
});

$("#ed-save").addEventListener("click", async () => {
  const btn = $("#ed-save");
  btn.classList.add("busy");
  try {
    await api("/api/config/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        uid: $("#ed-uid").value,
        label: $("#ed-label").value,
        target_kind: $("#ed-kind").value,
        target_name: $("#ed-name").value
      })
    });
    closeEditor();
    await refreshCards();
  } catch (e) {
    // Keep the dialog open on failure - the operator's typing is still in it.
    $("#ed-err").textContent = e.message;
  } finally {
    btn.classList.remove("busy");
  }
});

$("#ed-delete").addEventListener("click", async () => {
  if (!editing) return;
  if (!confirm("Delete this card? The physical tag will stop doing anything.")) return;
  try {
    await api("/api/config/cards/" + encodeURIComponent(editing.uid), { method: "DELETE" });
    closeEditor();
    await refreshCards();
  } catch (e) {
    $("#ed-err").textContent = e.message;
  }
});

/* ---------- polling ---------- */

let lastUnassigned = -1;

async function poll() {
  try {
    render(await api("/api/status"));
    // Surface a newly-tapped unknown tag without needing a reload.
    const u = await api("/api/config/unassigned");
    if (u.unassigned.length !== lastUnassigned) {
      lastUnassigned = u.unassigned.length;
      if ($("#editor").hidden) await refreshCards();
    }
  } catch (e) {
    // Two strikes before declaring offline, so one dropped request on
    // flaky wifi doesn't make the panel flash red mid-session.
    if (++failures >= 2) markOffline();
  }
}

/* ---------- wiring ---------- */

$("#idle").addEventListener("click", (e) => fire("go_idle", {}, e.target));

async function runCheck(physical, btn) {
  const box = $("#check-results");
  box.innerHTML = "";
  box.append(el("div", "check-summary warn",
    physical ? "Running — watch and listen to the table…" : "Running…"));
  btn.classList.add("busy");
  try {
    const rep = await api("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ physical: !!physical })
    });
    box.innerHTML = "";
    const c = rep.counts || {};
    const head = el("div", "check-summary " + rep.overall,
      `${rep.overall.toUpperCase()} · ${c.pass || 0} passed, ` +
      `${c.warn || 0} warnings, ${c.fail || 0} failed · ${rep.duration_s}s`);
    box.append(head);
    rep.results.forEach(r => {
      const line = el("div", "check-line " + r.status);
      line.append(el("span", "who", r.name));
      line.append(el("span", "what", r.detail));
      box.append(line);
    });
  } catch (e) {
    box.innerHTML = "";
    box.append(el("div", "check-summary fail", "Check failed: " + e.message));
  } finally {
    btn.classList.remove("busy");
  }
}

$("#check-run").addEventListener("click", (e) => runCheck(false, e.currentTarget));
$("#check-full").addEventListener("click", (e) => runCheck(true, e.currentTarget));

// Canonical definition is STATUS_SCREEN in warlock/devices/base.py. Repeated
// here because the panel has to name it to ask for it; if it ever changes,
// both move together.
const STATUS_SCREEN = "(status screen)";

$("#show-status").addEventListener("click", (e) =>
  fire("set_background", { name: STATUS_SCREEN }, e.currentTarget));

/* ---------- player bar + signals (plan doc 3.7) ---------- */

const SIGNAL_MARK = { question: "?", need: "!" };

// Seats come from /api/zones, signals ride on /api/status. Kept apart
// because the seats change when somebody claims one and the signals change
// every few seconds; redrawing the whole bar on every poll would fight a
// finger that is mid-tap.
let barSeats = [];
// Kept so the bar can be redrawn when the pin preference changes, without
// waiting up to three seconds for the next poll to supply the signals.
let lastSignals = [];

function renderPlayerBar(signals) {
  signals = signals || [];
  lastSignals = signals;
  const bar = $("#players-bar");
  let seated = barSeats.filter(z => z.player);

  // UNPINNED MEANS UNPINNED, NOT GONE.
  //
  // The bar costs about 34px of the scarcest space on the panel, so a GM
  // may reasonably not want a permanent roster. But if "off" meant "gone",
  // a player pressing `?` would light their own button while nobody was
  // watching -- a promise the table cannot keep, and the player has no way
  // to discover it was never received.
  //
  // So unpinned hides the bar only while it has nothing to say. A raised
  // signal pulls it back, showing just whoever raised it; clearing the
  // last one lets it go again. Quiet when quiet, present when it matters.
  if (!barPinned()) {
    const raised = new Set(signals.map(sig => sig.colour));
    seated = seated.filter(z => raised.has(z.colour));
  }

  if (!seated.length) {
    bar.hidden = true; bar.innerHTML = ""; bar.dataset.want = "";
    measureChrome();
    return;
  }
  const wasHidden = bar.hidden;
  bar.hidden = false;
  if (wasHidden) measureChrome();

  const byColour = {};
  signals.forEach(sig => { byColour[sig.colour] = sig; });

  const want = seated.map(z =>
    z.colour + "|" + z.player + "|" + (byColour[z.colour] || {}).kind).join(",");
  if (bar.dataset.want === want) return;
  bar.dataset.want = want;

  bar.innerHTML = "";
  seated.forEach(z => {
    const sig = byColour[z.colour];
    const pill = el("span");
    pill.className = "player-pill" + (sig ? " signalling" : "");
    pill.style.setProperty("--seat", z.colour);
    const dot = el("span"); dot.className = "player-dot";
    const nm = el("span"); nm.append(document.createTextNode(z.player));
    pill.append(dot, nm);
    if (sig) {
      const mark = el("span");
      mark.className = "player-mark";
      mark.append(document.createTextNode(SIGNAL_MARK[sig.kind] || "!"));
      pill.append(mark);
      pill.title = "Tap to clear";
      pill.addEventListener("click", async () => {
        // Clear locally first so the tap feels answered; the next poll is
        // the source of truth either way.
        pill.classList.remove("signalling");
        const m = pill.querySelector(".player-mark");
        if (m) m.remove();
        bar.dataset.want = "";
        try {
          await api("/api/signals/clear", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ colour: z.colour })
          });
        } catch (e) { /* the poll will put it back if it did not land */ }
      });
    }
    bar.append(pill);
  });
}

/* ---------- dice, GM side (plan doc 3.7) ---------- */

// Same behaviour as the phone's pad: the result stays up until a digit is
// pressed. Duplicated rather than shared because the two live in different
// documents; if a third ever appears, that is the moment to extract it.
const GM_DICE = [4, 6, 8, 10, 12, 20];
let gmEntry = "";
let gmHolding = false;

function gmPadShow(t) { $("#gm-pad-display").textContent = t; }

function gmDigit(d) {
  if (gmHolding) { gmEntry = ""; gmHolding = false; }
  if (gmEntry.length >= 3) return;
  gmEntry = (gmEntry === "0" ? "" : gmEntry) + d;
  gmPadShow(gmEntry || "0");
}

async function gmRoll(sides) {
  const count = Math.max(1, parseInt(gmEntry || "1", 10));
  try {
    const data = await api("/api/roll", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: count, sides: sides })
    });
    gmPadShow(String(data.total));
    gmHolding = true; gmEntry = "";
    $("#rolls-log").dataset.stamp = "";
    refreshRolls();
  } catch (e) { gmPadShow("—"); gmHolding = true; }
}

function buildGmDice() {
  const box = $("#gm-dice-shapes");
  if (box.childElementCount) return;
  GM_DICE.forEach(sides => {
    const b = el("button");
    b.className = "die";
    b.append(document.createTextNode("d" + sides));
    b.addEventListener("click", () => gmRoll(sides));
    box.append(b);
  });
}

document.querySelectorAll(".gm-key[data-d]").forEach(b =>
  b.addEventListener("click", () => gmDigit(b.dataset.d)));
$("#gm-pad-clear").addEventListener("click", () => {
  gmEntry = ""; gmHolding = false; gmPadShow("0");
});
buildGmDice();

/* ---------- dice log, GM side (plan doc 3.7) ---------- */

async function refreshRolls() {
  let data;
  try { data = await api("/api/rolls"); }
  catch (e) { return; }
  const rows = data.rolls || [];
  const log = $("#rolls-log");
  if (!rows.length) { log.innerHTML = ""; log.dataset.stamp = ""; return; }
  const stamp = rows.length + ":" + (rows[0] || {}).at;
  if (log.dataset.stamp === stamp) return;
  log.dataset.stamp = stamp;
  log.innerHTML = "";
  rows.forEach(r => {
    const row = el("div");
    row.className = "roll-row";
    const who = el("span");
    who.style.color = r.colour;
    who.append(document.createTextNode((r.name || r.colour) + "  "));
    row.append(who, document.createTextNode(r.label));
    log.append(row);
  });
}

/* ---------- whispers, GM side (plan doc 3.7) ---------- */

// Which thread is open, and how many messages we had last time we looked.
// The unread mark is per thread and local to this panel: the table does not
// track "read", because two GMs on two devices would disagree about it and
// neither would be wrong.
let waColour = null;
let waSeen = {};
let waThreads = [];
// Seated players merged with existing threads -- see refreshWhispers.
let waPeople = [];

async function refreshWhispers() {
  let data;
  try { data = await api("/api/whispers"); }
  catch (e) { return; }
  waThreads = data.threads || [];
  // WHO YOU CAN WHISPER IS WHO IS SITTING DOWN, not who has already
  // written. Building the tab list from the threads alone meant the GM
  // could only ever REPLY -- with nobody having messaged there was no
  // button, no list and no way to start one, which is the wrong way round:
  // the GM is the one who most often needs to say something quietly first.
  // The controller opens a thread on the first message either way, so a
  // player with no history is a tab with an empty log, not a special case.
  const seatedFirst = barSeats.filter(z => z.player && z.zone > 0);
  const byColour = {};
  seatedFirst.forEach(z => { byColour[z.colour] = { colour: z.colour, name: z.player,
                                                    messages: [], last_from: null }; });
  waThreads.forEach(t => { byColour[t.colour] = t; });
  // Seated players in seat order, then any thread from someone who has
  // since left -- their history should not vanish because they stood up.
  const people = seatedFirst.map(z => byColour[z.colour])
    .concat(waThreads.filter(t => !seatedFirst.some(z => z.colour === t.colour)));
  waPeople = people;

  const open = $("#whisper-open");
  open.hidden = !people.length;
  if (!people.length) { closeWhispers(); return; }
  // Land on somebody, so the reply box always has a destination.
  if (!waColour || !people.some(t => t.colour === waColour)) waColour = people[0].colour;

  let unread = 0;
  waThreads.forEach(t => {
    const seen = waSeen[t.colour] || 0;
    // Only the GM's own messages count as read on arrival; a player's
    // message is unread until the thread is opened.
    if (t.colour !== waColour && t.messages.length > seen &&
        t.last_from === "player") unread++;
  });
  $("#whisper-count").textContent = unread ? "· " + unread : "";
  $("#whisper-open").classList.toggle("waiting", unread > 0);

  const key = people.map(t => t.colour + ":" + t.messages.length).join(",")
              + "|" + waColour;
  const tabs = $("#whisper-tabs");
  if (tabs.dataset.key !== key) {
    tabs.dataset.key = key;
    tabs.innerHTML = "";
    people.forEach(t => {
      const b = el("button");
      b.className = "whisper-tab"
        + (t.colour === waColour ? " active" : "")
        + ((t.messages.length > (waSeen[t.colour] || 0) &&
            t.last_from === "player" && t.colour !== waColour) ? " unread" : "");
      b.style.setProperty("--seat", t.colour);
      b.append(document.createTextNode((t.name || t.colour)));
      b.addEventListener("click", () => {
        waColour = t.colour;
        waSeen[t.colour] = t.messages.length;
        tabs.dataset.key = "";
        renderGmThread();
      });
      tabs.append(b);
    });
  }
  if (waColour) {
    waSeen[waColour] = (people.find(t => t.colour === waColour) || {})
      .messages?.length || 0;
  }
  renderGmThread();
}

function renderGmThread() {
  const log = $("#gm-whisper-log");
  const t = waPeople.find(x => x.colour === waColour);
  if (!t) { log.innerHTML = ""; log.dataset.stamp = ""; return; }
  const stamp = t.colour + ":" + t.messages.length;
  if (log.dataset.stamp === stamp) return;
  log.dataset.stamp = stamp;
  log.innerHTML = "";
  t.messages.forEach(m => {
    const row = el("div");
    // Mirrored from the player's view: the GM's own words sit on the right
    // there too, so a screenshared panel does not confuse anyone.
    row.className = "bubble " + (m.from === "gm" ? "from-me" : "from-gm");
    row.append(document.createTextNode(m.text));
    log.append(row);
  });
  log.scrollTop = log.scrollHeight;
}

$("#gm-whisper-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const box = $("#gm-whisper-text");
  const text = box.value.trim();
  if (!text || !waColour) return;
  box.value = "";
  try {
    await api("/api/whispers/reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ colour: waColour, text: text })
    });
    $("#gm-whisper-log").dataset.stamp = "";
    refreshWhispers();
  } catch (e) { box.value = text; }
});

const OVERLAY_LABEL = { none: "No Overlay", grid: "Square Grid", hex: "Hex Grid" };

function renderOverlayButtons(dd) {
  const row = $("#overlay-row");
  const modes = dd.overlays || ["none", "grid", "hex"];
  const current = dd.overlay || "none";

  // Rebuild only when the set of modes changes; otherwise just move the
  // highlight, so a poll mid-tap does not tear the row out from under a
  // finger.
  if (row.dataset.modes !== modes.join(",")) {
    row.dataset.modes = modes.join(",");
    row.innerHTML = "";
    modes.forEach(m => {
      const b = el("button");
      b.dataset.mode = m;
      b.append(document.createTextNode(OVERLAY_LABEL[m] || m));
      b.addEventListener("click", () => fire("set_overlay", { mode: m }, b));
      row.append(b);
    });
  }
  row.querySelectorAll("button").forEach(b => {
    b.classList.toggle("active", b.dataset.mode === current);
  });
}

/* ---------- initiative (plan doc 3.9) ---------- */

// Player turns only. The GM taps the seats below in the order they want;
// nothing is parsed, sorted or guessed.

let seatsByZone = {};      // zone id -> seat row, filled by renderSeats
let ordering = false;      // building the order by tapping seats
let draft = [];            // seats tapped so far, in order
// Defaults matter: the round/turn readout reads these before the first
// poll lands, and "round undefined" is worse than no readout at all.
let initState = { order: [], index: null, running: false,
                  round: 0, turn: 0, of: 0 };

async function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
}

function renderInitiative() {
  const list = $("#init-list");
  const rows = ordering ? draft.map(z => ({ zone: z })) : initState.order;

  $("#init-set").textContent = ordering ? "Done" : "Set Initiative Order";
  $("#init-help").hidden = !ordering;
  // Round and turn, beside "running" -- the one number a GM is otherwise
  // tracking on paper while the table tracks everything else for them.
  $("#init-state").textContent = ordering
    ? (draft.length + " tapped")
    : (initState.running
        ? ("running · round " + initState.round +
           " · turn " + initState.turn + "/" + initState.of)
        : "");

  list.innerHTML = "";
  if (!rows.length) {
    const p = el("li", "init-empty");
    p.append(document.createTextNode(
      ordering ? "Tap players below…" : "No order set."));
    list.append(p);
  } else {
    rows.forEach((row, i) => {
      const seat = seatsByZone[row.zone] || {};
      const live = !ordering && initState.running && i === initState.index;
      const li = el("li", live ? "now" : "");
      const pos = el("span", "init-pos");
      pos.append(document.createTextNode(String(i + 1)));
      const dot = el("span", "init-dot");
      dot.style.setProperty("--seat", row.colour || seat.colour || "");
      const name = el("div");
      // A seat nobody claimed still takes a turn - the GM may be running
      // this before everyone has joined.
      name.append(document.createTextNode(
        row.player || seat.player || (seat.label || ("Seat " + row.zone))));
      li.append(pos, dot, name);
      list.append(li);
    });
  }

  const canRun = !ordering && initState.order.length > 0;
  $("#init-run").disabled = !canRun;
  $("#init-run").textContent = initState.running ? "Restart from Top" : "Run Initiative";
  $("#init-prev").disabled = !(canRun && initState.running);
  $("#init-next").disabled = !(canRun && initState.running);
}

async function refreshInitiative() {
  try {
    initState = await api("/api/initiative");
    renderInitiative();
  } catch (e) { /* the status strip already reports an unreachable table */ }
}

$("#init-set").addEventListener("click", async () => {
  if (!ordering) {
    ordering = true;
    draft = initState.order.map(r => r.zone);
    document.body.classList.add("ordering");
    renderInitiative();
    refreshSeats();
    return;
  }
  ordering = false;
  document.body.classList.remove("ordering");
  try {
    initState = await postJSON("/api/initiative/order", { order: draft });
  } catch (e) { showError(e.message); }
  renderInitiative();
  refreshSeats();
});

$("#init-run").addEventListener("click", async () => {
  try { initState = await postJSON("/api/initiative/run", {}); }
  catch (e) { showError(e.message); }
  renderInitiative();
});

$("#init-next").addEventListener("click", async () => {
  try { initState = await postJSON("/api/initiative/advance", { step: 1 }); }
  catch (e) { showError(e.message); }
  renderInitiative();
});

$("#init-prev").addEventListener("click", async () => {
  try { initState = await postJSON("/api/initiative/advance", { step: -1 }); }
  catch (e) { showError(e.message); }
  renderInitiative();
});

function tapSeat(zone) {
  const at = draft.indexOf(zone);
  // Tapping again removes, so a mis-tap costs one tap to undo rather than
  // starting the whole order over.
  if (at >= 0) draft.splice(at, 1);
  else draft.push(zone);
  renderInitiative();
  refreshSeats();
}

/* ---------- seats (plan doc 4.7) ---------- *//* ---------- seats (plan doc 4.7) ---------- */

// Every seat colour name in warlock/zones.py is also a valid CSS colour
// keyword, so the swatch needs no lookup table that could drift from the
// palette the table actually lights.
function renderSeats(z) {
  // The bar needs the same seat rows, so it is filled from the fetch that
  // already happens rather than polling /api/zones a second time.
  barSeats = z.zones || [];
  const row = $("#seat-count-row");
  if (row.dataset.max !== String(z.max_players)) {
    row.dataset.max = String(z.max_players);
    row.innerHTML = "";
    for (let n = 1; n <= z.max_players; n++) {
      const b = el("button");
      b.dataset.count = String(n);
      b.append(document.createTextNode(String(n)));
      b.addEventListener("click", async () => {
        await fire("set_player_count", { count: n }, b);
        refreshSeats();
      });
      row.append(b);
    }
  }
  row.querySelectorAll("button").forEach(b => {
    b.classList.toggle("active", b.dataset.count === String(z.player_count));
  });

  // The visible control. Seven numbered buttons ate a whole row to express
  // one number; a select says the same thing in one field and leaves the
  // row for the two controls beside it.
  const sel = $("#seat-count");
  if (sel.dataset.max !== String(z.max_players)) {
    sel.dataset.max = String(z.max_players);
    sel.innerHTML = "";
    for (let n = 1; n <= z.max_players; n++) {
      const o = document.createElement("option");
      o.value = String(n);
      o.textContent = String(n);
      sel.append(o);
    }
    sel.addEventListener("change", async () => {
      await fire("set_player_count", { count: Number(sel.value) });
      refreshSeats();
    });
  }
  sel.value = String(z.player_count);

  // Keep a lookup so the initiative list can show colours and names
  // without fetching the seats again on every render.
  seatsByZone = {};
  z.zones.forEach(seat => { seatsByZone[seat.zone] = seat; });

  const list = $("#seat-list");
  list.innerHTML = "";
  z.zones.forEach(seat => {
    const line = el("div", "seat");
    const sw = el("div", "swatch");
    sw.style.background = seat.colour;
    const name = el("div");
    name.append(document.createTextNode(seat.label));
    const who = el("span", "who" + (seat.player ? "" : " empty"));
    who.append(document.createTextNode(seat.player || "unclaimed"));
    name.append(document.createTextNode(" "));
    name.append(who);

    // The GM's seat takes no turn and cannot be flashed at: it is where
    // they are already sitting.
    const isPlayer = seat.zone > 0;

    if (ordering && isPlayer) {
      const at = draft.indexOf(seat.zone);
      const pos = el("span", "seat-pos");
      pos.append(document.createTextNode(at >= 0 ? String(at + 1) : "+"));
      line.append(sw, name, pos, el("span"));
      line.addEventListener("click", () => tapSeat(seat.zone));
    } else {
      const size = el("div", "size");
      size.append(document.createTextNode(seat.inches + " in"));
      const acts = el("span", "seat-acts");
      if (isPlayer) {
        const flash = el("button", "seat-flash");
        flash.append(document.createTextNode("Flash"));
        flash.addEventListener("click", (ev) => {
          ev.stopPropagation();
          fire("flash_player", { zone: seat.zone }, flash);
        });
        acts.append(flash);

        // Only offered for a seat somebody is actually in: a "Remove" on an
        // empty chair is a button that cannot do anything.
        if (seat.player) {
          const kick = el("button", "seat-kick");
          kick.append(document.createTextNode("Remove"));
          kick.title = "Empty this seat";
          kick.addEventListener("click", async (ev) => {
            ev.stopPropagation();
            // Confirmed because it is somebody else's session state, and a
            // mis-tap in a dim room silently drops a player out of the
            // initiative order as well as their seat.
            if (!confirm("Remove " + seat.player + " from the "
                         + seat.colour + " seat?")) return;
            kick.classList.add("busy");
            try {
              await postJSON("/api/seats/release", { colour: seat.colour });
              await refreshSeats();
              await refreshInitiative();
            } catch (e) {
              showError(e.message);
            } finally {
              kick.classList.remove("busy");
            }
          });
          acts.append(kick);
        }
      }
      line.append(sw, name, size, acts);
    }
    list.append(line);
  });

  // Say plainly when the control is inert. A button that silently does
  // nothing is the failure mode the status strip exists to prevent.
  $("#seat-note").textContent = z.supported
    ? "The GM's section is fixed at 38 in; players divide the rest, "
      + "numbered clockwise from the GM."
    : "No 'zones' pattern on the Pixelblaze \u2014 seat colours will not "
      + "light until patterns/zones.js is uploaded.";
}

async function refreshSeats() {
  try {
    renderSeats(await api("/api/zones"));
  } catch (e) {
    $("#seat-note").textContent = "could not read seats: " + e.message;
  }
}

$("#seat-show").addEventListener("click", (ev) => {
  fire("show_seat_colours", {}, ev.currentTarget);
});

/* ---------- session recording (plan doc 3.10) ---------- */

function renderRecording(r) {
  const btn = $("#rec-toggle");
  const note = $("#rec-note");
  btn.classList.toggle("on", !!r.recording);
  btn.disabled = !r.available;

  if (!r.available) {
    btn.textContent = "Record Session";
    note.textContent = "No recorder on this build.";
    return;
  }
  if (r.recording) {
    const m = Math.floor(r.seconds / 60), sec = Math.floor(r.seconds % 60);
    btn.textContent = "Stop Recording";
    note.textContent = "Recording " + (r.file || "") + " \u2014 " +
      m + "m " + (sec < 10 ? "0" : "") + sec + "s";
    note.classList.remove("warn");
  } else {
    btn.textContent = "Record Session";
    // Hours remaining, not gigabytes: nobody converts GB to session length
    // in their head at the start of a game.
    note.textContent = r.error
      ? r.error
      : "Room mic. About " + r.hours_left + " hours of space left.";
    note.classList.toggle("warn", !!r.error || r.hours_left < 3);
  }
}

async function refreshRecording() {
  try { renderRecording(await api("/api/recording")); }
  catch (e) { $("#rec-note").textContent = "could not read recorder: " + e.message; }
}

$("#rec-toggle").addEventListener("click", async (ev) => {
  const on = ev.currentTarget.classList.contains("on");
  await fire(on ? "stop_recording" : "start_recording", {}, ev.currentTarget);
  refreshRecording();
});

/* ---------- sound ---------- */

function renderAudio(a) {
  const slider = $("#vol");
  // Do not fight a finger: a poll landing mid-drag must not snap the slider
  // back to the server's value.
  if (document.activeElement !== slider) {
    slider.value = String(Math.round(a.volume * 100));
    $("#vol-val").textContent = slider.value + "%";
  }

  const row = $("#audio-out-row");
  const names = a.outputs || [];
  row.style.gridTemplateColumns = "repeat(" + Math.max(1, names.length) + ",1fr)";
  if (row.dataset.names !== names.join(",")) {
    row.dataset.names = names.join(",");
    row.innerHTML = "";
    names.forEach(n => {
      const b = el("button");
      b.dataset.out = n;
      b.append(document.createTextNode(n));
      b.addEventListener("click", async () => {
        // Switching rebuilds the mixer, so it is slow enough to be worth
        // saying something rather than looking frozen.
        $("#audio-note").textContent = "switching to " + n + "\u2026";
        await fire("set_audio_output", { name: n }, b);
        await refreshAudio();
      });
      row.append(b);
    });
  }
  row.querySelectorAll("button").forEach(b => {
    b.classList.toggle("active", b.dataset.out === a.current);
  });

  $("#audio-note").textContent = a.current
    ? ""
    : "Playing to " + (a.device || "the default device") +
      ", which is not one of the configured outputs.";
}

async function refreshAudio() {
  try { renderAudio(await api("/api/audio")); }
  catch (e) { $("#audio-note").textContent = "could not read sound: " + e.message; }
}

const vol = $("#vol");
vol.addEventListener("input", () => { $("#vol-val").textContent = vol.value + "%"; });
// On release, not on every pixel of the drag: each change is a config write,
// and the SD card is the one component here with a wear limit.
vol.addEventListener("change", () => {
  fire("set_volume", { level: Number(vol.value) / 100 });
});

const bright = $("#bright");
bright.addEventListener("input", () => {
  $("#bright-val").textContent = bright.value + "%";
});
bright.addEventListener("change", () => {
  fire("set_brightness", { level: Number(bright.value) / 100 });
});

buildUI().catch(e => showError("could not load: " + e.message));
poll();
setInterval(poll, 3000);

// Re-poll the moment the iPad wakes or the app is re-opened, so you are
// never looking at a frozen picture from an hour ago.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) poll();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

/* ---------- navigation (plan doc 3.7 redesign) ----------
 *
 * Four panels and a card page, swapped by a bottom tab bar. No router and
 * no history: the browser back button on a wall-mounted iPad is not a
 * navigation control anybody reaches for, and a history stack would mean
 * a GM's third card tap could be undone by a stray swipe.
 *
 * PANEL STATE SURVIVES A SWITCH because nothing is destroyed -- panels are
 * hidden, not rebuilt. A half-typed dice count, a selected initiative
 * order and a part-written whisper are all still there on return. That is
 * the whole reason this is `hidden` toggling rather than re-rendering.
 *
 * At >= 1200px the CSS overrides Players and Run to both be visible and
 * drops the tab bar; `current` keeps being tracked anyway, so shrinking
 * the window lands somewhere sensible rather than nowhere.
 */

const PANELS = ["players", "run", "dice", "settings", "cards"];
const LANDING = "players";      // people arriving is what happens first
let current = LANDING;

function goto(name) {
  if (!PANELS.includes(name)) return;
  current = name;
  PANELS.forEach(n => {
    const panel = document.getElementById("panel-" + n);
    if (panel) panel.hidden = n !== name;
  });
  // Same active-state logic for the bottom tabs and the browser-width
  // launcher: whichever one exists at the current width, both are kept in
  // sync so neither goes stale under a resize.
  document.querySelectorAll(".tab, .wide-nav-btn").forEach(t =>
    t.classList.toggle("active", t.dataset.goto === name));
  // Cards is not a destination of its own, so nothing lights up for it.
  // Settings stays lit while you are inside it, because that is where you
  // came from and where the back button returns you.
  if (name === "cards") {
    document.querySelectorAll('[data-goto="settings"]').forEach(t =>
      t.classList.add("active"));
  }
  // At browser width these three are fixed overlays; the body class is
  // what reveals the close control the missing tab bar would have been.
  document.body.classList.toggle(
    "panel-over", name === "dice" || name === "settings" || name === "cards");
  // A panel switch scrolls to the top of the new panel, not to wherever
  // the last one was left.
  window.scrollTo(0, 0);
}

document.querySelectorAll(".tab, .wide-nav-btn").forEach(t =>
  t.addEventListener("click", () => goto(t.dataset.goto)));

$("#open-cards").addEventListener("click", () => goto("cards"));
$("#cards-back").addEventListener("click", () => goto("settings"));
$("#wide-close").addEventListener("click", () => goto(LANDING));

goto(LANDING);

/* ---------- the whisper overlay ----------
 *
 * Opened deliberately, closed deliberately. `body.locked` stops the panel
 * underneath scrolling while a finger drags inside the thread -- without
 * it the page behind pulls, which is the specific complaint this replaced.
 */

function openWhispers() {
  $("#whisper-section").hidden = false;
  document.body.classList.add("locked");
  // Mark whatever thread is showing as read on open rather than on poll:
  // opening it is the act of reading it.
  if (waColour) {
    const t = waThreads.find(x => x.colour === waColour);
    if (t) waSeen[waColour] = t.messages.length;
  }
  refreshWhispers();
}

function closeWhispers() {
  $("#whisper-section").hidden = true;
  document.body.classList.remove("locked");
}

$("#whisper-open").addEventListener("click", openWhispers);
$("#whisper-close").addEventListener("click", closeWhispers);
// Escape closes it on a browser; on a tablet the button is the only way,
// which is why the button is not optional.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#whisper-section").hidden) closeWhispers();
});

/* ---------- per-device view preferences ----------
 *
 * localStorage rather than table config: this is how one GM likes to look
 * at the panel, not something true about the table, and two GMs on two
 * devices should not fight over it. Same mechanism the player page already
 * uses to remember a seat.
 */

const PREF_BAR = "wt.playerbar";

function barPinned() {
  return localStorage.getItem(PREF_BAR) !== "0";
}

function applyBarPref() {
  const on = barPinned();
  $("#pref-playerbar").checked = on;
  document.body.classList.toggle("bar-unpinned", !on);
  renderPlayerBar(lastSignals);
}

$("#pref-playerbar").addEventListener("change", (e) => {
  localStorage.setItem(PREF_BAR, e.currentTarget.checked ? "1" : "0");
  applyBarPref();
});

applyBarPref();

/* ---------- chrome measurement ----------
 *
 * The panel columns size themselves against the space the header and the
 * tab bar leave behind. That number is not a constant: the header grows by
 * ~34px when the player bar appears and shrinks again when it goes, and it
 * reflows entirely between breakpoints. Measuring beats guessing -- a
 * hard-coded value is wrong on one device the day somebody sits down.
 */
function measureChrome() {
  const head = document.querySelector("header").getBoundingClientRect().height;
  const bar = document.getElementById("tabbar");
  // display:none at browser width, where it contributes nothing.
  const tabs = getComputedStyle(bar).display === "none"
    ? 0 : bar.getBoundingClientRect().height;
  // The footer counts too: version and the error line sit below the
  // panels, and a column tall enough to push them under the tab bar would
  // hide the one place errors are reported.
  const foot = document.querySelector("footer").getBoundingClientRect().height;
  document.documentElement.style.setProperty(
    "--chrome", Math.ceil(head + tabs + foot + 20) + "px");
}

measureChrome();
addEventListener("resize", measureChrome);

// The header changes height when the player bar comes and goes, which is
// driven by a poll rather than by any event we could listen for -- hence
// an observer.
//
// THE rAF IS NOT DECORATION. Writing --chrome from inside the callback
// re-runs layout on the element being observed, the browser sees a
// resize loop, and it responds by silently dropping the notification --
// no error, no warning, the observer simply stops working. That shipped:
// with two players seated the header grew from 53px to 140px, --chrome
// stayed at its startup value, and the columns overflowed the page by
// 18px. Deferring the write to the next frame ends the callback before
// the layout it causes, which breaks the loop.
let chromePending = false;
new ResizeObserver(() => {
  if (chromePending) return;
  chromePending = true;
  requestAnimationFrame(() => { chromePending = false; measureChrome(); });
}).observe(document.querySelector("header"));
