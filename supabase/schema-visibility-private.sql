-- "No one" as a visibility option (Sep 17 2026).
--
-- upcoming_visibility gains a third value, 'private': your upcoming shows,
-- saved shows and stubs are yours alone -- not even accepted followers see
-- them. can_see_upcoming() is the one gate every reader goes through
-- (attendance_for_user, saved_shows_of, stubs_for_user, followed_attendance),
-- so this is the only function that changes.
--
-- Run once, in full, in the Supabase SQL Editor.

alter table public.profiles drop constraint if exists profiles_upcoming_visibility_valid;
alter table public.profiles add constraint profiles_upcoming_visibility_valid
  check (upcoming_visibility in ('followers', 'public', 'private'));

create or replace function public.can_see_upcoming(p_target uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select p_target is not null
     and (
       p_target = auth.uid()
       or exists (
         select 1 from public.profiles p
          where p.id = p_target and p.upcoming_visibility = 'public'
       )
       or (
         public.i_follow(p_target)
         and exists (
           select 1 from public.profiles p
            where p.id = p_target and p.upcoming_visibility = 'followers'
         )
       )
     );
$$;

revoke all on function public.can_see_upcoming(uuid) from public;
grant execute on function public.can_see_upcoming(uuid) to anon, authenticated;

-- Check: the three allowed values.
select conname, pg_get_constraintdef(oid) from pg_constraint where conname = 'profiles_upcoming_visibility_valid';
