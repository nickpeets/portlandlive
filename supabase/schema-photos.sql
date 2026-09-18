-- Show photos (Sep 18 2026): a shared gallery on every show page.
--
-- Nick's rules: anyone on the page can look; only someone holding the
-- show's STUB (earned by "I was there") can add. Photos are resized in the
-- browser before upload (~1,600px JPEG), a person may add up to 12 per
-- show, and can delete their own. Reports work like every other report on
-- the site (target_type 'photo'): a pending or upheld report hides the
-- photo; upholding also deletes the row (the file is removed by the
-- moderator's client, which has the delete policy).
--
-- Storage: bucket "photos", public read, files under <user_id>/<slug>/...
-- so the insert/delete policies can check ownership from the path alone.
--
-- Run once, in full, in the Supabase SQL Editor.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', true, 4194304, array['image/jpeg', 'image/webp'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "photos public read" on storage.objects;
drop policy if exists "photos insert own" on storage.objects;
drop policy if exists "photos delete own" on storage.objects;
create policy "photos public read" on storage.objects for select to anon, authenticated
  using (bucket_id = 'photos');
create policy "photos insert own" on storage.objects for insert to authenticated
  with check (bucket_id = 'photos' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "photos delete own" on storage.objects for delete to authenticated
  using (bucket_id = 'photos' and (storage.foldername(name))[1] = auth.uid()::text);

create table if not exists public.show_photos (
  id uuid primary key default gen_random_uuid(),
  show_slug text not null,
  user_id uuid not null references auth.users (id) on delete cascade,
  path text not null unique,
  width integer,
  height integer,
  title text not null default '',
  venue text not null default '',
  show_date text not null default '',
  created_at timestamptz not null default now(),
  constraint show_photos_slug_length check (char_length(show_slug) between 1 and 300),
  constraint show_photos_path_length check (char_length(path) between 1 and 400)
);
create index if not exists show_photos_slug_idx on public.show_photos (show_slug, created_at desc);
create index if not exists show_photos_recent_idx on public.show_photos (created_at desc);
alter table public.show_photos enable row level security;
revoke all on public.show_photos from anon, authenticated;

alter table public.content_reports drop constraint if exists content_reports_target_type_valid;
alter table public.content_reports add constraint content_reports_target_type_valid
  check (target_type in ('comment', 'ticket_message', 'show_message', 'avatar', 'photo'));

-- Everyone can read a show's photos, minus any under a pending or upheld report.
create or replace function public.photos_for_show(p_slug text)
returns table (id uuid, user_id uuid, path text, width integer, height integer, created_at timestamptz,
               display_name text, avatar_url text)
language sql security definer set search_path = public stable as $$
  select ph.id, ph.user_id, ph.path, ph.width, ph.height, ph.created_at, p.display_name, p.avatar_url
    from public.show_photos ph
    left join public.profiles p on p.id = ph.user_id
   where ph.show_slug = p_slug
     and not exists (select 1 from public.content_reports r
                      where r.target_type = 'photo' and r.target_id = ph.id
                        and (r.status is null or r.status = 'upheld'))
   order by ph.created_at desc
   limit 200;
$$;
revoke all on function public.photos_for_show(text) from public;
grant execute on function public.photos_for_show(text) to anon, authenticated;

-- Add one photo. The stub is the ticket: a row in user_stubs for the caller
-- whose stub_id matches AND whose date is the slug's date (slugs start with
-- YYYY-MM-DD). Title/venue/date are copied from that stub row, never from the
-- client. 12 per person per show. Rate-limited like everything else.
create or replace function public.add_show_photo(p_slug text, p_stub_id text, p_path text, p_width integer, p_height integer)
returns uuid language plpgsql security definer set search_path = public as $$
declare s public.user_stubs%rowtype; new_id uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('add_show_photo', 40) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  select * into s from public.user_stubs where user_id = auth.uid() and stub_id = p_stub_id limit 1;
  if s.stub_id is null or s.date is null or s.date <> left(p_slug, 10) then
    raise exception 'no_stub' using errcode = 'P0001';
  end if;
  if p_path not like auth.uid()::text || '/%' then raise exception 'bad_path' using errcode = 'P0001'; end if;
  if (select count(*) from public.show_photos where user_id = auth.uid() and show_slug = p_slug) >= 12 then
    raise exception 'photo_limit' using errcode = 'P0001';
  end if;
  insert into public.show_photos (show_slug, user_id, path, width, height, title, venue, show_date)
  values (p_slug, auth.uid(), p_path, p_width, p_height, coalesce(s.title, ''), coalesce(s.venue, ''), coalesce(s.date, ''))
  returning id into new_id;
  return new_id;
end; $$;
revoke all on function public.add_show_photo(text, text, text, integer, integer) from public;
grant execute on function public.add_show_photo(text, text, text, integer, integer) to authenticated;

-- Delete your own. Returns the storage path so the client removes the file.
create or replace function public.delete_show_photo(p_id uuid)
returns text language plpgsql security definer set search_path = public as $$
declare pth text;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  delete from public.show_photos where id = p_id and user_id = auth.uid() returning path into pth;
  return pth;
end; $$;
revoke all on function public.delete_show_photo(uuid) from public;
grant execute on function public.delete_show_photo(uuid) to authenticated;

-- The strip on the home feed: newest photos across shows, last 21 days.
create or replace function public.latest_photos(p_limit integer default 20)
returns table (id uuid, show_slug text, path text, width integer, height integer, title text, venue text, show_date text, created_at timestamptz)
language sql security definer set search_path = public stable as $$
  select ph.id, ph.show_slug, ph.path, ph.width, ph.height, ph.title, ph.venue, ph.show_date, ph.created_at
    from public.show_photos ph
   where ph.created_at > now() - interval '21 days'
     and not exists (select 1 from public.content_reports r
                      where r.target_type = 'photo' and r.target_id = ph.id
                        and (r.status is null or r.status = 'upheld'))
   order by ph.created_at desc
   limit greatest(1, least(coalesce(p_limit, 20), 60));
$$;
revoke all on function public.latest_photos(integer) from public;
grant execute on function public.latest_photos(integer) to anon, authenticated;

-- Moderation: the report queue can name a photo, and upholding removes it.
CREATE OR REPLACE FUNCTION public.report_queue()
 RETURNS TABLE(report_id uuid, target_type text, target_id uuid, reason text, created_at timestamp with time zone, body text, author_id uuid, still_exists boolean)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $function$
  select r.id, r.target_type, r.target_id, r.reason, r.created_at,
         case r.target_type
           when 'comment'        then (select c.body from public.comments c where c.id = r.target_id)
           when 'ticket_message' then (select m.body from public.ticket_messages m where m.id = r.target_id)
           when 'show_message'   then (select m.body from public.show_messages m where m.id = r.target_id)
           when 'avatar'         then (select p.avatar_url from public.profiles p where p.id = r.target_id)
           when 'photo'          then (select 'photo: ' || ph.path || ' (' || ph.title || ' @ ' || ph.venue || ')' from public.show_photos ph where ph.id = r.target_id)
         end,
         case r.target_type
           when 'comment'        then (select c.user_id   from public.comments c where c.id = r.target_id)
           when 'ticket_message' then (select m.sender_id from public.ticket_messages m where m.id = r.target_id)
           when 'show_message'   then (select m.sender_id from public.show_messages m where m.id = r.target_id)
           when 'avatar'         then r.target_id
           when 'photo'          then (select ph.user_id from public.show_photos ph where ph.id = r.target_id)
         end,
         case r.target_type
           when 'comment'        then exists (select 1 from public.comments c where c.id = r.target_id)
           when 'ticket_message' then exists (select 1 from public.ticket_messages m where m.id = r.target_id)
           when 'show_message'   then exists (select 1 from public.show_messages m where m.id = r.target_id)
           when 'avatar'         then exists (select 1 from public.profiles p where p.id = r.target_id and p.avatar_url is not null)
           when 'photo'          then exists (select 1 from public.show_photos ph where ph.id = r.target_id)
         end
    from public.content_reports r
   where public.is_moderator() and r.status is null
   order by r.created_at
$function$;

CREATE OR REPLACE FUNCTION public.resolve_report(p_report_id uuid, p_status text)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public'
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
    elsif r.target_type = 'photo' then
      delete from public.show_photos where id = r.target_id;
    end if;
  end if;
end;
$function$;

-- Check: the bucket and the table exist.
select id, public, file_size_limit from storage.buckets where id = 'photos';
