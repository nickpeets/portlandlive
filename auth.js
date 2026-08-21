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

  const SUPABASE_URL = "__SUPABASE_URL__";
  const SUPABASE_ANON_KEY = "__SUPABASE_ANON_KEY__";

  if (!window.supabase || typeof window.supabase.createClient !== "function") {
    console.error("[auth] supabase-js failed to load; auth is disabled.");
    return;
  }
  if (SUPABASE_URL.indexOf("__SUPABASE_URL__") === 0 || SUPABASE_ANON_KEY.indexOf("__SUPABASE_ANON_KEY__") === 0) {
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
  }

  function renderLoggedIn(displayName) {
    el.signInBtn.hidden = true;
    el.userPill.hidden = false;
    el.displayName.textContent = displayName || "Account";
    el.menu.hidden = true;
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
        const { data, error } = await sb.auth.signUp({
          email: el.emailInput.value.trim(),
          password: el.passwordInput.value,
          options: { data: { display_name: displayName } }
        });
        if (error) {
          setMsg(error.message, true);
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
