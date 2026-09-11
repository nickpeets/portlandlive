-- PortlandLive — Fork Stage 8: reporting and moderation
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 1
-- (profiles), Stage 2 (comments), Stage 4 (ticket_messages),
-- schema-show-threads.sql (show_messages) and schema-avatars.sql
-- (clear_avatar touches profiles.avatar_url).
--
-- PROVENANCE: transcribed from the live catalog of project
-- mhdysfdqoqrohlltgsig, dumped 2026-09-11 (Stage 10 spec, Part 0). Not
-- designed here; copied. index.html has cited this filename since
-- Stage 8 (`// ===== REPORTING & MODERATION (Fork Stage 8) =====`) ("see supabase/schema-reporting.sql for the reasoning behind the
-- design"). The reasoning was never written down; what follows is the
-- mechanism as the catalog shows it. The load-bearing rule the client
-- documents -- a report HIDES CONTENT IMMEDIATELY, pending review -- is
-- implemented inside hidden_targets(), whose body is below.
--
-- The shape, from the catalog:
--
--   * content_reports is write-once by the reporter (INSERT + SELECT own,
--     nothing else). Review fields (status, reviewed_at, reviewed_by) are
--     changed only by resolve_report(), a SECURITY DEFINER function --
--     there is no UPDATE grant or policy.
--   * "pending" is status IS NULL. The partial index
--     content_reports_pending_idx is the queue.
--   * One report per (reporter, target) -- unique index, so a duplicate is
--     a key error, which is why the client remembers what it has reported.
--   * moderators is a bare allow-list: RLS enabled, ZERO policies, no grants
--     to anon or authenticated. It is unreachable through PostgREST by any
--     client role. Rows are managed with the service role or in the SQL
--     Editor. is_moderator() reads it as SECURITY DEFINER.

create table if not exists public.content_reports (
  id uuid primary key default gen_random_uuid(),

  -- Which table the target_id points into. Not a foreign key: the four
  -- targets live in four tables, and a report must survive the deletion of
  -- what it reports (report_queue exposes still_exists for that case).
  target_type text not null,
  target_id uuid not null,

  -- Set by the insert trigger, not the client (see set_report_reporter).
  reporter_id uuid not null references auth.users (id) on delete cascade,

  reason text not null,
  created_at timestamptz not null default now(),

  -- NULL while pending. resolve_report() sets the three review columns.
  status text,
  reviewed_at timestamptz,
  reviewed_by uuid references auth.users (id) on delete set null,

  constraint content_reports_target_type_valid check (
    target_type in ('comment', 'ticket_message', 'show_message', 'avatar')
  ),
  -- Mirrors RP_REASONS in index.html.
  constraint content_reports_reason_valid check (
    reason in ('spam', 'harassment', 'sexual', 'violence', 'illegal', 'other')
  ),
  constraint content_reports_status_valid check (
    status is null or status in ('upheld', 'dismissed')
  )
);

-- The moderator's queue: pending reports, oldest first.
create index if not exists content_reports_pending_idx
  on public.content_reports (created_at)
  where status is null;

-- "Is this thing reported?" -- what hidden_targets() answers per block.
create index if not exists content_reports_target_idx
  on public.content_reports (target_type, target_id);

-- One report per person per target. Uniqueness by index, not constraint.
create unique index if not exists content_reports_reporter_target_idx
  on public.content_reports (reporter_id, target_type, target_id);

create table if not exists public.moderators (
  user_id uuid primary key references auth.users (id) on delete cascade,
  added_at timestamptz not null default now()
);

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.set_report_reporter()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  new.reporter_id := auth.uid();
  if new.reporter_id is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;
  new.status := null;
  new.reviewed_at := null;
  new.reviewed_by := null;
  return new;
end;
$function$;

drop trigger if exists content_reports_set_reporter on public.content_reports;

create trigger content_reports_set_reporter
  before insert on public.content_reports
  for each row execute function public.set_report_reporter();

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.is_moderator()
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select exists (select 1 from public.moderators m where m.user_id = auth.uid())
$function$;

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.hidden_targets(p_target_type text, p_ids uuid[])
 RETURNS TABLE(target_id uuid)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select distinct r.target_id
    from public.content_reports r
   where r.target_type = p_target_type
     and r.target_id = any(p_ids)
     and (r.status is null or r.status = 'upheld')
$function$;

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.report_queue()
 RETURNS TABLE(report_id uuid, target_type text, target_id uuid, reason text, created_at timestamp with time zone, body text, author_id uuid, still_exists boolean)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select r.id, r.target_type, r.target_id, r.reason, r.created_at,
         case r.target_type
           when 'comment'        then (select c.body from public.comments c where c.id = r.target_id)
           when 'ticket_message' then (select m.body from public.ticket_messages m where m.id = r.target_id)
           when 'show_message'   then (select m.body from public.show_messages m where m.id = r.target_id)
           when 'avatar'         then (select p.avatar_url from public.profiles p where p.id = r.target_id)
         end,
         case r.target_type
           when 'comment'        then (select c.user_id   from public.comments c where c.id = r.target_id)
           when 'ticket_message' then (select m.sender_id from public.ticket_messages m where m.id = r.target_id)
           when 'show_message'   then (select m.sender_id from public.show_messages m where m.id = r.target_id)
           when 'avatar'         then r.target_id
         end,
         case r.target_type
           when 'comment'        then exists (select 1 from public.comments c where c.id = r.target_id)
           when 'ticket_message' then exists (select 1 from public.ticket_messages m where m.id = r.target_id)
           when 'show_message'   then exists (select 1 from public.show_messages m where m.id = r.target_id)
           when 'avatar'         then exists (select 1 from public.profiles p where p.id = r.target_id and p.avatar_url is not null)
         end
    from public.content_reports r
   where public.is_moderator() and r.status is null
   order by r.created_at
$function$;

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.resolve_report(p_report_id uuid, p_status text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  r public.content_reports%rowtype;
begin
  if not public.is_moderator() then
    raise exception 'not a moderator' using errcode = 'insufficient_privilege';
  end if;
  if p_status not in ('upheld', 'dismissed') then
    raise exception 'invalid status' using errcode = 'check_violation';
  end if;
  select * into r from public.content_reports where id = p_report_id;
  if r.id is null then
    raise exception 'no such report' using errcode = 'no_data_found';
  end if;
  update public.content_reports
     set status = p_status, reviewed_at = now(), reviewed_by = auth.uid()
   where id = p_report_id;
  if p_status = 'upheld' then
    if r.target_type = 'comment' then
      delete from public.comments where id = r.target_id;
    elsif r.target_type = 'ticket_message' then
      delete from public.ticket_messages where id = r.target_id;
    elsif r.target_type = 'show_message' then
      delete from public.show_messages where id = r.target_id;
    elsif r.target_type = 'avatar' then
      update public.profiles set avatar_url = null where id = r.target_id;
    end if;
  end if;
end;
$function$;

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.clear_avatar(p_user_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  if not public.is_moderator() then
    raise exception 'not a moderator' using errcode = 'insufficient_privilege';
  end if;
  update public.profiles set avatar_url = null where id = p_user_id;
end;
$function$;

alter table public.content_reports enable row level security;
alter table public.moderators enable row level security;

drop policy if exists content_reports_insert_own on public.content_reports;
drop policy if exists content_reports_select_own on public.content_reports;

create policy content_reports_insert_own
  on public.content_reports
  for insert
  to authenticated
  with check (reporter_id = auth.uid());

create policy content_reports_select_own
  on public.content_reports
  for select
  to authenticated
  using (reporter_id = auth.uid());

-- No UPDATE or DELETE policy on content_reports; no policy of any kind on
-- moderators. Both are deliberate per the header.

grant select, insert on public.content_reports to authenticated;
-- moderators: no grants. Intentional.

-- Live ACLs (Q08) show these grants were issued without first revoking
-- EXECUTE from PUBLIC, so PUBLIC still holds EXECUTE on all five. The bodies
-- above are what actually refuse: clear_avatar and resolve_report raise
-- unless is_moderator(); report_queue returns no rows unless is_moderator();
-- is_moderator() is false for anon (auth.uid() is null); hidden_targets is
-- meant for anon. Transcribed as found; not corrected here.
grant execute on function public.is_moderator() to authenticated;
grant execute on function public.hidden_targets(text, uuid[]) to authenticated, anon;
grant execute on function public.report_queue() to authenticated;
grant execute on function public.resolve_report(uuid, text) to authenticated;
grant execute on function public.clear_avatar(uuid) to authenticated;
