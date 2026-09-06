/* Warlock Table — the interruption editor.
 *
 * An interruption layers over whatever is playing and then the table reverts
 * to it. Cards could always be re-pointed from the panel; making a brand-new
 * interruption still meant an ssh and a config edit. This is the other half
 * of the scene editor's job, and deliberately the same shape.
 *
 * TWO THINGS DIFFER FROM A SCENE, and both are real rather than cosmetic:
 *
 *  - Lights are OPTIONAL. Leaving them blank means "don't touch the current
 *    lighting", which is a genuinely useful card: a sound over whatever is
 *    already showing. So the rule cannot be "must have lights" — it is that
 *    the card must do SOMETHING, which the server enforces.
 *
 *  - There is a duration. With no sound, it is the whole timing story; with
 *    a sound, it is a floor, because the lights decide the length and a
 *    short clip should not cut a 9-second aura off mid-gesture.
 */

(function () {
  "use strict";

  var $ = function (s) { return document.querySelector(s); };
  var lastOptions = {};

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

  function render(data) {
    var opts = data.options || {};
    if (opts.audio || opts.lights || opts.backgrounds) lastOptions = opts;
    fill($("#int-audio"), opts.audio, "— no sound —");
    fill($("#int-lights"), opts.lights, "— leave the lights alone —");
    fill($("#int-background"), opts.backgrounds, "— no map —");

    var note = $("#int-duration-note");
    if (note) {
      note.textContent = opts.fallback_s
        ? "seconds — blank means as long as the sound runs, or "
          + opts.fallback_s + "s with no sound"
        : "seconds — optional";
    }

    var list = $("#int-list");
    list.innerHTML = "";
    $("#int-count").textContent = data.interruptions.length + " interruptions";

    data.interruptions.forEach(function (it) {
      var row = document.createElement("div");
      row.className = "card-row";

      var name = document.createElement("span");
      name.className = "uid";
      name.textContent = it.name;

      var detail = document.createElement("span");
      detail.className = "target";
      var bits = [];
      bits.push(it.audio || "no sound");
      bits.push(it.lights || "lights unchanged");
      if (it.background) bits.push(it.background);
      if (it.duration_s) bits.push(it.duration_s + "s");
      if (it.used_by && it.used_by.length) {
        bits.push(it.used_by.length + " card"
                  + (it.used_by.length === 1 ? "" : "s"));
      }
      detail.textContent = bits.join(" · ");

      var edit = document.createElement("button");
      edit.className = "small";
      edit.textContent = "Edit";
      edit.addEventListener("click", function () { load(it); });

      var del = document.createElement("button");
      del.className = "small";
      del.textContent = "Delete";
      // The server refuses to delete one a card still points at, so do not
      // offer a button that is going to fail. Same rule as the idle scene.
      var used = it.used_by && it.used_by.length;
      del.disabled = !!used;
      del.title = used ? "still used by " + it.used_by.join(", ") : "";
      del.addEventListener("click", function () {
        if (!window.confirm("Delete the interruption “" + it.name + "”?")) return;
        window.api("/api/config/interruptions/" + encodeURIComponent(it.name),
                   { method: "DELETE" })
          .then(function (d) {
            render({ interruptions: d.interruptions, options: lastOptions });
            if (window.rebuildVocabulary) window.rebuildVocabulary();
          })
          .catch(function (e) { window.showError(e.message); });
      });

      row.appendChild(name);
      row.appendChild(detail);
      row.appendChild(edit);
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  function load(it) {
    $("#int-form-title").textContent = "Editing " + it.name;
    $("#int-name").value = it.name;
    $("#int-audio").value = it.audio || "";
    $("#int-lights").value = it.lights || "";
    $("#int-background").value = it.background || "";
    $("#int-duration").value = it.duration_s == null ? "" : it.duration_s;
    $("#int-duck").checked = it.duck !== false;
    window.scrollTo(0, 0);
  }

  function clearForm() {
    $("#int-form-title").textContent = "New Interruption";
    $("#int-name").value = "";
    $("#int-audio").value = "";
    $("#int-lights").value = "";
    $("#int-background").value = "";
    $("#int-duration").value = "";
    $("#int-duck").checked = true;
  }

  function refresh() {
    return window.api("/api/config/interruptions")
      .then(function (d) { render(d); return d; })
      .catch(function (e) { window.showError(e.message); });
  }

  $("#int-clear").addEventListener("click", clearForm);

  $("#int-save").addEventListener("click", function () {
    var btn = this;
    var duration = $("#int-duration").value;
    btn.disabled = true;
    window.api("/api/config/interruptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("#int-name").value,
        audio: $("#int-audio").value,
        lights: $("#int-lights").value,
        background: $("#int-background").value,
        duration_s: duration === "" ? null : parseFloat(duration),
        duck: $("#int-duck").checked
      })
    }).then(function (d) {
      render({ interruptions: d.interruptions, options: lastOptions });
      clearForm();
      // A new interruption changes what the Run panel offers, so rebuild it
      // rather than leaving a stale grid until someone reloads.
      if (window.rebuildVocabulary) window.rebuildVocabulary();
    }).catch(function (e) {
      window.showError(e.message);
    }).then(function () { btn.disabled = false; });
  });

  document.addEventListener("panelshown", function (ev) {
    if (ev.detail !== "cards-edit") return;
    refresh();
  });
})();
