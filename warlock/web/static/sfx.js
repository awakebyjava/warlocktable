/* Warlock Table — sound effect switches.
 *
 * Three levels, coarse to fine, because 54 toggles is too many to be the only
 * way in:
 *
 *   profiles   one tap for a whole sensible set
 *   families   the eight groups
 *   sounds     the individual switch, for the one that grates
 *
 * Every sound also has a speaker button, and it plays even when the sound is
 * switched OFF — you cannot decide about something you are not allowed to
 * hear. That is the one deliberate inconsistency here.
 */

(function () {
  "use strict";

  var $ = function (s) { return document.querySelector(s); };
  var listed = null;      // the full sound list, fetched once per open

  function post(path, body) {
    return window.api("/api/sfx/" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }

  // --- the small entry in Settings ---------------------------------------

  function renderEntry(s) {
    var box = $("#sfx-enabled");
    if (box) box.checked = !!s.enabled;
    var state = $("#sfx-state");
    if (!state) return;
    if (!s.enabled) state.textContent = "off";
    else if (!s.running || !s.healthy) state.textContent = "not running";
    else {
      var on = s.families.filter(function (f) { return f.on; }).length;
      state.textContent = s.sounds + " sounds, " + on + " of " +
                          s.families.length + " groups on";
    }
  }

  // --- the page -----------------------------------------------------------

  function renderPage(s) {
    renderEntry(s);

    var profiles = $("#sfx-profiles");
    profiles.innerHTML = "";
    (s.profiles || []).forEach(function (name) {
      var b = document.createElement("button");
      b.textContent = name;
      b.addEventListener("click", function () {
        post("profile", { profile: name }).then(refresh)
          .catch(function (e) { window.showError(e.message); });
      });
      profiles.appendChild(b);
    });

    var fams = $("#sfx-families");
    fams.innerHTML = "";
    (s.families || []).forEach(function (f) {
      var row = document.createElement("div");
      row.className = "check-row";
      row.style.gridTemplateColumns = "1fr";

      var label = document.createElement("label");
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = f.on;
      box.addEventListener("change", function () {
        post("family", { family: f.name, on: box.checked }).then(refresh)
          .catch(function (e) { window.showError(e.message); });
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode(
        " " + f.name + "  ·  " + f.count + " sounds" +
        (f.muted ? ", " + f.muted + " switched off individually" : "") +
        (f.ducks ? "  ·  dips the soundscape" : "")));
      row.appendChild(label);
      fams.appendChild(row);
    });
  }

  function renderList(sounds, status) {
    listed = sounds;
    var off = {};
    (status.families || []).forEach(function (f) { off[f.name] = !f.on; });

    var list = $("#sfx-list");
    list.innerHTML = "";
    $("#sfx-count").textContent = sounds.length + " total";

    var family = null;
    sounds.forEach(function (snd) {
      if (snd.family !== family) {
        family = snd.family;
        var head = document.createElement("h2");
        head.textContent = family;
        head.style.marginTop = "18px";
        list.appendChild(head);
      }

      var row = document.createElement("div");
      row.className = "card-row";

      var play = document.createElement("button");
      play.className = "small";
      play.textContent = "▶";
      play.title = "Hear it, whether it is switched on or not";
      play.addEventListener("click", function (ev) {
        ev.stopPropagation();
        post("play", { sound: snd.id })
          .catch(function (e) { window.showError(e.message); });
      });

      var name = document.createElement("span");
      name.className = "uid";
      name.textContent = snd.id;

      var what = document.createElement("span");
      what.className = "target";
      what.textContent = snd.present ? (snd.intent || "") : "AUDIO MISSING";

      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = snd.on;
      // A sound inside a switched-off family cannot be on; show that rather
      // than letting the tick lie about what will happen.
      box.disabled = off[snd.family];
      box.title = off[snd.family]
        ? "the " + snd.family + " group is switched off"
        : "play this sound";
      box.addEventListener("change", function () {
        post("mute", { sound: snd.id, on: box.checked }).then(function (st) {
          renderPage(st);
        }).catch(function (e) { window.showError(e.message); });
      });

      row.appendChild(play);
      row.appendChild(name);
      row.appendChild(what);
      row.appendChild(box);
      list.appendChild(row);
    });
  }

  function refresh() {
    return window.api("/api/sfx").then(function (s) {
      renderPage(s);
      return window.api("/api/sfx/sounds").then(function (d) {
        renderList(d.sounds, s);
        return s;
      });
    }).catch(function (e) { window.showError(e.message); });
  }

  // --- wiring -------------------------------------------------------------

  var box = $("#sfx-enabled");
  if (box) {
    box.addEventListener("change", function () {
      post("enabled", { enabled: box.checked }).then(renderEntry)
        .catch(function (e) { window.showError(e.message); });
    });
  }

  // Load when the page is shown, however it was reached.
  document.addEventListener("panelshown", function (ev) {
    if (ev.detail === "sfx") refresh();
  });

  window.api("/api/sfx").then(renderEntry).catch(function () {
    var entry = document.getElementById("sfx-entry");
    if (entry) entry.hidden = true;    // older build, no endpoint
  });
})();
