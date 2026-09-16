-- PortlandLive -- Direct messages (Sep 2026). Run once, in full, in the
-- Supabase SQL Editor. Depends on schema-follows.sql (follows) and
-- schema-profile-pages.sql (rate_limit_take).
--
-- Nick's rule: you can message someone if either of you follows the other.
-- Once a thread exists, both people can keep writing in it regardless
-- (so a reply never needs a follow-back). Pair it with "remove follower":
-- remove someone and, with no follow in either direction, they cannot open
-- a NEW thread with you.
--
-- Two people, one thread. No email, no realtime, no read receipts beyond
-- an unread flag for the inbox badge. Tables are reachable only through
-- the SECURITY DEFINER functions below; RLS is on with no policies.
--
-- Re-running: safe.

create table if not exists public.dm_threads (
  id uuid primary key default gen_random_uuid(),
  user_a uuid not null references auth.users (id) on delete cascade,
  user_b uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  last_at timestamptz not null default now(),
  constraint dm_threads_ordered check (user_a < user_b),
  unique (user_a, user_b)
);
create table if not exists public.dm_messages (
  id bigserial primary key,
  thread_id uuid not null references public.dm_threads (id) on delete cascade,
  sender_id uuid not null references auth.users (id) on delete cascade,
  body text not null check (length(body) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index if not exists dm_messages_thread_idx on public.dm_messages (thread_id, created_at);
create table if not exists public.dm_reads (
  thread_id uuid not null references public.dm_threads (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  last_read_at timestamptz not null default now(),
  primary key (thread_id, user_id)
);
alter table public.dm_threads enable row level security;
alter table public.dm_messages enable row level security;
alter table public.dm_reads enable row level security;
revoke all on public.dm_threads, public.dm_messages, public.dm_reads from anon, authenticated;

-- Can the caller start a conversation with p_other? Either follows the other.
create or replace function public.dm_can_message(p_other uuid)
returns boolean language sql security definer set search_path = public stable as $$
  select auth.uid() is not null and p_other is not null and p_other <> auth.uid() and exists (
    select 1 from public.follows f
     where (f.follower_id = auth.uid() and f.followee_id = p_other)
        or (f.follower_id = p_other and f.followee_id = auth.uid()));
$$;
revoke all on function public.dm_can_message(uuid) from public;
grant execute on function public.dm_can_message(uuid) to authenticated;

-- The thread with p_other: existing, or new if the follow rule allows.
create or replace function public.dm_open(p_other uuid)
returns uuid language plpgsql security definer set search_path = public as $$
declare a uuid; b uuid; t uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if p_other is null or p_other = auth.uid() then raise exception 'bad_target' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('dm_open', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  a := least(auth.uid(), p_other); b := greatest(auth.uid(), p_other);
  select id into t from public.dm_threads where user_a = a and user_b = b;
  if t is not null then return t; end if;
  if not public.dm_can_message(p_other) then raise exception 'not_allowed' using errcode = 'P0001'; end if;
  insert into public.dm_threads (user_a, user_b) values (a, b) returning id into t;
  return t;
end; $$;
revoke all on function public.dm_open(uuid) from public;
grant execute on function public.dm_open(uuid) to authenticated;

create or replace function public.dm_send(p_thread uuid, p_body text)
returns bigint language plpgsql security definer set search_path = public as $$
declare mid bigint; v_body text;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('dm_send', 120) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  if not exists (select 1 from public.dm_threads where id = p_thread and auth.uid() in (user_a, user_b)) then
    raise exception 'not_allowed' using errcode = 'P0001';
  end if;
  v_body := trim(both from coalesce(p_body, ''));
  if length(v_body) < 1 then raise exception 'empty' using errcode = 'P0001'; end if;
  insert into public.dm_messages (thread_id, sender_id, body) values (p_thread, auth.uid(), left(v_body, 2000)) returning id into mid;
  update public.dm_threads set last_at = now() where id = p_thread;
  insert into public.dm_reads (thread_id, user_id, last_read_at) values (p_thread, auth.uid(), now())
    on conflict (thread_id, user_id) do update set last_read_at = excluded.last_read_at;
  return mid;
end; $$;
revoke all on function public.dm_send(uuid, text) from public;
grant execute on function public.dm_send(uuid, text) to authenticated;

-- The messages in a thread, oldest first; opening marks it read.
create or replace function public.dm_messages(p_thread uuid, p_limit integer default 200)
returns table (id bigint, sender_id uuid, body text, created_at timestamptz)
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not exists (select 1 from public.dm_threads where dm_threads.id = p_thread and auth.uid() in (user_a, user_b)) then
    raise exception 'not_allowed' using errcode = 'P0001';
  end if;
  insert into public.dm_reads (thread_id, user_id, last_read_at) values (p_thread, auth.uid(), now())
    on conflict (thread_id, user_id) do update set last_read_at = excluded.last_read_at;
  return query
    select m.id, m.sender_id, m.body, m.created_at
      from public.dm_messages m
     where m.thread_id = p_thread
     order by m.created_at desc
     limit greatest(1, least(coalesce(p_limit, 200), 500));
end; $$;
revoke all on function public.dm_messages(uuid, integer) from public;
grant execute on function public.dm_messages(uuid, integer) to authenticated;

-- The caller's conversations, newest activity first, with the other person
-- and an unread flag (a message from them after the caller last opened it).
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
   order by t.last_at desc
   limit greatest(1, least(coalesce(p_limit, 100), 500));
$$;
revoke all on function public.dm_threads_mine(integer) from public;
grant execute on function public.dm_threads_mine(integer) to authenticated;
