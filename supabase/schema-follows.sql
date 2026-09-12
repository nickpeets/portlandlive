-- PortlandLive — Fork Stage 10, Part 4: follows
--
-- Run this once, in full, in the Supabase SQL Editor, BEFORE deploying the
-- matching index.html / auth.js. Depends on schema-handles.sql and
-- schema-profile-pages.sql (can_see_upcoming, which this file re-declares).
--
-- Shape (spec, Part 4): a row is a follow. No status, no approval, no
-- blocking in this stage. Unfollow deletes the row. Follow and unfollow
-- happen from a profile page only; there is no find-people surface.
--
-- What this file adds beyond the table:
--   i_follow(target)      does the CALLER follow target. This is the gate:
--                         "followers only" means the target's followers may
--                         see, so the question is whether the viewer is one.
--   follows_me(other)     does other follow the caller. Drives "Follow back".
--   can_see_upcoming      re-declared with the follower clause. Part 2 left
--                         the hook here deliberately; this is the only place
--                         followers are added to visibility.
--   follow_counts(target) public numbers for the profile header.
--   follow_state(target)  the caller's relationship to target, one call.
--   my_new_followers()    the caller's followers, newest first, WITH handle
--                         -- the inbox row links to #/u/<handle>. Scoped to
--                         the caller's own followers: people who chose to
--                         follow you have shown you their handle already.
--
-- Lists are NOT built here (see the end of this file for why).
--
-- Re-running: safe.

create table if not exists public.follows (
  follower_id uuid not null references auth.users (id) on delete cascade,
  followee_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (follower_id, followee_id),
  constraint follows_not_self check (follower_id <> followee_id)
);

-- "Who follows X, newest first" and "who does X follow, newest first".
create index if not exists follows_followee_created_at_idx
  on public.follows (followee_id, created_at desc);
create index if not exists follows_follower_created_at_idx
  on public.follows (follower_id, created_at desc);

-- The client sends followee_id only; follower_id is the session, set here,
-- the same way every other user-owned table in this project does it.
create or replace function public.set_follow_follower()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  new.follower_id := auth.uid();
  if new.follower_id is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;
  return new;
end;
$$;

drop trigger if exists follows_set_follower on public.follows;

create trigger follows_set_follower
  before insert on public.follows
  for each row execute function public.set_follow_follower();

alter table public.follows enable row level security;

drop policy if exists follows_select_all on public.follows;
drop policy if exists follows_insert_own on public.follows;
drop policy if exists follows_delete_own on public.follows;

-- Spec: counts and lists are public. Note what this does and does not
-- expose: pairs of ids. Ids and display names are already public
-- (profiles_select_public_avatar); handles are not, and nothing here maps
-- an id to one. The functions below do not depend on this policy staying
-- public -- narrowing it later to follower_id = auth.uid() breaks nothing.
create policy follows_select_all
  on public.follows
  for select
  to anon, authenticated
  using (true);

create policy follows_insert_own
  on public.follows
  for insert
  to authenticated
  with check (follower_id = auth.uid());

create policy follows_delete_own
  on public.follows
  for delete
  to authenticated
  using (follower_id = auth.uid());

-- No UPDATE: a follow is created or deleted, never edited.
grant select on public.follows to anon, authenticated;
grant insert, delete on public.follows to authenticated;

-- ---------------------------------------------------------------------------
-- Relationship helpers
-- ---------------------------------------------------------------------------
create or replace function public.i_follow(p_target uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select auth.uid() is not null
     and p_target is not null
     and exists (
       select 1 from public.follows f
        where f.follower_id = auth.uid() and f.followee_id = p_target
     );
$$;

revoke all on function public.i_follow(uuid) from public;
grant execute on function public.i_follow(uuid) to anon, authenticated;

create or replace function public.follows_me(p_other uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select auth.uid() is not null
     and p_other is not null
     and exists (
       select 1 from public.follows f
        where f.follower_id = p_other and f.followee_id = auth.uid()
     );
$$;

revoke all on function public.follows_me(uuid) from public;
grant execute on function public.follows_me(uuid) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- The gate. Part 2's version plus one clause. Same name, same callers
-- (attendance_for_user), nothing else changes.
-- ---------------------------------------------------------------------------
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
       or public.i_follow(p_target)
     );
$$;

revoke all on function public.can_see_upcoming(uuid) from public;
grant execute on function public.can_see_upcoming(uuid) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- Profile page reads
-- ---------------------------------------------------------------------------
create or replace function public.follow_counts(p_target uuid)
returns table (followers integer, following integer)
language sql
security definer
set search_path = public
stable
as $$
  select (select count(*)::integer from public.follows where followee_id = p_target),
         (select count(*)::integer from public.follows where follower_id = p_target);
$$;

revoke all on function public.follow_counts(uuid) from public;
grant execute on function public.follow_counts(uuid) to anon, authenticated;

create or replace function public.follow_state(p_target uuid)
returns table (i_follow boolean, follows_me boolean)
language sql
security definer
set search_path = public
stable
as $$
  select public.i_follow(p_target), public.follows_me(p_target);
$$;

revoke all on function public.follow_state(uuid) from public;
grant execute on function public.follow_state(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Inbox
-- ---------------------------------------------------------------------------
create or replace function public.my_new_followers(p_limit integer default 50)
returns table (follower_id uuid, handle text, display_name text, created_at timestamptz)
language sql
security definer
set search_path = public
stable
as $$
  select f.follower_id, p.handle, p.display_name, f.created_at
    from public.follows f
    join public.profiles p on p.id = f.follower_id
   where f.followee_id = auth.uid()
   order by f.created_at desc
   limit greatest(1, least(coalesce(p_limit, 50), 200));
$$;

revoke all on function public.my_new_followers(integer) from public;
grant execute on function public.my_new_followers(integer) to authenticated;

-- ---------------------------------------------------------------------------
-- Not built: follower / following LISTS
-- ---------------------------------------------------------------------------
-- The header shows counts. A list with names that link would need handles,
-- and "the followers of X, with handles" is an id -> handle mapper scoped
-- by the follow graph: walk it from any profile and you harvest the handle
-- of everyone connected -- the exact thing D3 raises the price of. It is
-- also a real product question (is who-you-watch anyone's business?) that
-- the spec did not settle. If lists are wanted, the shape is:
--   followers_of(p_target uuid) / following_of(p_target uuid)
--   SECURITY DEFINER, on rate_limit_take('follow_list', 30),
--   never a plain select on follows joined to profiles.
