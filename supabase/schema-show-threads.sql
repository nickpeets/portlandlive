-- PortlandLive — Fork Stage 6: Who's Going messaging (show_threads, show_messages)
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 1
-- (profiles) and on schema-show-attendees.sql.
--
-- PROVENANCE: transcribed from the live catalog of project
-- mhdysfdqoqrohlltgsig, dumped 2026-09-11 (Stage 10 spec, Part 0). Not
-- designed here; copied. index.html has cited this filename since
-- Stage 6 (the comment above `// ===== WHO'S GOING (Fork Stage 6) =====`).
--
-- This is the second, narrower messaging door, separate from Stage 4's
-- ticket_threads: a thread is between two people on the same show's
-- attendee list. What the catalog shows about how that is enforced:
--
--   * authenticated holds SELECT on show_threads and NOT insert. There is no
--     INSERT policy either. The only way a thread comes into existence is
--     public.start_show_thread(), a SECURITY DEFINER function granted to
--     authenticated (index.html: sb.rpc('start_show_thread', ...)).
--     This is the precedent Stage 10's D1 functions follow.
--   * user_a < user_b is a CHECK, so the (show_slug, user_a, user_b) unique
--     index is one row per pair regardless of who started it.

create table if not exists public.show_threads (
  id uuid primary key default gen_random_uuid(),
  show_slug text not null,
  user_a uuid not null references auth.users (id) on delete cascade,
  user_b uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),

  constraint show_threads_show_slug_length check (
    char_length(show_slug) between 1 and 200
  ),
  constraint show_threads_distinct_participants check (user_a <> user_b),
  constraint show_threads_ordered_participants check (user_a < user_b)
);

create unique index if not exists show_threads_show_pair_idx
  on public.show_threads (show_slug, user_a, user_b);
create index if not exists show_threads_user_a_idx
  on public.show_threads (user_a);
create index if not exists show_threads_user_b_idx
  on public.show_threads (user_b);

create table if not exists public.show_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.show_threads (id) on delete cascade,
  sender_id uuid not null references auth.users (id) on delete cascade,
  body text not null,
  created_at timestamptz not null default now(),

  constraint show_messages_body_length check (
    char_length(trim(body)) between 1 and 500
  )
);

create index if not exists show_messages_thread_created_at_idx
  on public.show_messages (thread_id, created_at);

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.set_show_message_sender()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  ok boolean;
begin
  new.sender_id := auth.uid();
  if new.sender_id is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;

  select (t.user_a = new.sender_id or t.user_b = new.sender_id)
    into ok
    from public.show_threads t
   where t.id = new.thread_id;

  if ok is not true then
    raise exception 'not a participant in this thread'
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end;
$function$;

drop trigger if exists show_messages_set_sender on public.show_messages;

create trigger show_messages_set_sender
  before insert on public.show_messages
  for each row execute function public.set_show_message_sender();

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.start_show_thread(p_show_slug text, p_other_user_id uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  me uuid := auth.uid();
  lo uuid;
  hi uuid;
  existing uuid;
  new_id uuid;
begin
  if me is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;
  if p_other_user_id is null or p_other_user_id = me then
    raise exception 'invalid target user' using errcode = 'check_violation';
  end if;

  -- Both parties must actually be marked as going to this show. Checked here,
  -- server-side, not just assumed from the UI only showing the button to
  -- attendees -- the RPC is the actual boundary, the UI is just convenience.
  if not exists (
    select 1 from public.show_attendees
     where show_slug = p_show_slug and user_id = me
  ) then
    raise exception 'you are not marked as going to this show'
      using errcode = 'insufficient_privilege';
  end if;
  if not exists (
    select 1 from public.show_attendees
     where show_slug = p_show_slug and user_id = p_other_user_id
  ) then
    raise exception 'that person is not marked as going to this show'
      using errcode = 'insufficient_privilege';
  end if;

  if me < p_other_user_id then
    lo := me; hi := p_other_user_id;
  else
    lo := p_other_user_id; hi := me;
  end if;

  select id into existing
    from public.show_threads
   where show_slug = p_show_slug and user_a = lo and user_b = hi;

  if existing is not null then
    return existing;
  end if;

  insert into public.show_threads (show_slug, user_a, user_b)
  values (p_show_slug, lo, hi)
  returning id into new_id;

  return new_id;
end;
$function$;

alter table public.show_threads enable row level security;
alter table public.show_messages enable row level security;

drop policy if exists show_threads_select_participants on public.show_threads;
drop policy if exists show_messages_select_participants on public.show_messages;
drop policy if exists show_messages_insert_participants on public.show_messages;

create policy show_threads_select_participants
  on public.show_threads
  for select
  to authenticated
  using (auth.uid() = user_a or auth.uid() = user_b);

-- No INSERT / UPDATE / DELETE policy on show_threads. See the header.

create policy show_messages_select_participants
  on public.show_messages
  for select
  to authenticated
  using (exists (
    select 1 from public.show_threads t
     where t.id = show_messages.thread_id
       and (t.user_a = auth.uid() or t.user_b = auth.uid())
  ));

create policy show_messages_insert_participants
  on public.show_messages
  for insert
  to authenticated
  with check (
    sender_id = auth.uid()
    and exists (
      select 1 from public.show_threads t
       where t.id = show_messages.thread_id
         and (t.user_a = auth.uid() or t.user_b = auth.uid())
    )
  );

-- Lets a participant resolve the other person's display_name. Same shape as
-- Stage 4's profiles_select_thread_participants (schema-ticket-messages.sql),
-- against show_threads instead of ticket_threads.
--
-- NOTE (Part 0 finding): this policy is currently shadowed. The avatar
-- stage added profiles_select_public_avatar, a USING (true) SELECT policy
-- for anon and authenticated (schema-avatars.sql). Permissive policies OR
-- together, so this one never decides anything while that one exists. It is
-- transcribed because it is live, not because it is load-bearing.
drop policy if exists profiles_select_show_thread_participants on public.profiles;

create policy profiles_select_show_thread_participants
  on public.profiles
  for select
  to authenticated
  using (exists (
    select 1 from public.show_threads t
     where (t.user_a = auth.uid() and t.user_b = profiles.id)
        or (t.user_b = auth.uid() and t.user_a = profiles.id)
  ));

grant select on public.show_threads to authenticated;
grant select, insert on public.show_messages to authenticated;

-- Live ACL for start_show_thread is {=X, postgres=X, authenticated=X}: the
-- grant below was issued without first revoking EXECUTE from PUBLIC (the
-- Postgres default on a new function), so PUBLIC -- and therefore anon --
-- still holds EXECUTE. The body raises 'not signed in' when auth.uid() is
-- null, so anon gets an error, not a thread. Stage 5's handoff_count and the
-- display_name_available RPC do revoke from public first. Transcribed as
-- found; not corrected here.
grant execute on function public.start_show_thread(text, uuid) to authenticated;
