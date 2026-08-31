-- PortlandLive — Fork Stage 4: trade-scoped messaging
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 1
-- (profiles) and Stage 3 (ticket_posts).
--
-- This is NOT a direct-message system. A thread exists only because someone
-- reached out about one specific ticket_posts row; there is no way to start a
-- conversation with a person, only about a spare. A thread dies with its post
-- (on delete cascade): canceling a spare ends the conversations about it.
--
-- Out of scope for v1, deliberately: read receipts, realtime, a unified inbox
-- or unread badge, reputation, and any "handoff complete" marker. Load on
-- open and refresh after send is enough until real usage says otherwise.

create table if not exists public.ticket_threads (
  id uuid primary key default gen_random_uuid(),
  ticket_post_id uuid not null references public.ticket_posts (id) on delete cascade,
  -- Both derived server-side; see set_ticket_thread_participants below.
  poster_id uuid not null references auth.users (id) on delete cascade,
  requester_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint ticket_threads_distinct_participants check (poster_id <> requester_id)
);

-- Reaching out twice to the same spare reopens the same thread rather than
-- forking a second one.
create unique index if not exists ticket_threads_post_requester_idx
  on public.ticket_threads (ticket_post_id, requester_id);

create index if not exists ticket_threads_poster_idx
  on public.ticket_threads (poster_id);

create table if not exists public.ticket_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.ticket_threads (id) on delete cascade,
  sender_id uuid not null references auth.users (id) on delete cascade,
  body text not null,
  created_at timestamptz not null default now(),
  -- 1000, against comments' 500: arranging a handoff ("I can meet at the box
  -- office from 7, my number is...") needs more room than a reaction to a show.
  constraint ticket_messages_body_length check (
    char_length(trim(body)) between 1 and 1000
  )
);

create index if not exists ticket_messages_thread_created_at_idx
  on public.ticket_messages (thread_id, created_at);

-- Identity is derived, never accepted from the client -- same pattern as
-- Stages 2 and 3. requester_id is whoever is calling; poster_id is looked up
-- from the ticket_posts row, so a client cannot open a thread that names
-- someone else as either participant.
create or replace function public.set_ticket_thread_participants()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  owner uuid;
begin
  new.requester_id := auth.uid();
  if new.requester_id is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;

  select tp.user_id into owner
    from public.ticket_posts tp
   where tp.id = new.ticket_post_id;

  if owner is null then
    raise exception 'no such ticket post %', new.ticket_post_id
      using errcode = 'foreign_key_violation';
  end if;

  if owner = new.requester_id then
    raise exception 'cannot message yourself about your own post'
      using errcode = 'check_violation';
  end if;

  new.poster_id := owner;
  return new;
end;
$$;

drop trigger if exists ticket_threads_set_participants on public.ticket_threads;
create trigger ticket_threads_set_participants
  before insert on public.ticket_threads
  for each row execute function public.set_ticket_thread_participants();

-- sender_id forced to the caller, and the caller must be one of the thread's
-- two participants. The RLS WITH CHECK below enforces the same thing; this
-- fails earlier and with a clearer message.
create or replace function public.set_ticket_message_sender()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  ok boolean;
begin
  new.sender_id := auth.uid();
  if new.sender_id is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;

  select (t.poster_id = new.sender_id or t.requester_id = new.sender_id)
    into ok
    from public.ticket_threads t
   where t.id = new.thread_id;

  if ok is not true then
    raise exception 'not a participant in this thread'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end;
$$;

drop trigger if exists ticket_messages_set_sender on public.ticket_messages;
create trigger ticket_messages_set_sender
  before insert on public.ticket_messages
  for each row execute function public.set_ticket_message_sender();

alter table public.ticket_threads enable row level security;
alter table public.ticket_messages enable row level security;

drop policy if exists ticket_threads_select_participants on public.ticket_threads;
drop policy if exists ticket_threads_insert_requester on public.ticket_threads;
drop policy if exists ticket_messages_select_participants on public.ticket_messages;
drop policy if exists ticket_messages_insert_participants on public.ticket_messages;

-- Unlike comments and ticket_posts, this is private between two people.
-- There is no anon policy and no anon grant: logged out sees nothing at all.
create policy ticket_threads_select_participants
  on public.ticket_threads
  for select
  to authenticated
  using (auth.uid() = poster_id or auth.uid() = requester_id);

create policy ticket_threads_insert_requester
  on public.ticket_threads
  for insert
  to authenticated
  with check (requester_id = auth.uid() and poster_id <> auth.uid());

create policy ticket_messages_select_participants
  on public.ticket_messages
  for select
  to authenticated
  using (exists (
    select 1 from public.ticket_threads t
     where t.id = ticket_messages.thread_id
       and (t.poster_id = auth.uid() or t.requester_id = auth.uid())
  ));

create policy ticket_messages_insert_participants
  on public.ticket_messages
  for insert
  to authenticated
  with check (sender_id = auth.uid() and exists (
    select 1 from public.ticket_threads t
     where t.id = ticket_messages.thread_id
       and (t.poster_id = auth.uid() or t.requester_id = auth.uid())
  ));

-- No UPDATE or DELETE policy on either table in v1: messages are not editable
-- and threads are not deletable. A thread goes away only when its ticket_posts
-- row does, via the cascade.

-- Reading the other person's name.
--
-- ticket_messages carries only sender_id, and Stage 1's profiles_select_own
-- limits a user to their OWN profile row -- so without something here, a
-- poster literally cannot find out who is messaging them. A requester can
-- read the poster's name off ticket_posts.display_name, but nothing flows the
-- other way.
--
-- Stage 1's schema.sql anticipated exactly this and named the fix: "add a
-- SELECT policy scoped to 'the other participant in a thread I'm also in'
-- (e.g. via an EXISTS subquery against the thread-participants table), never
-- a blanket 'authenticated users can read all profiles' policy." That is what
-- this is. It is additive -- profiles_select_own is untouched -- and it
-- exposes a display_name only to the one other person already in a thread
-- with that user. It is not a directory: you cannot enumerate, search, or
-- look up anyone you are not already talking to.
drop policy if exists profiles_select_thread_participants on public.profiles;

create policy profiles_select_thread_participants
  on public.profiles
  for select
  to authenticated
  using (exists (
    select 1 from public.ticket_threads t
     where (t.poster_id = auth.uid() and t.requester_id = profiles.id)
        or (t.requester_id = auth.uid() and t.poster_id = profiles.id)
  ));

-- Base privileges: authenticated only, and only what the policies allow.
-- anon is granted nothing on either table.
grant select, insert on public.ticket_threads to authenticated;
grant select, insert on public.ticket_messages to authenticated;
