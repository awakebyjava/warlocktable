/* Warlock Table — accounts, for the table owner.
 *
 * The user list with emails; add, rename, reset a PIN, export a library,
 * delete. Same shape as the other editors. Two things are deliberate:
 *
 *  - Delete shows what goes with the account first -- scenes, cards, maps
 *    -- because "block with a list" is the rule everywhere else (4.5) and
 *    an account is the biggest thing that can be deleted.
 *  - A PIN reset does not set a PIN: it clears it, signs the person out
 *    everywhere, and their next sign-in asks them to choose one. Nobody
 *    else ever knows anyone's PIN.
 */

(function () {
  "use strict";

  var $ = function (s) { return document.querySelector(s); };
  var editing = null;

  function post(path, body) {
    return window.api(path, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  }

  function render(users) {
    var list = $("#adm-list");
    list.innerHTML = "";
    $("#adm-count").textContent = users.length + (users.length === 1 ? " account" : " accounts");
    users.forEach(function (u) {
      var row = document.createElement("div");
      row.className = "card-row";
      var name = document.createElement("span");
      name.className = "uid";
      name.textContent = u.name + (u.role === "admin" ? "  ·  table owner" : "");
      var detail = document.createElement("span");
      detail.className = "target";
      detail.textContent = u.email + (u.has_pin ? "" : "  ·  no PIN yet");

      var edit = document.createElement("button");
      edit.className = "small"; edit.textContent = "Edit";
      edit.addEventListener("click", function () { load(u); });

      var reset = document.createElement("button");
      reset.className = "small"; reset.textContent = "Reset PIN";
      reset.addEventListener("click", function () {
        if (!window.confirm("Clear " + u.name + "'s PIN and sign them out everywhere? "
                            + "They choose a new one at their next sign-in.")) return;
        post("/api/auth/admin/users/" + encodeURIComponent(u.id) + "/reset-pin")
          .then(refresh).catch(function (e) { window.showError(e.message); });
      });

      var exp = document.createElement("a");
      exp.className = "small";
      exp.textContent = "Export";
      exp.href = "/api/auth/admin/users/" + encodeURIComponent(u.id) + "/export";
      exp.setAttribute("download", "");
      // An <a download>, not a button: the browser saves the zip. Dressed
      // like the buttons beside it.
      exp.style.cssText = "display:inline-block;padding:6px 10px;border:1px solid var(--line);"
        + "border-radius:2px;text-decoration:none;color:var(--bone);font:inherit;"
        + "font-size:11px;letter-spacing:.08em;text-transform:uppercase";

      var del = document.createElement("button");
      del.className = "small"; del.textContent = "Delete";
      del.disabled = u.role === "admin";
      del.title = u.role === "admin" ? "the table owner cannot be deleted" : "";
      del.addEventListener("click", function () { confirmDelete(u); });

      row.appendChild(name); row.appendChild(detail);
      row.appendChild(edit); row.appendChild(reset); row.appendChild(exp); row.appendChild(del);
      list.appendChild(row);
    });
  }

  async function confirmDelete(u) {
    var f;
    try { f = await window.api("/api/auth/admin/users/" + encodeURIComponent(u.id) + "/footprint"); }
    catch (e) { window.showError(e.message); return; }
    var bits = [];
    if (f.scenes) bits.push(f.scenes + " scene" + (f.scenes === 1 ? "" : "s"));
    if (f.interruptions) bits.push(f.interruptions + " interruption" + (f.interruptions === 1 ? "" : "s"));
    if (f.random_tables) bits.push(f.random_tables + " random table" + (f.random_tables === 1 ? "" : "s"));
    if (f.cards.length) bits.push(f.cards.length + " card" + (f.cards.length === 1 ? "" : "s")
      + " (" + f.cards.map(function (c) { return c.label; }).join(", ") + ") — those tags become unknown to the table");
    if (f.maps) bits.push(f.maps + " map file" + (f.maps === 1 ? "" : "s"));
    if (f.sounds) bits.push(f.sounds + " sound file" + (f.sounds === 1 ? "" : "s"));
    var msg = "Delete " + u.name + "'s account?" + (bits.length
      ? "\n\nThis also removes their library:\n  • " + bits.join("\n  • ")
        + "\n\nExport it first if any of that is worth keeping."
      : "\n\nTheir library is empty.");
    if (!window.confirm(msg)) return;
    window.api("/api/auth/admin/users/" + encodeURIComponent(u.id), { method: "DELETE" })
      .then(refresh).catch(function (e) { window.showError(e.message); });
  }

  function load(u) {
    editing = u.id;
    $("#adm-form-title").textContent = "Editing " + u.name;
    $("#adm-name").value = u.name;
    $("#adm-email").value = u.email;
    $("#adm-pin").value = "";
    $("#adm-pin-field").hidden = true;      // PINs are reset, never typed by the admin
    window.scrollTo(0, 0);
  }

  function clearForm() {
    editing = null;
    $("#adm-form-title").textContent = "New Account";
    $("#adm-name").value = "";
    $("#adm-email").value = "";
    $("#adm-pin").value = "";
    $("#adm-pin-field").hidden = false;
  }

  function refresh() {
    return window.api("/api/auth/admin/users")
      .then(function (d) { render(d.users || []); })
      .catch(function (e) { window.showError(e.message); });
  }

  $("#adm-clear").addEventListener("click", clearForm);
  $("#adm-save").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    var body = { name: $("#adm-name").value, email: $("#adm-email").value };
    var p;
    if (editing) {
      p = post("/api/auth/admin/users/" + encodeURIComponent(editing), body);
    } else {
      var pin = $("#adm-pin").value.trim();
      if (pin) body.pin = pin;
      p = post("/api/auth/admin/users", body);
    }
    p.then(function () { clearForm(); return refresh(); })
     .catch(function (e) { window.showError(e.message); })
     .then(function () { btn.disabled = false; });
  });

  document.addEventListener("panelshown", function (ev) {
    if (ev.detail !== "admin") return;
    clearForm();
    refresh();
  });
})();
