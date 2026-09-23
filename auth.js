// PortlandLive -- Fork Stage 1: Supabase accounts (sign up / log in / log out)
// Stage 10 Part 1 added handles: a required @handle at sign-up
// (handle_available RPC, stored via handle_new_user), the caller's own
// handle in the header menu (my_handle RPC -- profiles.handle is not
// selectable by any client role, see supabase/schema-handles.sql), and a
// one-time rename for accounts whose handle was assigned from their name
// (set_handle RPC).
//
// This is the ONLY backend surface at this stage: an auth.users identity
// plus a display_name in public.profiles. No comments, no ticket posts, no
// messaging live yet -- see BUILDLOG.md / the PR description for scope.
//
// SUPABASE_ANON_KEY below is the public/anon key. It is meant to be shipped
// in client-side code -- Supabase's Row Level Security (see supabase/schema.sql)
// is what actually protects data, not secrecy of this key. The service_role
// key must NEVER appear here, in any client-side file, or in a commit.
(function () {
  "use strict";

  const SUPABASE_URL = "https://mhdysfdqoqrohlltgsig.supabase.co";
  const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1oZHlzZmRxb3Fyb2hsbHRnc2lnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODczMjg4OTgsImV4cCI6MjEwMjkwNDg5OH0.8-U0mRC32n1oGL0JaK3iK54L3pJDoDhuXRmOXQih-h0";

  if (!window.supabase || typeof window.supabase.createClient !== "function") {
    console.error("[auth] supabase-js failed to load; auth is disabled.");
    return;
  }
  if (!SUPABASE_URL || SUPABASE_URL.indexOf("__") === 0 || !SUPABASE_ANON_KEY || SUPABASE_ANON_KEY.indexOf("__") === 0) {
    console.warn("[auth] Supabase credentials not configured yet; auth is disabled.");
    return;
  }

  const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
  });
  // Exposed only so the browser console / test harness can drive the same
  // client the UI uses when verifying auth end to end. Not used by any other
  // page script.
  window.__plAuth = sb;

  const $ = (id) => document.getElementById(id);

  const el = {
    signInBtn: $("authSignInBtn"),
    userPill: $("authUserPill"),
    displayName: $("authDisplayName"),
    quickMenuAccount: $("quickMenuAccount"),
    menuBtn: $("authMenuBtn"),
    menu: $("authMenu"),
    logoutBtn: $("authLogoutBtn"),
    overlay: $("authOverlay"),
    sheet: $("authSheet"),
    close: $("authClose"),
    tabSignIn: $("authTabSignIn"),
    tabSignUp: $("authTabSignUp"),
    title: $("authTitle"),
    form: $("authForm"),
    displayNameField: $("authDisplayNameField"),
    displayNameInput: $("authDisplayNameInput"),
    handleField: $("authHandleField"),
    handleInput: $("authHandleInput"),
    handle: $("authHandle"),
    handleEditor: $("handleEditor"),
    visibilityEditor: $("visibilityEditor"),
    nameEditor: $("nameEditor"),
    tickerEditor: $("tickerEditor"),
    emailInput: $("authEmailInput"),
    passwordInput: $("authPasswordInput"),
    submitBtn: $("authSubmitBtn"),
    msg: $("authMsg")
  };

  let mode = "signin"; // "signin" | "signup"

  function setMode(next) {
    mode = next;
    const isSignUp = mode === "signup";
    el.tabSignIn.classList.toggle("active", !isSignUp);
    el.tabSignUp.classList.toggle("active", isSignUp);
    el.displayNameField.hidden = !isSignUp;
    el.displayNameInput.required = isSignUp;
    if (el.handleField) el.handleField.hidden = !isSignUp;
    if (el.handleInput) el.handleInput.required = isSignUp;
    el.passwordInput.autocomplete = isSignUp ? "new-password" : "current-password";
    el.title.textContent = isSignUp ? "Sign Up" : "Sign In";
    el.submitBtn.textContent = isSignUp ? "Create account" : "Sign In";
    setMsg("");
  }

  function setMsg(text, isError) {
    el.msg.textContent = text || "";
    el.msg.classList.toggle("auth-msg-error", !!isError);
  }

  function openSheet(startMode) {
    setMode(startMode || "signin");
    el.form.reset();
    el.overlay.classList.add("open");
    el.overlay.setAttribute("aria-hidden", "false");
    (mode === "signup" ? el.displayNameInput : el.emailInput).focus();
  }

  function closeSheet() {
    el.overlay.classList.remove("open");
    el.overlay.setAttribute("aria-hidden", "true");
    setMsg("");
  }

  function renderLoggedOut() {
    el.signInBtn.hidden = false;
    el.userPill.hidden = true;
    el.menu.hidden = true;
    // #authUserPill above is the RETIRED container (permanently hidden; kept
    // only because this file still looks it up by id). The row people actually
    // see is #quickMenuAccount inside the header quick-menu, and nothing was
    // clearing it -- so after signing out the header kept saying "Signed in as
    // <name>" until a reload. Clear the visible one too.
    if (el.quickMenuAccount) el.quickMenuAccount.hidden = true;
    if (el.displayName) el.displayName.textContent = "";
    if (el.handle) el.handle.textContent = "";
    renderHandleEditor(null);
    renderNameEditor(null, null);
    renderVisibilityEditor(null, null);
    renderTickerEditor(null);
  }

  // The header quick-menu is closed by its own outside-click handler in
  // index.html; a link inside it navigates without an outside click, so
  // close it the way handleLogout does.
  function closeQuickMenu() {
    const qlist = document.getElementById("quickMenuList");
    const qbtn = document.getElementById("quickMenuBtn");
    if (qlist) qlist.hidden = true;
    if (qbtn) qbtn.setAttribute("aria-expanded", "false");
  }

  function renderLoggedIn(displayName, handleInfo, visibility, userId) {
    el.signInBtn.hidden = true;
    el.userPill.hidden = false;
    el.displayName.textContent = displayName || "Account";
    el.menu.hidden = true;
    if (el.quickMenuAccount) el.quickMenuAccount.hidden = false;
    if (el.handle) {
      // Your @handle links to your own profile page (Stage 10 Part 2). The
      // handle charset is [A-Za-z0-9_] by database CHECK, so it is inert in
      // both the href and the text.
      if (handleInfo && handleInfo.handle) {
        el.handle.innerHTML = '<a href="#/u/' + encodeURIComponent(handleInfo.handle) + '">@' + handleInfo.handle + "</a>";
        const a = el.handle.querySelector("a");
        if (a) a.addEventListener("click", closeQuickMenu);
      } else {
        el.handle.textContent = "";
      }
    }
    renderHandleEditor(handleInfo);
    renderNameEditor(displayName, userId);
    renderVisibilityEditor(visibility, userId);
    renderTickerEditor(userId);
  }

  async function fetchDisplayName(userId) {
    const { data, error } = await sb
      .from("profiles")
      .select("display_name")
      .eq("id", userId)
      .single();
    if (error) {
      console.warn("[auth] could not load profile:", error.message);
      return null;
    }
    return data && data.display_name;
  }

  // profiles.handle is granted to no client role (D3), so even your own is
  // read through a SECURITY DEFINER function. Returns
  // { handle, rename_available } or null.
  async function fetchMyHandle() {
    try {
      const { data, error } = await sb.rpc("my_handle");
      if (error) {
        console.warn("[auth] my_handle unavailable:", error.message);
        return null;
      }
      const row = Array.isArray(data) ? data[0] : data;
      return row && row.handle ? { handle: row.handle, rename_available: !!row.rename_available } : null;
    } catch (err) {
      console.warn("[auth] my_handle threw:", err);
      return null;
    }
  }

  // upcoming_visibility has an explicit column grant (schema-profile-pages.sql),
  // and profiles_update_own scopes the write to your own row. Returns
  // 'followers' | 'public' | null.
  async function fetchVisibility(userId) {
    try {
      const { data, error } = await sb
        .from("profiles")
        .select("upcoming_visibility")
        .eq("id", userId)
        .single();
      if (error) {
        console.warn("[auth] could not load visibility:", error.message);
        return null;
      }
      return data && data.upcoming_visibility ? data.upcoming_visibility : null;
    } catch (err) {
      console.warn("[auth] visibility threw:", err);
      return null;
    }
  }

  // Who may see your upcoming shows, saved shows and stubs (D1): your
  // accepted followers, everyone, or no one (Sep 17 2026 -- 'private').
  // One setting, profiles.upcoming_visibility, read by can_see_upcoming().
  // Your name (Sep 23 2026, Nick: Tim couldn't change his). The name people
  // see -- not the @handle, which stays fixed. profiles.display_name is
  // already updatable by its owner (grant + profiles_update_own); the table
  // allows 1-60 characters. New activity shows the new name; comments and
  // posts made before keep the name they were made with.
  function renderNameEditor(displayName, userId) {
    const slot = el.nameEditor;
    if (!slot) return;
    if (!userId) {
      slot.hidden = true;
      slot.innerHTML = "";
      return;
    }
    slot.hidden = false;
    slot.innerHTML =
      '<div class="handle-edit">' +
        '<label class="av-edit-note" style="padding:0" for="pfNameInput">Your name</label>' +
        '<div class="handle-edit-row">' +
          '<input type="text" id="pfNameInput" maxlength="60" autocomplete="name" data-name-input>' +
          '<button type="button" class="av-edit-btn" data-name-save>Save</button>' +
        "</div>" +
        '<div class="handle-edit-msg" data-name-msg>The name people see. Your @handle stays the same.</div>' +
      "</div>";
    const input = slot.querySelector("[data-name-input]");
    const btn = slot.querySelector("[data-name-save]");
    const msg = slot.querySelector("[data-name-msg]");
    input.value = displayName || "";
    async function save() {
      const next = input.value.replace(/\s+/g, " ").trim();
      if (!next) { msg.textContent = "Your name can't be blank."; return; }
      if (next === (displayName || "")) { msg.textContent = "That's already your name."; return; }
      btn.disabled = true;
      msg.textContent = "Saving\u2026";
      const { error } = await sb.from("profiles").update({ display_name: next }).eq("id", userId);
      btn.disabled = false;
      if (error) { msg.textContent = "Couldn't save that. Try again."; return; }
      displayName = next;
      msg.textContent = "Saved.";
      if (el.displayName) el.displayName.textContent = next;
      try {
        if (typeof AV_CACHE !== "undefined" && AV_CACHE[userId]) AV_CACHE[userId].display_name = next;
        if (typeof window.reRenderCurrentView === "function") window.reRenderCurrentView();
      } catch (_) {}
    }
    btn.addEventListener("click", save);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); save(); } });
  }

  function renderVisibilityEditor(visibility, userId) {
    const slot = el.visibilityEditor;
    if (!slot) return;
    if (!visibility || !userId) {
      slot.hidden = true;
      slot.innerHTML = "";
      return;
    }
    slot.hidden = false;
    slot.innerHTML =
      '<div class="handle-edit">' +
        '<label class="av-edit-note" style="padding:0" for="pfVisSelect">Shows & stubs visible to</label>' +
        '<select id="pfVisSelect" data-vis-select>' +
          '<option value="followers">Followers only</option>' +
          '<option value="public">Everyone</option>' +
          '<option value="private">No one</option>' +
        "</select>" +
        '<div class="handle-edit-msg" data-vis-msg>Your upcoming shows, saved shows and stubs.</div>' +
        // People you may know (Sep 22 2026): both on unless switched off.
        '<label class="av-edit-note" style="padding:6px 0 0;display:flex;gap:6px;align-items:center"><input type="checkbox" data-pymk-pref="suggest_me" checked> Suggest me to others</label>' +
        '<label class="av-edit-note" style="padding:2px 0 0;display:flex;gap:6px;align-items:center"><input type="checkbox" data-pymk-pref="show_card" checked> Show People you may know</label>' +
        // Message emails (Sep 22 2026): one email per unread conversation.
        '<label class="av-edit-note" style="padding:2px 0 0;display:flex;gap:6px;align-items:center"><input type="checkbox" data-dm-email checked> Email me about messages and follow requests</label>' +
      "</div>";
    const sel = slot.querySelector("[data-vis-select]");
    const msg = slot.querySelector("[data-vis-msg]");
    const pymkBoxes = slot.querySelectorAll("[data-pymk-pref]");
    Promise.resolve(sb.rpc("pymk_prefs_get")).then(function (r) {
      const row = r && !r.error && r.data ? (Array.isArray(r.data) ? r.data[0] : r.data) : null;
      if (!row) return;
      pymkBoxes.forEach(function (b) { b.checked = row[b.getAttribute("data-pymk-pref")] !== false; });
    }).catch(function () {});
    const dmEmailBox = slot.querySelector("[data-dm-email]");
    Promise.resolve(sb.rpc("dm_email_pref_get")).then(function (r) {
      if (r && !r.error && dmEmailBox) dmEmailBox.checked = r.data !== false;
    }).catch(function () {});
    if (dmEmailBox) dmEmailBox.addEventListener("change", async function () {
      dmEmailBox.disabled = true;
      try {
        const { error } = await sb.rpc("dm_email_pref_set", { p_enabled: dmEmailBox.checked });
        if (error) { dmEmailBox.checked = !dmEmailBox.checked; msg.textContent = "Couldn\u2019t save. Try again."; msg.classList.add("is-error"); }
      } catch (err) { dmEmailBox.checked = !dmEmailBox.checked; }
      finally { dmEmailBox.disabled = false; }
    });
    pymkBoxes.forEach(function (b) {
      b.addEventListener("change", async function () {
        const key = b.getAttribute("data-pymk-pref");
        const args = key === "suggest_me" ? { p_suggest_me: b.checked } : { p_show_card: b.checked };
        b.disabled = true;
        try {
          const { error } = await sb.rpc("pymk_prefs_set", args);
          if (error) { b.checked = !b.checked; msg.textContent = "Couldn\u2019t save. Try again."; msg.classList.add("is-error"); }
          else if (key === "show_card" && typeof window.__pymkReset === "function") { window.__pymkReset(b.checked); }
        } catch (err) { b.checked = !b.checked; }
        finally { b.disabled = false; }
      });
    });
    sel.value = visibility;
    sel.addEventListener("change", async () => {
      const next = sel.value === "public" ? "public" : sel.value === "private" ? "private" : "followers";
      sel.disabled = true;
      msg.classList.remove("is-error");
      msg.textContent = "Saving\u2026";
      try {
        const { error } = await sb.from("profiles").update({ upcoming_visibility: next }).eq("id", userId);
        if (error) {
          msg.textContent = "Couldn\u2019t save. Try again.";
          msg.classList.add("is-error");
          sel.value = visibility;
        } else {
          visibility = next;
          msg.textContent = next === "public" ? "Anyone can see your shows and stubs."
            : next === "private" ? "Only you can see your shows and stubs."
            : "Only followers you\u2019ve approved can see your shows and stubs.";
        }
      } catch (err) {
        msg.textContent = "Couldn\u2019t save. Try again.";
        msg.classList.add("is-error");
        sel.value = visibility;
      } finally {
        sel.disabled = false;
      }
    });
  }

  // Ticker editor (Sep 18 2026): moderators write ticker lines here instead
  // of editing news.json. A line, the last day it runs, Add; the list below
  // shows what's on file with an x to delete. Rendered only when
  // is_moderator() says so.
  let _tickerRun = 0;
  async function renderTickerEditor(userId) {
    const slot = el.tickerEditor;
    if (!slot) return;
    if (!userId) { slot.hidden = true; slot.innerHTML = ""; slot.dataset.for = ""; return; }
    // Once per signed-in user: refreshAuthUI runs several times as a session
    // settles, and each pass was appending its own Media line (Sep 19 2026).
    if (slot.dataset.for === userId && slot.innerHTML) return;
    const run = ++_tickerRun;
    let isMod = false;
    try { const r = await sb.rpc("is_moderator"); isMod = !r.error && r.data === true; } catch (_) {}
    if (run !== _tickerRun) return;
    if (!isMod) { slot.hidden = true; slot.innerHTML = ""; return; }
    slot.dataset.for = userId;
    slot.hidden = false;
    const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    const twoWeeks = new Date(today + "T12:00:00"); twoWeeks.setDate(twoWeeks.getDate() + 14);
    const dflt = twoWeeks.toISOString().slice(0, 10);
    // Folded behind a "Ticker" line so the menu stays short on a phone.
    slot.innerHTML =
      '<button type="button" class="quick-menu-pill ticker-head" data-tk-toggle aria-expanded="false">Ticker <span class="ticker-caret">&#9656;</span></button>' +
      '<div class="handle-edit ticker-edit" hidden>' +
        '<input id="tkText" type="text" maxlength="200" placeholder="A line for the bar\u2026" data-tk-text>' +
        '<label class="av-edit-note" style="padding:6px 0 0" for="tkUntil">Runs until</label>' +
        '<div class="ticker-edit-row">' +
        '<input id="tkUntil" type="date" value="' + dflt + '" min="' + today + '" data-tk-until>' +
        '<button type="button" class="quick-menu-pill ticker-add" data-tk-add>Add</button></div>' +
        '<div class="handle-edit-msg" data-tk-msg></div>' +
        '<div class="ticker-list" data-tk-list></div>' +
      "</div>";
    slot.querySelector("[data-tk-toggle]").onclick = function (e) {
      e.stopPropagation();
      const box = slot.querySelector(".ticker-edit"), open = box.hidden;
      box.hidden = !open; this.setAttribute("aria-expanded", open ? "true" : "false");
      this.querySelector(".ticker-caret").innerHTML = open ? "&#9662;" : "&#9656;";
    };
    const msg = slot.querySelector("[data-tk-msg]"), list = slot.querySelector("[data-tk-list]");
    async function load() {
      try {
        const r = await sb.rpc("ticker_lines_all");
        const rows = (r && !r.error && r.data) || [];
        list.innerHTML = rows.length ? rows.map(function (l) {
          const live = l.run_from <= today && l.run_until >= today;
          return '<div class="ticker-line' + (live ? "" : " is-off") + '"><span class="ticker-line-text">' + esc(l.text) + '</span>' +
                 '<span class="ticker-line-until">' + (live ? "until " : (l.run_until < today ? "ended " : "from " + esc(l.run_from) + " to ")) + esc(l.run_until) + '</span>' +
                 '<button type="button" class="ticker-line-del" data-tk-edit="' + esc(l.id) + '" data-tk-edit-text="' + esc(l.text) + '" data-tk-edit-until="' + esc(l.run_until) + '" title="Edit line" aria-label="Edit this ticker line">&#9998;</button>' +
                 '<button type="button" class="ticker-line-del" data-tk-del="' + esc(l.id) + '" title="Delete line" aria-label="Delete this ticker line">&times;</button></div>';
        }).join("") : '<div class="handle-edit-msg">No lines of yours on file.</div>';
      } catch (_) {}
    }
    function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]; }); }
    // Assigned, not added: refreshAuthUI re-renders this editor on every auth
    // event, and stacked listeners fired Add (and the delete confirm) once per
    // render -- three rows from one click (Sep 18 2026).
    // Editing (Sep 21 2026, Nick: "modify the stubs for prizes on the ticker"):
    // the pencil loads a line into the boxes above and Add becomes Save. Save
    // writes the new line, then removes the old one, so a failed save never
    // loses the line that was there.
    let editingId = null;
    function stopEditing() {
      editingId = null;
      const b = slot.querySelector("[data-tk-add]"); if (b) b.textContent = "Add";
      const c = slot.querySelector("[data-tk-cancel]"); if (c) c.remove();
    }
    slot.onclick = async function (e) {
      e.stopPropagation();
      const ed = e.target.closest("[data-tk-edit]");
      if (ed) {
        editingId = ed.getAttribute("data-tk-edit");
        slot.querySelector("[data-tk-text]").value = ed.getAttribute("data-tk-edit-text") || "";
        const u = ed.getAttribute("data-tk-edit-until") || "";
        const ui = slot.querySelector("[data-tk-until]"); if (u) { if (u < ui.min) ui.min = u; ui.value = u; }
        const b = slot.querySelector("[data-tk-add]"); b.textContent = "Save";
        if (!slot.querySelector("[data-tk-cancel]")) {
          const c = document.createElement("button"); c.type = "button"; c.className = "quick-menu-pill ticker-add"; c.setAttribute("data-tk-cancel", ""); c.textContent = "Cancel";
          b.parentNode.appendChild(c);
        }
        msg.textContent = "Editing \u2014 change the line or the date, then Save.";
        slot.querySelector("[data-tk-text]").focus();
        return;
      }
      if (e.target.closest("[data-tk-cancel]")) { stopEditing(); slot.querySelector("[data-tk-text]").value = ""; msg.textContent = ""; return; }
      const add = e.target.closest("[data-tk-add]");
      if (add) {
        const text = slot.querySelector("[data-tk-text]").value.trim(), until = slot.querySelector("[data-tk-until]").value;
        if (!text) { msg.textContent = "Type the line first."; return; }
        if (!until) { msg.textContent = "Pick the last day it runs."; return; }
        const wasEditing = editingId;
        add.disabled = true; msg.textContent = wasEditing ? "Saving\u2026" : "Adding\u2026";
        try {
          const r = await sb.rpc("ticker_add", { p_text: text, p_until: until });
          if (r.error) { msg.textContent = "Couldn\u2019t " + (wasEditing ? "save" : "add") + ": " + r.error.message; }
          else {
            if (wasEditing) {
              try { const d = await sb.rpc("ticker_delete", { p_id: wasEditing }); if (d.error) msg.textContent = "Saved, but the old line is still there: " + d.error.message; } catch (_) {}
            }
            if (!/still there/.test(msg.textContent)) msg.textContent = (wasEditing ? "Saved. " : "") + "On the bar the next time the site loads.";
            slot.querySelector("[data-tk-text]").value = ""; stopEditing(); await load();
          }
        } catch (err) { msg.textContent = "Couldn\u2019t " + (wasEditing ? "save" : "add") + ". Try again."; }
        add.disabled = false;
        return;
      }
      const del = e.target.closest("[data-tk-del]");
      if (del) {
        if (!confirm("Delete this ticker line?")) return;
        del.disabled = true;
        try { const r = await sb.rpc("ticker_delete", { p_id: del.getAttribute("data-tk-del") }); if (r.error) { msg.textContent = "Couldn\u2019t delete: " + r.error.message; del.disabled = false; return; } }
        catch (_) { del.disabled = false; return; }
        await load();
      }
    };
    slot.querySelector("[data-tk-text]").onkeydown = function (e) { if (e.key === "Enter") { e.preventDefault(); slot.querySelector("[data-tk-add]").click(); } };
    await load();
    // Media usage (Sep 18 2026): files and bytes per bucket, so growth is
    // visible before Spend Cap's ceiling is. Storage only; egress is on the
    // Supabase dashboard (Reports -> Usage) and in its quota emails.
    try {
      const u = await sb.rpc("media_usage");
      const rows = (u && !u.error && u.data) || [];
      if (rows.length) {
        const gb = function (b) { return (b / 1073741824).toFixed(2) + " GB"; };
        const total = rows.reduce(function (s, r) { return s + Number(r.bytes || 0); }, 0);
        const old = slot.querySelector(".ticker-usage"); if (old) old.remove();
        const line = document.createElement("div");
        line.className = "handle-edit-msg ticker-usage";
        line.title = rows.map(function (r) { return r.bucket + ": " + r.files + " files, " + gb(Number(r.bytes || 0)); }).join("\n");
        line.textContent = "Media " + gb(total) + " of 100 GB \u00b7 " + rows.reduce(function (s, r) { return s + Number(r.files || 0); }, 0) + " files";
        slot.appendChild(line);
      }
    } catch (_) {}
  }

  async function refreshAuthUI() {
    const { data: { session } } = await sb.auth.getSession();
    if (!session || !session.user) {
      renderLoggedOut();
      return;
    }
    const [name, handleInfo, visibility] = await Promise.all([
      fetchDisplayName(session.user.id),
      fetchMyHandle(),
      fetchVisibility(session.user.id)
    ]);
    renderLoggedIn(name, handleInfo, visibility, session.user.id);
  }

  // Same charset and length as the database CHECK. Checked here first so the
  // form can explain the rule instead of round-tripping a guaranteed no.
  const HANDLE_RE = /^[A-Za-z0-9_]{3,20}$/;
  const HANDLE_RULE = "Handles are 3\u201320 letters, numbers or underscores.";

  // true = definitely taken (or reserved -- the RPC does not say which),
  // false = definitely free, null = could not tell (RPC missing or errored).
  // Null deliberately does NOT block signup; the database is the final word.
  async function handleTaken(handle) {
    try {
      const { data, error } = await sb.rpc("handle_available", { candidate: handle });
      if (error || typeof data !== "boolean") {
        console.warn("[auth] handle_available unavailable:", error && error.message);
        return null;
      }
      return !data;
    } catch (err) {
      console.warn("[auth] handle_available threw:", err);
      return null;
    }
  }

  // Tokens raised by handle_new_user / set_handle, plus GoTrue's flattening
  // of any trigger error into a generic "Database error saving new user".
  function handleErrorMessage(error) {
    const msg = ((error && error.message) || "").toLowerCase();
    if (msg.indexOf("handle_taken") !== -1 || msg.indexOf("profiles_handle_lower_idx") !== -1) return "That handle is taken. Try another.";
    if (msg.indexOf("handle_reserved") !== -1) return "That handle is reserved. Try another.";
    if (msg.indexOf("handle_invalid") !== -1) return HANDLE_RULE;
    if (msg.indexOf("handle_rename_unavailable") !== -1) return "This handle has already been changed once.";
    if (msg.indexOf("rate_limited") !== -1) return "Too many attempts. Wait a minute and try again.";
    if (msg.indexOf("database error saving new user") !== -1) return "That handle is taken. Try another.";
    return null;
  }

  // The one-time rename. Shown only when the account's handle was assigned
  // from its display name (backfill, or a sign-up from before handles) and
  // the rename has not been used. set_handle() clears the flag server-side;
  // nothing here can grant a second go.
  function renderHandleEditor(info) {
    const slot = el.handleEditor;
    if (!slot) return;
    if (!info || !info.rename_available) {
      slot.hidden = true;
      slot.innerHTML = "";
      return;
    }
    slot.hidden = false;
    slot.innerHTML =
      '<div class="handle-edit">' +
        '<div class="av-edit-note" style="padding:0">Your handle was made from your name. You can change it once.</div>' +
        '<div class="handle-edit-row">' +
          '<input type="text" maxlength="20" autocapitalize="off" spellcheck="false" placeholder="' + info.handle.replace(/"/g, "&quot;") + '" data-handle-input>' +
          '<button type="button" class="av-edit-btn" data-handle-save>Save</button>' +
        '</div>' +
        '<div class="handle-edit-msg" data-handle-msg></div>' +
      '</div>';
    const input = slot.querySelector("[data-handle-input]");
    const save = slot.querySelector("[data-handle-save]");
    const msg = slot.querySelector("[data-handle-msg]");
    const say = (t, isErr) => { msg.textContent = t || ""; msg.classList.toggle("is-error", !!isErr); };

    async function submit() {
      const next = input.value.trim();
      if (!HANDLE_RE.test(next)) { say(HANDLE_RULE, true); input.focus(); return; }
      if (next.toLowerCase() === info.handle.toLowerCase()) { say("That is already your handle.", true); return; }
      save.disabled = true;
      say("Saving\u2026");
      try {
        // set_handle returns its outcome as a status string ('ok' or a
        // token) rather than raising, so a refused or failed attempt is
        // still counted against the rate limit -- see
        // supabase/schema-profile-pages.sql. A thrown error here is
        // something else (network, not signed in).
        const { data, error } = await sb.rpc("set_handle", { p_handle: next });
        if (error) {
          say(handleErrorMessage(error) || error.message, true);
          save.disabled = false;
          return;
        }
        if (data !== "ok") {
          say(handleErrorMessage({ message: String(data || "") }) || "Couldn\u2019t change that. Try another.", true);
          save.disabled = false;
          return;
        }
        // Server confirmed; re-read so the flag and header come from the
        // database, not from what we hoped happened.
        await refreshAuthUI();
      } catch (err) {
        say("Something went wrong. Try again.", true);
        save.disabled = false;
      }
    }
    save.addEventListener("click", submit);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
  }

  async function handleSubmit(evt) {
    evt.preventDefault();
    setMsg("");
    el.submitBtn.disabled = true;
    try {
      if (mode === "signup") {
        const displayName = el.displayNameInput.value.trim();
        if (!displayName) {
          setMsg("Enter a display name.", true);
          return;
        }
        // Display names are no longer unique (Stage 10 Part 1); the handle
        // is. It is the addressable key, so it is required, shape-checked
        // here, and availability-checked through handle_available -- a
        // SECURITY DEFINER RPC granted to anon, because sign-up has no
        // session and profiles.handle is selectable by nobody. If the check
        // itself fails we fall through and let the database decide rather
        // than blocking a legitimate signup.
        const handle = (el.handleInput ? el.handleInput.value : "").trim();
        if (!HANDLE_RE.test(handle)) {
          setMsg(HANDLE_RULE, true);
          if (el.handleInput) { el.handleInput.focus(); el.handleInput.select(); }
          return;
        }
        const taken = await handleTaken(handle);
        if (taken === true) {
          setMsg("That handle is taken. Try another.", true);
          el.handleInput.focus();
          el.handleInput.select();
          return;
        }
        const { data, error } = await sb.auth.signUp({
          email: el.emailInput.value.trim(),
          password: el.passwordInput.value,
          options: { data: { display_name: displayName, handle: handle } }
        });
        if (error) {
          // Backstop for the race between the check above and the insert:
          // two people can claim the same handle in the same instant, and
          // only profiles_handle_lower_idx settles it. handle_new_user
          // re-raises that as 'handle_taken'; GoTrue may also flatten it into
          // a generic "Database error saving new user", so both read as the
          // same thing rather than showing a raw database error to a person.
          const friendly = handleErrorMessage(error);
          setMsg(friendly || error.message, true);
          if (friendly && el.handleInput) { el.handleInput.focus(); el.handleInput.select(); }
          return;
        }
        if (data.session) {
          // Email confirmation is off: signUp() returned a live session already.
          closeSheet();
          await refreshAuthUI();
        } else {
          setMsg("Check your email to confirm your account, then sign in.", false);
        }
      } else {
        const { error } = await sb.auth.signInWithPassword({
          email: el.emailInput.value.trim(),
          password: el.passwordInput.value
        });
        if (error) {
          setMsg(error.message, true);
          return;
        }
        closeSheet();
        await refreshAuthUI();
        // Signing in re-renders the feed for the account; start it from the
        // top rather than wherever the sheet caught the page (Sep 18 2026).
        try { window.scrollTo({ top: 0, behavior: "instant" }); } catch (_) { window.scrollTo(0, 0); }
      }
    } catch (err) {
      setMsg("Something went wrong. Try again.", true);
      console.error("[auth]", err);
    } finally {
      el.submitBtn.disabled = false;
    }
  }

  async function handleLogout() {
    el.menu.hidden = true;
    // el.menu above is #authMenu -- part of the retired, permanently-hidden
    // #authUserPill block. The dropdown actually on screen is #quickMenuList,
    // which nothing was closing, so it stayed open after signing out. Close it
    // the same way its own outside-click handler in index.html does, including
    // the aria state on its trigger.
    const qlist = document.getElementById("quickMenuList");
    const qbtn = document.getElementById("quickMenuBtn");
    if (qlist) qlist.hidden = true;
    if (qbtn) qbtn.setAttribute("aria-expanded", "false");
    await sb.auth.signOut();
    renderLoggedOut();
  }

  el.signInBtn.addEventListener("click", () => openSheet("signin"));
  el.close.addEventListener("click", closeSheet);
  el.overlay.addEventListener("click", (e) => { if (e.target === el.overlay) closeSheet(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });
  el.tabSignIn.addEventListener("click", () => setMode("signin"));
  el.tabSignUp.addEventListener("click", () => setMode("signup"));
  el.form.addEventListener("submit", handleSubmit);
  el.menuBtn.addEventListener("click", () => { el.menu.hidden = !el.menu.hidden; });
  el.logoutBtn.addEventListener("click", handleLogout);
  document.addEventListener("click", (e) => {
    if (!el.userPill.contains(e.target)) el.menu.hidden = true;
  });

  sb.auth.onAuthStateChange((_event, _session) => {
    refreshAuthUI();
  });

  refreshAuthUI();
})();
