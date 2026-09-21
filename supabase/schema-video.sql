-- Video clips in the show gallery, and a media usage readout (Sep 18 2026).
--
-- Clips ride on the photo gallery: same table, same rules (a stub to post,
-- anyone views, 12 per person per show, delete your own, reports hide).
-- A row gets kind 'video', a video_path to the clip and path to its
-- thumbnail (a frame grabbed in the browser). Clips: 20 seconds, 60 MB,
-- stored as shot -- phones hand us H.264 MP4 -- in a "videos" bucket.
-- Spend Cap is on, so the ceiling is a restriction, never a bill; the usage
-- readout below is so Nick sees growth before the ceiling does.
--
-- Run once, in full, in the Supabase SQL Editor.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('videos', 'videos', true, 62914560, array['video/mp4', 'video/quicktime', 'video/webm'])
on conflict (id) do update
  set public = excluded.public, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "videos public read" on storage.objects;
drop policy if exists "videos insert own" on storage.objects;
drop policy if exists "videos delete own" on storage.objects;
create policy "videos public read" on storage.objects for select to anon, authenticated using (bucket_id = 'videos');
create policy "videos insert own" on storage.objects for insert to authenticated with check (bucket_id = 'videos' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "videos delete own" on storage.objects for delete to authenticated using (bucket_id = 'videos' and (storage.foldername(name))[1] = auth.uid()::text);

alter table public.show_photos add column if not exists kind text not null default 'photo';
alter table public.show_photos add column if not exists video_path text;
alter table public.show_photos add column if not exists duration_s integer;
alter table public.show_photos drop constraint if exists show_photos_kind_valid;
alter table public.show_photos add constraint show_photos_kind_valid check (kind in ('photo', 'video'));

-- The readers now return kind / video_path / duration too.
drop function if exists public.photos_for_show(text);
create or replace function public.photos_for_show(p_slug text)
returns table (id uuid, user_id uuid, path text, width integer, height integer, created_at timestamptz,
               display_name text, avatar_url text, kind text, video_path text, duration_s integer)
language sql security definer set search_path = public stable as $$
  select ph.id, ph.user_id, ph.path, ph.width, ph.height, ph.created_at, p.display_name, p.avatar_url,
         ph.kind, ph.video_path, ph.duration_s
    from public.show_photos ph left join public.profiles p on p.id = ph.user_id
   where ph.show_slug = p_slug
     and not exists (select 1 from public.content_reports r where r.target_type = 'photo' and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
   order by ph.created_at desc limit 200;
$$;
revoke all on function public.photos_for_show(text) from public;
grant execute on function public.photos_for_show(text) to anon, authenticated;

drop function if exists public.latest_photos(integer);
create or replace function public.latest_photos(p_limit integer default 20)
returns table (id uuid, show_slug text, path text, width integer, height integer, title text, venue text, show_date text, created_at timestamptz, kind text, video_path text)
language sql security definer set search_path = public stable as $$
  select ph.id, ph.show_slug, ph.path, ph.width, ph.height, ph.title, ph.venue, ph.show_date, ph.created_at, ph.kind, ph.video_path
    from public.show_photos ph
   where ph.created_at > now() - interval '21 days'
     and not exists (select 1 from public.content_reports r where r.target_type = 'photo' and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
   order by ph.created_at desc limit greatest(1, least(coalesce(p_limit, 20), 60));
$$;
revoke all on function public.latest_photos(integer) from public;
grant execute on function public.latest_photos(integer) to anon, authenticated;

-- Add a clip: the thumbnail path in p_path, the clip in p_video_path. Same
-- stub check and per-show cap as photos.
create or replace function public.add_show_video(p_slug text, p_stub_id text, p_path text, p_video_path text, p_width integer, p_height integer, p_duration integer)
returns uuid language plpgsql security definer set search_path = public as $$
declare s public.user_stubs%rowtype; new_id uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('add_show_photo', 40) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  select * into s from public.user_stubs where user_id = auth.uid() and stub_id = p_stub_id limit 1;
  if s.stub_id is null or s.date is null or s.date <> left(p_slug, 10) then raise exception 'no_stub' using errcode = 'P0001'; end if;
  if p_path not like auth.uid()::text || '/%' or p_video_path not like auth.uid()::text || '/%' then raise exception 'bad_path' using errcode = 'P0001'; end if;
  if coalesce(p_duration, 0) > 26 then raise exception 'too_long' using errcode = 'P0001'; end if;
  if (select count(*) from public.show_photos where user_id = auth.uid() and show_slug = p_slug) >= 12 then raise exception 'photo_limit' using errcode = 'P0001'; end if;
  insert into public.show_photos (show_slug, user_id, path, width, height, title, venue, show_date, kind, video_path, duration_s)
  values (p_slug, auth.uid(), p_path, p_width, p_height, coalesce(s.title, ''), coalesce(s.venue, ''), coalesce(s.date, ''), 'video', p_video_path, p_duration)
  returning id into new_id;
  return new_id;
end; $$;
revoke all on function public.add_show_video(text, text, text, text, integer, integer, integer) from public;
grant execute on function public.add_show_video(text, text, text, text, integer, integer, integer) to authenticated;

-- delete_show_photo also hands back the clip path so the client removes both.
drop function if exists public.delete_show_photo(uuid);
create or replace function public.delete_show_photo(p_id uuid)
returns table (path text, video_path text)
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  return query delete from public.show_photos ph where ph.id = p_id and ph.user_id = auth.uid() returning ph.path, ph.video_path;
end; $$;
revoke all on function public.delete_show_photo(uuid) from public;
grant execute on function public.delete_show_photo(uuid) to authenticated;

-- Moderator readout: files and bytes per bucket, live from storage.
create or replace function public.media_usage()
returns table (bucket text, files bigint, bytes bigint)
language sql security definer set search_path = public stable as $$
  select o.bucket_id, count(*), coalesce(sum((o.metadata->>'size')::bigint), 0)
    from storage.objects o
   where public.is_moderator() and o.bucket_id in ('photos', 'videos', 'posters', 'avatars')
   group by o.bucket_id order by o.bucket_id;
$$;
revoke all on function public.media_usage() from public;
grant execute on function public.media_usage() to authenticated;

select id, public, file_size_limit from storage.buckets where id in ('videos', 'photos');
