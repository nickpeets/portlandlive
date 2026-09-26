-- Ghost venues + easter eggs (Sep 25 2026, Nick). Run once, in full, in the
-- Supabase SQL Editor. Re-running is safe. Depends on schema-photos.sql,
-- schema-video.sql, schema-photo-likes.sql, schema-visibility-private.sql
-- (can_see_upcoming) and schema-blocks.sql.
--
-- 14 closed Portland rooms get an unlisted tribute page (#/ghost/<slug>).
-- People found them by searching the name. There they can:
--   * tap "I was there" (ghost_visits) -- a ghost stub, separate from show
--     stubs so it never touches show badges or the stub wall
--   * post old photos/flyers/clips (add_ghost_photo / add_ghost_video, into
--     show_photos under the slug ghost-<slug>) -- allowed once you've said
--     you were there
--   * leave memories in the comments (ordinary comments, slug ghost-<slug>)
-- Easter eggs found (rain, storm, sprinkles, flyer, foil, ghost:<slug>) are
-- kept in user_eggs for the badges on your own profile.

-- ---- The rooms ---------------------------------------------------------------
create table if not exists public.ghost_venues (
  slug text primary key,
  name text not null
);
alter table public.ghost_venues enable row level security;
revoke all on public.ghost_venues from anon, authenticated;
insert into public.ghost_venues (slug, name) values
  ('satyricon', 'Satyricon'), ('la-luna', 'La Luna'), ('x-ray-cafe', 'X-Ray Cafe'),
  ('berbatis-pan', 'Berbati''s Pan'), ('meow-meow', 'Meow Meow'), ('backspace', 'Backspace'),
  ('slabtown', 'Slabtown'), ('ash-street-saloon', 'Ash Street Saloon'), ('jimmy-maks', 'Jimmy Mak''s'),
  ('blue-monk', 'The Blue Monk'), ('tonic-lounge', 'Tonic Lounge'), ('biddy-mcgraws', 'Biddy McGraw''s'),
  ('mt-tabor-theater', 'Mt. Tabor Theater'), ('green-room', 'The Green Room')
on conflict (slug) do update set name = excluded.name;

-- ---- "I was there" -----------------------------------------------------------
create table if not exists public.ghost_visits (
  user_id uuid not null references auth.users (id) on delete cascade,
  ghost_slug text not null references public.ghost_venues (slug) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, ghost_slug)
);
alter table public.ghost_visits enable row level security;
revoke all on public.ghost_visits from anon, authenticated;

create or replace function public.ghost_visit(p_slug text, p_on boolean)
returns table (n integer, mine boolean)
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('ghost_visit', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  if not exists (select 1 from public.ghost_venues g where g.slug = p_slug) then raise exception 'not_found' using errcode = 'P0001'; end if;
  if p_on then
    insert into public.ghost_visits (user_id, ghost_slug) values (auth.uid(), p_slug) on conflict do nothing;
  else
    delete from public.ghost_visits v where v.user_id = auth.uid() and v.ghost_slug = p_slug;
  end if;
  return query select (select count(*)::integer from public.ghost_visits v where v.ghost_slug = p_slug),
                      exists (select 1 from public.ghost_visits v where v.ghost_slug = p_slug and v.user_id = auth.uid());
end; $$;
revoke all on function public.ghost_visit(text, boolean) from public;
grant execute on function public.ghost_visit(text, boolean) to authenticated;

-- Who was there: named when the viewer may see that person's shows (the same
-- rule as Who's Going), otherwise counted with no name (user_id null).
-- Blocked people either way are left out.
create or replace function public.ghost_was_there(p_slug text)
returns table (user_id uuid, display_name text, handle text, avatar_url text, mine boolean)
language sql security definer set search_path = public stable as $$
  select case when v.user_id = auth.uid() or public.can_see_upcoming(v.user_id) then v.user_id end,
         case when v.user_id = auth.uid() or public.can_see_upcoming(v.user_id) then p.display_name end,
         case when v.user_id = auth.uid() or public.can_see_upcoming(v.user_id) then p.handle end,
         case when v.user_id = auth.uid() or public.can_see_upcoming(v.user_id) then p.avatar_url end,
         v.user_id = auth.uid()
    from public.ghost_visits v
    left join public.profiles p on p.id = v.user_id
   where v.ghost_slug = p_slug
     and (auth.uid() is null or not public.is_blocked_between(auth.uid(), v.user_id))
   order by (v.user_id = auth.uid()) desc, v.created_at
   limit 500;
$$;
revoke all on function public.ghost_was_there(text) from public;
grant execute on function public.ghost_was_there(text) to anon, authenticated;

create or replace function public.my_ghost_visits()
returns table (ghost_slug text)
language sql security definer set search_path = public stable as $$
  select v.ghost_slug from public.ghost_visits v where v.user_id = auth.uid();
$$;
revoke all on function public.my_ghost_visits() from public;
grant execute on function public.my_ghost_visits() to authenticated;

-- ---- Photos and clips on a ghost page -----------------------------------------
-- Same table and storage as show photos, slug ghost-<slug>. The ticket is the
-- ghost visit instead of a stub; 12 per person per room, like a show.
create or replace function public.add_ghost_photo(p_slug text, p_path text, p_width integer, p_height integer)
returns uuid language plpgsql security definer set search_path = public as $$
declare g public.ghost_venues%rowtype; new_id uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('add_show_photo', 40) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  select * into g from public.ghost_venues where 'ghost-' || slug = p_slug;
  if g.slug is null or not exists (select 1 from public.ghost_visits v where v.user_id = auth.uid() and v.ghost_slug = g.slug) then
    raise exception 'no_stub' using errcode = 'P0001';
  end if;
  if p_path not like auth.uid()::text || '/%' then raise exception 'bad_path' using errcode = 'P0001'; end if;
  if (select count(*) from public.show_photos where user_id = auth.uid() and show_slug = p_slug) >= 12 then
    raise exception 'photo_limit' using errcode = 'P0001';
  end if;
  insert into public.show_photos (show_slug, user_id, path, width, height, title, venue, show_date)
  values (p_slug, auth.uid(), p_path, p_width, p_height, g.name, g.name, '')
  returning id into new_id;
  return new_id;
end; $$;
revoke all on function public.add_ghost_photo(text, text, integer, integer) from public;
grant execute on function public.add_ghost_photo(text, text, integer, integer) to authenticated;

create or replace function public.add_ghost_video(p_slug text, p_path text, p_video_path text, p_width integer, p_height integer, p_duration integer)
returns uuid language plpgsql security definer set search_path = public as $$
declare g public.ghost_venues%rowtype; new_id uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('add_show_photo', 40) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  select * into g from public.ghost_venues where 'ghost-' || slug = p_slug;
  if g.slug is null or not exists (select 1 from public.ghost_visits v where v.user_id = auth.uid() and v.ghost_slug = g.slug) then
    raise exception 'no_stub' using errcode = 'P0001';
  end if;
  if p_path not like auth.uid()::text || '/%' or p_video_path not like auth.uid()::text || '/%' then raise exception 'bad_path' using errcode = 'P0001'; end if;
  if coalesce(p_duration, 0) > 26 then raise exception 'too_long' using errcode = 'P0001'; end if;
  if (select count(*) from public.show_photos where user_id = auth.uid() and show_slug = p_slug) >= 12 then raise exception 'photo_limit' using errcode = 'P0001'; end if;
  insert into public.show_photos (show_slug, user_id, path, width, height, title, venue, show_date, kind, video_path, duration_s)
  values (p_slug, auth.uid(), p_path, p_width, p_height, g.name, g.name, '', 'video', p_video_path, p_duration)
  returning id into new_id;
  return new_id;
end; $$;
revoke all on function public.add_ghost_video(text, text, text, integer, integer, integer) from public;
grant execute on function public.add_ghost_video(text, text, text, integer, integer, integer) to authenticated;

-- The home feed's Latest photos strip leaves ghost rooms out: finding them
-- is the point. (Same definition as schema-photo-likes.sql plus one line.)
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
     and ph.show_slug not like 'ghost-%'
     and not exists (select 1 from public.content_reports r where r.target_type = 'photo'
                      and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
   order by ph.created_at desc limit greatest(1, least(coalesce(p_limit, 20), 60));
$$;
revoke all on function public.latest_photos(integer) from public;
grant execute on function public.latest_photos(integer) to anon, authenticated;

-- ---- Easter eggs found --------------------------------------------------------
create table if not exists public.user_eggs (
  user_id uuid not null references auth.users (id) on delete cascade,
  egg text not null check (egg ~ '^[a-z0-9:_-]{1,40}$'),
  found_at timestamptz not null default now(),
  primary key (user_id, egg)
);
alter table public.user_eggs enable row level security;
revoke all on public.user_eggs from anon, authenticated;

create or replace function public.egg_found(p_egg text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then return; end if;
  if p_egg !~ '^[a-z0-9:_-]{1,40}$' then return; end if;
  if not public.rate_limit_take('egg_found', 60) then return; end if;
  insert into public.user_eggs (user_id, egg) values (auth.uid(), p_egg) on conflict do nothing;
end; $$;
revoke all on function public.egg_found(text) from public;
grant execute on function public.egg_found(text) to authenticated;

create or replace function public.my_eggs()
returns table (egg text)
language sql security definer set search_path = public stable as $$
  select e.egg from public.user_eggs e where e.user_id = auth.uid();
$$;
revoke all on function public.my_eggs() from public;
grant execute on function public.my_eggs() to authenticated;

-- Check: the 14 rooms are in.
select count(*) as ghost_rooms from public.ghost_venues;
