// PortlandLive -- Fork Stage 1: Supabase accounts (sign up / log in / log out)
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
  }

  function renderLoggedIn(displayName) {
    el.signInBtn.hidden = true;
    el.userPill.hidden = false;
    el.displayName.textContent = displayName || "Account";
    el.menu.hidden = true;
    if (el.quickMenuAccount) el.quickMenuAccount.hidden = false;
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

  async function refreshAuthUI() {
    const { data: { session } } = await sb.auth.getSession();
    if (!session || !session.user) {
      renderLoggedOut();
      return;
    }
    const name = await fetchDisplayName(session.user.id);
    renderLoggedIn(name);
  }

  // true = definitely taken, false = definitely free, null = could not tell
  // (RPC missing or errored). Null deliberately does NOT block signup.
  async function displayNameTaken(name) {
    try {
      const { data, error } = await sb.rpc("display_name_available", { candidate: name });
      if (error || typeof data !== "boolean") {
        console.warn("[auth] display_name_available unavailable:", error && error.message);
        return null;
      }
      return !data;
    } catch (err) {
      console.warn("[auth] display_name_available threw:", err);
      return null;
    }
  }

  function isNameTakenError(error) {
    const msg = ((error && error.message) || "").toLowerCase();
    return msg.indexOf("display_name_taken") !== -1
        || msg.indexOf("profiles_display_name_unique_idx") !== -1
        || msg.indexOf("database error saving new user") !== -1;
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
        // Display names are unique, case- and whitespace-insensitively.
        // This cannot be checked with a plain select: anon has no privileges
        // on profiles, and profiles_select_own limits an authenticated user to
        // their own row, so a select would call every name free. The
        // display_name_available RPC (SECURITY DEFINER) is the only honest
        // way to ask. If the check itself fails we fall through and let the
        // database decide rather than blocking a legitimate signup.
        const taken = await displayNameTaken(displayName);
        if (taken === true) {
          setMsg("That name is taken. Try another.", true);
          el.displayNameInput.focus();
          el.displayNameInput.select();
          return;
        }
        const { data, error } = await sb.auth.signUp({
          email: el.emailInput.value.trim(),
          password: el.passwordInput.value,
          options: { data: { display_name: displayName } }
        });
        if (error) {
          // Backstop for the race between the check above and the insert:
          // two people can claim the same name in the same instant, and only
          // the unique index settles it. handle_new_user re-raises that as
          // 'display_name_taken'; GoTrue may also flatten it into a generic
          // "Database error saving new user", so treat both as the same thing
          // rather than showing a raw database error to a person.
          setMsg(isNameTakenError(error) ? "That name is taken. Try another." : error.message, true);
          if (isNameTakenError(error)) { el.displayNameInput.focus(); el.displayNameInput.select(); }
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
