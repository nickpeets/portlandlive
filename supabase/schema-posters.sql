-- Poster overrides, set from the show page by a moderator (Sep 18 2026).
--
-- A scraped show's poster comes from the venue's page each night; when a
-- venue has none, or a submitted show came in without one, Nick can set it
-- from the show page. The override lives here, keyed by the show's slug,
-- and the nightly build applies it LAST so it survives every scrape.
--
-- Storage: bucket "posters", public read; only a moderator can write.
--
-- Run once, in full, in the Supabase SQL Editor.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('posters', 'posters', true, 4194304, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update
  set public = excluded.public, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "posters public read" on storage.objects;
drop policy if exists "posters moderator write" on storage.objects;
drop policy if exists "posters moderator update" on storage.objects;
drop policy if exists "posters moderator delete" on storage.objects;
create policy "posters public read" on storage.objects for select to anon, authenticated using (bucket_id = 'posters');
create policy "posters moderator write" on storage.objects for insert to authenticated with check (bucket_id = 'posters' and public.is_moderator());
create policy "posters moderator update" on storage.objects for update to authenticated using (bucket_id = 'posters' and public.is_moderator());
create policy "posters moderator delete" on storage.objects for delete to authenticated using (bucket_id = 'posters' and public.is_moderator());

create table if not exists public.show_overrides (
  slug text primary key,
  image_url text,
  set_by uuid references auth.users (id) on delete set null,
  updated_at timestamptz not null default now(),
  constraint show_overrides_slug_length check (char_length(slug) between 1 and 300)
);
alter table public.show_overrides enable row level security;
revoke all on public.show_overrides from anon, authenticated;

-- Set (or clear, with null) a show's poster. Moderators only.
create or replace function public.set_show_poster(p_slug text, p_image_url text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  if p_image_url is null or btrim(p_image_url) = '' then
    delete from public.show_overrides where slug = p_slug;
    return;
  end if;
  insert into public.show_overrides (slug, image_url, set_by, updated_at)
  values (p_slug, p_image_url, auth.uid(), now())
  on conflict (slug) do update set image_url = excluded.image_url, set_by = excluded.set_by, updated_at = now();
end; $$;
revoke all on function public.set_show_poster(text, text) from public;
grant execute on function public.set_show_poster(text, text) to authenticated;

-- Everyone can read them: the build applies them nightly, and a show page
-- reads its own so a fresh poster shows at once.
create or replace function public.show_overrides_all()
returns table (slug text, image_url text)
language sql security definer set search_path = public stable as $$
  select o.slug, o.image_url from public.show_overrides o where o.image_url is not null;
$$;
revoke all on function public.show_overrides_all() from public;
grant execute on function public.show_overrides_all() to anon, authenticated;

create or replace function public.show_override(p_slug text)
returns text language sql security definer set search_path = public stable as $$
  select o.image_url from public.show_overrides o where o.slug = p_slug;
$$;
revoke all on function public.show_override(text) from public;
grant execute on function public.show_override(text) to anon, authenticated;

select id, public from storage.buckets where id = 'posters';
