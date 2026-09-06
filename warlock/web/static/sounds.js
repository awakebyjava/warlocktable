/* Warlock Table — uploading sound through the panel.
 *
 * Lives on the Sound Effects page, because that is where sound already is.
 *
 * THE KIND IS THE ONLY THING THE OPERATOR HAS TO DECIDE, and it is not
 * cosmetic: a bed and a cue are loop-closed and levelled to a target, while
 * a one-shot is neither. Crossfading a sting's tail over its attack destroys
 * it, and RMS-levelling a short hit makes its loudness depend on how much
 * silence trails it — measured at 8.7 dB for the same sound. So the choice
 * is three plain buttons rather than a dropdown someone can skip past.
 *
 * The upload is a raw PUT: the body IS the file. Same as map import, and for
 * the same reason — multipart in a stdlib server means the deprecated `cgi`
 * module or a hand-rolled parser.
 */

(function () {
  "use strict";

  var $ = function (s) { return document.querySelector(s); };
  var kind = "effect";          // the safe default: does the least to a file
  var kinds = [];
  var busy = false;

  function human(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  function drawKinds() {
    var row = $("#sound-kind-row");
    if (!row) return;
    row.innerHTML = "";
    kinds.forEach(function (k) {
      var b = document.createElement("button");
      b.textContent = k.label;
      b.dataset.kind = k.kind;
      b.classList.toggle("active", k.kind === kind);
      b.title = k.loops
        ? "Loops under a scene. Levelled to match, and its loop join is closed."
        : "Plays once. Left alone apart from its peak level.";
      b.addEventListener("click", function () {
        kind = k.kind;
        drawKinds();
      });
      row.appendChild(b);
    });
  }

  function drawList(uploads) {
    var list = $("#sound-list");
    if (!list) return;
    list.innerHTML = "";

    var rows = [];
    ["track", "cue"].forEach(function (group) {
      (uploads[group] || []).forEach(function (r) {
        r.group = group;
        rows.push(r);
      });
    });

    $("#sound-count").textContent =
      rows.length ? rows.length + (rows.length === 1 ? " sound" : " sounds") : "";

    if (!rows.length) {
      list.appendChild(Object.assign(document.createElement("p"),
        { className: "note", textContent: "Nothing uploaded yet." }));
      return;
    }

    rows.forEach(function (r) {
      var row = document.createElement("div");
      row.className = "card-row";

      var name = document.createElement("span");
      name.className = "uid";
      name.textContent = r.name;

      var detail = document.createElement("span");
      detail.className = "target";
      detail.textContent = (r.group === "cue" ? "music cue" : "track") +
        " · " + human(r.bytes) + " · " + r.uploaded_text;

      var del = document.createElement("button");
      del.className = "small";
      del.textContent = "Delete";
      del.addEventListener("click", function () {
        if (!window.confirm("Delete the uploaded sound “" + r.name + "”?\n\n" +
                            "Anything pointing at it will fall back to a file of " +
                            "the same name shipped with the table, if there is one.")) return;
        window.api("/api/sounds/" + encodeURIComponent(r.group) + "/" +
                   encodeURIComponent(r.name), { method: "DELETE" })
          .then(render)
          .catch(function (e) { window.showError(e.message); });
      });

      row.appendChild(name);
      row.appendChild(detail);
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  function render(d) {
    if (!d) return;
    if (d.kinds && d.kinds.length) {
      kinds = d.kinds;
      if (!kinds.some(function (k) { return k.kind === kind; })) {
        kind = kinds[0].kind;
      }
      drawKinds();
    }
    drawList(d.uploads || {});

    var btn = $("#sound-upload-btn");
    var note = $("#sound-note");
    if (d.can_import === false) {
      if (btn) btn.disabled = true;
      // An actionable message — usually one apt install — rather than a
      // control that looks live and fails on use.
      if (note) {
        note.textContent = d.error || "Uploading sound is not available on this table.";
        note.classList.add("warn-text");
      }
    } else {
      if (btn) btn.disabled = busy;
      if (note && !busy) {
        note.textContent = d.error || "";
        note.classList.toggle("warn-text", !!d.error);
      }
    }
  }

  function showResult(info) {
    var box = $("#sound-result");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = "";

    var h = document.createElement("p");
    h.innerHTML = "<b>" + info.name + "</b> added as a " +
      info.label.toLowerCase() + ".";
    box.appendChild(h);

    var facts = document.createElement("p");
    facts.className = "note";
    facts.textContent = info.after.seconds + "s · " +
      info.after.rms_db + " dB · " + human(info.bytes);
    box.appendChild(facts);

    // What was actually done to the file. Silent conversion is how you end
    // up not knowing why something sounds different from the original.
    (info.notes || []).forEach(function (n) {
      var p = document.createElement("p");
      p.className = "note";
      p.textContent = "· " + n;
      box.appendChild(p);
    });

    if (info.shadows) {
      var w = document.createElement("p");
      w.className = "note warn-text";
      w.textContent = "This now plays instead of " + info.shadows +
        ", which has the same name. That file is untouched — delete this " +
        "upload to go back to it.";
      box.appendChild(w);
    }
  }

  function upload(file) {
    if (!file || busy) return;
    busy = true;
    var btn = $("#sound-upload-btn");
    var note = $("#sound-note");
    if (btn) { btn.disabled = true; btn.classList.add("busy"); }
    if (note) {
      note.classList.remove("warn-text");
      note.textContent = "Converting " + file.name + "… large files take a moment.";
    }

    var q = "?kind=" + encodeURIComponent(kind) +
            "&name=" + encodeURIComponent(file.name);
    var as = ($("#sound-name").value || "").trim();
    if (as) q += "&as=" + encodeURIComponent(as);

    // A raw PUT: the body IS the file. See web/sounds.py.
    fetch("/api/sounds/upload" + q, { method: "PUT", body: file })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error(d.error || ("HTTP " + r.status));
          return d;
        });
      })
      .then(function (info) {
        showResult(info);
        $("#sound-name").value = "";
        if (note) note.textContent = "";
        // The Run panel's cue list and every track picker just changed.
        if (info.kind === "cue" && window.rebuildVocabulary) {
          window.rebuildVocabulary();
        }
        return window.api("/api/sounds").then(render);
      })
      .catch(function (e) {
        if (note) {
          note.textContent = e.message;
          note.classList.add("warn-text");
        }
      })
      .then(function () {
        busy = false;
        if (btn) { btn.disabled = false; btn.classList.remove("busy"); }
      });
  }

  var picker = $("#sound-file");
  var btn = $("#sound-upload-btn");
  if (btn && picker) {
    btn.addEventListener("click", function () { picker.click(); });
    picker.addEventListener("change", function () {
      var f = picker.files && picker.files[0];
      // Cleared so choosing the SAME file twice fires change again — the
      // ordinary case of "that came out wrong, try it as a cue instead".
      picker.value = "";
      upload(f);
    });
  }

  document.addEventListener("panelshown", function (ev) {
    if (ev.detail !== "sfx") return;
    window.api("/api/sounds").then(render).catch(function () {
      // An older build with no /api/sounds: hide the section rather than
      // leaving controls that cannot work.
      var s = document.getElementById("sound-upload-section");
      if (s) s.hidden = true;
    });
  });
})();
