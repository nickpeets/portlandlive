-- Welcome lines on the ticker (Sep 17 2026).
--
-- The nightly build asks for the people who joined since a given moment and
-- writes one "Welcome <name>" line each, which runs for that day only.
--
-- What this exposes: the DISPLAY NAME, which is already public wherever
-- someone comments, RSVPs or is followed. Not the handle -- handles stay
-- non-enumerable by design (schema-handles.sql, D3) -- and not the email,
-- the id, or anything else.
--
-- SECURITY DEFINER because profiles' own SELECT is revoked. The function
-- reads two columns, takes a floor no older than 7 days, and caps at 20 rows.
--
-- Run once, in full, in the Supabase SQL Editor.

create or replace function public.new_members(p_since timestamptz)
returns table (display_name text, joined_at timestamptz)
language sql
stable
security definer
set search_path = public
as $$
  select p.display_name, p.created_at
    from public.profiles p
   where p.display_name is not null
     and length(btrim(p.display_name)) > 0
     and p.created_at >= greatest(p_since, now() - interval '7 days')
   order by p.created_at
   limit 20;
$$;

revoke all on function public.new_members(timestamptz) from public;
grant execute on function public.new_members(timestamptz) to anon, authenticated;

-- Check: who would the next build welcome?
select * from public.new_members(now() - interval '2 days');
