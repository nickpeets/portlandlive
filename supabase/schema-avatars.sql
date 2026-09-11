-- PortlandLive — Fork Stage 9: avatars (profiles.avatar_url + the avatars bucket)
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 1
-- (profiles). schema-reporting.sql's clear_avatar() depends on this.
--
-- PROVENANCE: transcribed from the live catalog of project
-- mhdysfdqoqrohlltgsig, dumped 2026-09-11 (Stage 10 spec, Part 0). Not
-- designed here; copied. The bucket row may originally have been created in
-- the Dashboard; the insert below reproduces it either way.
--
-- Two things live here that are easy to misread:
--
--   1. profiles_select_public_avatar is USING (true) for anon AND
--      authenticated. It is the policy avLoad (index.html, "Bulk-load
--      avatars") relies on when it selects id,display_name,avatar_url for
--      arbitrary ids. It is LOAD-BEARING. Because permissive policies OR
--      together, it also makes profiles_select_own (schema.sql),
--      profiles_select_thread_participants (schema-ticket-messages.sql) and
--      profiles_select_show_thread_participants (schema-show-threads.sql)
--      dead: they are live, transcribed, and never the deciding policy.
--      Decided in Stage 10 (rev 2 review): leave it wide. What it exposes is
--      controlled by column grants, not by this policy -- see D3 below.
--
--   2. storage.objects carries INSERT/UPDATE/DELETE grants for anon. That is
--      a Supabase platform default on every project, not something this
--      stage granted. The four policies below are what actually gate the
--      bucket, and every write policy compares against auth.uid(), which is
--      NULL for anon. anon can read avatars and nothing else.
--
-- D3 (Stage 10, decided): profiles has NO table-level SELECT for anon or
-- authenticated. Reads are column grants. This file grants avatar_url; the
-- other three columns (id, display_name, created_at) are granted in
-- schema.sql, amended in the same Part 0 commit. A future column on
-- profiles is unreadable until it is granted explicitly, and `select=*`
-- against profiles is a permission error by design.

alter table public.profiles
  add column if not exists avatar_url text;

alter table public.profiles
  drop constraint if exists profiles_avatar_url_length;

alter table public.profiles
  add constraint profiles_avatar_url_length check (
    avatar_url is null or char_length(avatar_url) <= 500
  );

drop policy if exists profiles_select_public_avatar on public.profiles;
drop policy if exists profiles_update_own_avatar on public.profiles;

create policy profiles_select_public_avatar
  on public.profiles
  for select
  to anon, authenticated
  using (true);

-- Redundant with Stage 1's profiles_update_own in effect (that one is
-- `to public`); live and transcribed.
create policy profiles_update_own_avatar
  on public.profiles
  for update
  to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

-- Live column ACL on avatar_url: {authenticated=rw/postgres, anon=r/postgres}.
-- The update grant is column-level on top of the table-level UPDATE
-- authenticated already holds from schema.sql; transcribed as found. Order
-- matters only for reproducing that ACL byte-for-byte: the update grant
-- predates D3's select grant, which is why authenticated is listed first.
grant update (avatar_url) on public.profiles to authenticated;
grant select (avatar_url) on public.profiles to anon, authenticated;

-- ---------------------------------------------------------------------------
-- The bucket. Public (objects are served at
-- /storage/v1/object/public/avatars/<name> -- AV_BUCKET_BASE in index.html),
-- 2 MiB cap, image types only. These match AV_MAX_BYTES and AV_TYPES.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'avatars',
  'avatars',
  true,
  2097152,
  array['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- Object name is "<user_id>.<ext>" (avUpload in index.html). Every write
-- policy checks that the part before the first dot is the caller's uid, so
-- a user cannot write a name another user's policy would match.
drop policy if exists "avatars public read" on storage.objects;
drop policy if exists "avatars insert own" on storage.objects;
drop policy if exists "avatars update own" on storage.objects;
drop policy if exists "avatars delete own" on storage.objects;

create policy "avatars public read"
  on storage.objects
  for select
  to anon, authenticated
  using (bucket_id = 'avatars');

create policy "avatars insert own"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'avatars'
    and split_part(name, '.', 1) = auth.uid()::text
  );

create policy "avatars update own"
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'avatars'
    and split_part(name, '.', 1) = auth.uid()::text
  )
  with check (
    bucket_id = 'avatars'
    and split_part(name, '.', 1) = auth.uid()::text
  );

create policy "avatars delete own"
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'avatars'
    and split_part(name, '.', 1) = auth.uid()::text
  );

-- No grants on storage.objects here: see point 2 in the header. The platform
-- defaults (anon and authenticated: SELECT, INSERT, UPDATE, DELETE) are
-- already in place and are not this file's to manage.
