/* Warlock Table — the scene editor.
 *
 * A scene is the table's wiring: which lights, which ongoing soundscape,
 * which map. Until now those only existed in config.json, which meant editing
 * the table by hand over ssh.
 *
 * Every dropdown is filled from what the DEVICES actually report, not from a
 * hardcoded list — the same rule as the action registry and the card editor.
 * You cannot pick a pattern the Pixelblaze does not have, and the server
 * checks again on save in case the device list changed while the form was
 * open.
 */

(function () {
  "use strict";

  var $ = function (s) { return document.querySelector(s); };
  var editing = null;      // name being edited, or null for a new scene

  function fill(select, names, blankLabel) {
    select.innerHTML = "";
    if (blankLabel) {
      var none = document.createElement("option");
      none.value = "";
      none.textContent = blankLabel;
      select.appendChild(none);
    }
    (names || []).forEach(function (n) {
      var o = document.createElement("option");
      o.value = n;
      o.textContent = n;
      select.appendChild(o);
    });
  }

  var locked = false;   // a private library is open: shared entries are read-only

  function render(data) {
    locked = !!(data.campaign && data.campaign.shared_locked);
    var opts = data.options || {};
    fill($("#scene-lights"), opts.lights, null);
    fill($("#scene-soundscape"), opts.soundscapes, "— none, silent —");
    fill($("#scene-background"), opts.backgrounds, "— none —");

    var list = $("#scene-list");
    list.innerHTML = "";
    $("#scene-count").textContent = data.scenes.length + " scenes";

    data.scenes.forEach(function (sc) {
      var row = document.createElement("div");
      row.className = "card-row";

      var name = document.createElement("span");
      name.className = "uid";
      name.textContent = sc.name + (sc.is_idle ? "  (idle)" : "");

      var detail = document.createElement("span");
      detail.className = "target";
      var bits = [sc.lights];
      bits.push(sc.soundscape || "no sound");
      if (sc.background) bits.push(sc.background);
      if (sc.used_by && sc.used_by.length) {
        bits.push(sc.used_by.length + " card" + (sc.used_by.length === 1 ? "" : "s"));
      }
      if (sc.owner === "private") bits.unshift("mine");
      detail.textContent = bits.join(" · ");

      var shared = locked && sc.owner !== "private";
      var edit = document.createElement("button");
      edit.className = "small";
      edit.textContent = shared ? "View" : "Edit";
      edit.addEventListener("click", function () { load(sc, shared); });

      var del = document.createElement("button");
      del.className = "small";
      del.textContent = "Delete";
      // The idle scene is the table's resting state; the server refuses to
      // remove it, so do not offer a button that is going to fail. Same for
      // a shared scene while someone else's library is open.
      del.disabled = !!sc.is_idle || shared;
      del.title = sc.is_idle ? "the table falls back to this one"
                : shared ? "part of the table's shared library" : "";
      del.addEventListener("click", function () {
        if (!window.confirm("Delete the scene “" + sc.name + "”?")) return;
        window.api("/api/config/scenes/" + encodeURIComponent(sc.name),
                   { method: "DELETE" })
          .then(refresh)
          .catch(function (e) { window.showError(e.message); });
      });

      row.appendChild(name);
      row.appendChild(detail);
      row.appendChild(edit);
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  function load(sc, readOnly) {
    editing = sc.name;
    $("#scene-form-title").textContent = readOnly
      ? sc.name + " \u2014 shared, the table owner's. Make your own instead."
      : "Editing " + sc.name;
    $("#scene-save").disabled = !!readOnly;
    $("#scene-name").value = sc.name;
    $("#scene-lights").value = sc.lights || "";
    $("#scene-soundscape").value = sc.soundscape || "";
    $("#scene-background").value = sc.background || "";
    $("#scene-crossfade").value = sc.crossfade_s;
    $("#scene-crossfade-out").textContent = sc.crossfade_s + "s";
    $("#scene-duck").checked = !!sc.duck;
    window.scrollTo(0, 0);
  }

  function clearForm() {
    editing = null;
    $("#scene-save").disabled = false;
    $("#scene-form-title").textContent = "New Scene";
    $("#scene-name").value = "";
    $("#scene-soundscape").value = "";
    $("#scene-background").value = "";
    $("#scene-crossfade").value = 1.5;
    $("#scene-crossfade-out").textContent = "1.5s";
    $("#scene-duck").checked = true;
  }

  function refresh() {
    return window.api("/api/config/scenes")
      .then(function (d) { render(d); return d; })
      .catch(function (e) { window.showError(e.message); });
  }

  $("#scene-crossfade").addEventListener("input", function () {
    $("#scene-crossfade-out").textContent = this.value + "s";
  });

  $("#scene-clear").addEventListener("click", clearForm);

  $("#scene-save").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    window.api("/api/config/scenes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("#scene-name").value,
        lights: $("#scene-lights").value,
        soundscape: $("#scene-soundscape").value,
        background: $("#scene-background").value,
        crossfade_s: parseFloat($("#scene-crossfade").value),
        duck: $("#scene-duck").checked
      })
    }).then(function (d) {
      render({ scenes: d.scenes, options: lastOptions });
      clearForm();
      // A new scene changes what the Run panel offers, so rebuild it rather
      // than leaving a stale grid until the next reload.
      if (window.rebuildVocabulary) window.rebuildVocabulary();
    }).catch(function (e) {
      window.showError(e.message);
    }).then(function () { btn.disabled = false; });
  });

  var lastOptions = {};
  document.addEventListener("panelshown", function (ev) {
    if (ev.detail !== "scenes") return;
    refresh().then(function (d) { if (d) lastOptions = d.options || {}; });
  });
})();
