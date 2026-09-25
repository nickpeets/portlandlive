-- Show tallies on feed cards (Sep 24 2026, Nick).
--
-- One line under each listing: "♥ 14 · 6 going", plus "· 2 you follow" when
-- people you follow are going. One call for the whole feed, not one per card.
--
--   h  hearts per show (fav_key)        -- counts only, never who
--   g  "I'm going" per show (show_slug) -- counts everyone, including people
--      set to "No one" (same rule as Who's Going: counted, not named)
--   f  people YOU follow who are going  -- accepted follows only, and only
--      people whose visibility lets you see their upcoming shows
--      (can_see_upcoming), so a "No one" friend is never in this number;
--      blocks either way are excluded. Signed-out callers get no f rows.
--
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe.

create or replace function public.show_tallies(p_keys text[], p_slugs text[])
returns table (kind text, id text, n integer)
language sql security definer set search_path = public stable as $$
  select 'h'::text, f.fav_key, count(*)::integer
    from public.user_favorites f
   where f.fav_key = any (coalesce(p_keys, '{}'::text[]))
   group by f.fav_key
  union all
  select 'g'::text, a.show_slug, count(*)::integer
    from public.show_attendees a
   where a.show_slug = any (coalesce(p_slugs, '{}'::text[]))
   group by a.show_slug
  union all
  select 'f'::text, a.show_slug, count(*)::integer
    from public.show_attendees a
    join public.follows fo
      on fo.followee_id = a.user_id
     and fo.follower_id = auth.uid()
     and fo.status = 'accepted'
   where auth.uid() is not null
     and a.show_slug = any (coalesce(p_slugs, '{}'::text[]))
     and public.can_see_upcoming(a.user_id)
     and not public.is_blocked_between(auth.uid(), a.user_id)
   group by a.show_slug;
$$;

revoke all on function public.show_tallies(text[], text[]) from public;
grant execute on function public.show_tallies(text[], text[]) to anon, authenticated;

-- Check: the ten shows with the most going marks right now.
select id as show_slug, n as going
  from public.show_tallies('{}', (select array_agg(distinct show_slug) from public.show_attendees))
 where kind = 'g'
 order by n desc
 limit 10;
