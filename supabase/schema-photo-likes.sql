-- Photo likes, credit, "First in", and photos as giveaway entries
-- (Sep 24 2026, Nick). Run once, in full, in the Supabase SQL Editor.
-- Re-running is safe. Depends on schema-photos.sql, schema-video.sql,
-- schema-blocks.sql, schema-giveaway.sql.
--
--   * A heart on every photo and clip. photo_like() toggles yours; counts are
--     public, who liked is never listed.
--   * my_photo_likes(): your bell -- "Anita and 4 others liked your photo".
--     Your own likes and blocked people never notify you.
--   * photos_for_show / latest_photos now also return the poster's @handle
--     (the credit links to their profile), the like count, whether YOU liked
--     it, and (show pages) which one was first in.
--   * Giveaway: +1 entry per show you post a photo or clip from during the
--     entry window, one per show however many you post. Posting already
--     needs a stub for that show, so it's always a real person at a real show.

-- ---- Likes -----------------------------------------------------------------
create table if not exists public.photo_likes (
  photo_id uuid not null references public.show_photos (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (photo_id, user_id)
);
create index if not exists photo_likes_photo_idx on public.photo_likes (photo_id, created_at desc);
alter table public.photo_likes enable row level security;
revoke all on public.photo_likes from anon, authenticated;

create or replace function public.photo_like(p_id uuid, p_on boolean)
returns table (likes integer, liked boolean)
language plpgsql security definer set search_path = public as $$
declare v_owner uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('photo_like', 200) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  select ph.user_id into v_owner from public.show_photos ph where ph.id = p_id;
  if v_owner is null then raise exception 'not_found' using errcode = 'P0001'; end if;
  if public.is_blocked_between(auth.uid(), v_owner) then raise exception 'blocked' using errcode = 'P0001'; end if;
  if p_on then
    insert into public.photo_likes (photo_id, user_id) values (p_id, auth.uid()) on conflict do nothing;
  else
    delete from public.photo_likes l where l.photo_id = p_id and l.user_id = auth.uid();
  end if;
  return query
    select (select count(*)::integer from public.photo_likes l where l.photo_id = p_id),
           exists (select 1 from public.photo_likes l where l.photo_id = p_id and l.user_id = auth.uid());
end; $$;
revoke all on function public.photo_like(uuid, boolean) from public;
grant execute on function public.photo_like(uuid, boolean) to authenticated;

-- Your bell: one row per photo of yours that other people liked.
create or replace function public.my_photo_likes(p_limit integer default 30)
returns table (photo_id uuid, show_slug text, title text, kind text, n integer,
               last_at timestamptz, last_user_id uuid, last_name text, last_handle text)
language sql security definer set search_path = public stable as $$
  with l as (
    select l.photo_id, l.user_id, l.created_at
      from public.photo_likes l
      join public.show_photos ph on ph.id = l.photo_id
     where ph.user_id = auth.uid()
       and l.user_id <> auth.uid()
       and not public.is_blocked_between(auth.uid(), l.user_id)
  ),
  g as (
    select photo_id, count(*)::integer as n, max(created_at) as last_at from l group by photo_id
  )
  select g.photo_id, ph.show_slug, ph.title, ph.kind, g.n, g.last_at,
         lu.user_id, p.display_name, p.handle
    from g
    join public.show_photos ph on ph.id = g.photo_id
    cross join lateral (select l.user_id from l where l.photo_id = g.photo_id
                         order by l.created_at desc limit 1) lu
    left join public.profiles p on p.id = lu.user_id
   where auth.uid() is not null
   order by g.last_at desc
   limit greatest(1, least(coalesce(p_limit, 30), 100));
$$;
revoke all on function public.my_photo_likes(integer) from public;
grant execute on function public.my_photo_likes(integer) to authenticated;

-- ---- Show page gallery: + handle, likes, liked, is_first ---------------------
drop function if exists public.photos_for_show(text);
create or replace function public.photos_for_show(p_slug text)
returns table (id uuid, user_id uuid, path text, width integer, height integer, created_at timestamptz,
               display_name text, avatar_url text, kind text, video_path text, duration_s integer,
               handle text, likes integer, liked boolean, is_first boolean)
language sql security definer set search_path = public stable as $$
  with vis as (
    select ph.* from public.show_photos ph
     where ph.show_slug = p_slug
       and not exists (select 1 from public.content_reports r where r.target_type = 'photo'
                        and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
  ),
  f1 as (select v.id from vis v order by v.created_at, v.id limit 1)
  select v.id, v.user_id, v.path, v.width, v.height, v.created_at, p.display_name, p.avatar_url,
         v.kind, v.video_path, v.duration_s, p.handle,
         (select count(*)::integer from public.photo_likes l where l.photo_id = v.id),
         exists (select 1 from public.photo_likes l where l.photo_id = v.id and l.user_id = auth.uid()),
         v.id = (select f1.id from f1)
    from vis v left join public.profiles p on p.id = v.user_id
   order by v.created_at desc limit 200;
$$;
revoke all on function public.photos_for_show(text) from public;
grant execute on function public.photos_for_show(text) to anon, authenticated;

-- ---- Home feed strip: + credit, handle, likes, liked --------------------------
drop function if exists public.latest_photos(integer);
create or replace function public.latest_photos(p_limit integer default 20)
returns table (id uuid, show_slug text, path text, width integer, height integer, title text, venue text,
               show_date text, created_at timestamptz, kind text, video_path text, display_name text,
               handle text, likes integer, liked boolean)
language sql security definer set search_path = public stable as $$
  select ph.id, ph.show_slug, ph.path, ph.width, ph.height, ph.title, ph.venue, ph.show_date, ph.created_at,
         ph.kind, ph.video_path, p.display_name, p.handle,
         (select count(*)::integer from public.photo_likes l where l.photo_id = ph.id),
         exists (select 1 from public.photo_likes l where l.photo_id = ph.id and l.user_id = auth.uid())
    from public.show_photos ph left join public.profiles p on p.id = ph.user_id
   where ph.created_at > now() - interval '21 days'
     and not exists (select 1 from public.content_reports r where r.target_type = 'photo'
                      and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
   order by ph.created_at desc limit greatest(1, least(coalesce(p_limit, 20), 60));
$$;
revoke all on function public.latest_photos(integer) from public;
grant execute on function public.latest_photos(integer) to anon, authenticated;

-- ---- Giveaway: photos and clips count ----------------------------------------
-- Same shape as before plus a photos column. giveaway_totals, _summary and
-- _draw read e.total, so they pick this up unchanged.
drop function if exists public.giveaway_my_status(text);
drop function if exists public.giveaway_entries(text);
create or replace function public.giveaway_entries(p_slug text)
returns table (user_id uuid, base integer, invites integer, pending integer, photos integer, total integer)
language sql security definer set search_path = public stable as $$
  with g as (select * from public.giveaways where slug = p_slug),
  going as (
    select distinct a.user_id from public.show_attendees a, g
     where a.created_at between g.starts_at and g.ends_at
  ),
  inv as (
    select p.id as inviter, r.user_id as invitee,
           (r.user_id in (select user_id from going)) as qualified
      from public.signup_refs r
      join public.profiles p on r.ref = 'inv-' || lower(p.handle)
      , g
     where r.created_at between g.starts_at and g.ends_at
  ),
  pics as (
    select ph.user_id, count(distinct ph.show_slug)::integer as n
      from public.show_photos ph, g
     where ph.created_at between g.starts_at and g.ends_at
       and not exists (select 1 from public.content_reports r where r.target_type = 'photo'
                        and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
     group by ph.user_id
  ),
  people as (select user_id from going union select inviter from inv union select user_id from pics)
  select pe.user_id,
         (case when pe.user_id in (select user_id from going) then 1 else 0 end) as base,
         (select count(*)::integer from inv where inv.inviter = pe.user_id and inv.qualified) as invites,
         (select count(*)::integer from inv where inv.inviter = pe.user_id and not inv.qualified) as pending,
         coalesce((select pics.n from pics where pics.user_id = pe.user_id), 0) as photos,
         (case when pe.user_id in (select user_id from going) then 1 else 0 end)
           + (select count(*)::integer from inv where inv.inviter = pe.user_id and inv.qualified)
           + coalesce((select pics.n from pics where pics.user_id = pe.user_id), 0) as total
    from people pe
   where not exists (select 1 from public.moderators m where m.user_id = pe.user_id);
$$;
revoke all on function public.giveaway_entries(text) from public;

create or replace function public.giveaway_my_status(p_slug text)
returns table (handle text, base integer, invites integer, pending integer, photos integer, total integer, is_moderator boolean, won boolean)
language sql security definer set search_path = public stable as $$
  select p.handle,
         coalesce(e.base, 0), coalesce(e.invites, 0), coalesce(e.pending, 0), coalesce(e.photos, 0), coalesce(e.total, 0),
         exists (select 1 from public.moderators m where m.user_id = auth.uid()),
         exists (select 1 from public.giveaways g where g.slug = p_slug and g.winner_id = auth.uid())
    from public.profiles p
    left join public.giveaway_entries(p_slug) e on e.user_id = p.id
   where p.id = auth.uid();
$$;
revoke all on function public.giveaway_my_status(text) from public;
grant execute on function public.giveaway_my_status(text) to authenticated;

-- Check: every piece is there, and the giveaway still totals.
select proname from pg_proc
 where proname in ('photo_like', 'my_photo_likes', 'photos_for_show', 'latest_photos', 'giveaway_entries', 'giveaway_my_status')
 order by proname;
select * from public.giveaway_totals('brothers-comatose-2026');
