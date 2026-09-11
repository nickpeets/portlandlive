-- PortlandLive — Fork Stage 10, Part 1: handles
--
-- Run this once, in full, in the Supabase SQL Editor, BEFORE deploying the
-- matching auth.js / index.html. Depends on Stage 1 (profiles),
-- schema-unique-display-name.sql (which this partly reverses) and
-- schema-avatars.sql (avatar_url must exist for the grant block at the end).
--
-- The handle is the addressable key; display_name stays the human label.
-- Decisions this file builds to (Stage 10 spec, rev 2):
--   D3  handle is NOT world-readable. It is never added to the column SELECT
--       grant on profiles, so anon and authenticated cannot select, filter
--       on, or sort by it. The only reads are handle_available() (yes/no for
--       sign-up), my_handle() (your own), and later stages' functions.
--
-- What this file does, in order:
--   1. profiles.handle + the one-time-rename flag, nullable for now
--   2. format and reserved-word checks, case-insensitive unique index
--   3. the functions: reserved list, validator, generator, handle_available,
--      my_handle, set_handle, and the new handle_new_user
--   4. backfill every existing profile from its display_name
--   5. set not null
--   6. drop display_name uniqueness and its RPC (coordinated with auth.js)
--   7. lock UPDATE on profiles down to named columns so a handle cannot be
--      changed by a direct PATCH -- "permanent" has to be enforced, not hoped
--
-- Re-running: safe. Every step is idempotent or guarded.

-- ---------------------------------------------------------------------------
-- 1. Columns
-- ---------------------------------------------------------------------------
alter table public.profiles add column if not exists handle text;

-- true only for handles this file (or the sign-up trigger's fallback path)
-- assigned rather than the user chose. Grants exactly one rename via
-- set_handle(), which flips it back to false. Never set true by the client:
-- UPDATE on this column is granted to nobody (step 7).
alter table public.profiles
  add column if not exists handle_rename_available boolean not null default false;

-- ---------------------------------------------------------------------------
-- 2. Shape
-- ---------------------------------------------------------------------------
-- One place for the reserved list. Used by the CHECK below and by every
-- function that validates a candidate, so they cannot drift apart.
create or replace function public.handle_reserved_words()
returns text[]
language sql
immutable
as $$
  select array[
    'admin', 'support', 'help', 'rainorshows', 'ros',
    'moderator', 'staff', 'system', 'noreply', 'corrections'
  ]::text[];
$$;

-- Letters, digits, underscore; 3 to 20. No periods (ambiguous at the end of a
-- sentence in a comment body). Stored as typed, compared lowercased.
alter table public.profiles drop constraint if exists profiles_handle_format;
alter table public.profiles add constraint profiles_handle_format
  check (handle ~ '^[a-zA-Z0-9_]{3,20}$');

alter table public.profiles drop constraint if exists profiles_handle_not_reserved;
alter table public.profiles add constraint profiles_handle_not_reserved
  check (lower(handle) <> all (public.handle_reserved_words()));

-- @ShakedownSteve keeps its capitals; nobody else can take @shakedownsteve.
create unique index if not exists profiles_handle_lower_idx
  on public.profiles (lower(handle));

-- ---------------------------------------------------------------------------
-- 3. Functions
-- ---------------------------------------------------------------------------
-- Shape only -- no database lookup. Used before touching the table.
create or replace function public.handle_valid(h text)
returns boolean
language sql
immutable
as $$
  select h is not null
     and h ~ '^[a-zA-Z0-9_]{3,20}$'
     and lower(h) <> all (public.handle_reserved_words());
$$;

-- Turns a display_name into a free handle. Shared by the backfill (step 4)
-- and by handle_new_user()'s fallback path, so both produce the same answer
-- for the same input:
--   * strip everything but [A-Za-z0-9]  ("Nick P." -> "NickP")
--   * nothing left (non-Latin script)   -> user_<first 8 of the uuid>
--   * truncate to 19, not 20, so a collision suffix cannot overflow
--   * under 3 chars -> pad with '_'      ("Al" -> "Al_")
--   * on collision (case-insensitive, reserved words included) append 2, 3...
--     trimming the base so base + suffix never exceeds 20
-- Internal: not granted to any client role.
create or replace function public.generate_handle(p_display_name text, p_id uuid)
returns text
language plpgsql
set search_path = public
as $$
declare
  base text;
  candidate text;
  n integer := 2;
begin
  base := regexp_replace(coalesce(p_display_name, ''), '[^A-Za-z0-9]', '', 'g');
  if base = '' then
    base := 'user_' || left(p_id::text, 8);
  end if;
  base := left(base, 19);
  if length(base) < 3 then
    base := rpad(base, 3, '_');
  end if;

  candidate := base;
  while not public.handle_valid(candidate)
     or exists (select 1 from public.profiles p where lower(p.handle) = lower(candidate))
  loop
    candidate := left(base, 20 - length(n::text)) || n::text;
    n := n + 1;
  end loop;
  return candidate;
end;
$$;

revoke all on function public.generate_handle(text, uuid) from public;

-- Sign-up pre-check. Mirrors the retired display_name_available: anon has no
-- session, so this is granted to anon as well. Answers one yes/no about a
-- string the caller already typed. false for invalid shape, reserved words
-- and taken handles alike -- it never says which, and never returns a row.
create or replace function public.handle_available(candidate text)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select public.handle_valid(candidate)
     and not exists (
       select 1 from public.profiles p
        where lower(p.handle) = lower(candidate)
     );
$$;

revoke all on function public.handle_available(text) from public;
grant execute on function public.handle_available(text) to anon, authenticated;

-- Your own handle. Needed because D3 grants SELECT on handle to nobody, and
-- column grants cannot say "except your own row".
create or replace function public.my_handle()
returns table (handle text, rename_available boolean)
language sql
security definer
set search_path = public
stable
as $$
  select p.handle, p.handle_rename_available
    from public.profiles p
   where p.id = auth.uid();
$$;

revoke all on function public.my_handle() from public;
grant execute on function public.my_handle() to authenticated;

-- The one-time rename for backfilled handles. Handles are otherwise
-- permanent. Succeeds at most once per account: the flag is cleared in the
-- same statement that writes the new handle.
create or replace function public.set_handle(p_handle text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  me uuid := auth.uid();
  allowed boolean;
begin
  if me is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;
  if p_handle is null or p_handle !~ '^[a-zA-Z0-9_]{3,20}$' then
    raise exception 'handle_invalid' using errcode = 'check_violation';
  end if;
  if lower(p_handle) = any (public.handle_reserved_words()) then
    raise exception 'handle_reserved' using errcode = 'check_violation';
  end if;

  select p.handle_rename_available into allowed
    from public.profiles p where p.id = me;
  if allowed is not true then
    raise exception 'handle_rename_unavailable' using errcode = 'insufficient_privilege';
  end if;

  update public.profiles
     set handle = p_handle,
         handle_rename_available = false
   where id = me;
  return p_handle;
exception
  when unique_violation then
    raise exception 'handle_taken' using errcode = 'unique_violation';
end;
$$;

revoke all on function public.set_handle(text) from public;
grant execute on function public.set_handle(text) to authenticated;

-- Sign-up. Replaces the schema-unique-display-name.sql version. The handle
-- comes from signUp()'s options.data.handle (auth.users.raw_user_meta_data),
-- exactly like display_name does.
--   * handle present  -> must be valid and free; a race on the unique index
--                        surfaces as 'handle_taken'. Chosen, so no rename.
--   * handle absent   -> a client from before this stage. Generate one the
--                        way the backfill does and grant the one rename.
-- display_name is no longer unique, so the only unique_violation that can
-- reach the handler is profiles_handle_lower_idx; the constraint name is
-- checked rather than assumed.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_display_name text;
  v_handle text;
  v_backfilled boolean := false;
  v_constraint text;
begin
  v_display_name := coalesce(nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''), 'New user');
  v_handle := nullif(trim(new.raw_user_meta_data ->> 'handle'), '');

  if v_handle is null then
    v_handle := public.generate_handle(v_display_name, new.id);
    v_backfilled := true;
  elsif v_handle !~ '^[a-zA-Z0-9_]{3,20}$' then
    raise exception 'handle_invalid' using errcode = 'check_violation';
  elsif lower(v_handle) = any (public.handle_reserved_words()) then
    raise exception 'handle_reserved' using errcode = 'check_violation';
  end if;

  insert into public.profiles (id, display_name, handle, handle_rename_available)
  values (new.id, v_display_name, v_handle, v_backfilled);
  return new;
exception
  when unique_violation then
    get stacked diagnostics v_constraint = constraint_name;
    if v_constraint = 'profiles_handle_lower_idx' then
      raise exception 'handle_taken' using errcode = 'unique_violation';
    end if;
    raise;
end;
$$;

-- The trigger itself (on_auth_user_created) is unchanged; it already points
-- at this function by name.

-- ---------------------------------------------------------------------------
-- 4. Backfill
-- ---------------------------------------------------------------------------
-- Oldest accounts first, so the person who has had a name longest keeps it
-- unsuffixed. Every handle assigned here gets the one-time rename.
do $$
declare
  r record;
begin
  for r in
    select id, display_name
      from public.profiles
     where handle is null
     order by created_at, id
  loop
    update public.profiles
       set handle = public.generate_handle(r.display_name, r.id),
           handle_rename_available = true
     where id = r.id;
  end loop;
end;
$$;

-- ---------------------------------------------------------------------------
-- 5. Now every row has one
-- ---------------------------------------------------------------------------
alter table public.profiles alter column handle set not null;

-- ---------------------------------------------------------------------------
-- 6. display_name stops being unique -- coordinated with auth.js
-- ---------------------------------------------------------------------------
-- Three things were wired to the index and move together in this commit:
-- the index, the display_name_available RPC, and the sign-up form's
-- name-taken flow in auth.js. handle_new_user() above no longer maps a
-- unique_violation to 'display_name_taken'. schema-unique-display-name.sql
-- is superseded and must not be re-run.
drop index if exists public.profiles_display_name_unique_idx;
drop function if exists public.display_name_available(text);

-- ---------------------------------------------------------------------------
-- 7. UPDATE becomes per-column, like SELECT already is (D3)
-- ---------------------------------------------------------------------------
-- Until now authenticated held table-wide UPDATE on profiles, and
-- profiles_update_own lets a user update their own row -- which together
-- would let PATCH /profiles?id=eq.<me> write handle (and flip the rename flag
-- back on) freely. "Permanent" is enforced here, by grant: handle and
-- handle_rename_available are updatable by no client role. set_handle() runs
-- as definer and is the only write path.
--
-- A table-level REVOKE also drops every column-level UPDATE grant on the
-- table (verified, Postgres 16), so avatar_url's is re-granted here as well.
-- schema.sql and schema-avatars.sql are amended in the same commit so a
-- fresh install lands in this exact state.
revoke update on public.profiles from authenticated;
grant update (display_name, avatar_url) on public.profiles to authenticated;

-- D3: nothing here touches the SELECT grants. handle is not in them.
