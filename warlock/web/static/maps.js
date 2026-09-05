/* Warlock Table — map import (map-import-specification.md).
 *
 * Two views in one page: the library, and the editor. Kept out of app.js
 * because it shares nothing with the rest of the panel — no polling, no
 * controller state, no scene wiring. It borrows `goto`, `api` and
 * `showError` off window and is otherwise self-contained.
 *
 * THE ONE RULE THAT SHAPES THIS FILE (spec section 2): every control is
 * always live. Auto-detection only ever pre-fills the sliders. Nothing here
 * disables a control, hides one, or branches on whether detection succeeded
 * — because detection WILL be wrong sometimes, and the whole design is
 * arranged so that when it is, the cost is one slider drag.
 *
 * SCALE IS AN EXPONENTIAL SLIDER. A linear one is useless here: the
 * interesting range runs from about 0.1x to 8x, and on a linear track
 * everything below 1x is crushed into the first eighth of the travel. The
 * slider carries log2(scale), so each unit is a doubling and the whole
 * range is reachable with the same sensitivity everywhere.
 */

(function () {
  "use strict";

  var $ = function (sel) { return document.querySelector(sel); };

  var session = null;      // the open editing session, or null
  var state = null;        // last payload from the server
  var previewing = false;  // is the table currently showing our render
  var pending = false;     // a preview render is in flight
  var queued = false;      // ...and another change arrived while it was

  // ---------------------------------------------------------------- library

  function bytes(n) {
    if (!n) return "0 MB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function loadLibrary() {
    window.api("/api/maps").then(function (data) {
      var list = $("#map-list");
      list.innerHTML = "";
      $("#map-count").textContent =
        data.maps.length ? data.maps.length + " saved" : "";

      if (!data.maps.length) {
        var empty = document.createElement("p");
        empty.className = "note";
        empty.textContent = "Nothing uploaded yet.";
        list.appendChild(empty);
      }

      data.maps.forEach(function (m) {
        var row = document.createElement("div");
        row.className = "card-row";

        var name = document.createElement("span");
        name.className = "uid";
        name.textContent = m.title;

        var detail = document.createElement("span");
        detail.className = "target";
        var bits = [bytes(m.bytes)];
        // A map scaled down to fit no longer has 5 ft squares, and that is
        // exactly the thing you want to know before standing minis on it.
        if (Math.abs(m.feet_per_square - 5) > 0.05) {
          bits.push(m.feet_per_square.toFixed(1) + " ft squares");
        }
        if (!m.present) bits.push("FILES MISSING");
        detail.textContent = bits.join(" · ");

        var del = document.createElement("button");
        del.className = "small";
        del.textContent = "Delete";
        del.addEventListener("click", function (ev) {
          ev.stopPropagation();
          if (!window.confirm("Delete “" + m.title +
                              "”? This removes the image, the original " +
                              "and its settings.")) return;
          window.api("/api/maps/" + encodeURIComponent(m.slug),
                     { method: "DELETE" })
            .then(loadLibrary)
            .catch(function (e) { window.showError(e.message); });
        });

        row.appendChild(name);
        row.appendChild(detail);
        row.appendChild(del);
        list.appendChild(row);
      });

      var usage = $("#map-usage");
      usage.textContent = "Using " + bytes(data.usage.total_bytes) +
        " on the table" + (data.usage.over_warn ? " — getting full." : ".");
      usage.classList.toggle("warn-text", !!data.usage.over_warn);
    }).catch(function (e) {
      $("#map-list").innerHTML = "";
      $("#map-usage").textContent = e.message;
    });
  }

  // ----------------------------------------------------------------- upload

  $("#map-upload-btn").addEventListener("click", function () {
    $("#map-file").click();
  });

  $("#map-file").addEventListener("change", function (ev) {
    var file = ev.target.files && ev.target.files[0];
    if (!file) return;
    ev.target.value = "";     // so re-picking the same file fires again

    var btn = $("#map-upload-btn");
    btn.disabled = true;
    btn.textContent = "Reading “" + file.name + "”…";

    // A raw PUT, not multipart: the body IS the file. See web/maps.py for
    // why — multipart in a stdlib server means the deprecated cgi module.
    fetch("/api/maps/upload?name=" + encodeURIComponent(file.name), {
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream" },
      body: file
    }).then(function (res) {
      return res.json().then(function (j) {
        if (!res.ok) throw new Error(j.error || res.statusText);
        return j;
      });
    }).then(function (info) {
      openEditor(info);
    }).catch(function (e) {
      window.showError(e.message);
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Upload an Image";
    });
  });

  // ----------------------------------------------------------------- editor

  function openEditor(info) {
    session = info.id;
    previewing = false;
    $("#map-restore").hidden = true;
    $("#maps-library").hidden = true;
    $("#maps-editor").hidden = false;
    $("#map-title").value = info.title || "";
    apply(info);
    window.scrollTo(0, 0);
  }

  function closeEditor() {
    if (previewing) stopPreview();
    session = null;
    state = null;
    $("#maps-editor").hidden = true;
    $("#maps-library").hidden = false;
    loadLibrary();
  }

  $("#map-cancel").addEventListener("click", closeEditor);

  /* Push server state into the controls. */
  function apply(info) {
    state = info;
    var t = info.transform;

    setSlider("#s-scale", "#o-scale", Math.log2(t.scale),
              t.scale.toFixed(3) + "×");
    setSlider("#s-panx", "#o-panx", t.pan_x, Math.round(t.pan_x) + " px");
    setSlider("#s-pany", "#o-pany", t.pan_y, Math.round(t.pan_y) + " px");
    setSlider("#s-rot", "#o-rot", t.rotation, t.rotation.toFixed(1) + "°");
    setSlider("#s-bright", "#o-bright", info.brightness,
              Math.round(info.brightness * 100) + "%");
    setSlider("#s-contrast", "#o-contrast", info.contrast,
              Math.round(info.contrast * 100) + "%");

    $("#map-drawgrid").checked = !!info.draw_grid;
    $("#map-black").checked = !!info.plain_black;

    var squares = $("#map-squares");
    if (document.activeElement !== squares) {
      squares.value = info.fit.squares_wide;
    }

    $("#map-detect").textContent = info.detection.message || "";

    var warn = $("#map-warn");
    warn.textContent = info.warning || "";
    warn.hidden = !info.warning;

    // The fit decision (spec 8.4). Offered, never taken automatically:
    // cropping and shrinking the squares are both legitimate, and which one
    // is right depends on the game, not on the arithmetic.
    var fit = $("#map-fit");
    if (info.fit.fits) {
      fit.hidden = true;
    } else {
      fit.hidden = false;
      fit.innerHTML = "";
      var msg = document.createElement("div");
      msg.textContent = info.fit.message;
      fit.appendChild(msg);
      var shrink = document.createElement("button");
      shrink.className = "small";
      shrink.textContent = "Scale it down to fit";
      shrink.addEventListener("click", function () { adjust({ fit: "scale_down" }); });
      fit.appendChild(shrink);
      var keep = document.createElement("span");
      keep.className = "note";
      keep.textContent = " or leave it and the edges will be cropped.";
      fit.appendChild(keep);
    }

    refreshPreview();
  }

  function setSlider(slider, output, value, label) {
    var el = $(slider);
    // Never fight the user's thumb: if they are dragging this control right
    // now, the server's echo of its own value must not yank it.
    if (document.activeElement !== el) el.value = value;
    $(output).textContent = label;
  }

  // ---------------------------------------------------------------- changes

  function adjust(changes) {
    if (!session) return;
    return window.api("/api/maps/" + session + "/adjust", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes)
    }).then(apply).catch(function (e) { window.showError(e.message); });
  }

  /* Slider drags fire continuously; renders take a moment. Coalesce them:
   * one render in flight, at most one waiting, and the waiting one always
   * carries the newest values. Without this a drag queues thirty renders
   * and the preview lags seconds behind the thumb. */
  var debounce = null;
  function live(changes) {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(function () { adjust(changes); }, 120);
  }

  function bindSlider(sel, key, transform, format) {
    $(sel).addEventListener("input", function () {
      var raw = parseFloat(this.value);
      var value = transform ? transform(raw) : raw;
      var out = $(sel.replace("#s-", "#o-"));
      if (out) out.textContent = format(value);
      var change = {};
      change[key] = value;
      live(change);
    });
  }

  bindSlider("#s-scale", "scale", function (v) { return Math.pow(2, v); },
             function (v) { return v.toFixed(3) + "×"; });
  bindSlider("#s-panx", "pan_x", null, function (v) { return Math.round(v) + " px"; });
  bindSlider("#s-pany", "pan_y", null, function (v) { return Math.round(v) + " px"; });
  bindSlider("#s-rot", "rotation", null, function (v) { return v.toFixed(1) + "°"; });
  bindSlider("#s-bright", "brightness", null,
             function (v) { return Math.round(v * 100) + "%"; });
  bindSlider("#s-contrast", "contrast", null,
             function (v) { return Math.round(v * 100) + "%"; });

  // Nudges. A slider cannot be dragged to a precise sub-square offset on a
  // tablet, and grid PHASE is exactly where precision matters — half a
  // square out puts every miniature in the wrong place.
  document.querySelectorAll("[data-nudge]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!state) return;
      var key = btn.dataset.nudge;
      var change = {};
      change[key] = state.transform[key] + parseFloat(btn.dataset.by);
      adjust(change);
    });
  });

  document.querySelectorAll("[data-set]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var change = {};
      change[btn.dataset.set] = parseFloat(btn.dataset.by);
      adjust(change);
    });
  });

  $("#map-squares").addEventListener("change", function () {
    var n = parseFloat(this.value);
    if (n > 0) adjust({ squares_across: n });
  });

  $("#map-recentre").addEventListener("click", function () {
    adjust({ pan_x: 0, pan_y: 0 });
  });

  $("#map-realign").addEventListener("click", function () {
    adjust({ realign_grid: true });
  });

  $("#map-drawgrid").addEventListener("change", function () {
    adjust({ draw_grid: this.checked });
  });

  $("#map-black").addEventListener("change", function () {
    adjust({ plain_black: this.checked });
  });

  $("#map-title").addEventListener("change", function () {
    adjust({ title: this.value });
  });

  // ---------------------------------------------------------------- preview

  function refreshPreview() {
    if (!session) return;
    if (pending) { queued = true; return; }
    pending = true;
    $("#map-busy").hidden = false;

    var img = $("#map-preview");
    var url = "/api/maps/" + session + "/preview.png?width=960&t=" + Date.now();
    var next = new Image();
    next.onload = function () {
      img.src = next.src;
      pending = false;
      $("#map-busy").hidden = true;
      if (queued) { queued = false; refreshPreview(); }
    };
    next.onerror = function () {
      pending = false;
      $("#map-busy").hidden = true;
    };
    next.src = url;
  }

  $("#map-to-table").addEventListener("click", function () {
    if (!session) return;
    var btn = this;
    btn.disabled = true;
    btn.textContent = "Rendering…";
    window.api("/api/maps/" + session + "/preview", { method: "POST" })
      .then(function () {
        previewing = true;
        $("#map-restore").hidden = false;
      })
      .catch(function (e) { window.showError(e.message); })
      .then(function () {
        btn.disabled = false;
        btn.textContent = "Show on Table";
      });
  });

  function stopPreview() {
    return window.api("/api/maps/preview/stop", { method: "POST" })
      .then(function () {
        previewing = false;
        $("#map-restore").hidden = true;
      }).catch(function () { /* the table is fine either way */ });
  }

  $("#map-restore").addEventListener("click", stopPreview);

  // ---------------------------------------------------------------- publish

  $("#map-publish").addEventListener("click", function () {
    if (!session) return;
    var title = ($("#map-title").value || "").trim();
    if (!title) {
      window.showError("Give the map a name first.");
      $("#map-title").focus();
      return;
    }
    var btn = this;
    btn.disabled = true;
    btn.textContent = "Saving…";
    window.api("/api/maps/" + session + "/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title })
    }).then(function () {
      session = null;
      previewing = false;
      $("#maps-editor").hidden = true;
      $("#maps-library").hidden = false;
      loadLibrary();
    }).catch(function (e) {
      window.showError(e.message);
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Save to the Table";
    });
  });

  // Load the library the first time the page is opened, not at startup:
  // most sessions never come in here, and the listing reads the disk.
  var opened = false;
  var openBtn = document.getElementById("open-maps");
  if (openBtn) {
    openBtn.addEventListener("click", function () {
      if (!opened) { opened = true; }
      loadLibrary();
    });
  }
})();
