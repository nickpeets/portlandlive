-- Follow requests (Sep 17 2026).
--
-- WHY: "followers only" was not a privacy setting, because a follow was
-- self-serve -- anyone who knew your handle could follow themselves in and
-- read everything gated on can_see_upcoming(). A follow now starts as a
-- REQUEST that you approve or decline, which also gives your notifications
-- something to do (Nick's words: "hey i have some activity!").
--
-- WHAT COUNTS AS A FOLLOW: only status = 'accepted'. Every existing reader
-- is narrowed below -- i_follow, follows_me, follow_counts, followers_of,
-- following_of, my_new_followers, dm_can_message, followed_attendance.
-- can_see_upcoming() is not touched: it calls i_follow(), so it tightens on
-- its own. The feed function is followed_attendance().
--
-- EXISTING FOLLOWS ARE GRANDFATHERED as accepted. Nobody loses a follower
-- they already had, and nobody's wall silently empties.
--
-- A decline DELETES the row rather than remembering a no: there is no
-- blocklist here, and the person can ask again. Removing a follower
-- (remove_follower, schema-people.sql) is unchanged and still works.
--
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe.

-- ---------------------------------------------------------------------------
-- 1. The column
-- ---------------------------------------------------------------------------
-- Added once. The rows that exist at that moment are real follows, so they
-- are created as 'accepted' through the column default; the default is then
-- flipped to 'pending' for everything that comes after. Guarded on the
-- column's existence so a re-run cannot touch anyone's pending requests.
do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'follows' and column_name = 'status'
  ) then
    alter table public.follows add column status text not null default 'accepted';
    alter table public.follows add column responded_at timestamptz;
    update public.follows set responded_at = created_at;
    alter table public.follows alter column status set default 'pending';
  end if;
end
$$;

alter table public.follows drop constraint if exists follows_status_valid;
alter table public.follows add constraint follows_status_valid
  check (status in ('pending', 'accepted'));

-- "My pending requests, newest first."
create index if not exists follows_pending_idx
  on public.follows (followee_id, created_at desc) where status = 'pending';

-- Status is set by the trigger below and changed only through approve_follow;
-- there is still no UPDATE policy, so no client can promote its own request.
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
  new.status := 'pending';                 -- every follow starts as a request
  new.responded_at := null;
  return new;
end;
$$;

drop trigger if exists follows_set_follower on public.follows;
create trigger follows_set_follower
  before insert on public.follows
  for each row execute function public.set_follow_follower();

-- ---------------------------------------------------------------------------
-- 2. Accepted-only readers
-- ---------------------------------------------------------------------------
create or replace function public.i_follow(p_target uuid)
returns boolean language sql security definer set search_path = public stable as $$
  select auth.uid() is not null and p_target is not null
     and exists (select 1 from public.follows f
                  where f.follower_id = auth.uid() and f.followee_id = p_target
                    and f.status = 'accepted');
$$;

create or replace function public.follows_me(p_other uuid)
returns boolean language sql security definer set search_path = public stable as $$
  select auth.uid() is not null and p_other is not null
     and exists (select 1 from public.follows f
                  where f.follower_id = p_other and f.followee_id = auth.uid()
                    and f.status = 'accepted');
$$;

create or replace function public.follow_counts(p_target uuid)
returns table (followers integer, following integer)
language sql security definer set search_path = public stable as $$
  select (select count(*)::integer from public.follows
           where followee_id = p_target and status = 'accepted'),
         (select count(*)::integer from public.follows
           where follower_id = p_target and status = 'accepted');
$$;

-- i_requested: my own outgoing request is still waiting, so the button can
-- say "Requested" instead of offering to follow again. The extra column means
-- the old function must go first -- Postgres will not replace a function whose
-- result columns changed.
drop function if exists public.follow_state(uuid);
create or replace function public.follow_state(p_target uuid)
returns table (i_follow boolean, follows_me boolean, i_requested boolean)
language sql security definer set search_path = public stable as $$
  select public.i_follow(p_target),
         public.follows_me(p_target),
         exists (select 1 from public.follows f
                  where f.follower_id = auth.uid() and f.followee_id = p_target
                    and f.status = 'pending');
$$;
revoke all on function public.follow_state(uuid) from public;
grant execute on function public.follow_state(uuid) to authenticated;

create or replace function public.my_new_followers(p_limit integer default 50)
returns table (follower_id uuid, handle text, display_name text, created_at timestamptz)
language sql security definer set search_path = public stable as $$
  select f.follower_id, p.handle, p.display_name, coalesce(f.responded_at, f.created_at)
    from public.follows f
    join public.profiles p on p.id = f.follower_id
   where f.followee_id = auth.uid() and f.status = 'accepted'
   order by coalesce(f.responded_at, f.created_at) desc
   limit greatest(1, least(coalesce(p_limit, 50), 200));
$$;

create or replace function public.dm_can_message(p_other uuid)
returns boolean language sql security definer set search_path = public stable as $$
  select auth.uid() is not null and p_other is not null and p_other <> auth.uid() and exists (
    select 1 from public.follows f
     where f.status = 'accepted'
       and ((f.follower_id = auth.uid() and f.followee_id = p_other)
         or (f.follower_id = p_other and f.followee_id = auth.uid())));
$$;

-- ---------------------------------------------------------------------------
-- 3. The requests themselves
-- ---------------------------------------------------------------------------
create or replace function public.follow_requests(p_limit integer default 50)
returns table (follower_id uuid, handle text, display_name text, avatar_url text, created_at timestamptz)
language sql security definer set search_path = public stable as $$
  select f.follower_id, p.handle, p.display_name, p.avatar_url, f.created_at
    from public.follows f
    join public.profiles p on p.id = f.follower_id
   where f.followee_id = auth.uid() and f.status = 'pending'
   order by f.created_at desc
   limit greatest(1, least(coalesce(p_limit, 50), 200));
$$;
revoke all on function public.follow_requests(integer) from public;
grant execute on function public.follow_requests(integer) to authenticated;

create or replace function public.approve_follow(p_follower uuid)
returns boolean language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  update public.follows
     set status = 'accepted', responded_at = now()
   where followee_id = auth.uid() and follower_id = p_follower and status = 'pending';
  get diagnostics n = row_count;
  return n > 0;
end;
$$;
revoke all on function public.approve_follow(uuid) from public;
grant execute on function public.approve_follow(uuid) to authenticated;

create or replace function public.decline_follow(p_follower uuid)
returns boolean language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  delete from public.follows
   where followee_id = auth.uid() and follower_id = p_follower and status = 'pending';
  get diagnostics n = row_count;
  return n > 0;
end;
$$;
revoke all on function public.decline_follow(uuid) from public;
grant execute on function public.decline_follow(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Lists and the feed: accepted only
-- ---------------------------------------------------------------------------
create or replace function public.followers_of(p_target uuid, p_limit integer default 100)
returns table (id uuid, handle text, display_name text, avatar_url text, since timestamptz)
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('followers_of', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  return query
    select p.id, p.handle, p.display_name, p.avatar_url, f.created_at
      from public.follows f
      join public.profiles p on p.id = f.follower_id
     where f.followee_id = p_target and f.status = 'accepted'
     order by f.created_at desc
     limit greatest(1, least(coalesce(p_limit, 100), 500));
end;
$$;

create or replace function public.following_of(p_target uuid, p_limit integer default 100)
returns table (id uuid, handle text, display_name text, avatar_url text, since timestamptz)
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('following_of', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  return query
    select p.id, p.handle, p.display_name, p.avatar_url, f.created_at
      from public.follows f
      join public.profiles p on p.id = f.followee_id
     where f.follower_id = p_target and f.status = 'accepted'
     order by f.created_at desc
     limit greatest(1, least(coalesce(p_limit, 100), 500));
end;
$$;

create or replace function public.followed_attendance(p_slugs text[])
returns table (show_slug text, user_id uuid, handle text, display_name text, avatar_url text, created_at timestamptz)
language sql security definer set search_path = public stable as $$
  select a.show_slug, a.user_id, p.handle, p.display_name, p.avatar_url, a.created_at
    from public.follows f
    join public.show_attendees a on a.user_id = f.followee_id
    join public.profiles p on p.id = a.user_id
   where f.follower_id = auth.uid()
     and f.status = 'accepted'
     and a.show_slug = any (coalesce(p_slugs, '{}'::text[]))
     and public.can_see_upcoming(a.user_id)
   order by a.show_slug, a.created_at;
$$;

-- Check: pending vs accepted right now.
select status, count(*) from public.follows group by status order by status;
