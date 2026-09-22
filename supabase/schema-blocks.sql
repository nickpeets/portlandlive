-- Block (Sep 22 2026). Run once, in full, in the Supabase SQL Editor.
-- Re-running is safe. Depends on schema-follow-requests.sql, schema-messages.sql,
-- schema-dm-delete-thread.sql, schema-profile-pages.sql, schema-pymk.sql.
--
-- Nick's design: Block lives in a menu on someone's profile and in a message
-- thread. Blocking removes follows both ways; after that the blocked person
-- can't follow you, message you, or see your profile (it reads "not
-- available"), and isn't told. Their comments and Who's Going entries are
-- hidden for YOU only (the page does that). Undo from "Blocked people" on
-- your own profile. Report is still the tool for the whole site.

create table if not exists public.blocks (
  blocker_id uuid not null references auth.users (id) on delete cascade,
  blocked_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker_id, blocked_id),
  check (blocker_id <> blocked_id)
);
alter table public.blocks enable row level security;
revoke all on public.blocks from anon, authenticated;

create or replace function public.is_blocked_between(p_a uuid, p_b uuid)
returns boolean language sql security definer set search_path = public stable as $$
  select p_a is not null and p_b is not null and exists (
    select 1 from public.blocks b
     where (b.blocker_id = p_a and b.blocked_id = p_b) or (b.blocker_id = p_b and b.blocked_id = p_a));
$$;
revoke all on function public.is_blocked_between(uuid, uuid) from public;

create or replace function public.block_user(p_other uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if p_other is null or p_other = auth.uid() then raise exception 'bad_target' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('block_user', 30) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  insert into public.blocks (blocker_id, blocked_id) values (auth.uid(), p_other) on conflict do nothing;
  delete from public.follows
   where (follower_id = auth.uid() and followee_id = p_other)
      or (follower_id = p_other and followee_id = auth.uid());
  return true;
end; $$;
revoke all on function public.block_user(uuid) from public;
grant execute on function public.block_user(uuid) to authenticated;

create or replace function public.unblock_user(p_other uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  delete from public.blocks where blocker_id = auth.uid() and blocked_id = p_other;
  return true;
end; $$;
revoke all on function public.unblock_user(uuid) from public;
grant execute on function public.unblock_user(uuid) to authenticated;

-- The caller's own block list (only ever the caller's).
create or replace function public.my_blocks()
returns table (id uuid, handle text, display_name text, avatar_url text, created_at timestamptz)
language sql security definer set search_path = public stable as $$
  select p.id, p.handle, p.display_name, p.avatar_url, b.created_at
    from public.blocks b join public.profiles p on p.id = b.blocked_id
   where b.blocker_id = auth.uid()
   order by b.created_at desc;
$$;
revoke all on function public.my_blocks() from public;
grant execute on function public.my_blocks() to authenticated;

-- No new follow across a block, either way.
create or replace function public.follows_block_guard()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if public.is_blocked_between(auth.uid(), new.followee_id) then
    raise exception 'blocked' using errcode = 'P0001';
  end if;
  return new;
end; $$;
drop trigger if exists follows_block_guard on public.follows;
create trigger follows_block_guard before insert on public.follows
  for each row execute function public.follows_block_guard();

-- No new conversation and no new message across a block.
create or replace function public.dm_threads_block_guard()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if public.is_blocked_between(new.user_a, new.user_b) then
    raise exception 'blocked' using errcode = 'P0001';
  end if;
  return new;
end; $$;
drop trigger if exists dm_threads_block_guard on public.dm_threads;
create trigger dm_threads_block_guard before insert on public.dm_threads
  for each row execute function public.dm_threads_block_guard();

create or replace function public.dm_messages_block_guard()
returns trigger language plpgsql security definer set search_path = public as $$
declare a uuid; b uuid;
begin
  select user_a, user_b into a, b from public.dm_threads where id = new.thread_id;
  if public.is_blocked_between(a, b) then
    raise exception 'blocked' using errcode = 'P0001';
  end if;
  return new;
end; $$;
drop trigger if exists dm_messages_block_guard on public.dm_messages;
create trigger dm_messages_block_guard before insert on public.dm_messages
  for each row execute function public.dm_messages_block_guard();

-- Opening an existing conversation across a block is refused too.
create or replace function public.dm_open(p_other uuid)
returns uuid language plpgsql security definer set search_path = public as $$
declare a uuid; b uuid; t uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if p_other is null or p_other = auth.uid() then raise exception 'bad_target' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('dm_open', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  if public.is_blocked_between(auth.uid(), p_other) then raise exception 'blocked' using errcode = 'P0001'; end if;
  a := least(auth.uid(), p_other); b := greatest(auth.uid(), p_other);
  select id into t from public.dm_threads where user_a = a and user_b = b;
  if t is not null then return t; end if;
  if not public.dm_can_message(p_other) then raise exception 'not_allowed' using errcode = 'P0001'; end if;
  insert into public.dm_threads (user_a, user_b) values (a, b) returning id into t;
  return t;
end; $$;
revoke all on function public.dm_open(uuid) from public;
grant execute on function public.dm_open(uuid) to authenticated;

-- Conversations list: a blocked conversation disappears for both people.
create or replace function public.dm_threads_mine(p_limit integer default 100)
returns table (thread_id uuid, other_id uuid, handle text, display_name text, avatar_url text,
               last_at timestamptz, last_body text, last_sender uuid, unread boolean)
language sql security definer set search_path = public stable as $$
  select t.id,
         case when t.user_a = auth.uid() then t.user_b else t.user_a end as other_id,
         p.handle, p.display_name, p.avatar_url,
         t.last_at,
         (select m.body from public.dm_messages m where m.thread_id = t.id order by m.created_at desc limit 1),
         (select m.sender_id from public.dm_messages m where m.thread_id = t.id order by m.created_at desc limit 1),
         exists (select 1 from public.dm_messages m
                  where m.thread_id = t.id and m.sender_id <> auth.uid()
                    and m.created_at > coalesce((select r.last_read_at from public.dm_reads r where r.thread_id = t.id and r.user_id = auth.uid()), 'epoch'::timestamptz))
    from public.dm_threads t
    join public.profiles p on p.id = case when t.user_a = auth.uid() then t.user_b else t.user_a end
   where auth.uid() in (t.user_a, t.user_b)
     and t.last_at > coalesce((select h.hidden_at from public.dm_hidden h where h.thread_id = t.id and h.user_id = auth.uid()), 'epoch'::timestamptz)
     and not public.is_blocked_between(t.user_a, t.user_b)
   order by t.last_at desc
   limit greatest(1, least(coalesce(p_limit, 100), 500));
$$;

-- A profile that blocked you reads "not available" to you.
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
       and not exists (select 1 from public.blocks b where b.blocker_id = p.id and b.blocked_id = auth.uid())
     limit 1;
end;
$$;
revoke all on function public.profile_by_handle(text) from public;
grant execute on function public.profile_by_handle(text) to anon, authenticated;

-- People you may know never suggests someone across a block.
create or replace function public.people_you_may_know(p_limit integer default 12)
returns table (id uuid, handle text, display_name text, avatar_url text,
               mutuals integer, mutual_names text[], shared_shows integer)
language plpgsql
security definer
set search_path = public
as $$
declare v_me uuid := auth.uid();
begin
  if v_me is null then return; end if;
  if exists (select 1 from public.pymk_prefs x where x.user_id = v_me and not x.show_card) then return; end if;
  if not public.rate_limit_take('people_you_may_know', 30) then
    raise exception 'rate_limited' using errcode = 'P0001';
  end if;
  return query
  with fof as (
    select f2.followee_id as cand,
           count(distinct f1.followee_id)::integer as n,
           (array_agg(coalesce(nullif(pm.display_name, ''), pm.handle) order by f1.created_at desc))[1:2] as names
      from public.follows f1
      join public.follows f2 on f2.follower_id = f1.followee_id and f2.status = 'accepted'
      join public.profiles pm on pm.id = f1.followee_id
     where f1.follower_id = v_me and f1.status = 'accepted'
     group by f2.followee_id
  ), shared as (
    select a2.user_id as cand, count(distinct a2.show_slug)::integer as n
      from public.show_attendees a1
      join public.show_attendees a2 on a2.show_slug = a1.show_slug and a2.user_id <> a1.user_id
      join public.profiles pv on pv.id = a2.user_id and pv.upcoming_visibility <> 'private'
     where a1.user_id = v_me
     group by a2.user_id
  ), linked as (
    select coalesce(fof.cand, shared.cand) as cand,
           coalesce(fof.n, 0) as m, coalesce(fof.names, '{}'::text[]) as names,
           coalesce(shared.n, 0) as s
      from fof full join shared on shared.cand = fof.cand
  ), c as (
    -- Newest-members fallback (Sep 22 2026): people who joined in the last
    -- 30 days fill whatever slots the two real signals leave. They sort
    -- after every linked person (score 0) and show as "New on Rain Or
    -- Shows" on the card (mutuals = 0 and shared_shows = 0).
    select * from linked
    union all
    select np.id, 0, '{}'::text[], 0
      from public.profiles np
     where np.created_at > now() - interval '30 days'
       and not exists (select 1 from linked l where l.cand = np.id)
  )
  select p.id, p.handle, p.display_name, p.avatar_url, c.m, c.names, c.s
    from c
    join public.profiles p on p.id = c.cand
   where c.cand <> v_me
     and p.handle is not null
     and not exists (select 1 from public.follows f where f.follower_id = v_me and f.followee_id = c.cand)
     and not exists (select 1 from public.pymk_hidden h where h.user_id = v_me and h.hidden_id = c.cand)
     and not exists (select 1 from public.pymk_prefs x where x.user_id = c.cand and not x.suggest_me)
     and not public.is_blocked_between(v_me, c.cand)
   order by (c.m * 3 + c.s * 2) desc, c.m desc, p.created_at desc, lower(p.handle)
   limit greatest(1, least(coalesce(p_limit, 12), 25));
end;
$$;
revoke all on function public.people_you_may_know(integer) from public;
grant execute on function public.people_you_may_know(integer) to authenticated;

select proname from pg_proc where proname in ('block_user', 'unblock_user', 'my_blocks', 'is_blocked_between') order by proname;
