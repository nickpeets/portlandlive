-- PortlandLive — Fork Stage 10, Part 2: profile pages and D1
--
-- Run this once, in full, in the Supabase SQL Editor, BEFORE deploying the
-- matching index.html / auth.js. Depends on schema-handles.sql (Part 1),
-- schema-show-attendees.sql, schema-stubs.sql and schema-avatars.sql.
--
-- Three things happen here. The reads a public profile page at #/u/<handle>
-- needs; a rate limit on the handle resolver and, on the same gate, Part 1's
-- handle_available and set_handle (section 3); and D1, a real behaviour
-- change, which is the reason this file exists at all:
--
--   D1 (decided). show_attendees SELECT was open to anon (Part 0, Q12/Q13:
--   USING (true) for anon and authenticated). That let the same endpoint
--   Who's Going uses answer ?user_id=eq.<uuid>&select=show_slug -- a
--   person's whole upcoming schedule, to anyone holding a uuid. With handles
--   resolving to ids from Part 2 on, that had to close first. Direct reads
--   become self-only; every other read goes through a SECURITY DEFINER
--   function that decides per call. Same shape as start_show_thread
--   (schema-show-threads.sql): the RPC is the boundary, the UI is convenience.
--
-- profiles_public (a view) was in the spec and is dropped: with USING (true)
-- on the base table it protected nothing, and D3's column grants are what
-- limit exposure. The profile header reads through profile_by_handle()
-- instead, because handle is selectable by no client role.
--
-- Re-running: safe. Every step is idempotent.

-- ---------------------------------------------------------------------------
-- 1. Who may see my upcoming shows
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column if not exists upcoming_visibility text not null default 'followers';

alter table public.profiles drop constraint if exists profiles_upcoming_visibility_valid;
alter table public.profiles add constraint profiles_upcoming_visibility_valid
  check (upcoming_visibility in ('followers', 'public'));

-- Column grants do not extend to columns added later (D3 made SELECT and
-- UPDATE on profiles per-column), so this is explicit or the settings toggle
-- reads nothing. handle stays out of every grant.
grant select (upcoming_visibility) on public.profiles to anon, authenticated;
grant update (upcoming_visibility) on public.profiles to authenticated;

-- ---------------------------------------------------------------------------
-- 2. D1: close show_attendees
-- ---------------------------------------------------------------------------
-- authenticated KEEPS its SELECT grant: Postgres requires SELECT on any
-- column named in a DELETE's WHERE, and leaving a show is
--   delete from show_attendees where show_slug = ? and user_id = ?
-- (index.html, [data-wg-leave]). The policy below is what narrows the read
-- to the caller's own rows. anon loses the grant outright.
drop policy if exists show_attendees_select_all on public.show_attendees;
drop policy if exists show_attendees_select_own on public.show_attendees;

create policy show_attendees_select_own
  on public.show_attendees
  for select
  to authenticated
  using (user_id = auth.uid());

revoke select on public.show_attendees from anon;

-- The per-show roster, unchanged behaviour: public, in join order. This is
-- what Who's Going calls now instead of selecting the table.
--
-- SUPERSEDED by schema-name-links.sql (Part 3.5), which re-creates this
-- with a handle column. The DROP below is what lets this file re-run at all
-- (a return-type change cannot go through CREATE OR REPLACE); re-running it
-- reverts to the four-column version -- Who's Going still renders, names
-- stop linking -- until schema-name-links.sql is run again.
drop function if exists public.attendees_for_show(text);

create function public.attendees_for_show(p_show_slug text)
returns table (id uuid, user_id uuid, display_name text, created_at timestamptz)
language sql
security definer
set search_path = public
stable
as $$
  select a.id, a.user_id, a.display_name, a.created_at
    from public.show_attendees a
   where a.show_slug = p_show_slug
   order by a.created_at;
$$;

revoke all on function public.attendees_for_show(text) from public;
grant execute on function public.attendees_for_show(text) to anon, authenticated;

-- The one gate for "may the caller see this person's upcoming shows".
-- Part 2: yourself, or a profile set to 'public'. Part 4 adds followers here
-- (or follows_me(p_target)) and nowhere else.
create or replace function public.can_see_upcoming(p_target uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select p_target is not null
     and (
       p_target = auth.uid()
       or exists (
         select 1 from public.profiles p
          where p.id = p_target and p.upcoming_visibility = 'public'
       )
     );
$$;

revoke all on function public.can_see_upcoming(uuid) from public;
grant execute on function public.can_see_upcoming(uuid) to anon, authenticated;

-- The only per-person path. The database has no show dates -- shows live
-- in shows.json -- so "upcoming" is decided by the caller passing the slugs
-- currently in the feed, and the answer is the intersection. Nothing about
-- shows outside that list, past or otherwise, is returned. An empty result
-- is the same whether the person has no upcoming shows or the caller may
-- not see them; the page reads upcoming_visibility separately to word that.
create or replace function public.attendance_for_user(p_target uuid, p_slugs text[])
returns table (show_slug text, created_at timestamptz)
language sql
security definer
set search_path = public
stable
as $$
  select a.show_slug, a.created_at
    from public.show_attendees a
   where a.user_id = p_target
     and a.show_slug = any (coalesce(p_slugs, '{}'::text[]))
     and public.can_see_upcoming(p_target)
   order by a.created_at;
$$;

revoke all on function public.attendance_for_user(uuid, text[]) from public;
grant execute on function public.attendance_for_user(uuid, text[]) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. Rate limiting for the handle resolver
-- ---------------------------------------------------------------------------
-- profile_by_handle() maps a guessed handle onto an id, display_name and
-- avatar -- a list anon can already read in full (profiles_select_public_avatar
-- is USING (true)). D3 keeps handles out of that list so harvesting the
-- mapping has a cost; an unlimited resolver would give it back for free.
-- The spec's profile_lookup was going to be 30/min for this reason; that
-- function is dropped (redundant with this one) and its limit moves here.
--
-- Keying. Signed-in callers are keyed on auth.uid(). anon has no uid, so
-- it is keyed on the client IP, which PostgREST exposes in the
-- request.headers GUC: Supabase sits behind Cloudflare, which sets
-- cf-connecting-ip and cannot be spoofed past it; x-forwarded-for (first
-- hop) and x-real-ip are fallbacks. If no IP can be read at all -- which
-- should not happen through the API -- the caller shares one global bucket
-- with a higher cap rather than going unlimited. Chosen over a purely
-- global limit because a global bucket lets one scraper deny profile pages
-- to everyone; per-IP contains the damage to the scraper.
--
-- Honest limits of the limit: a scraper with many IPs is slowed, not
-- stopped. D3 is the primary defence; this raises the price.
--
-- Pruning is done inline (each call clears its own key's stale rows; one
-- call in a hundred sweeps everything older than ten minutes) so nothing
-- depends on pg_cron being enabled.
create table if not exists public.profile_lookup_log (
  key text not null,
  created_at timestamptz not null default now()
);

create index if not exists profile_lookup_log_key_created_at_idx
  on public.profile_lookup_log (key, created_at);

-- Written only by the SECURITY DEFINER function below. No policies, no
-- client grants: unreachable through PostgREST, like moderators.
alter table public.profile_lookup_log enable row level security;

-- The caller's IP as the API proxy reports it, or null.
create or replace function public.request_ip()
returns text
language plpgsql
stable
set search_path = public
as $$
declare
  h json;
  ip text;
begin
  begin
    h := nullif(current_setting('request.headers', true), '')::json;
  exception when others then
    h := null;
  end;
  if h is null then
    return null;
  end if;
  ip := coalesce(
    nullif(trim(h ->> 'cf-connecting-ip'), ''),
    nullif(trim(split_part(coalesce(h ->> 'x-forwarded-for', ''), ',', 1)), ''),
    nullif(trim(h ->> 'x-real-ip'), '')
  );
  return ip;
end;
$$;

revoke all on function public.request_ip() from public;

-- One bucket per caller per named operation. Returns true and records the
-- call, or false when the caller has used its allowance for the last 60s.
-- p_limit is per user or per IP; the shared no-IP bucket gets ten times it.
drop function if exists public.rate_limit_take(text);

create or replace function public.rate_limit_take(p_op text, p_limit integer)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  who text;
  k text;
  lim integer;
  n integer;
begin
  who := case
    when auth.uid() is not null then 'u:' || auth.uid()::text
    when public.request_ip() is not null then 'ip:' || public.request_ip()
    else 'anon:*'
  end;
  k := p_op || ':' || who;
  lim := case when who = 'anon:*' then p_limit * 10 else p_limit end;

  delete from public.profile_lookup_log
   where key = k and created_at < now() - interval '60 seconds';
  if random() < 0.01 then
    delete from public.profile_lookup_log
     where created_at < now() - interval '10 minutes';
  end if;

  select count(*) into n
    from public.profile_lookup_log
   where key = k and created_at >= now() - interval '60 seconds';
  if n >= lim then
    return false;
  end if;

  insert into public.profile_lookup_log (key) values (k);
  return true;
end;
$$;

revoke all on function public.rate_limit_take(text, integer) from public;

-- ---------------------------------------------------------------------------
-- 3b. The handle oracles go on the same gate
-- ---------------------------------------------------------------------------
-- handle_available() (Part 1) answers yes/no about a handle to anon. On its
-- own that is an enumeration primitive: guess cheaply here to learn which
-- handles exist, then spend the rate-limited profile_by_handle calls only on
-- confirmed hits -- which routes around the limit above. set_handle() has
-- the same shape for a signed-in caller whose one-time rename is still
-- available: a 'handle_taken' failure does not consume the rename, so it
-- could be asked indefinitely. Both are re-declared here with the gate.
--
-- 60/min, twice the resolver's limit. The client only calls
-- handle_available on submit, never per keystroke, so a person retrying
-- candidates makes single digits per minute and is never refused; and the
-- answer is worth less than the resolver's (a bit, not an id), which is
-- what justifies the higher number. Over the limit both raise
-- 'rate_limited' rather than returning false, which would read as "taken".
-- auth.js already treats an errored pre-check as "could not tell" and lets
-- the database decide, so sign-up degrades rather than blocks.
--
-- The remaining oracle is sign-up itself (handle_new_user raises
-- 'handle_taken'); that costs a GoTrue signUp per guess and sits behind
-- Supabase Auth's own per-IP sign-up limits.
create or replace function public.handle_available(candidate text)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.rate_limit_take('handle_available', 60) then
    raise exception 'rate_limited' using errcode = 'P0001';
  end if;
  return public.handle_valid(candidate)
     and not exists (
       select 1 from public.profiles p
        where lower(p.handle) = lower(candidate)
     );
end;
$$;

revoke all on function public.handle_available(text) from public;
grant execute on function public.handle_available(text) to anon, authenticated;

-- set_handle() changes contract here, deliberately. The Part 1 version
-- RAISED 'handle_taken' and friends. A raised exception that leaves the
-- function aborts the whole statement -- including the rate-limit row
-- recorded a moment earlier -- so a failed probe would never count, and
-- "guess a taken handle" would be free forever (found by test, not by
-- reasoning). Outcomes are therefore RETURNED as a status string:
--   'ok' | 'handle_taken' | 'handle_invalid' | 'handle_reserved'
--   | 'handle_rename_unavailable' | 'rate_limited'
-- and the log row survives every one of them. The race on the unique
-- index is caught in an inner block and returned the same way. Only
-- "not signed in" still raises; anon cannot execute this anyway.
-- auth.js reads the status; the rename still spends the flag exactly once.
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
  if not public.rate_limit_take('set_handle', 60) then
    return 'rate_limited';
  end if;
  if p_handle is null or p_handle !~ '^[a-zA-Z0-9_]{3,20}$' then
    return 'handle_invalid';
  end if;
  if lower(p_handle) = any (public.handle_reserved_words()) then
    return 'handle_reserved';
  end if;

  select p.handle_rename_available into allowed
    from public.profiles p where p.id = me;
  if allowed is not true then
    return 'handle_rename_unavailable';
  end if;

  -- Cheap answer first, then the index settles any race.
  if exists (select 1 from public.profiles p where lower(p.handle) = lower(p_handle) and p.id <> me) then
    return 'handle_taken';
  end if;
  begin
    update public.profiles
       set handle = p_handle,
           handle_rename_available = false
     where id = me;
  exception
    when unique_violation then
      return 'handle_taken';
  end;
  return 'ok';
end;
$$;

revoke all on function public.set_handle(text) from public;
grant execute on function public.set_handle(text) to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Profile page reads
-- ---------------------------------------------------------------------------
-- Header. Exact match, compared lowercased, one row or none. This is the
-- public handle -> profile resolver a profile URL needs; it returns the id
-- because the stub grid, attendance and avatar loads key on it, and with D1
-- in place an id no longer unlocks anything a handle does not. Rate-limited
-- (section 3); over the limit it raises 'rate_limited' rather than
-- returning an empty result that would read as "no such person".
-- VOLATILE because it records the call; supabase-js sends rpc() as POST.
create or replace function public.profile_by_handle(p_handle text)
returns table (
  id uuid, handle text, display_name text, avatar_url text,
  created_at timestamptz, upcoming_visibility text
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.rate_limit_take('profile_by_handle', 30) then
    raise exception 'rate_limited' using errcode = 'P0001';
  end if;
  return query
    select p.id, p.handle, p.display_name, p.avatar_url, p.created_at, p.upcoming_visibility
      from public.profiles p
     where p_handle is not null
       and lower(p.handle) = lower(trim(p_handle))
     limit 1;
end;
$$;

revoke all on function public.profile_by_handle(text) from public;
grant execute on function public.profile_by_handle(text) to anon, authenticated;

-- The stub grid. user_stubs is self-scoped (schema-stubs.sql); the grid is
-- public by decision (spec, Part 2 visibility table). Newest first, the same
-- fields the shelf renders from -- there is no image and no slug to fetch.
create or replace function public.stubs_for_user(p_target uuid)
returns table (
  stub_id text, title text, venue text, neighborhood text, address text,
  date text, "time" text, created_at timestamptz
)
language sql
security definer
set search_path = public
stable
as $$
  select s.stub_id, s.title, s.venue, s.neighborhood, s.address, s.date, s."time", s.created_at
    from public.user_stubs s
   where s.user_id = p_target
   order by s.created_at desc;
$$;

revoke all on function public.stubs_for_user(uuid) from public;
grant execute on function public.stubs_for_user(uuid) to anon, authenticated;

-- Handoff count and avatars already have public paths: handoff_count(uuid)
-- (schema-handoff.sql) and the id/display_name/avatar_url column grants
-- (schema.sql, schema-avatars.sql). Follower and following counts arrive
-- with Part 4; the page shows zero until then.
