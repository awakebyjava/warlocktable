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
