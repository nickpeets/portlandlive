-- Saved shows on your profile (Sep 17 2026).
--
-- A heart is the step before "I'm going": it says you're thinking about a
-- show, and it gives your wall something to say before you commit. Hearts
-- were private until now (schema-favorites.sql).
--
-- Audience: the SAME rule as upcoming shows and stubs, can_see_upcoming() --
-- yourself, your accepted followers, or everyone if you set
-- upcoming_visibility = 'public'. One switch governs all of it.
--
-- Shape copied from attendance_for_user: the database holds no show dates, so
-- the caller passes the keys currently in the feed and gets the intersection.
-- Nothing about past shows, and nothing about hearted bands or venues, is
-- ever returned.
--
-- Run once, in full, in the Supabase SQL Editor.

create or replace function public.saved_shows_of(p_target uuid, p_keys text[])
returns table (fav_key text, created_at timestamptz)
language sql
security definer
set search_path = public
stable
as $$
  select f.fav_key, f.created_at
    from public.user_favorites f
   where f.user_id = p_target
     and public.can_see_upcoming(p_target)
     and f.fav_key = any(p_keys)
     and f.fav_key not like 'band::%'
     and f.fav_key not like 'venue::%'
   order by f.created_at desc
   limit 200;
$$;

revoke all on function public.saved_shows_of(uuid, text[]) from public;
grant execute on function public.saved_shows_of(uuid, text[]) to anon, authenticated;
