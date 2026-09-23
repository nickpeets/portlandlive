-- Stories, part 1 (Sep 23 2026). Run once, in full, in the Supabase SQL
-- Editor. Re-running is safe. Depends on schema-reporting.sql (moderators,
-- is_moderator) and schema-handles.sql (profiles.handle).
--
-- Nick: a blog/newsletter section Tim (@timstout) and Nick write, built into
-- the site. HIDDEN to start: while app_flags.stories_public is false, only
-- writers see the section or can read a story at all. Flip it to go public:
--   update public.app_flags set on = true where key = 'stories_public';
--
-- A story is a title, a cover photo and a list of blocks (text, photo, show).
-- Writers write; a moderator can edit or unpublish anything.

create table if not exists public.writers (
  user_id uuid primary key references auth.users (id) on delete cascade,
  added_at timestamptz not null default now()
);
alter table public.writers enable row level security;
revoke all on public.writers from anon, authenticated;

insert into public.writers (user_id)
select p.id from public.profiles p where lower(p.handle) = 'timstout'
on conflict do nothing;
insert into public.writers (user_id)
select m.user_id from public.moderators m
on conflict do nothing;

create table if not exists public.app_flags (
  key text primary key,
  "on" boolean not null default false
);
alter table public.app_flags enable row level security;
revoke all on public.app_flags from anon, authenticated;
insert into public.app_flags (key, "on") values ('stories_public', false) on conflict do nothing;

create or replace function public.is_writer()
returns boolean language sql security definer set search_path = public stable as $$
  select auth.uid() is not null and exists (select 1 from public.writers w where w.user_id = auth.uid());
$$;
revoke all on function public.is_writer() from public;
grant execute on function public.is_writer() to anon, authenticated;

-- Can the caller see Stories at all? Writers always; everyone once it's public.
create or replace function public.stories_visible()
returns boolean language sql security definer set search_path = public stable as $$
  select public.is_writer() or coalesce((select f."on" from public.app_flags f where f.key = 'stories_public'), false);
$$;
revoke all on function public.stories_visible() from public;
grant execute on function public.stories_visible() to anon, authenticated;

create table if not exists public.stories (
  id uuid primary key default gen_random_uuid(),
  slug text unique,
  title text not null default '' check (char_length(title) <= 200),
  cover_url text check (cover_url is null or char_length(cover_url) <= 1000),
  body jsonb not null default '[]'::jsonb,
  author_id uuid not null references auth.users (id) on delete cascade,
  status text not null default 'draft' check (status in ('draft', 'published')),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (octet_length(body::text) <= 200000)
);
alter table public.stories enable row level security;
revoke all on public.stories from anon, authenticated;

-- The list: published stories for anyone who can see Stories; writers also
-- get every draft (theirs and each other's -- it's a two-person desk).
create or replace function public.stories_list()
returns table (id uuid, slug text, title text, cover_url text, status text, published_at timestamptz,
               updated_at timestamptz, author_handle text, author_name text, author_id uuid)
language sql security definer set search_path = public stable as $$
  select s.id, s.slug, s.title, s.cover_url, s.status, s.published_at, s.updated_at,
         p.handle, p.display_name, s.author_id
    from public.stories s join public.profiles p on p.id = s.author_id
   where public.stories_visible()
     and (s.status = 'published' or public.is_writer())
   order by coalesce(s.published_at, s.updated_at) desc
   limit 200;
$$;
revoke all on function public.stories_list() from public;
grant execute on function public.stories_list() to anon, authenticated;

create or replace function public.story_get(p_key text)
returns table (id uuid, slug text, title text, cover_url text, body jsonb, status text, published_at timestamptz,
               updated_at timestamptz, author_handle text, author_name text, author_id uuid, can_edit boolean)
language sql security definer set search_path = public stable as $$
  select s.id, s.slug, s.title, s.cover_url, s.body, s.status, s.published_at, s.updated_at,
         p.handle, p.display_name, s.author_id,
         public.is_writer()
    from public.stories s join public.profiles p on p.id = s.author_id
   where public.stories_visible()
     and (s.slug = p_key or s.id::text = p_key)
     and (s.status = 'published' or public.is_writer())
   limit 1;
$$;
revoke all on function public.story_get(text) from public;
grant execute on function public.story_get(text) to anon, authenticated;

-- Save (create when p_id is null). Writers only. Returns the story id.
create or replace function public.story_save(p_id uuid, p_title text, p_cover_url text, p_body jsonb)
returns uuid language plpgsql security definer set search_path = public as $$
declare v_id uuid;
begin
  if not public.is_writer() then raise exception 'not a writer' using errcode = 'insufficient_privilege'; end if;
  if jsonb_typeof(coalesce(p_body, '[]'::jsonb)) <> 'array' then raise exception 'bad body' using errcode = 'P0001'; end if;
  if p_id is null then
    insert into public.stories (title, cover_url, body, author_id)
    values (left(coalesce(p_title, ''), 200), nullif(p_cover_url, ''), coalesce(p_body, '[]'::jsonb), auth.uid())
    returning id into v_id;
  else
    update public.stories
       set title = left(coalesce(p_title, ''), 200), cover_url = nullif(p_cover_url, ''),
           body = coalesce(p_body, '[]'::jsonb), updated_at = now()
     where id = p_id
    returning id into v_id;
    if v_id is null then raise exception 'not found' using errcode = 'P0001'; end if;
  end if;
  return v_id;
end; $$;
revoke all on function public.story_save(uuid, text, text, jsonb) from public;
grant execute on function public.story_save(uuid, text, text, jsonb) to authenticated;

-- Publish / unpublish. The slug is made once, from the title, at first
-- publish, and never changes after (links stay good).
create or replace function public.story_publish(p_id uuid, p_publish boolean)
returns text language plpgsql security definer set search_path = public as $$
declare v_title text; v_slug text; base text; n int := 1;
begin
  if not public.is_writer() then raise exception 'not a writer' using errcode = 'insufficient_privilege'; end if;
  select title, slug into v_title, v_slug from public.stories where id = p_id;
  if not found then raise exception 'not found' using errcode = 'P0001'; end if;
  if p_publish then
    if coalesce(btrim(v_title), '') = '' then raise exception 'needs a title' using errcode = 'P0001'; end if;
    if v_slug is null then
      base := trim(both '-' from left(regexp_replace(lower(v_title), '[^a-z0-9]+', '-', 'g'), 80));
      if base = '' then base := 'story'; end if;
      v_slug := base;
      while exists (select 1 from public.stories where slug = v_slug) loop
        n := n + 1; v_slug := base || '-' || n;
      end loop;
    end if;
    update public.stories set status = 'published', slug = v_slug,
           published_at = coalesce(published_at, now()), updated_at = now() where id = p_id;
  else
    update public.stories set status = 'draft', updated_at = now() where id = p_id;
  end if;
  return v_slug;
end; $$;
revoke all on function public.story_publish(uuid, boolean) from public;
grant execute on function public.story_publish(uuid, boolean) to authenticated;

create or replace function public.story_delete(p_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if not public.is_writer() then raise exception 'not a writer' using errcode = 'insufficient_privilege'; end if;
  delete from public.stories where id = p_id and status = 'draft';
  return found;
end; $$;
revoke all on function public.story_delete(uuid) from public;
grant execute on function public.story_delete(uuid) to authenticated;

-- Photos for stories: public to read, writers to upload.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('stories', 'stories', true, 6291456, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update
  set public = excluded.public, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;
drop policy if exists "stories public read" on storage.objects;
drop policy if exists "stories writer write" on storage.objects;
drop policy if exists "stories writer update" on storage.objects;
drop policy if exists "stories writer delete" on storage.objects;
create policy "stories public read" on storage.objects for select to anon, authenticated using (bucket_id = 'stories');
create policy "stories writer write" on storage.objects for insert to authenticated with check (bucket_id = 'stories' and public.is_writer());
create policy "stories writer update" on storage.objects for update to authenticated using (bucket_id = 'stories' and public.is_writer());
create policy "stories writer delete" on storage.objects for delete to authenticated using (bucket_id = 'stories' and public.is_writer());

-- Who's on the desk:
select p.handle, p.display_name from public.writers w join public.profiles p on p.id = w.user_id order by p.handle;
