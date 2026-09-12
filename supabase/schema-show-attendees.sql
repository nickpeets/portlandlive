-- PortlandLive — Fork Stage 6: Who's Going (public attendee list)
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 1
-- (profiles).
--
-- PROVENANCE: this file was not written when the stage shipped. It is a
-- transcription of the live catalog of project mhdysfdqoqrohlltgsig, dumped
-- 2026-09-11 (Part 0 of the Stage 10 spec). Every column, constraint, index,
-- policy, grant and trigger below is copied from that dump, not designed
-- here. index.html has cited this filename since Stage 6 (the comment
-- above `// ===== WHO'S GOING (Fork Stage 6) =====`).
--
-- What the dump shows, in one line: the roster for a show is world-readable,
-- and a row can be written or removed only by the user it names. That open
-- SELECT is the fact Stage 10's D1 is built on (see the spec).
--
-- SUPERSEDED IN PART by schema-profile-pages.sql (Stage 10, Part 2 -- D1):
-- show_attendees_select_all is dropped there, replaced by a self-only
-- policy, anon's SELECT grant is revoked, and attendees_for_show() becomes
-- the public per-show read. Re-running THIS file afterwards would reopen
-- the table; run schema-profile-pages.sql again if you do.

create table if not exists public.show_attendees (
  id uuid primary key default gen_random_uuid(),

  -- Plain text, not a foreign key: shows live in shows.json / archive.json,
  -- not in the database. Same shape as comments.show_slug.
  show_slug text not null,

  user_id uuid not null references auth.users (id) on delete cascade,

  -- Denormalized copy of profiles.display_name, set by the insert trigger
  -- below (the client sends show_slug only -- the `[data-wg-join]`
  -- handler in index.html).
  display_name text not null,

  created_at timestamptz not null default now(),

  constraint show_attendees_show_slug_length check (
    char_length(show_slug) between 1 and 200
  ),
  constraint show_attendees_display_name_length check (
    char_length(trim(display_name)) between 1 and 60
  )
);

-- The Who's Going panel reads "everyone on this show, in join order".
create index if not exists show_attendees_show_slug_created_at_idx
  on public.show_attendees (show_slug, created_at);

-- One row per person per show. Uniqueness is by index, not constraint, in
-- the live catalog.
create unique index if not exists show_attendees_show_user_idx
  on public.show_attendees (show_slug, user_id);

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.set_attendee_display_name()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  new.user_id := auth.uid();
  if new.user_id is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;
  select p.display_name into new.display_name
    from public.profiles p
   where p.id = new.user_id;
  if new.display_name is null then
    raise exception 'no profile row for %', new.user_id
      using errcode = 'foreign_key_violation';
  end if;
  return new;
end;
$function$;

drop trigger if exists show_attendees_set_display_name on public.show_attendees;

create trigger show_attendees_set_display_name
  before insert on public.show_attendees
  for each row execute function public.set_attendee_display_name();

alter table public.show_attendees enable row level security;

drop policy if exists show_attendees_select_all on public.show_attendees;
drop policy if exists show_attendees_insert_own on public.show_attendees;
drop policy if exists show_attendees_delete_own on public.show_attendees;

-- Open to signed-out visitors. This is the policy that makes the roster a
-- public read and, by the same token, makes ?user_id=eq.<uuid> answerable
-- for anyone holding a uuid -- the exposure D1 closes.
create policy show_attendees_select_all
  on public.show_attendees
  for select
  to anon, authenticated
  using (true);

create policy show_attendees_insert_own
  on public.show_attendees
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy show_attendees_delete_own
  on public.show_attendees
  for delete
  to authenticated
  using (user_id = auth.uid());

-- No UPDATE policy and no UPDATE grant: a row is joined or left, never edited.

grant select on public.show_attendees to anon;
grant select, insert, delete on public.show_attendees to authenticated;
