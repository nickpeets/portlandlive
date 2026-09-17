-- Stubs follow the same audience rule as everything else (Sep 17 2026).
--
-- Stubs were the "public record": anyone could read any profile's stub
-- grid. With follow requests in place, Nick's rule is that a non-follower
-- sees nothing on a profile, stubs included. stubs_for_user now returns rows
-- only when can_see_upcoming(target) says so -- yourself, an ACCEPTED
-- follower, or anyone if that person set their shows to public. Same switch,
-- same function, nothing new to reason about.
--
-- Run once, in full, in the Supabase SQL Editor.

create or replace function public.stubs_for_user(p_target uuid)
returns table (
  stub_id text, title text, venue text, neighborhood text, address text,
  date text, "time" text, created_at timestamptz
)
language sql
security definer
set search_path = public
stable
as $$
  select s.stub_id, s.title, s.venue, s.neighborhood, s.address, s.date, s."time", s.created_at
    from public.user_stubs s
   where s.user_id = p_target
     and public.can_see_upcoming(p_target)
   order by s.created_at desc;
$$;

-- Check: your own stubs still come back for you.
select count(*) as my_stubs from public.stubs_for_user(auth.uid());
