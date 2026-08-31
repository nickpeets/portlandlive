-- PortlandLive — Fork Stage 5: handoff tracking + reputation badge
--
-- Run this once, in full, in the Supabase SQL Editor (Dashboard -> SQL Editor
-- -> New query -> paste -> Run). Like every prior stage it needs privileges
-- the anon key does not have (SECURITY DEFINER functions, table grants), so it
-- cannot be applied from client-side code.
--
-- Depends on Stage 4: public.ticket_threads must already exist.
--
-- Scope: a poster marks one thread handed off; anyone can read a poster's
-- count of handed-off threads. Deliberately NOT here, and not coming:
-- 1-5 stars, written reviews, any free-text feedback about a person. The
-- reputation surface is a single integer, which is the whole point -- there is
-- no text to moderate and no score to argue with.
--
-- Tracked PER THREAD, not per post. A post with quantity 3 can have up to 3
-- threads, each markable on its own, so "2 of my 3 spares actually went to
-- someone" is expressible. Marking is a self-report by the poster: one-way, no
-- undo, no confirmation step from the requester. That matches the plain-counts
-- philosophy of Stages 2 and 3 -- these are counts, not verified facts, and
-- pretending otherwise by adding a both-parties handshake would buy accuracy
-- the rest of the design does not claim.

alter table public.ticket_threads
  add column if not exists handed_off_at timestamptz;

-- The badge query is "count this poster's handed-off threads", so the partial
-- index carries only the rows that can ever match. Stage 4's
-- ticket_threads_poster_idx stays for the thread-list reads.
create index if not exists ticket_threads_poster_handed_off_idx
  on public.ticket_threads (poster_id)
  where handed_off_at is not null;

-- The one-way ratchet, in the database rather than in the UI.
--
-- Stage 4 shipped no UPDATE path on this table at all, so everything about
-- mutating a thread row is being introduced here and is scoped to exactly one
-- column. Three separate layers have to agree before a write lands:
--
--   1. A column-level UPDATE grant, so `set poster_id = ...` is not even
--      syntactically available to the authenticated role.
--   2. An RLS policy, so only the thread's poster can update the row.
--   3. This trigger, which is the backstop that does not depend on either of
--      the above being configured correctly.
--
-- The timestamp itself is never read from the client. Same reasoning as
-- user_id in Stage 3 and requester_id/sender_id in Stage 4: the safest way to
-- handle a value a client should not control is to overwrite it, not to
-- validate it. Because it is assigned here unconditionally there is no clock
-- skew to tolerate and no "is this close enough to now()" judgment call.
create or replace function public.enforce_ticket_thread_handoff()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  -- (a) One-way: already marked means no re-marking, no un-marking, no
  --     re-timestamping. This is the check that makes the count monotonic.
  if old.handed_off_at is not null then
    raise exception 'thread % is already marked handed off', old.id
      using errcode = 'check_violation';
  end if;

  -- (b) Nothing but handed_off_at may move in this statement. Comparing whole
  --     row images minus that one key covers every current column and any
  --     column a later stage adds, which an enumerated list would not.
  if (to_jsonb(old) - 'handed_off_at') is distinct from (to_jsonb(new) - 'handed_off_at') then
    raise exception 'only handed_off_at may be updated on ticket_threads'
      using errcode = 'check_violation';
  end if;

  -- (c) The stored value is the server's, always. Whatever the client sent for
  --     this column -- a forged past date, a far-future one, null -- is
  --     discarded here without being inspected.
  new.handed_off_at := now();
  return new;
end;
$$;

drop trigger if exists ticket_threads_enforce_handoff on public.ticket_threads;

create trigger ticket_threads_enforce_handoff
  before update on public.ticket_threads
  for each row execute function public.enforce_ticket_thread_handoff();

drop policy if exists ticket_threads_update_handoff on public.ticket_threads;

-- Only the poster, and only on their own threads. USING gates which existing
-- rows are updatable; WITH CHECK re-tests the row the trigger produced, so a
-- row cannot be updated into someone else's ownership.
create policy ticket_threads_update_handoff
  on public.ticket_threads
  for update
  to authenticated
  using (auth.uid() = poster_id)
  with check (auth.uid() = poster_id);

-- Column-scoped on purpose: RLS decides WHICH ROWS, this decides WHICH
-- COLUMNS. A `set poster_id = ...` is refused by the grant system before any
-- policy or trigger runs. anon gets nothing, as in Stage 4.
grant update (handed_off_at) on public.ticket_threads to authenticated;

-- The public badge.
--
-- ticket_threads is invisible to anon and, for authenticated users, readable
-- only for threads they participate in -- so nobody can compute this count by
-- querying the table, which is the point. This function is the only way to ask
-- the question, and it answers with a bare integer: no thread ids, no
-- requester identities, no timestamps, no rows. Exactly the shape of Stage 1's
-- display_name_available, for the same reason.
--
-- Public because the thing it describes is public: ticket_posts are readable
-- logged out, so the credibility signal attached to a poster has to be too, or
-- it is useless to the person deciding whether to reach out.
create or replace function public.handoff_count(target_user_id uuid)
returns integer
language sql
security definer
set search_path = public
stable
as $$
  select count(*)::int
    from public.ticket_threads
   where poster_id = target_user_id
     and handed_off_at is not null;
$$;

-- Batched form of the same question, for a show page rendering many posters at
-- once: one round trip instead of one per poster. It returns only counts, keyed
-- by the ids the caller already supplied (and which are already public on
-- ticket_posts.user_id) -- no more information than calling handoff_count in a
-- loop, just fewer requests. Posters with no handed-off threads come back as 0
-- rather than being omitted, so the caller never has to guess.
create or replace function public.handoff_counts(target_user_ids uuid[])
returns table (user_id uuid, handoff_count integer)
language sql
security definer
set search_path = public
stable
as $$
  select u.id,
         (select count(*)::int
            from public.ticket_threads t
           where t.poster_id = u.id
             and t.handed_off_at is not null)
    from unnest(target_user_ids) as u(id)
   group by u.id;
$$;

revoke all on function public.handoff_count(uuid) from public;
revoke all on function public.handoff_counts(uuid[]) from public;
grant execute on function public.handoff_count(uuid) to anon, authenticated;
grant execute on function public.handoff_counts(uuid[]) to anon, authenticated;
