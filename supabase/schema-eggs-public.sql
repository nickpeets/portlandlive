-- Easter eggs on anyone's profile (Oct 1 2026, Nick): the eggs and ghost
-- visits of one person, readable by whoever can see their profile -- the
-- same gate as stubs and saved shows (can_see_upcoming). Your own page keeps
-- using my_eggs / my_ghost_visits.
--
-- Run once, in full, in the Supabase SQL Editor.

create or replace function public.eggs_for_user(p_target uuid)
returns table (kind text, key text)
language sql security definer set search_path = public stable as $$
  select 'egg'::text, e.egg
    from public.user_eggs e
   where e.user_id = p_target and public.can_see_upcoming(p_target)
  union all
  select 'visit'::text, v.ghost_slug
    from public.ghost_visits v
   where v.user_id = p_target and public.can_see_upcoming(p_target);
$$;
revoke all on function public.eggs_for_user(uuid) from public;
grant execute on function public.eggs_for_user(uuid) to anon, authenticated;

-- Check: your own eggs and visits come back for you.
select kind, count(*) from public.eggs_for_user(auth.uid()) group by kind;
