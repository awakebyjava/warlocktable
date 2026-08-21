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
  $("#err").textContent = msg || "";
  if (msg) setTimeout(() => { if ($("#err").textContent === msg) $("#err").textContent = ""; }, 6000);
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

function chip(name, state) {
  const c = $(`.chip[data-sys="${name}"]`);
  if (!c) return;
  c.className = "chip " + state;
}

function render(s) {
  document.body.classList.remove("offline");
  failures = 0;

  const sub = s.subsystems || {};
  chip("lights",  sub.lights  ? "ok" : "bad");
  chip("audio",   sub.audio   ? "ok" : "bad");
  chip("display", sub.display ? "ok" : "bad");

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

  // Table screen: reflect the device's own state rather than what we last
  // asked for, so the controls cannot drift out of sync with reality.
  const dd = s.display_device;
  if (dd) {
    $("#display-section").style.display = "";
    renderOverlayButtons(dd);
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
let initState = { order: [], index: null, running: false };

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
  $("#init-state").textContent = ordering
    ? (draft.length + " tapped")
    : (initState.running ? "running" : "");

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
      let flash = el("span");
      if (isPlayer) {
        flash = el("button", "seat-flash");
        flash.append(document.createTextNode("Flash"));
        flash.addEventListener("click", (ev) => {
          ev.stopPropagation();
          fire("flash_player", { zone: seat.zone }, flash);
        });
      }
      line.append(sw, name, size, flash);
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
