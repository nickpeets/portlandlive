-- PortlandLive — Fork Stage 2: comments on show pages
--
-- Run this once, in full, in the Supabase SQL Editor for the project
-- (Dashboard -> SQL Editor -> New query -> paste -> Run). Like Stage 1's
-- schema.sql it needs privileges the anon key does not have (creating a
-- SECURITY DEFINER function, granting table privileges), so it cannot be
-- applied from client-side code.
--
-- Depends on Stage 1: public.profiles must already exist.
--
-- Scope, deliberately: comments only. No editing, no threading, no replies,
-- no votes, no ticket exchange, no messaging. Those are later stages.

create table if not exists public.comments (
  id uuid primary key default gen_random_uuid(),

  -- The show page's slug, matched as plain text. Intentionally NOT a foreign
  -- key: shows live in shows.json / archive.json, not in the database, so
  -- there is no shows table to reference. A comment can therefore outlive the
  -- listing it was posted against (a show dropping out of shows.json into
  -- archive.json keeps the same slug, so the thread follows it).
  show_slug text not null,

  user_id uuid not null references auth.users (id) on delete cascade,

  -- Denormalized copy of profiles.display_name, frozen at post time: a comment
  -- keeps the name its author had when they wrote it, and reads need no join.
  -- NOT client-supplied — see the set_comment_display_name trigger below.
  display_name text not null,

  body text not null,
  created_at timestamptz not null default now(),

  constraint comments_body_length check (
    char_length(trim(body)) between 1 and 500
  ),
  constraint comments_show_slug_length check (
    char_length(show_slug) between 1 and 200
  ),
  constraint comments_display_name_length check (
    char_length(trim(display_name)) between 1 and 60
  )
);

-- Every read is "the comments for one show, in time order".
create index if not exists comments_show_slug_created_at_idx
  on public.comments (show_slug, created_at);

-- The client sends body + show_slug; user_id and display_name are derived
-- server-side. Without this a logged-in user could post under someone else's
-- name simply by putting a different string in the insert, since display_name
-- is denormalized and nothing else would check it.
create or replace function public.set_comment_display_name()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  new.user_id := auth.uid();
  select p.display_name into new.display_name
    from public.profiles p
   where p.id = new.user_id;
  if new.display_name is null then
    raise exception 'no profile row for %', new.user_id
      using errcode = 'foreign_key_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists comments_set_display_name on public.comments;

create trigger comments_set_display_name
  before insert on public.comments
  for each row execute function public.set_comment_display_name();

alter table public.comments enable row level security;

-- Drop-and-recreate so this script is safe to re-run.
drop policy if exists comments_select_all on public.comments;
drop policy if exists comments_insert_own on public.comments;
drop policy if exists comments_delete_own on public.comments;

-- Public commentary on a public listings site: anyone reads, logged in or not.
create policy comments_select_all
  on public.comments
  for select
  to anon, authenticated
  using (true);

-- Only a logged-in user, only as themselves. The trigger above already forces
-- user_id = auth.uid(); this policy is the belt to that trigger's braces, and
-- is what actually blocks an insert from anon (auth.uid() is null there).
create policy comments_insert_own
  on public.comments
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy comments_delete_own
  on public.comments
  for delete
  to authenticated
  using (user_id = auth.uid());

-- No UPDATE policy, by design: v1 has no editing. With RLS on and no policy
-- for a command, that command is denied for everyone — nothing further needed.

-- RLS policies do not grant base table access; Postgres privileges still apply.
-- anon reads only. authenticated reads, posts and deletes (its own, per policy).
-- update is granted to nobody, matching the absent UPDATE policy.
grant select on public.comments to anon;
grant select, insert, delete on public.comments to authenticated;
