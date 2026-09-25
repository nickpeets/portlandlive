-- Heating Up (Sep 24 2026, Nick). Run once, in full, in the Supabase SQL
-- Editor. Re-running is safe. Depends on schema-favorites.sql and
-- schema-show-attendees.sql.
--
-- Shows gaining momentum: hearts and "I'm going" marks made in the LAST 7
-- DAYS only, so the list moves. The page scores each show (going counts
-- double a heart), keeps upcoming shows in the next 30 days scoring 3+, and
-- only offers "Heating Up" once 5 shows qualify. Counts only -- never who.

create or replace function public.show_heat(p_keys text[], p_slugs text[])
returns table (kind text, id text, n integer)
language sql security definer set search_path = public stable as $$
  select 'h'::text, f.fav_key, count(*)::integer
    from public.user_favorites f
   where f.fav_key = any (coalesce(p_keys, '{}'::text[]))
     and f.created_at > now() - interval '7 days'
   group by f.fav_key
  union all
  select 'g'::text, a.show_slug, count(*)::integer
    from public.show_attendees a
   where a.show_slug = any (coalesce(p_slugs, '{}'::text[]))
     and a.created_at > now() - interval '7 days'
   group by a.show_slug;
$$;
revoke all on function public.show_heat(text[], text[]) from public;
grant execute on function public.show_heat(text[], text[]) to anon, authenticated;

-- Check: the ten hottest upcoming shows by going marks this week.
select id as show_slug, n as going_this_week
  from public.show_heat('{}', (select array_agg(distinct show_slug) from public.show_attendees
                                where show_slug >= to_char(now() at time zone 'America/Los_Angeles', 'YYYY-MM-DD')))
 where kind = 'g'
 order by n desc
 limit 10;
