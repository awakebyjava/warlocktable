/* Warlock Table — Pixels dice management.
 *
 * Three things on one page, in the order a GM meets them:
 *
 *  - HEARD: dice the scanner has seen recently. A die that is rolled near
 *    the table appears here with no setup, the way an unknown card appears
 *    under "Unregistered". Tapping one prefills the form below.
 *
 *  - KNOWN: the dice the table has been told about -- a name for the log,
 *    and optionally the seat whose player owns it, so that seat's phone
 *    sees its rolls (pixels-dice-specification.md, section 6).
 *
 *  - TRIGGERS: an ordered table of landings that make the table react.
 *    Faces are exact values, never a threshold, and the whole list is
 *    sent on every save because order is the rule: first match wins.
 *
 * Same shape as interruptions.js. Dropdowns are built from what the
 * server says exists, so nothing can be assigned that is not there.
 */

(function () {
  "use strict";

  var $ = function (s) { return document.querySelector(s); };
  var last = null;          // the last /api/dice payload
  var editingTrigger = -1;  // index in last.triggers, or -1 for a new one

  function option(select, value, label) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = label == null ? value : label;
    select.appendChild(o);
  }

  function fill(select, values, blankLabel) {
    var keep = select.value;
    select.innerHTML = "";
    if (blankLabel != null) option(select, "", blankLabel);
    (values || []).forEach(function (v) {
      if (typeof v === "string") option(select, v);
      else option(select, v.value, v.label);
    });
    if (keep) select.value = keep;
  }

  function facesText(faces) {
    if (!faces || !faces.length) return "any face";
    return faces.length === 1 ? String(faces[0]) : faces.join(", ");
  }

  function parseFaces(text) {
    var t = (text || "").trim();
    if (!t) return null;
    var out = [];
    t.split(/[\s,]+/).forEach(function (piece) {
      if (!piece) return;
      if (!/^-?\d+$/.test(piece)) {
        throw new Error("faces must be whole numbers, like 20 or 18, 19, 20");
      }
      out.push(parseInt(piece, 10));
    });
    return out.length ? out : null;
  }

  function dieLabel(key) {
    if (!key || key === "any") return "any die";
    var known = (last && last.known || []).filter(function (d) { return d.die === key; })[0];
    return known ? known.name : key;
  }

  /* ---------- rendering ---------- */

  var locked = false;   // a private library is open: the trigger table is the owner's

  function render(data) {
    last = data;
    locked = !!(data.campaign && data.campaign.shared_locked);
    $("#px-trig-save").disabled = locked;
    $("#px-trig-title").textContent = locked
      ? "Triggers are the table owner's while your library is open" : "New Trigger";
    var scanner = data.scanner || {};
    $("#px-enabled").checked = !!data.enabled;
    $("#px-scanner").textContent = scanner.healthy
      ? "scanning · " + (scanner.rolls || 0) + " rolls this session"
      : "scanner " + (scanner.error ? "down: " + scanner.error : "off");

    // Heard: what the scanner sees, minus dice already known.
    var knownKeys = {};
    (data.known || []).forEach(function (d) { knownKeys[d.die] = true; });
    var heard = (scanner.dice || []).filter(function (d) { return !knownKeys[d.die]; });
    $("#px-heard-section").style.display = heard.length ? "" : "none";
    var heardList = $("#px-heard");
    heardList.innerHTML = "";
    heard.forEach(function (d) {
      var row = document.createElement("div");
      row.className = "card-row unassigned";
      var id = document.createElement("span");
      id.className = "uid";
      id.textContent = d.name || d.die;
      var detail = document.createElement("span");
      detail.className = "target";
      detail.textContent = [d.die, d.type, "battery " + d.battery + "%",
                            d.rolls + " roll" + (d.rolls === 1 ? "" : "s")].join(" · ");
      var reg = document.createElement("button");
      reg.className = "small";
      reg.textContent = "Register";
      reg.addEventListener("click", function () {
        loadDie({ die: d.die, name: d.name || "", type: d.type || "", seat: "" });
      });
      row.appendChild(id); row.appendChild(detail); row.appendChild(reg);
      heardList.appendChild(row);
    });

    // Dropdowns.
    fill($("#px-die-type"), data.types, "— not sure —");
    fill($("#px-die-seat"), data.seats, "— nobody's, just the table's —");
    var dieChoices = (data.known || []).map(function (d) {
      return { value: d.die, label: d.name + " (" + d.die + ")" };
    });
    heard.forEach(function (d) {
      dieChoices.push({ value: d.die, label: (d.name || d.die) + " — heard, not registered" });
    });
    fill($("#px-trig-die"), dieChoices, "any die");
    fill($("#px-trig-type"), data.types, "any type");
    fillTargetNames();

    // Known dice.
    var known = $("#px-known");
    known.innerHTML = "";
    $("#px-known-count").textContent = (data.known || []).length + " registered";
    (data.known || []).forEach(function (d) {
      var row = document.createElement("div");
      row.className = "card-row";
      var name = document.createElement("span");
      name.className = "uid";
      name.textContent = d.name;
      var detail = document.createElement("span");
      detail.className = "target";
      var live = (scanner.dice || []).filter(function (h) { return h.die === d.die; })[0];
      var bits = [d.die, d.type || "type unknown",
                  d.seat ? "seat: " + d.seat : "no seat"];
      if (live) bits.push("battery " + live.battery + "%");
      detail.textContent = bits.join(" · ");
      if (d.seat) detail.style.color = d.seat;
      var edit = document.createElement("button");
      edit.className = "small";
      edit.textContent = "Edit";
      edit.addEventListener("click", function () { loadDie(d); });
      var del = document.createElement("button");
      del.className = "small";
      del.textContent = "Delete";
      del.addEventListener("click", function () {
        if (!window.confirm("Forget the die “" + d.name + "”?")) return;
        window.api("/api/dice/known/" + encodeURIComponent(d.die), { method: "DELETE" })
          .then(render).catch(function (e) { window.showError(e.message); });
      });
      row.appendChild(name); row.appendChild(detail);
      row.appendChild(edit); row.appendChild(del);
      known.appendChild(row);
    });

    // Triggers, in order, with the order editable.
    var list = $("#px-triggers");
    list.innerHTML = "";
    var trigs = data.triggers || [];
    $("#px-trig-count").textContent = trigs.length + (trigs.length === 1 ? " row" : " rows")
      + " · first match wins";
    trigs.forEach(function (t, i) {
      var row = document.createElement("div");
      row.className = "card-row";
      var head = document.createElement("span");
      head.className = "uid";
      head.textContent = (i + 1) + ". " + dieLabel(t.die) + " · "
        + (t.type || "any type") + " · " + facesText(t.face);
      var detail = document.createElement("span");
      detail.className = "target";
      detail.textContent = "→ " + t.target_kind.replace("_", " ") + ": " + t.target_name;

      var up = document.createElement("button");
      up.className = "small"; up.textContent = "▲"; up.disabled = i === 0 || locked;
      up.addEventListener("click", function () { move(i, -1); });
      var down = document.createElement("button");
      down.className = "small"; down.textContent = "▼"; down.disabled = i === trigs.length - 1 || locked;
      down.addEventListener("click", function () { move(i, 1); });
      var edit = document.createElement("button");
      edit.className = "small"; edit.textContent = "Edit"; edit.disabled = locked;
      edit.addEventListener("click", function () { loadTrigger(i); });
      var del = document.createElement("button");
      del.className = "small"; del.textContent = "Delete"; del.disabled = locked;
      del.addEventListener("click", function () {
        var next = trigs.slice(); next.splice(i, 1);
        saveTriggers(next);
      });
      row.appendChild(head); row.appendChild(detail);
      row.appendChild(up); row.appendChild(down);
      row.appendChild(edit); row.appendChild(del);
      list.appendChild(row);
    });
  }

  function fillTargetNames() {
    if (!last) return;
    var kind = $("#px-trig-kind").value;
    fill($("#px-trig-name"), (last.targets || {})[kind] || []);
  }

  /* ---------- the die form ---------- */

  function loadDie(d) {
    $("#px-die-title").textContent = d.name ? "Editing " + d.name : "Register " + d.die;
    $("#px-die-key").value = d.die || "";
    $("#px-die-name").value = d.name || "";
    $("#px-die-type").value = d.type || "";
    $("#px-die-seat").value = d.seat || "";
    window.scrollTo(0, 0);
  }

  function clearDie() {
    $("#px-die-title").textContent = "Register a Die";
    $("#px-die-key").value = "";
    $("#px-die-name").value = "";
    $("#px-die-type").value = "";
    $("#px-die-seat").value = "";
  }

  $("#px-die-clear").addEventListener("click", clearDie);
  $("#px-die-save").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    window.api("/api/dice/known", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        die: $("#px-die-key").value,
        name: $("#px-die-name").value,
        type: $("#px-die-type").value,
        seat: $("#px-die-seat").value
      })
    }).then(function (d) { render(d); clearDie(); })
      .catch(function (e) { window.showError(e.message); })
      .then(function () { btn.disabled = false; });
  });

  /* ---------- the trigger form ---------- */

  function loadTrigger(i) {
    var t = last.triggers[i];
    editingTrigger = i;
    $("#px-trig-title").textContent = "Editing trigger " + (i + 1);
    $("#px-trig-die").value = t.die === "any" ? "" : t.die;
    $("#px-trig-type").value = t.type || "";
    $("#px-trig-faces").value = t.face ? t.face.join(", ") : "";
    $("#px-trig-kind").value = t.target_kind;
    fillTargetNames();
    $("#px-trig-name").value = t.target_name;
    window.scrollTo(0, 0);
  }

  function clearTrigger() {
    editingTrigger = -1;
    $("#px-trig-title").textContent = "New Trigger";
    $("#px-trig-die").value = "";
    $("#px-trig-type").value = "";
    $("#px-trig-faces").value = "";
  }

  function toWire(t) {
    var out = { target: { type: t.target_kind, name: t.target_name } };
    if (t.die && t.die !== "any") out.die = t.die;
    if (t.type) out.type = t.type;
    if (t.face && t.face.length) out.face = t.face.length === 1 ? t.face[0] : t.face;
    return out;
  }

  function saveTriggers(rows) {
    return window.api("/api/dice/triggers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ triggers: rows.map(toWire) })
    }).then(function (d) { render(d); return d; })
      .catch(function (e) { window.showError(e.message); });
  }

  function move(i, delta) {
    var rows = last.triggers.slice();
    var j = i + delta;
    if (j < 0 || j >= rows.length) return;
    var tmp = rows[i]; rows[i] = rows[j]; rows[j] = tmp;
    saveTriggers(rows);
  }

  $("#px-trig-kind").addEventListener("change", fillTargetNames);
  $("#px-trig-clear").addEventListener("click", clearTrigger);
  $("#px-trig-save").addEventListener("click", function () {
    var btn = this;
    var faces;
    try { faces = parseFaces($("#px-trig-faces").value); }
    catch (e) { window.showError(e.message); return; }
    var row = {
      die: $("#px-trig-die").value || "any",
      type: $("#px-trig-type").value || null,
      face: faces,
      target_kind: $("#px-trig-kind").value,
      target_name: $("#px-trig-name").value
    };
    if (!row.target_name) { window.showError("pick what the trigger does"); return; }
    var rows = (last.triggers || []).slice();
    if (editingTrigger >= 0) rows[editingTrigger] = row; else rows.push(row);
    btn.disabled = true;
    saveTriggers(rows).then(function () { clearTrigger(); btn.disabled = false; });
  });

  $("#px-enabled").addEventListener("change", function () {
    var box = this;
    window.api("/api/dice/enabled", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: box.checked })
    }).then(render).catch(function (e) { window.showError(e.message); refresh(); });
  });

  /* ---------- lifecycle ---------- */

  var timer = null;

  function refresh() {
    return window.api("/api/dice")
      .then(function (d) { render(d); return d; })
      .catch(function (e) { window.showError(e.message); });
  }

  document.addEventListener("panelshown", function (ev) {
    if (timer) { clearInterval(timer); timer = null; }
    if (ev.detail !== "pixels") return;
    refresh();
    // Heard dice and batteries change while the page is open; a roll
    // should show up without reloading. Cheap, and only while visible.
    timer = setInterval(function () {
      if (document.hidden) return;
      // Don't stomp on a half-filled form: only the lists re-render, and
      // fill() keeps the current dropdown values.
      refresh();
    }, 4000);
  });
})();
