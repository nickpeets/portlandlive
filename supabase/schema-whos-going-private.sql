-- Who's Going respects "No one" (Sep 22 2026).
--
-- WHY: attendees_for_show() named everyone who marked going, including
-- people whose visibility is "No one" (upcoming_visibility = 'private').
-- Nick's call: keep naming everyone else -- "I'm going" is a public signal --
-- and COUNT the No-one people without naming them, so the page reads
-- "Nicky Sweets and 25 others".
--
-- Shape: same columns, same order, so nothing else changes. A hidden row
-- comes back with id, user_id, display_name and handle all NULL (the user id
-- alone would identify them). Your own row is never hidden from you.
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe.

create or replace function public.attendees_for_show(p_show_slug text)
returns table (id uuid, user_id uuid, display_name text, handle text, created_at timestamptz)
language sql
security definer
set search_path = public
stable
as $$
  select case when h.hide then null else a.id end,
         case when h.hide then null else a.user_id end,
         case when h.hide then null else a.display_name end,
         case when h.hide then null else p.handle end,
         a.created_at
    from public.show_attendees a
    left join public.profiles p on p.id = a.user_id
    cross join lateral (
      select (p.upcoming_visibility = 'private'
              and a.user_id is distinct from auth.uid()) as hide
    ) h
   where a.show_slug = p_show_slug
   order by a.created_at;
$$;

revoke all on function public.attendees_for_show(text) from public;
grant execute on function public.attendees_for_show(text) to anon, authenticated;

-- Check: how many going marks are now counted but not named.
select count(*) as no_one_marks
  from public.show_attendees a
  join public.profiles p on p.id = a.user_id
 where p.upcoming_visibility = 'private';
