-- Heating Up, widening window (Oct 13 2026, Nick). Run once, in full, in the
-- Supabase SQL Editor. Re-running is safe. Depends on schema-heating-up.sql.
--
-- Same counts as show_heat, but for three windows at once: hearts and
-- "I'm going" marks made in the last 7, 14 and 30 days. The page uses the
-- shortest window in which 5+ shows qualify, so a slow week widens the list
-- instead of making the whole feature vanish. Counts only -- never who.
-- show_heat (7 days only) stays for pages loaded before this change.

create or replace function public.show_heat_windows(p_keys text[], p_slugs text[])
returns table (kind text, id text, n7 integer, n14 integer, n30 integer)
language sql security definer set search_path = public stable as $$
  select 'h'::text, f.fav_key,
         (count(*) filter (where f.created_at > now() - interval '7 days'))::integer,
         (count(*) filter (where f.created_at > now() - interval '14 days'))::integer,
         count(*)::integer
    from public.user_favorites f
   where f.fav_key = any (coalesce(p_keys, '{}'::text[]))
     and f.created_at > now() - interval '30 days'
   group by f.fav_key
  union all
  select 'g'::text, a.show_slug,
         (count(*) filter (where a.created_at > now() - interval '7 days'))::integer,
         (count(*) filter (where a.created_at > now() - interval '14 days'))::integer,
         count(*)::integer
    from public.show_attendees a
   where a.show_slug = any (coalesce(p_slugs, '{}'::text[]))
     and a.created_at > now() - interval '30 days'
   group by a.show_slug;
$$;
revoke all on function public.show_heat_windows(text[], text[]) from public;
grant execute on function public.show_heat_windows(text[], text[]) to anon, authenticated;

-- Check: how many upcoming shows score 3+ in each window (going x2 + hearts).
-- Heating Up shows once a window reaches 5. (The page also limits it to music
-- in the next 90 days, so its numbers can be a little lower than these.)
with w as (
  select show_slug as id, 'g' as kind, created_at from public.show_attendees
   where show_slug >= to_char(now() at time zone 'America/Los_Angeles', 'YYYY-MM-DD')
)
select d as window_days,
       count(*) filter (where score >= 3) as shows_scoring_3_plus_from_going
  from (select d, id, 2 * count(*) as score
          from w, unnest(array[7, 14, 30]) d
         where created_at > now() - make_interval(days => d)
         group by d, id) t
 group by d order by d;
