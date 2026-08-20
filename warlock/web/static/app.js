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

  const c = await api("/api/config/cards");
  const box = $("#cards");
  box.innerHTML = "";
  $("#card-count").textContent = `(${c.cards.length})`;
  c.cards.forEach(card => {
    const row = el("div", "card-row");
    const left = el("div");
    left.append(el("div", null, card.label));
    left.append(el("div", "uid", card.uid));
    row.append(left);
    row.append(el("div", "target", `${card.target_kind}: ${card.target_name}`));
    box.append(row);
  });
}

/* ---------- polling ---------- */

async function poll() {
  try {
    render(await api("/api/status"));
  } catch (e) {
    // Two strikes before declaring offline, so one dropped request on
    // flaky wifi doesn't make the panel flash red mid-session.
    if (++failures >= 2) markOffline();
  }
}

/* ---------- wiring ---------- */

$("#idle").addEventListener("click", (e) => fire("go_idle", {}, e.target));

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
